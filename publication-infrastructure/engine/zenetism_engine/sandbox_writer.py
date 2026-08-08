"""Sandbox-only draft planning, mutation, reload, and exact validation."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote, urlsplit

from .archival import prepare_archival_copy
from .errors import DraftValidationError, SandboxRequestError, SandboxSafetyError
from .sandbox_boundary import (
    SANDBOX_API_BASE,
    RuntimeSandboxCredentials,
    require_sandbox_request_url,
)
from .sandbox_metadata import SandboxDraftPackage, serialize_sandbox_draft

_RECORD_ID_RE = re.compile(r"[A-Za-z0-9-]+")
_REQUEST_METHODS = frozenset({"GET", "POST", "PUT"})
_DRAFT_ID_TOKEN = "{sandbox_draft_id}"


class SandboxTransport(Protocol):
    """Minimal transport surface needed for an unpublished Sandbox draft."""

    def request(
        self,
        method: str,
        url: str,
        *,
        credentials: RuntimeSandboxCredentials,
        json_body: object | None = None,
        binary_body: bytes | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DraftRequest:
    method: str
    path: str
    purpose: str
    json_body: object | None = None
    binary_summary: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "method": self.method,
            "url": f"{SANDBOX_API_BASE}{self.path}",
            "purpose": self.purpose,
        }
        if self.json_body is not None:
            result["json_body"] = deepcopy(self.json_body)
        if self.binary_summary is not None:
            result["binary_body"] = deepcopy(self.binary_summary)
        return result


@dataclass(frozen=True)
class SandboxDraftPlan:
    mode: str
    source_record_id: str | None
    package: SandboxDraftPackage
    requests: tuple[DraftRequest, ...]

    def audit_summary(self) -> dict[str, Any]:
        return {
            "operation": "prepare_unpublished_sandbox_draft",
            "mode": self.mode,
            "sandbox_api_base": SANDBOX_API_BASE,
            "authentication": "runtime environment only; value omitted",
            "final_release_action_available": False,
            "package": self.package.audit_summary(),
            "requests": [item.as_dict() for item in self.requests],
        }


@dataclass(frozen=True)
class SandboxDraftResult:
    dry_run: bool
    audit: dict[str, Any]
    draft: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "dry_run": self.dry_run,
            "status": "dry_run_only" if self.dry_run else "unpublished_sandbox_draft_validated",
            "audit": deepcopy(self.audit),
        }
        if self.draft is not None:
            result["draft"] = deepcopy(self.draft)
        if self.validation is not None:
            result["validation"] = deepcopy(self.validation)
        return result


class UrllibSandboxTransport:
    """Fixed-host transport with no redirect following and no write retries."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_RejectRedirects())

    def request(
        self,
        method: str,
        url: str,
        *,
        credentials: RuntimeSandboxCredentials,
        json_body: object | None = None,
        binary_body: bytes | None = None,
    ) -> dict[str, Any]:
        method = _require_method(method)
        safe_url = require_sandbox_request_url(url)
        if json_body is not None and binary_body is not None:
            raise SandboxSafetyError("a Sandbox request cannot mix JSON and binary bodies")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {credentials.token}",
            "User-Agent": "zenetism-publication-engine-stage2a",
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif binary_body is not None:
            data = binary_body
            headers["Content-Type"] = "application/octet-stream"

        request = urllib.request.Request(safe_url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned HTTP {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} could not be completed"
            ) from None
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned invalid JSON"
            ) from None
        if not isinstance(value, dict):
            raise SandboxRequestError(
                f"Sandbox {method} {_safe_path(safe_url)} returned a non-object JSON value"
            )
        return value


