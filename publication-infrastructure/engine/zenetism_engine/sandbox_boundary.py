"""Hard boundary for Zenodo Sandbox writes and runtime-only credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .errors import SandboxAuthenticationError, SandboxSafetyError

SANDBOX_ORIGIN = "https://sandbox.zenodo.org"
SANDBOX_API_BASE = f"{SANDBOX_ORIGIN}/api"
SANDBOX_TOKEN_ENV = "ZENODO_SANDBOX_TOKEN"


def require_sandbox_api_base(value: str) -> str:
    """Return the one permitted API base or reject the proposed write surface."""
    parsed = urlsplit(value.strip())
    port = _safe_port(parsed)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sandbox.zenodo.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/api"}
    ):
        raise SandboxSafetyError(
            "write base must be the official Zenodo Sandbox HTTPS origin or API base"
        )
    return SANDBOX_API_BASE


def require_sandbox_request_url(value: str) -> str:
    """Reject every request URL outside the exact Sandbox API origin."""
    parsed = urlsplit(value)
    port = _safe_port(parsed)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sandbox.zenodo.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/api/")
    ):
        raise SandboxSafetyError("write request is outside the Zenodo Sandbox API allowlist")
    return urlunsplit(("https", "sandbox.zenodo.org", parsed.path, "", ""))


def _safe_port(parsed: SplitResult) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise SandboxSafetyError("write URL contains an invalid port") from exc


@dataclass(frozen=True, repr=False)
class RuntimeSandboxCredentials:
    """Authentication material that is never serialized into plans or diagnostics."""

    token: str

    def __post_init__(self) -> None:
        if not self.token or any(character.isspace() for character in self.token):
            raise SandboxAuthenticationError("Sandbox authentication value is invalid")

    @classmethod
    def from_environment(cls) -> "RuntimeSandboxCredentials":
        token = os.environ.get(SANDBOX_TOKEN_ENV, "")
        if not token.strip():
            raise SandboxAuthenticationError(
                f"Sandbox authentication requires {SANDBOX_TOKEN_ENV} at runtime"
            )
        return cls(token=token.strip())

    def __repr__(self) -> str:
        return "RuntimeSandboxCredentials(<redacted>)"

    def __str__(self) -> str:
        return "RuntimeSandboxCredentials(<redacted>)"
