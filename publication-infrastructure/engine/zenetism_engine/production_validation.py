"""Local verification-channel model for a future production draft."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import ProductionValidationError
from .sandbox_verification import (
    FAILED,
    PASSED_API,
    PASSED_VISUAL,
    VISUAL_VERIFICATION_REQUIRED,
    FieldVerification,
    VerificationReport,
)

_UI_VERIFICATION_FIELDS = frozenset({"metadata.copyright"})


@dataclass(frozen=True)
class ArchitectProductionVisualConfirmation:
    """Explicit architect confirmation for one future production draft."""

    draft_id: str
    fields: dict[str, Any]

    @classmethod
    def from_object(cls, value: object) -> "ArchitectProductionVisualConfirmation":
        if not isinstance(value, dict):
            raise ProductionValidationError(
                "production visual confirmation must contain a JSON object"
            )
        if value.get("environment") != "production":
            raise ProductionValidationError(
                "production visual confirmation requires the closed production identity"
            )
        if value.get("confirmed_by") != "architect":
            raise ProductionValidationError(
                "production visual confirmation must be explicitly confirmed by architect"
            )
        if value.get("verification_channel") != "visual":
            raise ProductionValidationError(
                "production visual confirmation channel must be visual"
            )
        draft_id = value.get("draft_id")
        if not isinstance(draft_id, str) or not draft_id.isdecimal():
            raise ProductionValidationError(
                "production visual confirmation requires a numeric draft identifier"
            )
        fields = value.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ProductionValidationError(
                "production visual confirmation requires explicit field values"
            )
        unexpected = sorted(set(fields) - _UI_VERIFICATION_FIELDS)
        if unexpected:
            raise ProductionValidationError(
                "production visual confirmation contains an API-verifiable or unsupported field: "
                + ", ".join(unexpected)
            )
        return cls(draft_id=draft_id, fields=deepcopy(fields))

    def value_for(self, field: str, *, expected_draft_id: str) -> tuple[bool, Any]:
        if self.draft_id != expected_draft_id:
            raise ProductionValidationError(
                "production visual confirmation draft differs from the validated draft"
            )
        if field not in self.fields:
            return False, None
        return True, deepcopy(self.fields[field])


def validate_production_metadata(
    expected: object,
    observed: object,
    *,
    draft_id: str,
    architect_visual_confirmation: ArchitectProductionVisualConfirmation | None = None,
) -> VerificationReport:
    """Validate manifest-controlled metadata without granting an unavailable field an API pass."""
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        raise ProductionValidationError(
            "production metadata validation requires JSON objects"
        )
    if not expected:
        raise ProductionValidationError(
            "production metadata validation requires manifest-controlled fields"
        )
    if not isinstance(draft_id, str) or not draft_id.isdecimal():
        raise ProductionValidationError(
            "production metadata validation requires a numeric draft identifier"
        )

    resolved_values = _resolved_api_values(expected, observed)
    fields: list[FieldVerification] = []
    for path, expected_value in _leaf_values(expected):
        field = ".".join(path)
        if field in resolved_values:
            present, observed_value = True, deepcopy(resolved_values[field])
        else:
            present, observed_value = _path_value(observed, path)
        if field in _UI_VERIFICATION_FIELDS and not present:
            fields.append(
                _visual_field(
                    field,
                    expected_value,
                    draft_id=draft_id,
                    confirmation=architect_visual_confirmation,
                )
            )
            continue
        if not present:
            fields.append(
                _failed(
                    field,
                    expected_value,
                    None,
                    "required API-verifiable field is missing",
                )
            )
            continue
        if type(observed_value) is not type(expected_value) or observed_value != expected_value:
            fields.append(
                _failed(
                    field,
                    expected_value,
                    observed_value,
                    "API read-back differs from the manifest-controlled value",
                )
            )
            continue
        fields.append(
            FieldVerification(
                field=field,
                state=PASSED_API,
                channel="api",
                expected=deepcopy(expected_value),
                observed=deepcopy(observed_value),
            )
        )

    if not fields:
        raise ProductionValidationError(
            "production metadata validation found no manifest-controlled fields"
        )
    report = VerificationReport(tuple(fields))
    if report.has_failures:
        failed_fields = ", ".join(
            item.field for item in report.fields if item.state == FAILED
        )
        raise ProductionValidationError(
            "production metadata read-back validation failed: " + failed_fields
        )
    return report


def _resolved_api_values(
    expected: dict[str, Any], observed: dict[str, Any]
) -> dict[str, Any]:
    """Reconcile only explicit modern and supported legacy API representations."""
    resolved: dict[str, Any] = {}
    metadata = observed.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    _resolve_access(expected, observed, metadata, resolved)
    _resolve_resource_type(expected, metadata, resolved)
    _resolve_rights(expected, metadata, resolved)
    _resolve_language(expected, metadata, resolved)
    _resolve_people(expected, metadata, resolved)
    _resolve_repository_url(expected, observed, metadata, resolved)
    _resolve_keywords(expected, metadata, resolved)
    _resolve_related_identifiers(expected, metadata, resolved)
    _resolve_one_file_order(expected, observed, resolved)
    return resolved


def _resolve_access(
    expected: dict[str, Any],
    observed: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    expected_access = expected.get("access")
    if not isinstance(expected_access, dict):
        return
    modern = observed.get("access")
    modern = modern if isinstance(modern, dict) else {}
    legacy_present = "access_right" in metadata
    legacy_value = metadata.get("access_right")
    legacy_access = (
        {"record": "public", "files": "public"}
        if legacy_value == "open"
        else {"record": legacy_value, "files": legacy_value}
    )
    for key in ("record", "files"):
        field = f"access.{key}"
        if key not in expected_access:
            continue
        candidates: list[Any] = []
        if key in modern:
            candidates.append(modern[key])
        if legacy_present:
            candidates.append(legacy_access[key])
        _resolve_candidates(field, candidates, resolved)


def _resolve_resource_type(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, _ = _path_value(expected, ("metadata", "resource_type", "id"))
    if not present:
        return
    value = metadata.get("resource_type")
    if not isinstance(value, dict):
        return
    candidates: list[Any] = []
    if "id" in value:
        candidates.append(value["id"])
    legacy_keys = {"title", "type", "subtype"}
    if "id" not in value and legacy_keys.intersection(value):
        legacy_id: Any = (
            "publication-report"
            if {
                "title": value.get("title"),
                "type": value.get("type"),
                "subtype": value.get("subtype"),
            }
            == {"title": "Report", "type": "publication", "subtype": "report"}
            else deepcopy(value)
        )
        candidates.append(legacy_id)
    _resolve_candidates("metadata.resource_type.id", candidates, resolved)


def _resolve_rights(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, _ = _path_value(expected, ("metadata", "rights"))
    if not present:
        return
    candidates: list[Any] = []
    if "rights" in metadata:
        candidates.append(deepcopy(metadata["rights"]))
    if "license" in metadata:
        license_value = metadata["license"]
        if isinstance(license_value, dict) and set(license_value) == {"id"}:
            candidates.append([{"id": license_value["id"]}])
        else:
            candidates.append(deepcopy(license_value))
    _resolve_candidates("metadata.rights", candidates, resolved)


def _resolve_language(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, _ = _path_value(expected, ("metadata", "languages"))
    if not present:
        return
    candidates: list[Any] = []
    if "languages" in metadata:
        candidates.append(deepcopy(metadata["languages"]))
    if "language" in metadata:
        candidates.append([{"id": metadata["language"]}])
    _resolve_candidates("metadata.languages", candidates, resolved)


def _resolve_people(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    for key, contributor in (("creators", False), ("contributors", True)):
        present, expected_people = _path_value(expected, ("metadata", key))
        if not present or key not in metadata:
            continue
        observed_people = metadata[key]
        resolved[f"metadata.{key}"] = _canonical_people(
            observed_people,
            expected_people,
            contributor=contributor,
        )


def _canonical_people(
    observed: Any,
    expected: Any,
    *,
    contributor: bool,
) -> Any:
    if not isinstance(observed, list) or not isinstance(expected, list):
        return deepcopy(observed)
    if len(observed) != len(expected):
        return deepcopy(observed)
    for observed_item, expected_item in zip(observed, expected):
        if not isinstance(observed_item, dict) or not isinstance(expected_item, dict):
            return deepcopy(observed)
        person = expected_item.get("person_or_org")
        if not isinstance(person, dict):
            return deepcopy(observed)
        expected_name = person.get("family_name")
        if (
            person.get("type") != "personal"
            or person.get("given_name") != ""
            or not isinstance(expected_name, str)
            or not expected_name
        ):
            return deepcopy(observed)

        modern_present = "person_or_org" in observed_item
        legacy_present = "name" in observed_item
        candidates: list[Any] = []
        if modern_present:
            expected_keys = set(expected_item)
            legacy_keys = (
                {"name", "affiliation", "type"}
                if contributor
                else {"name", "affiliation"}
            )
            allowed_keys = expected_keys | (legacy_keys if legacy_present else set())
            modern_projection = {
                key: deepcopy(observed_item.get(key)) for key in expected_keys
            }
            candidates.append(
                expected_name
                if set(observed_item) == allowed_keys
                and modern_projection == expected_item
                else deepcopy(observed_item)
            )
        if legacy_present:
            required_keys = {"name", "affiliation", "type"} if contributor else {
                "name",
                "affiliation",
            }
            allowed_keys = required_keys | (
                set(expected_item) if modern_present else set()
            )
            legacy_name: Any = (
                observed_item.get("name")
                if set(observed_item) == allowed_keys
                and observed_item.get("affiliation") is None
                else deepcopy(observed_item)
            )
            if contributor:
                role = expected_item.get("role")
                expected_type = (
                    "Researcher"
                    if role == {"id": "researcher"}
                    else None
                )
                if observed_item.get("type") != expected_type:
                    legacy_name = deepcopy(observed_item)
            candidates.append(legacy_name)
        if not candidates:
            return deepcopy(observed)
        if any(candidate != candidates[0] for candidate in candidates[1:]):
            raise ProductionValidationError(
                "production modern and legacy person representations conflict"
            )
        if candidates[0] != expected_name:
            return deepcopy(observed)
    return deepcopy(expected)


def _resolve_repository_url(
    expected: dict[str, Any],
    observed: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    field = "custom_fields.code:codeRepository"
    present, _ = _path_value(
        expected, ("custom_fields", "code:codeRepository")
    )
    if not present:
        return
    candidates: list[Any] = []
    modern = observed.get("custom_fields")
    if isinstance(modern, dict) and "code:codeRepository" in modern:
        candidates.append(modern["code:codeRepository"])
    legacy = metadata.get("custom")
    if isinstance(legacy, dict) and "code:codeRepository" in legacy:
        candidates.append(legacy["code:codeRepository"])
    _resolve_candidates(field, candidates, resolved)


def _resolve_keywords(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, _ = _path_value(expected, ("metadata", "subjects"))
    if not present:
        return
    candidates: list[Any] = []
    if "subjects" in metadata:
        candidates.append(deepcopy(metadata["subjects"]))
    if "keywords" in metadata:
        keywords = metadata["keywords"]
        candidates.append(
            [{"subject": item} for item in keywords]
            if isinstance(keywords, list)
            and all(isinstance(item, str) for item in keywords)
            else deepcopy(keywords)
        )
    _resolve_candidates("metadata.subjects", candidates, resolved)


def _resolve_related_identifiers(
    expected: dict[str, Any],
    metadata: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, expected_relations = _path_value(
        expected, ("metadata", "related_identifiers")
    )
    if not present or "related_identifiers" not in metadata:
        return
    observed_relations = metadata["related_identifiers"]
    resolved["metadata.related_identifiers"] = _canonical_related_identifiers(
        observed_relations,
        expected_relations,
    )


def _canonical_related_identifiers(observed: Any, expected: Any) -> Any:
    if not isinstance(observed, list) or not isinstance(expected, list):
        return deepcopy(observed)
    if len(observed) != len(expected):
        return deepcopy(observed)
    for observed_item, expected_item in zip(observed, expected):
        if not isinstance(observed_item, dict) or not isinstance(expected_item, dict):
            return deepcopy(observed)
        expected_identity = (
            expected_item.get("identifier"),
            expected_item.get("scheme"),
            _path_value(expected_item, ("relation_type", "id"))[1],
            _path_value(expected_item, ("resource_type", "id"))[1],
        )
        modern_present = "relation_type" in observed_item or isinstance(
            observed_item.get("resource_type"), dict
        )
        legacy_present = "relation" in observed_item or isinstance(
            observed_item.get("resource_type"), str
        )
        candidates: list[tuple[Any, Any, Any, Any] | Any] = []
        if modern_present:
            candidates.append(
                expected_identity
                if not legacy_present and observed_item == expected_item
                else deepcopy(observed_item)
            )
        if legacy_present:
            relation = observed_item.get("relation")
            candidates.append(
                (
                    observed_item.get("identifier"),
                    observed_item.get("scheme"),
                    "isdocumentedby" if relation == "isDocumentedBy" else relation,
                    observed_item.get("resource_type"),
                )
                if not modern_present
                and set(observed_item)
                == {"identifier", "relation", "resource_type", "scheme"}
                else deepcopy(observed_item)
            )
        if not candidates:
            return deepcopy(observed)
        if any(candidate != candidates[0] for candidate in candidates[1:]):
            raise ProductionValidationError(
                "production modern and legacy related-identifier representations conflict"
            )
        if candidates[0] != expected_identity:
            return deepcopy(observed)
    return deepcopy(expected)


def _resolve_one_file_order(
    expected: dict[str, Any],
    observed: dict[str, Any],
    resolved: dict[str, Any],
) -> None:
    present, expected_order = _path_value(expected, ("files", "order"))
    if not present:
        return
    files = observed.get("files")
    if not isinstance(files, dict) or "order" not in files:
        return
    observed_order = files["order"]
    if observed_order == expected_order:
        resolved["files.order"] = deepcopy(expected_order)
        return
    if (
        observed_order == []
        and isinstance(expected_order, list)
        and len(expected_order) == 1
        and files.get("default_preview") == expected_order[0]
        and isinstance(files.get("entries"), dict)
        and set(files["entries"]) == {expected_order[0]}
        and isinstance(files["entries"][expected_order[0]], dict)
        and files["entries"][expected_order[0]].get("status") == "completed"
    ):
        resolved["files.order"] = deepcopy(expected_order)


def _resolve_candidates(
    field: str,
    candidates: list[Any],
    resolved: dict[str, Any],
) -> None:
    if not candidates:
        return
    if any(
        type(candidate) is not type(candidates[0]) or candidate != candidates[0]
        for candidate in candidates[1:]
    ):
        raise ProductionValidationError(
            f"production modern and legacy representations conflict for {field}"
        )
    resolved[field] = deepcopy(candidates[0])


def _visual_field(
    field: str,
    expected: Any,
    *,
    draft_id: str,
    confirmation: ArchitectProductionVisualConfirmation | None,
) -> FieldVerification:
    if confirmation is None:
        return FieldVerification(
            field=field,
            state=VISUAL_VERIFICATION_REQUIRED,
            channel="visual",
            expected=deepcopy(expected),
            observed=None,
            detail="field is unavailable through the supported API read-back",
        )
    try:
        present, observed = confirmation.value_for(
            field, expected_draft_id=draft_id
        )
    except ProductionValidationError as exc:
        return _failed(field, expected, None, str(exc), channel="visual")
    if not present:
        return FieldVerification(
            field=field,
            state=VISUAL_VERIFICATION_REQUIRED,
            channel="visual",
            expected=deepcopy(expected),
            observed=None,
            detail="explicit architect confirmation does not include this field",
        )
    if type(observed) is not type(expected) or observed != expected:
        return _failed(
            field,
            expected,
            observed,
            "architect-confirmed value differs from the manifest-controlled value",
            channel="visual",
        )
    return FieldVerification(
        field=field,
        state=PASSED_VISUAL,
        channel="visual",
        expected=deepcopy(expected),
        observed=deepcopy(observed),
        detail="explicit architect visual confirmation",
    )


def _leaf_values(value: dict[str, Any], prefix: tuple[str, ...] = ()):
    for key in sorted(value):
        current = prefix + (key,)
        item = value[key]
        if isinstance(item, dict):
            yield from _leaf_values(item, current)
        else:
            yield current, item


def _path_value(value: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    current: object = value
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, deepcopy(current)


def _failed(
    field: str,
    expected: Any,
    observed: Any,
    detail: str,
    *,
    channel: str = "api",
) -> FieldVerification:
    return FieldVerification(
        field=field,
        state=FAILED,
        channel=channel,
        expected=deepcopy(expected),
        observed=deepcopy(observed),
        detail=detail,
    )