class SandboxDraftWriter:
    """Prepare or execute one manifest-controlled, unpublished Sandbox draft."""

    def __init__(
        self,
        *,
        transport: SandboxTransport | None = None,
        credential_loader: Callable[[], RuntimeSandboxCredentials] | None = None,
    ) -> None:
        self._transport = transport or UrllibSandboxTransport()
        self._credential_loader = (
            credential_loader or RuntimeSandboxCredentials.from_environment
        )

    def plan(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        mode: str = "create",
        source_record_id: str | None = None,
    ) -> SandboxDraftPlan:
        mode, source_record_id = _require_mode(mode, source_record_id)
        archival_copy = prepare_archival_copy(manifest, repository_root=repository_root)
        package = serialize_sandbox_draft(manifest, archival_copy)
        return SandboxDraftPlan(
            mode=mode,
            source_record_id=source_record_id,
            package=package,
            requests=_planned_requests(mode, source_record_id, package),
        )

    def run(
        self,
        manifest: object,
        *,
        repository_root: str | Path,
        mode: str = "create",
        source_record_id: str | None = None,
        dry_run: bool = True,
    ) -> SandboxDraftResult:
        plan = self.plan(
            manifest,
            repository_root=repository_root,
            mode=mode,
            source_record_id=source_record_id,
        )
        audit = plan.audit_summary()
        audit["dry_run"] = dry_run
        if dry_run:
            audit["requests_sent"] = 0
            return SandboxDraftResult(dry_run=True, audit=audit)
        return self._execute(plan, audit)

    def _execute(
        self, plan: SandboxDraftPlan, audit: dict[str, Any]
    ) -> SandboxDraftResult:
        credentials = self._credential_loader()
        transport = self._transport
        package = plan.package
        source_concept_doi: str | None = None

        if plan.mode == "new-version":
            source_path = f"/records/{_record_segment(plan.source_record_id)}"
            source = _send(transport, credentials, "GET", source_path)
            source_concept_doi = _required_path(source, "parent.pids.doi.identifier", str)
            started = _send(
                transport,
                credentials,
                "POST",
                f"{source_path}/versions",
            )
        else:
            started = _send(
                transport,
                credentials,
                "POST",
                "/records",
                json_body=package.create_payload,
            )

        draft_id = _record_segment(_required_path(started, "id", (str, int)))
        draft_path = f"/records/{draft_id}/draft"
        reserved = _send(transport, credentials, "POST", f"{draft_path}/pids/doi")
        reserved_doi = _required_path(reserved, "pids.doi.identifier", str)
        _send(
            transport,
            credentials,
            "POST",
            f"{draft_path}/files",
            json_body=[{"key": package.archival_copy.archival_filename}],
        )
        filename = quote(package.archival_copy.archival_filename, safe="")
        file_path = f"{draft_path}/files/{filename}"
        _send(
            transport,
            credentials,
            "PUT",
            f"{file_path}/content",
            binary_body=package.archival_copy.payload,
        )
        _send(transport, credentials, "POST", f"{file_path}/commit")
        _send(
            transport,
            credentials,
            "PUT",
            draft_path,
            json_body=package.saved_payload,
        )
        reloaded = _send(transport, credentials, "GET", draft_path)
        reloaded_file = _send(transport, credentials, "GET", file_path)
        validation = validate_saved_draft(
            package,
            reloaded,
            reloaded_file,
            expected_draft_id=draft_id,
            reserved_doi=reserved_doi,
            source_concept_doi=source_concept_doi,
        )
        audit["requests_sent"] = 9 if plan.mode == "new-version" else 8
        audit["saved_draft_id"] = draft_id
        audit["validation_passed"] = True
        return SandboxDraftResult(
            dry_run=False,
            audit=audit,
            draft=_safe_draft_summary(package, reloaded),
            validation=validation,
        )


