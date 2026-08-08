"""Engine-specific failures with concise diagnostic messages."""


class PublicationEngineError(Exception):
    """Base error for deterministic Publication Engine failures."""


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
