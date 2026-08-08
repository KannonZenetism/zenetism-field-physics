"""Verification-channel states and explicit architect visual confirmations."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DraftValidationError

PASSED_API = "passed_api"
VISUAL_VERIFICATION_REQUIRED = "visual_verification_required"
PASSED_VISUAL = "passed_visual"
FAILED = "failed"
VERIFICATION_STATES = frozenset(
    {PASSED_API, VISUAL_VERIFICATION_REQUIRED, PASSED_VISUAL, FAILED}
)


@dataclass(frozen=True)
class ArchitectVisualConfirmation:
    """One explicit architect confirmation tied to one Sandbox draft."""

    sandbox_draft_id: str
    fields: dict[str, Any]

    @classmethod
    def from_object(cls, value: object) -> "ArchitectVisualConfirmation":
        if not isinstance(value, dict):
            raise DraftValidationError(
                "architect visual confirmation must contain a JSON object"
            )
        draft_id = value.get("sandbox_draft_id")
        if not isinstance(draft_id, str) or not draft_id:
            raise DraftValidationError(
                "architect visual confirmation requires sandbox_draft_id"
            )
        if value.get("confirmed_by") != "architect":
            raise DraftValidationError(
                "visual confirmation must be explicitly confirmed_by architect"
            )
        if value.get("verification_channel") != "visual":
            raise DraftValidationError(
                "architect confirmation verification_channel must be visual"
            )
        fields = value.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise DraftValidationError(
                "architect visual confirmation requires explicit field values"
            )
        for field, observed in fields.items():
            if not isinstance(field, str) or not field:
                raise DraftValidationError(
                    "architect visual confirmation field names must be non-empty strings"
                )
            if not isinstance(observed, (str, int, bool)):
                raise DraftValidationError(
                    f"architect visual confirmation field {field} has an unsupported value"
                )
        return cls(sandbox_draft_id=draft_id, fields=deepcopy(fields))

    def value_for(self, field: str, *, expected_draft_id: str) -> tuple[bool, Any]:
        if self.sandbox_draft_id != expected_draft_id:
            raise DraftValidationError(
                "architect visual confirmation draft identifier differs from the validated draft"
            )
        if field not in self.fields:
            return False, None
        return True, deepcopy(self.fields[field])


def load_architect_visual_confirmation(path: str | Path) -> ArchitectVisualConfirmation:
    """Load one explicit draft-specific architect visual confirmation."""
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    return ArchitectVisualConfirmation.from_object(value)


@dataclass(frozen=True)
class FieldVerification:
    """One manifest-controlled field evaluated through one verification channel."""

    field: str
    state: str
    channel: str
    expected: Any
    observed: Any
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.state not in VERIFICATION_STATES:
            raise ValueError(f"unsupported verification state: {self.state}")

    def as_dict(self) -> dict[str, Any]:
        result = {
            "field": self.field,
            "state": self.state,
            "channel": self.channel,
            "expected": deepcopy(self.expected),
            "observed": deepcopy(self.observed),
        }
        if self.detail is not None:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True)
class VerificationReport:
    """Complete field-state report for one saved Sandbox draft."""

    fields: tuple[FieldVerification, ...]

    @property
    def complete(self) -> bool:
        return all(item.state in {PASSED_API, PASSED_VISUAL} for item in self.fields)

    @property
    def has_failures(self) -> bool:
        return any(item.state == FAILED for item in self.fields)

    @property
    def visual_verification_required(self) -> bool:
        return any(
            item.state == VISUAL_VERIFICATION_REQUIRED for item in self.fields
        )

    def as_dict(self) -> dict[str, Any]:
        state_counts = {
            state: sum(item.state == state for item in self.fields)
            for state in sorted(VERIFICATION_STATES)
        }
        return {
            "complete": self.complete,
            "passed": self.complete,
            "visual_verification_required": self.visual_verification_required,
            "state_counts": state_counts,
            "fields": [item.as_dict() for item in self.fields],
        }
