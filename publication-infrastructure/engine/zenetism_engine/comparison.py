"""Non-mutating payload comparison."""

from __future__ import annotations

from .models import GitHubCandidate, PayloadComparison, ZenodoPublishedRecord


def compare_payloads(
    github: GitHubCandidate, zenodo: ZenodoPublishedRecord
) -> PayloadComparison:
    return PayloadComparison(
        payload_status="matching" if github.payload == zenodo.payload else "differing",
        byte_size_status=(
            "matching"
            if github.checksums.byte_size == zenodo.checksums.byte_size
            else "differing"
        ),
        sha256_status=(
            "matching" if github.checksums.sha256 == zenodo.checksums.sha256 else "differing"
        ),
        md5_status=(
            "matching" if github.checksums.md5 == zenodo.checksums.md5 else "differing"
        ),
    )
