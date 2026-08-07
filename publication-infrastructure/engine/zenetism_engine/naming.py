"""Zenetism v2 canonical-to-archival filename rules."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .errors import FilenameError

VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")
UPLOAD_COPY_SUFFIX_RE = re.compile(r"\s*\([0-9]+\)$")


def require_document_version(value: object) -> str:
    """Accept only explicit document labels; never coerce a revision integer."""
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise FilenameError(f"document version must match vN, received {value!r}")
    return value


def reject_upload_copy_suffix(filename: str) -> None:
    path = PurePosixPath(filename)
    if UPLOAD_COPY_SUFFIX_RE.search(path.stem):
        raise FilenameError(f"upload-copy suffix is prohibited: {filename}")


def archival_filename(canonical_filename: str, version_label: object) -> str:
    version = require_document_version(version_label)
    path = PurePosixPath(canonical_filename)
    if path.name != canonical_filename or not path.suffix or path.stem == "":
        raise FilenameError(f"canonical filename must be one basename with an extension: {canonical_filename}")
    reject_upload_copy_suffix(canonical_filename)
    return f"{path.stem}_{version}{path.suffix}"


def validate_archival_filename(
    canonical_filename: str, version_label: object, observed_filename: str
) -> None:
    reject_upload_copy_suffix(observed_filename)
    expected = archival_filename(canonical_filename, version_label)
    if observed_filename != expected:
        raise FilenameError(
            f"archival filename mismatch: expected {expected!r}, received {observed_filename!r}"
        )
