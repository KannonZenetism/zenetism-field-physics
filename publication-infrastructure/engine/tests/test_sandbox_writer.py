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
from zenetism_engine.sandbox_verification import (
    PASSED_API,
    PASSED_VISUAL,
    VISUAL_VERIFICATION_REQUIRED,
    ArchitectVisualConfirmation,
    load_architect_visual_confirmation,
)
from zenetism_engine.sandbox_writer import (
    SandboxDraftWriter,
    UrllibSandboxTransport,
    sandbox_doi_from_response,
    validate_resume_draft,
    validate_saved_draft,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "publication-infrastructure/manifests/zenetism-in-plain-language-v2.json"
VISUAL_CONFIRMATION = (
    ROOT / "publication-infrastructure/sandbox-verifications/584224.json"
)


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
        reservation_response: dict[str, object] | None = None,
        creation_response: dict[str, object] | None = None,
        resume_draft: dict[str, object] | None = None,
        omit_copyright: bool = False,
    ):
        self.corrupt_version = corrupt_version
        self.diagnostic_error = diagnostic_error
        self.reserved_doi = reserved_doi
        resume_doi = (resume_draft or {}).get("doi")
        self.reloaded_doi = (
            reloaded_doi
            or (resume_doi if isinstance(resume_doi, str) else None)
            or reserved_doi
        )
        self.reservation_response = reservation_response
        self.creation_response = creation_response or {
            "id": "draft-123",
            "recid": "draft-123",
            "created": "2026-08-08T11:14:44+00:00",
            "status": "draft",
        }
        self.resume_draft = copy.deepcopy(resume_draft)
        self.omit_copyright = omit_copyright
        self.draft_id = str(
            (resume_draft or self.creation_response).get("id", "draft-123")
        )
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
            return copy.deepcopy(self.creation_response)
        if method == "POST" and url.endswith("/api/records"):
            return copy.deepcopy(self.creation_response)
        if method == "POST" and url.endswith("/draft/pids/doi"):
            if self.reservation_response is not None:
                return copy.deepcopy(self.reservation_response)
            return {"pids": {"doi": {"identifier": self.reserved_doi}}}
        if method == "PUT" and url.endswith("/draft"):
            self.saved_payload = copy.deepcopy(json_body)
            return {"id": self.draft_id}
        if method == "GET" and url.endswith("/draft"):
            if self.saved_payload is None:
                if self.resume_draft is not None:
                    return copy.deepcopy(self.resume_draft)
                raise AssertionError("draft was reloaded before it was saved")
            result = copy.deepcopy(self.saved_payload)
            if self.corrupt_version:
                result["metadata"]["version"] = "v99"  # type: ignore[index]
            if self.omit_copyright:
                del result["metadata"]["copyright"]  # type: ignore[index]
            result.update(
                {
                    "id": self.draft_id,
                    "status": "draft",
                    "is_published": False,
                    "pids": {"doi": {"identifier": self.reloaded_doi}},
                    "parent": {"pids": {"doi": {"identifier": self.source_concept}}},
                }
            )
            return result
        if method == "GET" and url.endswith("/draft/files"):
            assert self.saved_payload is not None
            return copy.deepcopy(self.saved_payload["files"])  # type: ignore[return-value]
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

    def test_doi_parser_accepts_top_level_doi(self) -> None:
        self.assertEqual(
            sandbox_doi_from_response({"doi": "10.5072/zenodo.584224"}),
            "10.5072/zenodo.584224",
        )

    def test_doi_parser_accepts_metadata_doi(self) -> None:
        self.assertEqual(
            sandbox_doi_from_response(
                {"metadata": {"doi": "10.5072/zenodo.584224"}}
            ),
            "10.5072/zenodo.584224",
        )

    def test_doi_parser_accepts_pids_identifier(self) -> None:
        self.assertEqual(
            sandbox_doi_from_response(
                {"pids": {"doi": {"identifier": "10.5072/zenodo.584224"}}}
            ),
            "10.5072/zenodo.584224",
        )

    def test_doi_parser_accepts_agreeing_duplicate_representations(self) -> None:
        doi = "10.5072/zenodo.584224"
        self.assertEqual(
            sandbox_doi_from_response(
                {
                    "doi": doi,
                    "metadata": {"doi": doi},
                    "pids": {"doi": {"identifier": doi}},
                }
            ),
            doi,
        )

    def test_doi_parser_rejects_conflicting_representations(self) -> None:
        with self.assertRaises(SandboxRequestError) as context:
            sandbox_doi_from_response(
                {
                    "doi": "10.5072/zenodo.584224",
                    "metadata": {"doi": "10.5072/zenodo.999999"},
                }
            )
        self.assertIn("conflicting DOI values", str(context.exception))

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
        self.assertEqual(len(result.audit["requests"]), 9)
        self.assertNotIn("sandbox_draft_id", result.audit)
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
        self.assertEqual(result.audit["requests_sent"], 9)
        self.assertEqual(
            [item["method"] for item in fake.requests],
            [
                "POST",
                "POST",
                "POST",
                "PUT",
                "POST",
                "PUT",
                "GET",
                "GET",
                "GET",
            ],
        )
        rendered = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertNotIn("unit-test-value", rendered)

    def test_top_level_reservation_doi_completes_existing_stage2a_flow(self) -> None:
        doi = "10.5072/zenodo.701"
        result = SandboxDraftWriter(
            transport=_FakeSandboxTransport(reservation_response={"doi": doi}),
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        ).run(self.manifest, repository_root=ROOT, dry_run=False)
        self.assertEqual(result.validation["reserved_doi"], doi)  # type: ignore[index]

    def test_recovery_is_preserved_before_doi_parsing(self) -> None:
        fake = _FakeSandboxTransport(
            reservation_response={},
            creation_response={
                "id": 584224,
                "recid": "584224",
                "conceptrecid": "584223",
                "created": "2026-08-08T11:14:44.784842+00:00",
                "status": "draft",
            },
        )
        writer = SandboxDraftWriter(
            transport=fake,
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        )
        with self.assertRaises(SandboxRequestError) as context:
            writer.run(self.manifest, repository_root=ROOT, dry_run=False)
        recovery = context.exception.recovery
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery["draft_id"], "584224")  # type: ignore[index]
        self.assertEqual(recovery["record_id"], "584224")  # type: ignore[index]
        self.assertEqual(  # type: ignore[index]
            recovery["edit_url"], "https://sandbox.zenodo.org/uploads/584224"
        )
        self.assertEqual(  # type: ignore[index]
            recovery["preview_url"],
            "https://sandbox.zenodo.org/records/584224?preview=1",
        )
        self.assertEqual(
            [item["method"] for item in fake.requests],
            ["POST", "POST"],
        )

    def test_resume_validation_accepts_verified_legacy_draft_shape(self) -> None:
        draft = self._resume_draft()
        result = validate_resume_draft(draft, expected_draft_id="584224")
        self.assertTrue(result["passed"])
        self.assertEqual(result["file_count"], 0)
        self.assertEqual(result["reserved_doi"], "10.5072/zenodo.584224")

    def test_resume_validation_rejects_files_or_submitted_state(self) -> None:
        draft_with_file = self._resume_draft()
        draft_with_file["files"] = [{"key": "unexpected.md"}]
        with self.assertRaises(DraftValidationError):
            validate_resume_draft(draft_with_file, expected_draft_id="584224")

        submitted = self._resume_draft()
        submitted["state"] = "done"
        submitted["submitted"] = True
        with self.assertRaises(DraftValidationError):
            validate_resume_draft(submitted, expected_draft_id="584224")

    def test_resume_mode_never_creates_a_second_draft(self) -> None:
        fake = _FakeSandboxTransport(resume_draft=self._resume_draft())
        result = SandboxDraftWriter(
            transport=fake,
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        ).run(
            self.manifest,
            repository_root=ROOT,
            mode="resume",
            sandbox_draft_id="584224",
            dry_run=False,
        )
        self.assertEqual(result.audit["saved_draft_id"], "584224")
        self.assertEqual(
            result.audit["doi_reservation"], "preserved_existing_reservation"
        )
        self.assertEqual(fake.requests[0]["method"], "GET")
        self.assertTrue(str(fake.requests[0]["url"]).endswith("/584224/draft"))
        self.assertFalse(
            any(
                request["method"] == "POST"
                and (
                    str(request["url"]).endswith("/api/records")
                    or str(request["url"]).endswith("/versions")
                )
                for request in fake.requests
            )
        )
        self.assertFalse(
            any(str(request["url"]).endswith("/pids/doi") for request in fake.requests)
        )

    def test_resume_mode_stops_before_mutation_when_files_exist(self) -> None:
        draft = self._resume_draft()
        draft["files"] = [{"key": "unexpected.md"}]
        fake = _FakeSandboxTransport(resume_draft=draft)
        writer = SandboxDraftWriter(
            transport=fake,
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        )
        with self.assertRaises(DraftValidationError) as context:
            writer.run(
                self.manifest,
                repository_root=ROOT,
                mode="resume",
                sandbox_draft_id="584224",
                dry_run=False,
            )
        self.assertEqual([request["method"] for request in fake.requests], ["GET"])
        self.assertEqual(context.exception.recovery["draft_id"], "584224")  # type: ignore[index]

    def test_resume_mode_requires_an_explicit_draft_id(self) -> None:
        with self.assertRaises(SandboxSafetyError):
            SandboxDraftWriter().plan(
                self.manifest,
                repository_root=ROOT,
                mode="resume",
            )

    @staticmethod
    def _resume_draft() -> dict[str, object]:
        doi = "10.5072/zenodo.584224"
        return {
            "id": 584224,
            "recid": "584224",
            "conceptrecid": "584223",
            "created": "2026-08-08T11:14:44.784842+00:00",
            "updated": "2026-08-08T11:14:45.721924+00:00",
            "status": "draft",
            "state": "unsubmitted",
            "submitted": False,
            "files": [],
            "doi": doi,
            "metadata": {"doi": doi},
        }

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
        self.assertEqual(result.audit["requests_sent"], 10)
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

    def test_api_unavailable_ui_field_requires_visual_verification(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        result = validate_saved_draft(
            package,
            draft,
            file_record,
            file_collection=files,
            expected_draft_id="584224",
            reserved_doi="10.5072/zenodo.584224",
        )
        copyright_result = self._field(result, "metadata.copyright")
        self.assertEqual(
            copyright_result["state"], VISUAL_VERIFICATION_REQUIRED
        )
        self.assertEqual(copyright_result["channel"], "visual")
        self.assertTrue(
            all(
                item["state"] == PASSED_API
                for item in result["fields"]
                if item["field"] != "metadata.copyright"
            )
        )
        self.assertFalse(result["complete"])
        self.assertFalse(result["passed"])

    def test_executed_result_is_incomplete_while_visual_verification_is_pending(self) -> None:
        result = SandboxDraftWriter(
            transport=_FakeSandboxTransport(omit_copyright=True),
            credential_loader=lambda: RuntimeSandboxCredentials("unit-test-value"),
        ).run(self.manifest, repository_root=ROOT, dry_run=False)
        rendered = result.as_dict()
        self.assertFalse(rendered["validation"]["complete"])
        self.assertFalse(rendered["audit"]["validation_passed"])
        self.assertEqual(
            rendered["status"],
            "unpublished_sandbox_draft_visual_verification_required",
        )

    def test_visual_verification_cannot_be_invented_automatically(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        result = validate_saved_draft(
            package,
            draft,
            file_record,
            file_collection=files,
            expected_draft_id="584224",
            reserved_doi="10.5072/zenodo.584224",
            architect_visual_confirmation=None,
        )
        states = {item["state"] for item in result["fields"]}
        self.assertIn(VISUAL_VERIFICATION_REQUIRED, states)
        self.assertNotIn(PASSED_VISUAL, states)

    def test_explicit_architect_confirmation_passes_visual_field(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        confirmation = load_architect_visual_confirmation(VISUAL_CONFIRMATION)
        result = validate_saved_draft(
            package,
            draft,
            file_record,
            file_collection=files,
            expected_draft_id="584224",
            reserved_doi="10.5072/zenodo.584224",
            architect_visual_confirmation=confirmation,
        )
        copyright_result = self._field(result, "metadata.copyright")
        self.assertEqual(copyright_result["state"], PASSED_VISUAL)
        self.assertEqual(copyright_result["observed"], "2026 Aelion Kannon")
        self.assertTrue(result["complete"])
        self.assertTrue(result["passed"])

    def test_incorrect_architect_confirmed_value_fails(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        confirmation = ArchitectVisualConfirmation.from_object(
            {
                "sandbox_draft_id": "584224",
                "confirmed_by": "architect",
                "verification_channel": "visual",
                "fields": {"metadata.copyright": "incorrect value"},
            }
        )
        with self.assertRaises(DraftValidationError) as context:
            validate_saved_draft(
                package,
                draft,
                file_record,
                file_collection=files,
                expected_draft_id="584224",
                reserved_doi="10.5072/zenodo.584224",
                architect_visual_confirmation=confirmation,
            )
        self.assertIn("architect-confirmed metadata.copyright differs", str(context.exception))

    def test_missing_api_visible_field_still_fails_closed(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        del draft["metadata"]["title"]  # type: ignore[index]
        with self.assertRaises(DraftValidationError) as context:
            validate_saved_draft(
                package,
                draft,
                file_record,
                file_collection=files,
                expected_draft_id="584224",
                reserved_doi="10.5072/zenodo.584224",
                architect_visual_confirmation=load_architect_visual_confirmation(
                    VISUAL_CONFIRMATION
                ),
            )
        self.assertIn("metadata.title is missing", str(context.exception))

    def test_complete_validation_requires_every_manifest_controlled_field(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        draft["metadata"]["language"] = "fra"  # type: ignore[index]
        with self.assertRaises(DraftValidationError) as context:
            validate_saved_draft(
                package,
                draft,
                file_record,
                file_collection=files,
                expected_draft_id="584224",
                reserved_doi="10.5072/zenodo.584224",
                architect_visual_confirmation=load_architect_visual_confirmation(
                    VISUAL_CONFIRMATION
                ),
            )
        self.assertIn("metadata.languages differs", str(context.exception))

    def test_visual_confirmation_does_not_override_api_visible_mismatch(self) -> None:
        package, draft, files, file_record = self._legacy_reference_readback()
        draft["metadata"]["copyright"] = "incorrect API value"  # type: ignore[index]
        with self.assertRaises(DraftValidationError) as context:
            validate_saved_draft(
                package,
                draft,
                file_record,
                file_collection=files,
                expected_draft_id="584224",
                reserved_doi="10.5072/zenodo.584224",
                architect_visual_confirmation=load_architect_visual_confirmation(
                    VISUAL_CONFIRMATION
                ),
            )
        self.assertIn("metadata.copyright differs", str(context.exception))

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

    def test_resume_cli_dry_run_names_only_the_explicit_draft(self) -> None:
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), redirect_stdout(output):
            status = main(
                [
                    "sandbox-resume",
                    "--manifest",
                    str(MANIFEST),
                    "--repository-root",
                    str(ROOT),
                    "--sandbox-draft-id",
                    "584224",
                ]
            )
        self.assertEqual(status, 0)
        value = json.loads(output.getvalue())
        self.assertTrue(value["dry_run"])
        self.assertEqual(value["audit"]["mode"], "resume")
        self.assertEqual(value["audit"]["sandbox_draft_id"], "584224")
        self.assertEqual(value["audit"]["requests_sent"], 0)
        self.assertTrue(
            value["audit"]["requests"][0]["url"].endswith("/584224/draft")
        )
        self.assertTrue(
            all(
                request["url"].startswith("https://sandbox.zenodo.org/api/")
                for request in value["audit"]["requests"]
            )
        )
        self.assertFalse(
            any(
                request["method"] == "POST"
                and request["url"].endswith("/api/records")
                for request in value["audit"]["requests"]
            )
        )

    def _legacy_reference_readback(self):  # type: ignore[no-untyped-def]
        package = SandboxDraftWriter().plan(
            self.manifest, repository_root=ROOT
        ).package
        expected = package.saved_payload["metadata"]
        doi = "10.5072/zenodo.584224"
        filename = package.archival_copy.archival_filename
        file_record = {
            "key": filename,
            "size": package.archival_copy.checksums.byte_size,
            "checksum": f"md5:{package.archival_copy.checksums.md5}",
            "status": "completed",
        }
        draft = {
            "id": 584224,
            "recid": "584224",
            "status": "draft",
            "state": "unsubmitted",
            "submitted": False,
            "doi": doi,
            "files": [copy.deepcopy(file_record)],
            "metadata": {
                "doi": doi,
                "access_right": "open",
                "resource_type": {
                    "title": "Report",
                    "type": "publication",
                    "subtype": "report",
                },
                "title": expected["title"],
                "publication_date": expected["publication_date"],
                "creators": [{"name": "Aelion Kannon"}],
                "contributors": [
                    {"name": "⚮ Liora", "type": "Researcher"},
                    {"name": "🔦 Lumen", "type": "Researcher"},
                ],
                "description": expected["description"],
                "keywords": [
                    item["subject"] for item in expected["subjects"]
                ],
                "version": expected["version"],
                "license": {"id": "cc-by-4.0"},
                "language": "eng",
                "related_identifiers": [
                    {
                        "identifier": item["identifier"],
                        "scheme": item["scheme"],
                        "relation": "isDocumentedBy",
                        "resource_type": "Other",
                    }
                    for item in expected["related_identifiers"]
                ],
                "custom": copy.deepcopy(package.saved_payload["custom_fields"]),
            },
        }
        file_collection = {
            "enabled": True,
            "entries": [copy.deepcopy(file_record)],
            "default_preview": filename,
            "order": [],
        }
        return package, draft, file_collection, file_record

    @staticmethod
    def _field(result: dict[str, object], field: str) -> dict[str, object]:
        for item in result["fields"]:  # type: ignore[index]
            if item["field"] == field:  # type: ignore[index]
                return item  # type: ignore[return-value]
        raise AssertionError(f"missing verification result for {field}")


if __name__ == "__main__":
    unittest.main()
