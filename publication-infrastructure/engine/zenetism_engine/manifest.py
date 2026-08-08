"""Structured v2 manifest construction from live read-only observations."""

from __future__ import annotations

import json
from pathlib import PurePosixPath, Path
from typing import Any

from .comparison import compare_payloads
from .description import corpus_classification, infer_description_form
from .github import GitHubClient
from .models import Observation, RelatedIdentifier, VersionMember
from .zenodo import ZenodoClient

SCHEMA_VERSION = "zenetism-publication-engine-v2-stage-1"
SITE_IDENTIFIER = "https://zenetism.aelionkannon.chatgpt.site"


def retrieve_observation(
    *,
    repository: str,
    branch: str,
    directory: str,
    canonical_filename: str,
    zenodo_identifier: str,
    github_client: GitHubClient | None = None,
    zenodo_client: ZenodoClient | None = None,
) -> Observation:
    github = (github_client or GitHubClient()).fetch_candidate(
        repository=repository,
        branch=branch,
        directory=directory,
        canonical_filename=canonical_filename,
    )
    zenodo = (zenodo_client or ZenodoClient()).fetch_published_record(
        zenodo_identifier, canonical_filename=canonical_filename
    )
    return Observation(
        github=github,
        zenodo=zenodo,
        comparison=compare_payloads(github, zenodo),
    )


def build_manifest(observation: Observation) -> dict[str, Any]:
    github = observation.github
    zenodo = observation.zenodo
    creator = zenodo.creator
    site_relation = next(
        (item for item in zenodo.related_identifiers if item.identifier == SITE_IDENTIFIER), None
    )
    previous = _previous_version(zenodo.version_family, zenodo.family_index)
    record_key = PurePosixPath(github.canonical_filename).stem
    default_selected = zenodo.default_preview == zenodo.archival_filename

    return {
        "schema_version": SCHEMA_VERSION,
        "record_key": record_key,
        "corpus_classification": corpus_classification(zenodo.description),
        "github": {
            "repository": github.repository,
            "branch": github.branch,
            "directory": github.directory,
            "canonical_filename": github.canonical_filename,
            "path": github.path,
            "commit": github.commit,
            "blob_sha": github.blob_sha,
            "byte_size": github.checksums.byte_size,
            "sha256": github.checksums.sha256,
            "md5": github.checksums.md5,
        },
        "zenodo": {
            "record_id": zenodo.record_id,
            "concept_record_id": zenodo.concept_record_id,
            "exact_version_doi": zenodo.exact_version_doi,
            "concept_doi": zenodo.concept_doi,
            "previous_version_doi": previous.exact_version_doi if previous else None,
            "target_version": zenodo.version_label,
            "record_revision": zenodo.record_revision,
            "version_family_index": zenodo.family_index,
            "is_latest": zenodo.is_latest,
            "publication_date": zenodo.publication_date,
            "archival_filename": zenodo.archival_filename,
            "archival_byte_size": zenodo.checksums.byte_size,
            "archival_checksum": zenodo.advertised_checksum,
            "archival_sha256": zenodo.checksums.sha256,
            "archival_md5": zenodo.checksums.md5,
            "metadata": {
                "title": zenodo.title,
                "resource_type": {
                    "id": zenodo.resource_type_id,
                    "title": zenodo.resource_type_title,
                },
                "access": zenodo.access,
                "license": {
                    "id": zenodo.license_id,
                    "title": zenodo.license_title,
                },
                "copyright": zenodo.copyright,
                "language": zenodo.language,
            },
            "version_family": [_version_member(item) for item in zenodo.version_family],
        },
        "creator": {
            "family_name": creator.family_name if creator else None,
            "given_names": creator.given_names if creator else None,
            "rendered_name": creator.name if creator else None,
        },
        "contributors": [
            {"name": item.name, "role": item.role} for item in zenodo.contributors
        ],
        "repository_url": zenodo.repository_url,
        "description": {
            "form": infer_description_form(zenodo.description),
            "rendered_html": zenodo.description,
        },
        "keywords": list(zenodo.keywords),
        "related_identifiers": [_related_identifier(item) for item in zenodo.related_identifiers],
        "site_relation": _related_identifier(site_relation) if site_relation else {
            "relation": None,
            "scheme": None,
            "resource_type": None,
            "identifier": None,
        },
        "preview": {
            "explicit_default_file": default_selected,
            "default_file": zenodo.default_preview,
        },
        "comparison": {
            "payload_status": observation.comparison.payload_status,
            "byte_size_status": observation.comparison.byte_size_status,
            "sha256_status": observation.comparison.sha256_status,
            "md5_status": observation.comparison.md5_status,
        },
        "publication": {"architect_publish_required": True},
    }


def write_manifest(manifest: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def load_manifest(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest root must be an object")
    return value


def _version_member(item: VersionMember) -> dict[str, Any]:
    return {
        "record_id": item.record_id,
        "exact_version_doi": item.exact_version_doi,
        "version_label": item.version_label,
        "record_revision": item.record_revision,
        "family_index": item.family_index,
        "is_latest": item.is_latest,
    }


def _related_identifier(item: RelatedIdentifier) -> dict[str, str]:
    return {
        "relation": item.relation,
        "scheme": item.scheme,
        "resource_type": item.resource_type,
        "identifier": item.identifier,
    }


def _previous_version(
    family: tuple[VersionMember, ...], current_index: int | None
) -> VersionMember | None:
    if current_index is None:
        return None
    prior = [
        item
        for item in family
        if item.family_index is not None and item.family_index < current_index
    ]
    return max(prior, key=lambda item: item.family_index or 0, default=None)
