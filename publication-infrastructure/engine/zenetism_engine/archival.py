"""Byte-immutable preparation of an approved Zenodo archival upload."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ManifestApprovalError
from .hashing import calculate_checksums
from .models import Checksums
from .naming import archival_filename, validate_archival_filename
from .validation import validate_manifest


@dataclass(frozen=True)
class ArchivalCopy:
    canonical_path: str
    canonical_filename: str
    archival_filename: str
    payload: bytes
    checksums: Checksums

    def audit_summary(self) -> dict[str, Any]:
        return {
            "canonical_path": self.canonical_path,
            "canonical_filename": self.canonical_filename,
            "archival_filename": self.archival_filename,
            "byte_size": self.checksums.byte_size,
            "sha256": self.checksums.sha256,
            "md5": self.checksums.md5,
            "bytes_changed": False,
        }


def require_approved_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict) or not manifest:
        raise ManifestApprovalError("an explicit architect-approved manifest is required")
    report = validate_manifest(manifest, manifest)
    if not report.passed:
        failures = [item.field for item in report.results if item.status == "fail"]
        raise ManifestApprovalError(
            "manifest preflight failed for approved fields: " + ", ".join(failures)
        )
    return manifest


def prepare_archival_copy(
    manifest: object, *, repository_root: str | Path
) -> ArchivalCopy:
    approved = require_approved_manifest(manifest)
    github = _object(approved, "github")
    zenodo = _object(approved, "zenodo")
    canonical_path = _string(github, "path")
    canonical_filename = _string(github, "canonical_filename")
    expected_canonical_path = str(
        PurePosixPath(_string(github, "directory")) / canonical_filename
    )
    if canonical_path != expected_canonical_path:
        raise ManifestApprovalError(
            "canonical path differs from the approved directory and filename"
        )
    version = _string(zenodo, "target_version")
    approved_archival_name = _string(zenodo, "archival_filename")
    expected_archival_name = archival_filename(canonical_filename, version)
    validate_archival_filename(canonical_filename, version, approved_archival_name)
    if approved_archival_name != expected_archival_name:
        raise ManifestApprovalError("approved archival filename does not match filename_vN")

    root = Path(repository_root).resolve()
    candidate = (root / canonical_path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ManifestApprovalError("canonical path escapes the repository root") from exc
    if not candidate.is_file():
        raise ManifestApprovalError("canonical path is not a regular file")
    payload = candidate.read_bytes()
    checksums = calculate_checksums(payload)

    manifest_values = {
        "github.byte_size": github.get("byte_size"),
        "github.sha256": github.get("sha256"),
        "github.md5": github.get("md5"),
        "zenodo.archival_byte_size": zenodo.get("archival_byte_size"),
        "zenodo.archival_sha256": zenodo.get("archival_sha256"),
        "zenodo.archival_md5": zenodo.get("archival_md5"),
    }
    observed_values = {
        "github.byte_size": checksums.byte_size,
        "github.sha256": checksums.sha256,
        "github.md5": checksums.md5,
        "zenodo.archival_byte_size": checksums.byte_size,
        "zenodo.archival_sha256": checksums.sha256,
        "zenodo.archival_md5": checksums.md5,
    }
    mismatches = [
        path for path, expected in manifest_values.items() if expected != observed_values[path]
    ]
    if mismatches:
        raise ManifestApprovalError(
            "canonical payload differs from approved manifest fields: " + ", ".join(mismatches)
        )

    return ArchivalCopy(
        canonical_path=canonical_path,
        canonical_filename=canonical_filename,
        archival_filename=approved_archival_name,
        payload=payload,
        checksums=checksums,
    )


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ManifestApprovalError(f"manifest field {key} must be an object")
    return result


def _string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ManifestApprovalError(f"manifest field {key} is required")
    return result
