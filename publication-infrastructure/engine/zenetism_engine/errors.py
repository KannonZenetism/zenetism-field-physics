"""Engine-specific failures with concise operator-facing messages."""


class PublicationEngineError(Exception):
    """Base error for deterministic Stage 1 failures."""


class RetrievalError(PublicationEngineError):
    """A required public record or file could not be retrieved."""


class RecordShapeError(PublicationEngineError):
    """A public API response omitted or changed a required structure."""


class VersionFamilyError(PublicationEngineError):
    """Exact-version and concept-family identity is invalid or ambiguous."""


class FilenameError(PublicationEngineError):
    """A canonical or archival filename violates the v2 convention."""
