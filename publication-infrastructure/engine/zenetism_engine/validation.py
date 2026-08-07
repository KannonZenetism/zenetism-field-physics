"""Exact, fail-closed comparison of governed manifest values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .naming import VERSION_RE, validate_archival_filename

_MISSING = object()

REQUIRED_PATHS = (
    "schema_version",
    "record_key",
    "corpus_classification",
    "github.repository",
    "github.branch",
    "github.directory",
    "github.canonical_filename",
    "github.path",
    "github.commit",
    "github.blob_sha",
    "github.byte_size",
    "github.sha256",
    "github.md5",
    "zenodo.record_id",
    "zenodo.concept_record_id",
    "zenodo.exact_version_doi",
    "zenodo.concept_doi",
    "zenodo.previous_version_doi",
    "zenodo.target_version",
    "zenodo.record_revision",
    "zenodo.version_family_index",
    "zenodo.is_latest",
    "zenodo.publication_date",
    "zenodo.archival_filename",
    "zenodo.archival_byte_size",
    "zenodo.archival_checksum",
    "zenodo.archival_sha256",
    "zenodo.archival_md5",
    "zenodo.metadata.title",
    "zenodo.metadata.resource_type.id",
    "zenodo.metadata.resource_type.title",
    "zenodo.metadata.access",
    "zenodo.metadata.license.id",
    "zenodo.metadata.license.title",
    "zenodo.metadata.copyright",
    "zenodo.metadata.language",
    "zenodo.version_family",
    "creator.family_name",
    "creator.given_names",
    "creator.rendered_name",
    "contributors",
    "repository_url",
    "description.form",
    "description.rendered_html",
    "keywords",
    "related_identifiers",
    "site_relation.relation",
    "site_relation.scheme",
    "site_relation.resource_type",
    "site_relation.identifier",
    "preview.explicit_default_file",
    "preview.default_file",
    "comparison.payload_status",
    "comparison.byte_size_status",
    "comparison.sha256_status",
    "comparison.md5_status",
    "publication.architect_publish_required",
)


@dataclass(frozen=True)
class ValidationItem:
    field: str
    status: str
    expected: Any
    observed: Any
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "status": self.status,
            "expected": self.expected,
            "observed": self.observed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    results: tuple[ValidationItem, ...]

    def as_dict(self) -> dict[str, Any]:
        passed_count = sum(item.status == "pass" for item in self.results)
        return {
            "passed": self.passed,
            "summary": {
                "passed": passed_count,
                "failed": len(self.results) - passed_count,
            },
            "results": [item.as_dict() for item in self.results],
        }


def validate_manifest(
    expected: dict[str, Any], observed: dict[str, Any]
) -> ValidationReport:
    items: dict[str, ValidationItem] = {}
    governed = set(REQUIRED_PATHS)
    governed.update(_leaf_paths(expected))

    for path in sorted(governed):
        expected_value = _get_path(expected, path)
        observed_value = _get_path(observed, path)
        if path in REQUIRED_PATHS and _missing_required(expected_value, path):
            items[path] = _fail(path, expected_value, observed_value, "required governed value is missing from manifest")
        elif path in REQUIRED_PATHS and _missing_required(observed_value, path):
            items[path] = _fail(path, expected_value, observed_value, "required retrieved value is missing")
        elif expected_value is _MISSING:
            items[path] = _fail(path, None, _display(observed_value), "governed path is missing from manifest")
        elif observed_value is _MISSING:
            items[path] = _fail(path, _display(expected_value), None, "governed path is missing from retrieval")
        elif observed_value != expected_value:
            items[path] = _fail(path, expected_value, observed_value, "exact value mismatch")
        else:
            items[path] = ValidationItem(path, "pass", expected_value, observed_value, "exact match")

    for item in _invariant_results(observed):
        items[item.field] = item

    results = tuple(items[path] for path in sorted(items))
    return ValidationReport(
        passed=bool(results) and all(item.status == "pass" for item in results),
        results=results,
    )


def _invariant_results(observed: dict[str, Any]) -> Iterable[ValidationItem]:
    version = _get_path(observed, "zenodo.target_version")
    version_ok = isinstance(version, str) and VERSION_RE.fullmatch(version) is not None
    yield _check(
        "invariant.document_version_is_explicit_vN",
        "vN string",
        _display(version),
        version_ok,
        "document version comes only from Zenodo metadata.version; record revision is never a fallback",
    )

    revision = _get_path(observed, "zenodo.record_revision")
    yield _check(
        "invariant.record_revision_is_diagnostic_integer",
        "integer stored separately from document version",
        _display(revision),
        isinstance(revision, int) and not isinstance(revision, bool),
        "Zenodo record revision remains a diagnostic field",
    )

    is_latest = _get_path(observed, "zenodo.is_latest")
    yield _check(
        "invariant.current_record_is_latest_family_member",
        True,
        _display(is_latest),
        is_latest is True,
        "the current published record must be the latest exact version in its concept family",
    )

    exact = _get_path(observed, "zenodo.exact_version_doi")
    concept = _get_path(observed, "zenodo.concept_doi")
    doi_ok = isinstance(exact, str) and isinstance(concept, str) and exact != concept
    yield _check(
        "invariant.exact_doi_differs_from_concept_doi",
        "distinct DOI values",
        {"exact": _display(exact), "concept": _display(concept)},
        doi_ok,
        "exact-version and all-versions identifiers must remain distinct",
    )

    canonical = _get_path(observed, "github.canonical_filename")
    archival = _get_path(observed, "zenodo.archival_filename")
    naming_ok = False
    naming_reason = "archival name matches filename_vN.ext and has no upload-copy suffix"
    if isinstance(canonical, str) and isinstance(archival, str):
        try:
            validate_archival_filename(canonical, version, archival)
            naming_ok = True
        except Exception as exc:  # exact exception text belongs in the validation result
            naming_reason = str(exc)
    yield _check(
        "invariant.archival_filename",
        "canonical filename plus _vN",
        _display(archival),
        naming_ok,
        naming_reason,
    )

    for status_path in (
        "comparison.payload_status",
        "comparison.byte_size_status",
        "comparison.sha256_status",
        "comparison.md5_status",
    ):
        value = _get_path(observed, status_path)
        yield _check(
            f"invariant.{status_path.replace('.', '_')}",
            "matching",
            _display(value),
            value == "matching",
            "GitHub and Zenodo payload observations must match",
        )

    preview = _get_path(observed, "preview.default_file")
    preview_flag = _get_path(observed, "preview.explicit_default_file")
    yield _check(
        "invariant.default_preview_matches_archival_file",
        _display(archival),
        _display(preview),
        preview_flag is True and preview == archival,
        "the public default preview selection must identify the archival file",
    )

    yield _check(
        "invariant.architect_publish_gate",
        True,
        _display(_get_path(observed, "publication.architect_publish_required")),
        _get_path(observed, "publication.architect_publish_required") is True,
        "Stage 1 never provides a publication action",
    )


def _check(
    field: str, expected: Any, observed: Any, passed: bool, reason: str
) -> ValidationItem:
    return ValidationItem(field, "pass" if passed else "fail", expected, observed, reason)


def _fail(field: str, expected: Any, observed: Any, reason: str) -> ValidationItem:
    return ValidationItem(field, "fail", _display(expected), _display(observed), reason)


def _display(value: Any) -> Any:
    return None if value is _MISSING else value


def _missing_required(value: Any, path: str) -> bool:
    if value is _MISSING or value is None:
        return True
    if isinstance(value, str) and value == "":
        # The established creator convention intentionally has blank given names.
        return path != "creator.given_names"
    if path in {"keywords", "zenodo.version_family"} and value == []:
        return True
    return False


def _get_path(value: object, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _leaf_paths(value: object, prefix: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        if not value and prefix:
            yield prefix
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _leaf_paths(child, path)
    else:
        yield prefix
