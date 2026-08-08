from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from zenetism_engine.errors import SandboxAuthenticationError, SandboxSafetyError
from zenetism_engine.sandbox_boundary import (
    SANDBOX_API_BASE,
    RuntimeSandboxCredentials,
    require_sandbox_api_base,
    require_sandbox_request_url,
)


class SandboxBoundaryTests(unittest.TestCase):
    def test_official_sandbox_url_is_accepted(self) -> None:
        self.assertEqual(require_sandbox_api_base(SANDBOX_API_BASE), SANDBOX_API_BASE)
        self.assertEqual(
            require_sandbox_request_url(f"{SANDBOX_API_BASE}/records"),
            f"{SANDBOX_API_BASE}/records",
        )

    def test_production_and_lookalike_urls_are_rejected(self) -> None:
        rejected = (
            "https://zenodo.org/api",
            "https://zenodo.org/api/deposit/depositions",
            "http://sandbox.zenodo.org/api",
            "https://sandbox.zenodo.org.evil.example/api",
            "https://sandbox.zenodo.org:444/api",
            "https://sandbox.zenodo.org:bad/api",
            "https://name@sandbox.zenodo.org/api",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(SandboxSafetyError):
                require_sandbox_api_base(value)

    def test_request_must_remain_inside_sandbox_api_path(self) -> None:
        for value in (
            "https://zenodo.org/api/records/1",
            "https://sandbox.zenodo.org/records/1",
            "https://sandbox.zenodo.org/api/records/1?access_token=",
        ):
            with self.subTest(value=value), self.assertRaises(SandboxSafetyError):
                require_sandbox_request_url(value)

    def test_missing_token_fails_only_when_credentials_are_loaded(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SandboxAuthenticationError) as context:
                RuntimeSandboxCredentials.from_environment()
        self.assertIn("ZENODO_SANDBOX_TOKEN", str(context.exception))

    def test_credentials_are_redacted(self) -> None:
        credentials = RuntimeSandboxCredentials("unit-test-value")
        self.assertNotIn(credentials.token, repr(credentials))
        self.assertNotIn(credentials.token, str(credentials))


if __name__ == "__main__":
    unittest.main()
