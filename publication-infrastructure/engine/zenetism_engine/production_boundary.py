"""Closed Zenodo environment identities and production credential boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from .errors import ProductionCredentialError, ProductionSafetyError

PRODUCTION_TOKEN_ENV = "ZENODO_PRODUCTION_TOKEN"
PRODUCTION_REQUIRED_SCOPES = ("deposit:write", "deposit:actions")


class ZenodoEnvironment(str, Enum):
    """The only Zenodo environment identities recognized by the engine."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"

    @classmethod
    def parse(cls, value: object) -> "ZenodoEnvironment":
        if not isinstance(value, str):
            raise ProductionSafetyError("Zenodo environment identity must be a string")
        try:
            return cls(value)
        except ValueError:
            raise ProductionSafetyError(
                "Zenodo environment identity must be sandbox or production"
            ) from None


@dataclass(frozen=True)
class ZenodoEnvironmentDescriptor:
    """Fixed service identity without a configurable host surface."""

    identity: ZenodoEnvironment
    origin: str
    api_base: str

    def as_dict(self) -> dict[str, str]:
        return {
            "identity": self.identity.value,
            "origin": self.origin,
            "api_base": self.api_base,
        }


_ENVIRONMENTS = {
    ZenodoEnvironment.SANDBOX: ZenodoEnvironmentDescriptor(
        identity=ZenodoEnvironment.SANDBOX,
        origin="https://sandbox.zenodo.org",
        api_base="https://sandbox.zenodo.org/api",
    ),
    ZenodoEnvironment.PRODUCTION: ZenodoEnvironmentDescriptor(
        identity=ZenodoEnvironment.PRODUCTION,
        origin="https://zenodo.org",
        api_base="https://zenodo.org/api",
    ),
}


def environment_descriptor(value: ZenodoEnvironment) -> ZenodoEnvironmentDescriptor:
    """Resolve only an already-validated closed environment identity."""
    if not isinstance(value, ZenodoEnvironment):
        raise ProductionSafetyError(
            "Zenodo environment must be supplied as a closed environment identity"
        )
    return _ENVIRONMENTS[value]


def production_environment() -> ZenodoEnvironmentDescriptor:
    """Return the fixed production identity."""
    return environment_descriptor(ZenodoEnvironment.PRODUCTION)


@dataclass(frozen=True, repr=False)
class RuntimeProductionCredentials:
    """Runtime-only material for the later architect-approved production cycle."""

    token: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.token, str)
            or not self.token
            or self.token != self.token.strip()
            or any(character.isspace() for character in self.token)
        ):
            raise ProductionCredentialError("production credential value is invalid")

    @classmethod
    def from_environment(cls) -> "RuntimeProductionCredentials":
        """Load the separate production value only when a later cycle explicitly calls it."""
        token = os.environ.get(PRODUCTION_TOKEN_ENV, "")
        if not token.strip():
            raise ProductionCredentialError(
                f"production draft preparation requires {PRODUCTION_TOKEN_ENV} at runtime"
            )
        return cls(token=token.strip())

    def __repr__(self) -> str:
        return "RuntimeProductionCredentials(<redacted>)"

    def __str__(self) -> str:
        return "RuntimeProductionCredentials(<redacted>)"