def validate_saved_draft(
    package: SandboxDraftPackage,
    draft: object,
    file_record: object,
    *,
    expected_draft_id: str | None = None,
    reserved_doi: str | None = None,
    source_concept_doi: str | None = None,
) -> dict[str, Any]:
    """Fail unless the reloaded unpublished draft equals the proposed package."""
    if not isinstance(draft, dict) or not isinstance(file_record, dict):
        raise DraftValidationError("Sandbox read-back must contain JSON objects")
    failures: list[str] = []
    _compare_expected(package.saved_payload, draft, "draft", failures)

    if expected_draft_id is not None and draft.get("id") != expected_draft_id:
        failures.append("draft.id differs from the created draft identifier")
    if draft.get("is_published") is not False:
        failures.append("draft.is_published must be explicitly false")
    draft_status = draft.get("status")
    if draft_status not in {"draft", "new_version_draft"}:
        failures.append("draft.status must identify an unpublished draft")

    doi = _optional_path(draft, "pids.doi.identifier")
    if not isinstance(doi, str) or not doi:
        failures.append("draft.pids.doi.identifier is missing after DOI reservation")
    elif reserved_doi is not None and doi != reserved_doi:
        failures.append("reloaded DOI differs from the reserved DOI")
    elif doi in package.existing_dois_not_supplied:
        failures.append("reserved DOI duplicates a prior exact-version or concept DOI")

    if source_concept_doi is not None:
        observed_concept = _optional_path(draft, "parent.pids.doi.identifier")
        if observed_concept != source_concept_doi:
            failures.append("draft concept DOI differs from the originating version family")

    archival = package.archival_copy
    if file_record.get("key") != archival.archival_filename:
        failures.append("file.key differs from the archival filename")
    if file_record.get("size") != archival.checksums.byte_size:
        failures.append("file.size differs from the canonical payload")
    expected_checksum = f"md5:{archival.checksums.md5}"
    if file_record.get("checksum") != expected_checksum:
        failures.append("file.checksum differs from the canonical payload")
    if file_record.get("status") != "completed":
        failures.append("file.status must be completed")

    if failures:
        raise DraftValidationError(
            "Sandbox draft read-back validation failed: " + "; ".join(failures)
        )
    return {
        "passed": True,
        "draft_state": "unpublished",
        "metadata_exact": True,
        "archival_filename": archival.archival_filename,
        "byte_size": archival.checksums.byte_size,
        "sha256": archival.checksums.sha256,
        "md5": archival.checksums.md5,
        "default_preview": archival.archival_filename,
        "reserved_doi": doi,
        "concept_doi_preserved": True,
    }


def _planned_requests(
    mode: str, source_record_id: str | None, package: SandboxDraftPackage
) -> tuple[DraftRequest, ...]:
    draft_path = f"/records/{_DRAFT_ID_TOKEN}/draft"
    filename = quote(package.archival_copy.archival_filename, safe="")
    file_path = f"{draft_path}/files/{filename}"
    requests: list[DraftRequest] = []
    if mode == "new-version":
        source = _record_segment(source_record_id)
        requests.extend(
            [
                DraftRequest("GET", f"/records/{source}", "read originating version family"),
                DraftRequest(
                    "POST", f"/records/{source}/versions", "create unpublished test-version draft"
                ),
            ]
        )
    else:
        requests.append(
            DraftRequest(
                "POST", "/records", "create unpublished Sandbox deposit", package.create_payload
            )
        )
    requests.extend(
        [
            DraftRequest("POST", f"{draft_path}/pids/doi", "reserve Sandbox DOI"),
            DraftRequest(
                "POST",
                f"{draft_path}/files",
                "initialize archival file",
                [{"key": package.archival_copy.archival_filename}],
            ),
            DraftRequest(
                "PUT",
                f"{file_path}/content",
                "upload byte-identical archival payload",
                binary_summary={
                    "byte_size": package.archival_copy.checksums.byte_size,
                    "sha256": package.archival_copy.checksums.sha256,
                    "md5": package.archival_copy.checksums.md5,
                },
            ),
            DraftRequest("POST", f"{file_path}/commit", "complete archival file upload"),
            DraftRequest(
                "PUT",
                draft_path,
                "save approved metadata and explicit default Preview",
                package.saved_payload,
            ),
            DraftRequest("GET", draft_path, "reload saved draft"),
            DraftRequest("GET", file_path, "read saved archival file metadata"),
        ]
    )
    return tuple(requests)


