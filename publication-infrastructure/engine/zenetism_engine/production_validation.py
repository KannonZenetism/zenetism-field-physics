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

    fields: list[FieldVerification] = []
    for path, expected_value in _leaf_values(expected):
        present, observed_value = _path_value(observed, path)
        field = ".".join(path)
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
