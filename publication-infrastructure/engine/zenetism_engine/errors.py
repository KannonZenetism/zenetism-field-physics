"""Engine-specific failures with concise diagnostic messages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class PublicationEngineError(Exception):
    """Base error for deterministic Publication Engine failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._recovery: dict[str, Any] | None = None

    @property
    def recovery(self) -> dict[str, Any] | None:
        """Return safe draft-recovery data attached after draft creation."""
        return deepcopy(self._recovery)

    def attach_recovery(self, recovery: dict[str, Any]) -> None:
        """Preserve the first safe recovery identity attached to this failure."""
        if self._recovery is None:
            self._recovery = deepcopy(recovery)


class RetrievalError(PublicationEngineError):
    """A required public record or file could not be retrieved."""


class RecordShapeError(PublicationEngineError):
    """A public API response omitted or changed a required structure."""


class VersionFamilyError(PublicationEngineError):
    """Exact-version and concept-family identity is invalid or ambiguous."""


class FilenameError(PublicationEngineError):
    """A canonical or archival filename violates the v2 convention."""


class SandboxSafetyError(PublicationEngineError):
    """A proposed write falls outside the fixed Sandbox safety boundary."""


class SandboxAuthenticationError(PublicationEngineError):
    """Runtime Sandbox authentication is absent or invalid."""


class ManifestApprovalError(PublicationEngineError):
    """An explicit approved manifest is absent or fails preflight."""


class SandboxRequestError(PublicationEngineError):
    """A Sandbox request failed without disclosing authentication material."""


class DraftValidationError(PublicationEngineError):
    """The saved Sandbox draft differs from the approved manifest."""


class ProductionSafetyError(PublicationEngineError):
    """A production-draft proposal falls outside the closed safety boundary."""


class ProductionFamilyError(PublicationEngineError):
    """Production record-family identity is missing, conflicting, or ambiguous."""


class ProductionPlanError(PublicationEngineError):
    """A local production-draft plan cannot be completed safely."""


class ProductionValidationError(PublicationEngineError):
    """Production draft read-back differs from the manifest-controlled package."""