def _send(
    transport: SandboxTransport,
    credentials: RuntimeSandboxCredentials,
    method: str,
    path: str,
    *,
    json_body: object | None = None,
    binary_body: bytes | None = None,
) -> dict[str, Any]:
    method = _require_method(method)
    url = require_sandbox_request_url(f"{SANDBOX_API_BASE}{path}")
    try:
        result = transport.request(
            method,
            url,
            credentials=credentials,
            json_body=json_body,
            binary_body=binary_body,
        )
    except SandboxRequestError:
        raise
    except Exception:
        raise SandboxRequestError(
            f"Sandbox {method} {_safe_path(url)} could not be completed"
        ) from None
    if not isinstance(result, dict):
        raise SandboxRequestError(
            f"Sandbox {method} {_safe_path(url)} returned a non-object JSON value"
        )
    return result


def _require_method(value: str) -> str:
    method = value.upper()
    if method not in _REQUEST_METHODS:
        raise SandboxSafetyError(f"Sandbox request method is not permitted: {method}")
    return method


def _require_mode(mode: str, source_record_id: str | None) -> tuple[str, str | None]:
    if mode not in {"create", "new-version"}:
        raise SandboxSafetyError("mode must be create or new-version")
    if mode == "new-version":
        return mode, _record_segment(source_record_id)
    if source_record_id is not None:
        raise SandboxSafetyError("--source-record-id is valid only in new-version mode")
    return mode, None


def _record_segment(value: object) -> str:
    if isinstance(value, bool):
        raise SandboxSafetyError("Sandbox record id contains unsupported characters")
    text = str(value) if value is not None else ""
    if not _RECORD_ID_RE.fullmatch(text):
        raise SandboxSafetyError("Sandbox record id contains unsupported characters")
    return text


def _required_path(value: dict[str, Any], path: str, expected_type: object) -> Any:
    result = _optional_path(value, path)
    if not isinstance(result, expected_type):
        raise SandboxRequestError(f"Sandbox response is missing required field {path}")
    return result


def _optional_path(value: object, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _compare_expected(
    expected: object, observed: object, path: str, failures: list[str]
) -> None:
    if isinstance(expected, dict):
        if not isinstance(observed, dict):
            failures.append(f"{path} is not an object")
            return
        for key, expected_value in expected.items():
            if key not in observed:
                failures.append(f"{path}.{key} is missing")
            else:
                _compare_expected(expected_value, observed[key], f"{path}.{key}", failures)
        return
    if isinstance(expected, list):
        if not isinstance(observed, list):
            failures.append(f"{path} is not a list")
            return
        if len(expected) != len(observed):
            failures.append(f"{path} length differs")
            return
        for index, expected_value in enumerate(expected):
            _compare_expected(expected_value, observed[index], f"{path}[{index}]", failures)
        return
    if type(expected) is not type(observed) or expected != observed:
        failures.append(f"{path} differs")


def _safe_draft_summary(
    package: SandboxDraftPackage, draft: dict[str, Any]
) -> dict[str, Any]:
    """Return validated fields without service links or authentication-bound details."""
    return {
        "id": draft["id"],
        "status": draft["status"],
        "is_published": draft["is_published"],
        "pids": {"doi": {"identifier": _optional_path(draft, "pids.doi.identifier")}},
        "parent": {
            "pids": {
                "doi": {"identifier": _optional_path(draft, "parent.pids.doi.identifier")}
            }
        },
        **deepcopy(package.saved_payload),
    }


def _safe_path(url: str) -> str:
    return urlsplit(url).path


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        raise SandboxSafetyError("Sandbox request redirect was rejected")
