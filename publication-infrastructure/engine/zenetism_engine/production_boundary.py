"""Closed Zenodo environment identities for Stage 3A planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import ProductionSafetyError


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
    """Return the fixed production identity for plan-only Stage 3A work."""
    return environment_descriptor(ZenodoEnvironment.PRODUCTION)
