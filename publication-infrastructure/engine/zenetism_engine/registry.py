"""Durable CSV publication-registry maintenance after successful validation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

REGISTRY_FIELDS = (
    "canonical_filename",
    "title",
    "corpus_classification",
    "github_directory",
    "github_commit",
    "github_sha256",
    "github_md5",
    "concept_doi",
    "latest_version_label",
    "latest_version_doi",
    "zenodo_archival_filename",
    "zenodo_checksum",
    "publication_date",
    "metadata_status",
    "file_status",
    "site_relation_status",
    "last_verification_date",
    "architect_approval_state",
    "notes",
)


def registry_row(
    manifest: dict[str, Any],
    validation_report: dict[str, Any],
    *,
    verification_date: str,
    architect_approval_state: str,
    notes: str,
) -> dict[str, str]:
    if validation_report.get("passed") is not True:
        raise ValueError("registry row requires a passing fail-closed validation report")
    return {
        "canonical_filename": _path(manifest, "github.canonical_filename"),
        "title": _path(manifest, "zenodo.metadata.title"),
        "corpus_classification": _path(manifest, "corpus_classification"),
        "github_directory": _path(manifest, "github.directory"),
        "github_commit": _path(manifest, "github.commit"),
        "github_sha256": _path(manifest, "github.sha256"),
        "github_md5": _path(manifest, "github.md5"),
        "concept_doi": _path(manifest, "zenodo.concept_doi"),
        "latest_version_label": _path(manifest, "zenodo.target_version"),
        "latest_version_doi": _path(manifest, "zenodo.exact_version_doi"),
        "zenodo_archival_filename": _path(manifest, "zenodo.archival_filename"),
        "zenodo_checksum": _path(manifest, "zenodo.archival_checksum"),
        "publication_date": _path(manifest, "zenodo.publication_date"),
        "metadata_status": "validated",
        "file_status": _path(manifest, "comparison.payload_status"),
        "site_relation_status": "validated",
        "last_verification_date": verification_date,
        "architect_approval_state": architect_approval_state,
        "notes": notes,
    }


def update_registry(path: str | Path, row: dict[str, str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, str]] = []
    if destination.exists():
        with destination.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != REGISTRY_FIELDS:
                raise ValueError("existing registry header does not match Publication Engine v2")
            existing = [dict(item) for item in reader]
    key = row["canonical_filename"]
    result = [row if item.get("canonical_filename") == key else item for item in existing]
    if not any(item.get("canonical_filename") == key for item in existing):
        result.append(row)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REGISTRY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)


def _path(value: dict[str, Any], path: str) -> str:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"manifest is missing registry field {path}")
        current = current[part]
    if current is None:
        raise ValueError(f"manifest registry field {path} is null")
    return str(current)
