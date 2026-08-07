"""Pinned, read-only GitHub candidate retrieval through the public REST API."""

from __future__ import annotations

import posixpath
from typing import Any
from urllib.parse import quote, urlencode

from .errors import RecordShapeError
from .hashing import calculate_checksums
from .http import ReadOnlyHttpClient
from .models import GitHubCandidate


class GitHubClient:
    api_root = "https://api.github.com"

    def __init__(self, http: ReadOnlyHttpClient | None = None) -> None:
        self.http = http or ReadOnlyHttpClient()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "zenetism-publication-engine-stage1",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _json(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        suffix = f"?{urlencode(query)}" if query else ""
        value, _ = self.http.get_json(f"{self.api_root}{path}{suffix}", headers=self.headers)
        return value

    def fetch_candidate(
        self,
        *,
        repository: str,
        branch: str,
        directory: str,
        canonical_filename: str,
    ) -> GitHubCandidate:
        if repository.count("/") != 1:
            raise RecordShapeError("GitHub repository must be owner/name")
        clean_directory = directory.strip("/")
        path = posixpath.join(clean_directory, canonical_filename)
        branch_record = self._json(f"/repos/{repository}/commits/{quote(branch, safe='')}")
        branch_head = _required_str(branch_record, "sha", "GitHub branch head")

        encoded_path = quote(path, safe="")
        metadata = self._json(
            f"/repos/{repository}/contents/{encoded_path}", {"ref": branch_head}
        )
        if metadata.get("type") != "file":
            raise RecordShapeError(f"GitHub path is not a file: {path}")
        blob_sha = _required_str(metadata, "sha", "GitHub file blob")

        commit_response = self.http.get(
            f"{self.api_root}/repos/{repository}/commits?"
            + urlencode({"sha": branch_head, "path": path, "per_page": "1"}),
            headers=self.headers,
        )
        import json

        try:
            commits = json.loads(commit_response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordShapeError("GitHub file history response is not JSON") from exc
        if not isinstance(commits, list) or not commits or not isinstance(commits[0], dict):
            raise RecordShapeError(f"GitHub returned no commit affecting {path}")
        file_commit = _required_str(commits[0], "sha", "GitHub file commit")

        raw_headers = dict(self.headers)
        raw_headers["Accept"] = "application/vnd.github.raw+json"
        raw = self.http.get(
            f"{self.api_root}/repos/{repository}/contents/{encoded_path}?"
            + urlencode({"ref": branch_head}),
            headers=raw_headers,
        ).body
        checksums = calculate_checksums(raw)
        advertised_size = metadata.get("size")
        if not isinstance(advertised_size, int) or advertised_size != checksums.byte_size:
            raise RecordShapeError(
                f"GitHub byte-size mismatch for {path}: API={advertised_size!r}, bytes={checksums.byte_size}"
            )

        return GitHubCandidate(
            repository=repository,
            branch=branch,
            directory=clean_directory,
            canonical_filename=canonical_filename,
            path=path,
            branch_head_commit=branch_head,
            commit=file_commit,
            blob_sha=blob_sha,
            checksums=checksums,
            payload=raw,
        )


def _required_str(value: dict[str, Any], key: str, context: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise RecordShapeError(f"{context} omitted required {key!r}")
    return result
