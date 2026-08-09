from __future__ import annotations

import copy
import inspect
import json
import re
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from zenetism_engine.cli import parser
from zenetism_engine.errors import (
    ProductionFamilyError,
    ProductionRequestError,
    ProductionSafetyError,
)
from zenetism_engine.production_boundary import (
    PRODUCTION_REQUIRED_SCOPES,
    PRODUCTION_TOKEN_ENV,
    RuntimeProductionCredentials,
)
from zenetism_engine.production_draft import ProductionDraftPlanner
from zenetism_engine.production_transport import (
    ProductionDraftExecutor,
    UrllibProductionDraftTransport,
)
import zenetism_engine.production_transport as production_transport_module

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    ROOT
    / "publication-infrastructure/manifests/zenetism-in-plain-language-v2.json"
)
TWO_STATE_MANIFEST_PATH = (
    ROOT
    / "publication-infrastructure/manifests/prose-formatting-reference-v9.json"
)
REGISTRY_PATH = ROOT / "publication-infrastructure/zenetism-publication-registry.csv"
PACKAGE = ROOT / "publication-infrastructure/engine/zenetism_engine"

SOURCE_ID = "21830364"
DRAFT_ID = "30000001"
NEW_DOI = "10.5281/zenodo.30000001"


def _family_member(
    *,
    record_id: str,
    exact_doi: str,
    version: str,
    family_index: int,
    is_latest: bool,
    concept_doi: str,
) -> dict[str, object]:
    return {
        "id": record_id,
        "recid": record_id,
        "doi": exact_doi,
        "metadata": {
            "doi": exact_doi,
            "conceptdoi": concept_doi,
            "version": version,
        },
        "pids": {"doi": {"identifier": exact_doi}},
        "parent": {"pids": {"doi": {"identifier": concept_doi}}},
        "versions": {"index": family_index, "is_latest": is_latest},
    }


def _family_observation(manifest: dict[str, object]) -> dict[str, object]:
    zenodo = manifest["zenodo"]
    assert isinstance(zenodo, dict)
    concept = str(zenodo["concept_doi"])
    prior = _family_member(
        record_id="21174439",
        exact_doi="10.5281/zenodo.21174439",
        version="v1",
        family_index=1,
        is_latest=False,
        concept_doi=concept,
    )
    latest = _family_member(
        record_id=SOURCE_ID,
        exact_doi="10.5281/zenodo.21830364",
        version="v2",
        family_index=2,
        is_latest=True,
        concept_doi=concept,
    )
    return {
        "concept_doi": concept,
        "latest": copy.deepcopy(latest),
        "members": [prior, latest],
    }


def _two_state_family_observation(
    manifest: dict[str, object]
) -> dict[str, object]:
    baseline = manifest["published_baseline"]
    assert isinstance(baseline, dict)
    zenodo = baseline["zenodo"]
    assert isinstance(zenodo, dict)
    concept = str(zenodo["concept_doi"])
    family = zenodo["version_family"]
    assert isinstance(family, list)
    members: list[dict[str, object]] = []
    for item in family:
        assert isinstance(item, dict)
        members.append(
            _family_member(
                record_id=str(item["record_id"]),
                exact_doi=str(item["exact_version_doi"]),
                version=str(item["version_label"]),
                family_index=int(item["family_index"]),
                is_latest=bool(item["is_latest"]),
                concept_doi=concept,
            )
        )
    latest = [item for item in members if item["versions"]["is_latest"]]
    assert len(latest) == 1
    return {
        "concept_doi": concept,
        "latest": copy.deepcopy(latest[0]),
        "members": members,
    }


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._payload


class _ScriptedOpener:
    def __init__(self, routes: dict[tuple[str, str], list[object]]) -> None:
        self.routes = routes
        self.requests: list[dict[str, object]] = []

    def open(self, request, timeout=0):
        method = request.get_method()
        url = request.full_url
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(request.header_items()),
                "body": request.data,
            }
        )
        key = (method, url)
        if key not in self.routes or not self.routes[key]:
            raise AssertionError(f"unexpected local production request: {method} {url}")
        value = self.routes[key].pop(0)
        if isinstance(value, BaseException):
            raise value
        if value is None:
            return _Response(b"")
        return _Response(json.dumps(value).encode("utf-8"))


class ProductionTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.family = _family_observation(cls.manifest)
        cls.plan = ProductionDraftPlanner().plan(
            cls.manifest,
            repository_root=ROOT,
            registry_path=REGISTRY_PATH,
            family_observation=cls.family,
            intent={
                "route": "new-version",
                "record_key": "zenetism-in-plain-language",
                "next_version": "v3",
            },
        )

    def _current_deposition(
        self, *, latest_draft: str | None = None
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "id": SOURCE_ID,
            "recid": SOURCE_ID,
            "doi": self.plan.family.latest.exact_version_doi,
            "conceptdoi": self.plan.family.concept_doi,
            "metadata": {
                "doi": self.plan.family.latest.exact_version_doi,
                "conceptdoi": self.plan.family.concept_doi,
                "version": "v2",
            },
            "submitted": True,
            "state": "done",
            "status": "published",
            "links": {},
        }
        if latest_draft is not None:
            result["links"] = {"latest_draft": latest_draft}
        return result

    def _new_version_result(
        self, *, latest_draft: str = f"https://zenodo.org/api/deposit/depositions/{DRAFT_ID}"
    ) -> dict[str, object]:
        return {
            "id": SOURCE_ID,
            "submitted": True,
            "state": "done",
            "links": {"latest_draft": latest_draft},
        }

    def _legacy_draft(
        self, *, concept_doi: str | None = None, version: str = "v2"
    ) -> dict[str, object]:
        concept = concept_doi or self.plan.family.concept_doi
        return {
            "id": DRAFT_ID,
            "recid": DRAFT_ID,
            "conceptdoi": concept,
            "metadata": {"conceptdoi": concept, "version": version},
            "submitted": False,
            "state": "unsubmitted",
            "status": "draft",
            "is_published": False,
        }

    def _initial_draft(self, *, file_state: str = "inherited") -> dict[str, object]:
        value = self._legacy_draft()
        value["parent"] = {
            "pids": {"doi": {"identifier": self.plan.family.concept_doi}}
        }
        entries: dict[str, object] = {}
        if file_state == "inherited":
            filename = self.plan.registry_identity["zenodo_archival_filename"]
            entries[filename] = {
                "key": filename,
                "checksum": self.plan.registry_identity["zenodo_checksum"],
                "size": self.plan.archival_copy.checksums.byte_size,
            }
        elif file_state == "approved":
            filename = self.plan.archival_copy.archival_filename
            entries[filename] = self._approved_file_entry()
        elif file_state == "ambiguous":
            entries = {
                "unexpected-a.md": {"key": "unexpected-a.md"},
                "unexpected-b.md": {"key": "unexpected-b.md"},
            }
        value["files"] = {"enabled": True, "entries": entries}
        return value

    def _approved_file_entry(self) -> dict[str, object]:
        return {
            "key": self.plan.archival_copy.archival_filename,
            "checksum": f"md5:{self.plan.archival_copy.checksums.md5}",
            "size": self.plan.archival_copy.checksums.byte_size,
        }

    def _final_draft(self, *, include_copyright: bool = True) -> dict[str, object]:
        value = copy.deepcopy(self.plan.metadata_payload)
        value.update(
            {
                "id": DRAFT_ID,
                "recid": DRAFT_ID,
                "doi": NEW_DOI,
                "pids": {"doi": {"identifier": NEW_DOI}},
                "parent": {
                    "pids": {"doi": {"identifier": self.plan.family.concept_doi}}
                },
                "submitted": False,
                "state": "unsubmitted",
                "status": "draft",
                "is_published": False,
            }
        )
        files = value["files"]
        assert isinstance(files, dict)
        files["entries"] = {
            self.plan.archival_copy.archival_filename: self._approved_file_entry()
        }
        if not include_copyright:
            del value["metadata"]["copyright"]
        return value

    def _routes(
        self,
        *,
        existing_draft: bool = False,
        initial_file_state: str = "inherited",
        legacy_initial: dict[str, object] | None = None,
        final_draft: dict[str, object] | None = None,
    ) -> dict[tuple[str, str], list[object]]:
        base = "https://zenodo.org/api"
        latest_url = f"{base}/deposit/depositions/{DRAFT_ID}"
        current = self._current_deposition(
            latest_draft=latest_url if existing_draft else None
        )
        routes: dict[tuple[str, str], list[object]] = {
            ("GET", f"{base}/records/{SOURCE_ID}"): [
                copy.deepcopy(self.family["latest"])
            ],
            ("GET", f"{base}/records/{SOURCE_ID}/versions"): [
                {"hits": {"hits": copy.deepcopy(self.family["members"])}},
            ],
            ("GET", f"{base}/deposit/depositions/{SOURCE_ID}"): [current],
            ("GET", latest_url): [
                legacy_initial or self._legacy_draft(),
                self._legacy_draft(version="v3"),
            ],
            ("GET", f"{base}/records/{DRAFT_ID}/draft"): [
                self._initial_draft(file_state=initial_file_state),
                final_draft or self._final_draft(),
            ],
            ("PUT", f"{base}/records/{DRAFT_ID}/draft"): [{}],
        }
        if not existing_draft:
            routes[(
                "POST",
                f"{base}/deposit/depositions/{SOURCE_ID}/actions/newversion",
            )] = [self._new_version_result()]
        if initial_file_state == "inherited":
            inherited = self.plan.registry_identity["zenodo_archival_filename"]
            routes[(
                "DELETE",
                f"{base}/records/{DRAFT_ID}/draft/files/{inherited}",
            )] = [None]
        if initial_file_state in {"inherited", "empty"}:
            approved = self.plan.archival_copy.archival_filename
            routes[("POST", f"{base}/records/{DRAFT_ID}/draft/files")] = [{}]
            routes[(
                "PUT",
                f"{base}/records/{DRAFT_ID}/draft/files/{approved}/content",
            )] = [{}]
            routes[(
                "POST",
                f"{base}/records/{DRAFT_ID}/draft/files/{approved}/commit",
            )] = [{}]
        return routes

    def _execute(self, routes: dict[tuple[str, str], list[object]]):
        opener = _ScriptedOpener(routes)
        marker = "stage3b-local-simulation-value"
        with patch(
            "urllib.request.build_opener",
            return_value=opener,
        ), patch.object(
            RuntimeProductionCredentials,
            "from_environment",
            side_effect=AssertionError("local suite attempted to load a production value"),
        ):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials(marker)
            )
            result = ProductionDraftExecutor(transport).prepare(self.plan)
        return result, opener, marker

    def test_required_newversion_and_bound_draft_operations_succeed_locally(self) -> None:
        result, opener, _ = self._execute(self._routes())
        value = result.as_dict()
        self.assertTrue(value["new_version_created"])
        self.assertEqual(value["draft_id"], DRAFT_ID)
        self.assertEqual(value["exact_version_doi"], NEW_DOI)
        self.assertTrue(value["validation"]["complete"])
        requests = [(item["method"], item["url"]) for item in opener.requests]
        self.assertIn(
            (
                "POST",
                f"https://zenodo.org/api/deposit/depositions/{SOURCE_ID}/actions/newversion",
            ),
            requests,
        )
        self.assertIn(
            ("PUT", f"https://zenodo.org/api/records/{DRAFT_ID}/draft"),
            requests,
        )
        upload = next(
            item
            for item in opener.requests
            if str(item["url"]).endswith(
                f"/{self.plan.archival_copy.archival_filename}/content"
            )
        )
        self.assertEqual(upload["body"], self.plan.archival_copy.payload)

    def test_existing_exact_family_draft_is_resumed_without_second_creation(self) -> None:
        result, opener, _ = self._execute(self._routes(existing_draft=True))
        self.assertFalse(result.new_version_created)
        self.assertFalse(
            any(
                item["method"] == "POST" and "/actions/" in str(item["url"])
                for item in opener.requests
            )
        )

    def test_existing_partially_prepared_exact_file_is_not_uploaded_again(self) -> None:
        result, opener, _ = self._execute(
            self._routes(existing_draft=True, initial_file_state="approved")
        )
        self.assertFalse(result.new_version_created)
        file_mutations = [
            item
            for item in opener.requests
            if "/draft/files" in str(item["url"])
            and item["method"] in {"POST", "PUT", "DELETE"}
        ]
        self.assertEqual(file_mutations, [])

    def test_existing_wrong_family_draft_fails_without_newversion_fallback(self) -> None:
        wrong = self._legacy_draft(concept_doi="10.5281/zenodo.99999999")
        routes = self._routes(existing_draft=True, legacy_initial=wrong)
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionSafetyError):
                executor.prepare(self.plan)
        self.assertFalse(
            any("/actions/newversion" in str(item["url"]) for item in opener.requests)
        )

    def test_recovered_draft_is_verified_before_any_write(self) -> None:
        wrong = self._legacy_draft(concept_doi="10.5281/zenodo.99999999")
        routes = self._routes(legacy_initial=wrong)
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionSafetyError) as context:
                executor.prepare(self.plan)
        self.assertIsNotNone(context.exception.recovery)
        draft_writes = [
            item
            for item in opener.requests
            if item["method"] in {"PUT", "DELETE"}
            or (
                item["method"] == "POST"
                and "/actions/newversion" not in str(item["url"])
            )
        ]
        self.assertEqual(draft_writes, [])

    def test_wrong_family_readback_fails_before_newversion(self) -> None:
        routes = self._routes()
        latest_key = ("GET", f"https://zenodo.org/api/records/{SOURCE_ID}")
        wrong = copy.deepcopy(self.family["latest"])
        wrong["parent"]["pids"]["doi"]["identifier"] = (
            "10.5281/zenodo.99999999"
        )
        routes[latest_key] = [wrong]
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionFamilyError):
                executor.prepare(self.plan)
        self.assertFalse(
            any("/actions/newversion" in str(item["url"]) for item in opener.requests)
        )

    def test_ambiguous_draft_files_fail_before_file_or_metadata_write(self) -> None:
        routes = self._routes(initial_file_state="ambiguous")
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionSafetyError):
                executor.prepare(self.plan)
        write_urls = [
            str(item["url"])
            for item in opener.requests
            if item["method"] in {"PUT", "DELETE"}
            or (
                item["method"] == "POST"
                and "/actions/newversion" not in str(item["url"])
            )
        ]
        self.assertEqual(write_urls, [])

    def test_latest_draft_host_injection_fails_before_draft_write(self) -> None:
        routes = self._routes()
        action_key = (
            "POST",
            f"https://zenodo.org/api/deposit/depositions/{SOURCE_ID}/actions/newversion",
        )
        routes[action_key] = [
            self._new_version_result(
                latest_draft=f"https://example.invalid/api/deposit/depositions/{DRAFT_ID}"
            )
        ]
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionSafetyError):
                executor.prepare(self.plan)
        self.assertEqual(opener.requests[-1]["url"], action_key[1])

    def test_direct_unpublished_newversion_response_can_bind_the_same_family(self) -> None:
        routes = self._routes()
        action_key = (
            "POST",
            f"https://zenodo.org/api/deposit/depositions/{SOURCE_ID}/actions/newversion",
        )
        direct = self._legacy_draft()
        direct["created"] = "2026-08-09T12:00:00+00:00"
        routes[action_key] = [direct]
        result, _, _ = self._execute(routes)
        self.assertEqual(result.recovery.draft_id, DRAFT_ID)
        self.assertTrue(result.new_version_created)

    def test_conflicting_direct_and_latest_draft_identities_fail_closed(self) -> None:
        routes = self._routes()
        action_key = (
            "POST",
            f"https://zenodo.org/api/deposit/depositions/{SOURCE_ID}/actions/newversion",
        )
        direct = self._legacy_draft()
        direct["links"] = {
            "latest_draft": "https://zenodo.org/api/deposit/depositions/30000002"
        }
        routes[action_key] = [direct]
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            )
            with self.assertRaises(ProductionSafetyError):
                executor.prepare(self.plan)
        self.assertEqual(opener.requests[-1]["url"], action_key[1])

    def test_executor_and_transport_cannot_create_or_bind_a_second_draft(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            executor = ProductionDraftExecutor(transport)
            executor.prepare(self.plan)
            with self.assertRaises(ProductionSafetyError):
                executor.prepare(self.plan)
            with self.assertRaises(ProductionSafetyError):
                transport.open_new_version_draft(self.plan)

    def test_transport_cannot_initiate_before_its_family_readback_passes(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            with self.assertRaises(ProductionSafetyError):
                transport.open_new_version_draft(self.plan)
        self.assertEqual(opener.requests, [])

    def test_private_sender_cannot_bypass_record_or_station_binding(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            transport.read_family(self.plan)
            wrong_record = production_transport_module._BoundProductionRequest(
                production_transport_module._RequestKind.INITIATE_NEW_VERSION,
                "POST",
                "/api/deposit/depositions/99999999/actions/newversion",
            )
            with self.assertRaises(ProductionSafetyError):
                transport._send(wrong_record)
            exact_but_early = production_transport_module._BoundProductionRequest(
                production_transport_module._RequestKind.INITIATE_NEW_VERSION,
                "POST",
                f"/api/deposit/depositions/{SOURCE_ID}/actions/newversion",
            )
            with self.assertRaises(ProductionSafetyError):
                transport._send(exact_but_early)
        self.assertFalse(
            any("/actions/newversion" in str(item["url"]) for item in opener.requests)
        )

    def test_transport_cannot_write_before_bound_draft_readback_passes(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            transport.read_family(self.plan)
            transport.open_new_version_draft(self.plan)
            with self.assertRaises(ProductionSafetyError):
                transport.delete_inherited_archival_file(self.plan)
            with self.assertRaises(ProductionSafetyError):
                transport.upload_approved_archival_file(self.plan)
            with self.assertRaises(ProductionSafetyError):
                transport.save_approved_metadata(self.plan)
        self.assertEqual(opener.requests[-1]["method"], "POST")
        self.assertIn("/actions/newversion", str(opener.requests[-1]["url"]))

    def test_fixed_surface_has_no_generic_or_irreversible_operation(self) -> None:
        public = {
            name
            for name, member in inspect.getmembers(
                UrllibProductionDraftTransport, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }
        self.assertEqual(
            public,
            {
                "read_family",
                "open_new_version_draft",
                "reload_bound_legacy_draft",
                "reload_bound_draft",
                "delete_inherited_archival_file",
                "upload_approved_archival_file",
                "save_approved_metadata",
            },
        )
        self.assertTrue(callable(UrllibProductionDraftTransport.from_environment))
        for method_name in public:
            parameters = set(
                inspect.signature(
                    getattr(UrllibProductionDraftTransport, method_name)
                ).parameters
            )
            self.assertTrue(
                parameters.isdisjoint(
                    {"url", "host", "path", "method", "action", "record_id", "draft_id"}
                )
            )
        for forbidden in ("publish", "edit", "discard", "request", "create_deposition"):
            self.assertFalse(hasattr(UrllibProductionDraftTransport, forbidden))

    def test_only_newversion_action_and_no_standalone_creation_are_reachable(self) -> None:
        implementation = (PACKAGE / "production_transport.py").read_text(
            encoding="utf-8"
        )
        action_paths = set(
            match.group(0) for match in re.finditer(r"/actions/[a-z]+", implementation)
        )
        self.assertEqual(action_paths, {"/actions/newversion"})
        self.assertNotIn(
            '"POST",\n                "/api/deposit/depositions"',
            implementation,
        )
        cli_help = parser().format_help().casefold()
        self.assertNotIn("production-publish", cli_help)
        self.assertNotIn("execute-production", cli_help)

    def test_runtime_interface_names_only_the_required_scopes(self) -> None:
        self.assertEqual(PRODUCTION_TOKEN_ENV, "ZENODO_PRODUCTION_TOKEN")
        self.assertEqual(
            PRODUCTION_REQUIRED_SCOPES,
            ("deposit:write", "deposit:actions"),
        )

    def test_credential_and_header_values_are_not_persisted(self) -> None:
        result, opener, marker = self._execute(self._routes())
        serialized = json.dumps(result.as_dict())
        self.assertNotIn(marker, serialized)
        self.assertNotIn("Bearer", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertEqual(
            repr(RuntimeProductionCredentials(marker)),
            "RuntimeProductionCredentials(<redacted>)",
        )
        self.assertTrue(
            all(
                marker in str(item["headers"].get("Authorization", ""))
                for item in opener.requests
            )
        )

    def test_transport_error_does_not_disclose_the_runtime_value(self) -> None:
        routes = self._routes()
        marker = "stage3b-local-simulation-value"
        legacy_key = (
            "GET",
            f"https://zenodo.org/api/deposit/depositions/{DRAFT_ID}",
        )
        routes[legacy_key][0] = urllib.error.URLError(marker)
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            executor = ProductionDraftExecutor(
                UrllibProductionDraftTransport(RuntimeProductionCredentials(marker))
            )
            with self.assertRaises(ProductionRequestError) as context:
                executor.prepare(self.plan)
        self.assertNotIn(marker, str(context.exception))
        self.assertNotIn("Authorization", str(context.exception))
        self.assertIsNotNone(context.exception.recovery)

    def test_local_transport_suite_uses_only_the_scripted_opener(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener), patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("deterministic suite attempted a real request"),
        ):
            result = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            ).prepare(self.plan)
        self.assertEqual(result.recovery.draft_id, DRAFT_ID)
        self.assertTrue(
            all(
                str(item["url"]).startswith("https://zenodo.org/api/")
                for item in opener.requests
            )
        )


class TwoStateProductionTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(TWO_STATE_MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.plan = ProductionDraftPlanner().plan(
            cls.manifest,
            repository_root=ROOT,
            registry_path=REGISTRY_PATH,
            family_observation=_two_state_family_observation(cls.manifest),
            intent={
                "route": "new-version",
                "record_key": "prose-formatting-reference",
                "next_version": "v9",
            },
        )

    def _inherited_draft(self, *, size: int) -> dict[str, object]:
        filename = self.plan.registry_identity["zenodo_archival_filename"]
        return {
            "files": {
                "enabled": True,
                "entries": {
                    filename: {
                        "key": filename,
                        "checksum": self.plan.registry_identity["zenodo_checksum"],
                        "size": size,
                    }
                },
            }
        }

    def test_inherited_v8_and_candidate_v9_payload_sizes_remain_distinct(self) -> None:
        self.assertEqual(self.plan.registry_identity["zenodo_byte_size"], "44971")
        self.assertEqual(self.plan.archival_copy.checksums.byte_size, 45220)
        self.assertEqual(
            production_transport_module._classify_file_state(
                self.plan,
                self._inherited_draft(size=44971),
            ),
            "inherited",
        )

    def test_inherited_v8_filename_with_candidate_v9_size_fails(self) -> None:
        with self.assertRaises(ProductionSafetyError):
            production_transport_module._classify_file_state(
                self.plan,
                self._inherited_draft(size=45220),
            )


if __name__ == "__main__":
    unittest.main()
