"""Immutable normalized observations from public GitHub and Zenodo data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Checksums:
    byte_size: int
    sha256: str
    md5: str


@dataclass(frozen=True)
class GitHubCandidate:
    repository: str
    branch: str
    directory: str
    canonical_filename: str
    path: str
    branch_head_commit: str
    commit: str
    blob_sha: str
    checksums: Checksums
    payload: bytes


@dataclass(frozen=True)
class Person:
    name: str
    family_name: str
    given_names: str
    role: str | None = None


@dataclass(frozen=True)
class RelatedIdentifier:
    identifier: str
    relation: str
    scheme: str
    resource_type: str


@dataclass(frozen=True)
class VersionMember:
    record_id: str
    exact_version_doi: str
    version_label: str | None
    record_revision: int | None
    family_index: int | None
    is_latest: bool


@dataclass(frozen=True)
class ZenodoPublishedRecord:
    requested_identifier: str
    record_id: str
    concept_record_id: str
    exact_version_doi: str
    concept_doi: str
    version_label: str | None
    record_revision: int | None
    family_index: int | None
    is_latest: bool
    publication_date: str | None
    archival_filename: str
    advertised_checksum: str
    checksums: Checksums
    payload: bytes
    title: str | None
    description: str | None
    keywords: tuple[str, ...]
    creator: Person | None
    contributors: tuple[Person, ...]
    repository_url: str | None
    related_identifiers: tuple[RelatedIdentifier, ...]
    copyright: str | None
    resource_type_id: str | None
    resource_type_title: str | None
    access: str | None
    license_id: str | None
    license_title: str | None
    language: str | None
    default_preview: str | None
    version_family: tuple[VersionMember, ...]
    raw_metadata: dict[str, Any]


@dataclass(frozen=True)
class PayloadComparison:
    payload_status: str
    byte_size_status: str
    sha256_status: str
    md5_status: str

    @property
    def matches(self) -> bool:
        return self.payload_status == "matching"


@dataclass(frozen=True)
class Observation:
    github: GitHubCandidate
    zenodo: ZenodoPublishedRecord
    comparison: PayloadComparison
