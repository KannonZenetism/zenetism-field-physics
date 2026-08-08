"""Payload hashing shared by both archival surfaces."""

from __future__ import annotations

import hashlib

from .models import Checksums


def calculate_checksums(payload: bytes) -> Checksums:
    return Checksums(
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        md5=hashlib.md5(payload).hexdigest(),  # noqa: S324 - archival comparison, not security
    )
