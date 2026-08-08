from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import zenetism_engine.sandbox_writer as sandbox_writer_module
from zenetism_engine.cli import main, parser
from zenetism_engine.errors import (
    DraftValidationError,
    ManifestApprovalError,
    SandboxAuthenticationError,
    SandboxRequestError,
    SandboxSafetyError,
)
from zenetism_engine.sandbox_boundary import RuntimeSandboxCredentials
from zenetism_engine.sandbox_writer import (
    SandboxDraftWriter,
    UrllibSandboxTransport,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "publication-infrastructure/manifests/zenetism-in-plain-language-v2.json"


class _NoRequestTransport:
    def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run sent a request")


class _FakeSandboxTransport:
    def __init__(
        self,
        *,
        corrupt_version: bool = False,
        diagnostic_error: str | None = None,
        reserved_doi: str = "10.5072/zenodo.701",
        reloaded_doi: str | None = None,
    ):
        self.corrupt_version = corrupt_version
        self.diagnostic_error = diagnostic_error
        self.reserved_doi = reserved_doi
        self.reloaded_doi = reloaded_doi or reserved_doi
        self.requests: list[dict[str, object]] = []
        self.saved_payload: dict[str, object] | None = None
        self.source_concept = "10.5072/zenodo.700"

    def request(
        self,
        method: str,
        url: str,
        *,
        credentials: RuntimeSandboxCredentials,
        json_body=None,
        binary_body=None,
    ) -> dict[str, object]:
        if self.diagnostic_error is not None:
            raise RuntimeError(self.diagnostic_error)
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json_body": copy.deepcopy(json_body),
                "binary_size": len(binary_body) if binary_body is not None else None,
            }
        )
        if method == "GET" and url.endswith("/api/records/source-1"):
            return {"parent": {"pids": {"doi": {"identifier": self.source_concept}}}}
        if method == "POST" and url.endswith("/versions"):
            return {"id": "draft-123"}
        if method == "POST" and url.endswith("/api/records"):
            return {"id": "draft-123"}
        if method == "POST" and url.endswith("/draft/pids/doi"):
            return {"pids": {"doi": {"identifier": self.reserved_doi}}}
        if method == "PUT" and url.endswith("/draft"):
            self.saved_payload = copy.deepcopy(json_body)
            return {"id": "draft-123"}
        if method == "GET" and url.endswith("/draft"):
            if self.saved_payload is None:
                raise AssertionError("draft was reloaded before it was saved")
            result = copy.deepcopy(self.saved_payload)
            if self.corrupt_version:
                result["metadata"]["version"] = "v99"  # type: ignore[index]
            result.update(
                {
                    "id": "draft-123",
                    "status": "draft",
                    "is_published": False,
                    "pids": {"doi": {"identifier": self.reloaded_doi}},
                    "parent": {"pids": {"doi": {"identifier": self.source_concept}}},
                }
            )
            return result
        if method == "GET" and "/draft/files/" in url:
            assert self.saved_payload is not None
            filename = self.saved_payload["files"]["default_preview"]  # type: ignore[index]
            return {
                "key": filename,
                "size": 13414,
                "checksum": "md5:ea3b7e4230d7c43940657c6a1116075c",
                "status": "completed",
            }
        return {}


class SandboxWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_dry_run_is_default_and_needs_no_token(self) -> None:
        credentials_loaded = False

        def load_credentials():
            nonlocal credentials_loaded
            credentials_loaded = True
            raise AssertionError("dry-run loaded credentials")

        writer = SandboxDraftWriter(
            transport=_NoRequestTransport(), credential_loader=load_credentials
        )
        result = writer.run(self.manifest, repository_root=ROOT)
        self.assertTrue(result.dry_run)
        self.assertFalse(credentials_loaded)
        self.assertEqual(result.audit["requests_sent"], 0)
        self.assertEqual(len(result.audit["requests"]), 8)
        self.assertFalse(result.audit["final_release_action_available"])

    def test_manifest_is_required(self) -> None:
        with self.assertRaises(ManifestApprovalError):
            SandboxDraftWriter().run({}, repository_root=ROOT)

    def test_execute_without_runtime_token_stops_before_any_request(self) -> None:
        fake = _FakeSandboxTransport()
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SandboxAuthenticationError):
                SandboxDraftWriter(transport=fake).run(
                    self.manifest, repository_root=ROOT, dry_run=False
                )
        self.assertEqual(fake.requests, [])

    def test_execute_saves_reloads_and_validates_an_unpublished_draft(self) -> None:
        fake = _FakeSandboxTransport()
        writer = SandboxDraftWriter(
            transport=fake,
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        )
        result = writer.run(self.manifest, repository_root=ROOT, dry_run=False)
        self.assertFalse(result.dry_run)
        self.assertEqual(result.validation["draft_state"], "unpublished")  # type: ignore[index]
        self.assertEqual(
            result.validation["default_preview"],  # type: ignore[index]
            "zenetism-in-plain-language_v2.md",
        )
        self.assertEqual(result.audit["requests_sent"], 8)
        self.assertEqual(
            [item["method"] for item in fake.requests],
            ["POST", "POST", "POST", "PUT", "POST", "PUT", "GET", "GET"],
        )
        rendered = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertNotIn("unit-test-value", rendered)

    def test_new_version_mode_preserves_the_source_concept_doi(self) -> None:
        fake = _FakeSandboxTransport()
        result = SandboxDraftWriter(
            transport=fake,
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        ).run(
            self.manifest,
            repository_root=ROOT,
            mode="new-version",
            source_record_id="source-1",
            dry_run=False,
        )
        self.assertTrue(result.validation["concept_doi_preserved"])  # type: ignore[index]
        self.assertEqual(result.audit["requests_sent"], 9)
        self.assertEqual(fake.requests[0]["method"], "GET")
        self.assertTrue(str(fake.requests[1]["url"]).endswith("/source-1/versions"))

    def test_saved_draft_mismatch_fails_closed(self) -> None:
        writer = SandboxDraftWriter(
            transport=_FakeSandboxTransport(corrupt_version=True),
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        )
        with self.assertRaises(DraftValidationError) as context:
            writer.run(self.manifest, repository_root=ROOT, dry_run=False)
        self.assertIn("metadata.version differs", str(context.exception))

    def test_reserved_doi_mismatch_fails_closed(self) -> None:
        writer = SandboxDraftWriter(
            transport=_FakeSandboxTransport(reloaded_doi="10.5072/zenodo.999"),
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        )
        with self.assertRaises(DraftValidationError) as context:
            writer.run(self.manifest, repository_root=ROOT, dry_run=False)
        self.assertIn("reloaded DOI differs", str(context.exception))

    def test_transport_errors_do_not_disclose_credentials(self) -> None:
        token = "unit-test-redaction-value"
        writer = SandboxDraftWriter(
            transport=_FakeSandboxTransport(diagnostic_error=token),
            credential_loader=lambda: RuntimeSandboxCredentials(token),
        )
        with self.assertRaises(SandboxRequestError) as context:
            writer.run(self.manifest, repository_root=ROOT, dry_run=False)
        self.assertNotIn(token, str(context.exception))

    def test_no_final_release_command_method_or_endpoint_exists(self) -> None:
        subparsers = next(action for action in parser()._actions if action.dest == "command")
        self.assertNotIn("publish", subparsers.choices)
        option_strings = {
            option
            for command_parser in subparsers.choices.values()
            for action in command_parser._actions
            for option in action.option_strings
        }
        self.assertFalse(any("publish" in option.casefold() for option in option_strings))
        self.assertFalse(any("publish" in name.casefold() for name in dir(SandboxDraftWriter)))
        source = Path(sandbox_writer_module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/actions/publish", source)

    def test_transport_rejects_delete_before_network_access(self) -> None:
        with self.assertRaises(SandboxSafetyError):
            UrllibSandboxTransport().request(
                "DELETE",
                "https://sandbox.zenodo.org/api/records/1/draft",
                credentials=RuntimeSandboxCredentials("unit-test-value"),
            )

    def test_transport_rejects_production_url_before_network_access(self) -> None:
        with self.assertRaises(SandboxSafetyError):
            UrllibSandboxTransport().request(
                "POST",
                "https://zenodo.org/api/records",
                credentials=RuntimeSandboxCredentials("unit-test-value"),
                json_body={},
            )

    def test_cli_is_dry_run_by_default(self) -> None:
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
            status = main(
                [
                    "sandbox-draft",
                    "--manifest",
                    str(MANIFEST),
                    "--repository-root",
                    str(ROOT),
                ]
            )
        self.assertEqual(status, 0)
        value = json.loads(output.getvalue())
        self.assertTrue(value["dry_run"])
        self.assertEqual(value["audit"]["requests_sent"], 0)


if __name__ == "__main__":
    unittest.main()
