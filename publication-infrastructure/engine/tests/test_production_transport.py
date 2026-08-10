from __future__ import annotations

import copy
import io
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
from zenetism_engine.production_draft import (
    ProductionDraftPlanner,
    ProductionDraftRecovery,
)
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


def _live_relation_member(
    value: dict[str, object],
    *,
    include_latest_marker: bool,
) -> dict[str, object]:
    record_id = str(value["id"])
    metadata = value["metadata"]
    versions = value["versions"]
    assert isinstance(metadata, dict)
    assert isinstance(versions, dict)
    relation: dict[str, object] = {
        "index": int(versions["index"]) - 1,
        "parent": {
            "pid_type": "recid",
            "pid_value": str(metadata["conceptdoi"]).rsplit(".", 1)[-1],
        },
    }
    if include_latest_marker:
        relation["is_last"] = bool(versions["is_latest"])
    return {
        "id": record_id,
        "doi": value["doi"],
        "conceptdoi": metadata["conceptdoi"],
        "metadata": {
            "version": metadata["version"],
            "relations": {"version": [relation]},
        },
        "links": {
            "latest": f"https://zenodo.org/api/records/{record_id}/versions/latest",
            "versions": f"https://zenodo.org/api/records/{record_id}/versions",
        },
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

    def _recovery(self, *, draft_id: str = DRAFT_ID) -> ProductionDraftRecovery:
        concept_record_id = self.plan.family.concept_doi.rsplit(".", 1)[-1]
        return ProductionDraftRecovery(
            draft_id=draft_id,
            record_id=None,
            edit_url=f"https://zenodo.org/uploads/{draft_id}",
            preview_url=f"https://zenodo.org/records/{draft_id}?preview=1",
            creation_result={
                "id": int(draft_id),
                "conceptrecid": concept_record_id,
                "created": "2026-08-10T08:27:58.542028+00:00",
                "modified": "2026-08-10T08:27:58.729012+00:00",
                "state": "unsubmitted",
                "submitted": False,
                "latest_draft": (
                    f"https://zenodo.org/api/deposit/depositions/{draft_id}"
                ),
            },
        )

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

    def _initial_draft(
        self,
        *,
        file_state: str = "inherited",
        include_root_files: bool = True,
    ) -> dict[str, object]:
        value = self._legacy_draft()
        value["parent"] = {
            "pids": {"doi": {"identifier": self.plan.family.concept_doi}}
        }
        if include_root_files:
            collection = self._draft_files_collection(file_state=file_state)
            entries = collection["entries"]
            assert isinstance(entries, list)
            collection["entries"] = {
                str(item["key"]): copy.deepcopy(item)
                for item in entries
                if isinstance(item, dict)
            }
            value["files"] = collection
        return value

    def _approved_file_entry(self) -> dict[str, object]:
        return {
            "key": self.plan.archival_copy.archival_filename,
            "checksum": f"md5:{self.plan.archival_copy.checksums.md5}",
            "size": self.plan.archival_copy.checksums.byte_size,
            "status": "completed",
        }

    def _draft_files_collection(
        self,
        *,
        file_state: str,
        final_configuration: bool = False,
        draft_id: str = DRAFT_ID,
    ) -> dict[str, object]:
        entries: list[dict[str, object]] = []
        default_preview: str | None = None
        order: list[str] = []
        if file_state == "inherited":
            filename = self.plan.registry_identity["zenodo_archival_filename"]
            entries.append(
                {
                    "key": filename,
                    "checksum": self.plan.registry_identity["zenodo_checksum"],
                    "size": self.plan.archival_copy.checksums.byte_size,
                    "status": "completed",
                }
            )
            default_preview = filename
            order = [filename]
        elif file_state == "approved":
            entries.append(self._approved_file_entry())
            if final_configuration:
                default_preview = self.plan.archival_copy.archival_filename
                order = [self.plan.archival_copy.archival_filename]
        elif file_state == "ambiguous":
            entries = [
                {
                    "key": "unexpected-a.md",
                    "checksum": "md5:" + "a" * 32,
                    "size": 1,
                    "status": "completed",
                },
                {
                    "key": "unexpected-b.md",
                    "checksum": "md5:" + "b" * 32,
                    "size": 1,
                    "status": "completed",
                },
            ]
        return {
            "id": draft_id,
            "enabled": True,
            "entries": entries,
            "default_preview": default_preview,
            "order": order,
            "links": {
                "self": f"https://zenodo.org/api/records/{draft_id}/draft/files"
            },
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
        include_root_files: bool = True,
        legacy_initial: dict[str, object] | None = None,
        final_draft: dict[str, object] | None = None,
        initial_dedicated_files: dict[str, object] | None = None,
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
                self._initial_draft(
                    file_state=initial_file_state,
                    include_root_files=include_root_files,
                ),
                final_draft or self._final_draft(),
            ],
            ("GET", f"{base}/records/{DRAFT_ID}/draft/files"): [
                initial_dedicated_files
                or self._draft_files_collection(file_state=initial_file_state),
                *(
                    [
                        self._draft_files_collection(
                            file_state="approved",
                        )
                    ]
                    if initial_file_state in {"inherited", "empty"}
                    else []
                ),
                self._draft_files_collection(
                    file_state="approved",
                    final_configuration=True,
                ),
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

    def test_existing_explicit_doi_readback_requires_no_reservation(self) -> None:
        result, opener, _ = self._execute(self._routes())
        self.assertEqual(result.exact_version_doi, NEW_DOI)
        self.assertFalse(
            any(
                str(item["url"]).endswith("/draft/pids/doi")
                for item in opener.requests
            )
        )

    def test_metadata_save_and_readback_preserve_explicit_publisher(self) -> None:
        result, opener, _ = self._execute(self._routes())
        self.assertEqual(
            next(
                item["body"]
                for item in opener.requests
                if item["method"] == "PUT"
                and str(item["url"]).endswith(f"/records/{DRAFT_ID}/draft")
            ),
            json.dumps(
                self.plan.metadata_payload,
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        states = {
            item["field"]: item["state"]
            for item in result.validation["fields"]
        }
        self.assertEqual(states["metadata.publisher"], "passed_api")

    def test_absent_doi_receives_one_confined_reservation_and_exact_readback(self) -> None:
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
        )
        base = "https://zenodo.org/api"
        legacy_url = f"{base}/deposit/depositions/{DRAFT_ID}"
        root_url = f"{base}/records/{DRAFT_ID}/draft"
        files_url = f"{root_url}/files"
        final = routes[("GET", root_url)][1]
        assert isinstance(final, dict)
        final.pop("doi", None)
        final.pop("pids", None)
        reserved_legacy = self._legacy_draft(version="v3")
        reserved_legacy["doi"] = NEW_DOI
        reserved_modern = copy.deepcopy(final)
        reserved_modern["pids"] = {"doi": {"identifier": NEW_DOI}}
        routes[("GET", legacy_url)].append(reserved_legacy)
        routes[("GET", root_url)].append(reserved_modern)
        routes[("GET", files_url)].append(
            self._draft_files_collection(
                file_state="approved",
                final_configuration=True,
            )
        )
        reserve_url = f"{root_url}/pids/doi"
        routes[("POST", reserve_url)] = [
            {"pids": {"doi": {"identifier": NEW_DOI}}}
        ]
        result, opener, _ = self._execute(routes)
        self.assertEqual(result.exact_version_doi, NEW_DOI)
        requests = [
            item for item in opener.requests if item["url"] == reserve_url
        ]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["method"], "POST")
        self.assertIsNone(requests[0]["body"])

    def test_already_reserved_doi_recovery_does_not_reserve_again(self) -> None:
        routes = self._routes()
        base = "https://zenodo.org/api"
        legacy_url = f"{base}/deposit/depositions/{DRAFT_ID}"
        root_url = f"{base}/records/{DRAFT_ID}/draft"
        legacy_final = routes[("GET", legacy_url)][1]
        modern_final = routes[("GET", root_url)][1]
        assert isinstance(legacy_final, dict)
        assert isinstance(modern_final, dict)
        legacy_final["metadata"]["doi"] = NEW_DOI
        modern_final.pop("doi", None)
        modern_final.pop("pids", None)
        result, opener, _ = self._execute(routes)
        self.assertEqual(result.exact_version_doi, NEW_DOI)
        self.assertFalse(
            any(
                str(item["url"]).endswith("/draft/pids/doi")
                for item in opener.requests
            )
        )

    def test_already_exists_reservation_response_reloads_explicit_doi(self) -> None:
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
        )
        base = "https://zenodo.org/api"
        legacy_url = f"{base}/deposit/depositions/{DRAFT_ID}"
        root_url = f"{base}/records/{DRAFT_ID}/draft"
        files_url = f"{root_url}/files"
        final = routes[("GET", root_url)][1]
        assert isinstance(final, dict)
        final.pop("doi", None)
        final.pop("pids", None)
        reserved_legacy = self._legacy_draft(version="v3")
        reserved_legacy["doi"] = NEW_DOI
        reserved_modern = copy.deepcopy(final)
        reserved_modern["pids"] = {"doi": {"identifier": NEW_DOI}}
        routes[("GET", legacy_url)].append(reserved_legacy)
        routes[("GET", root_url)].append(reserved_modern)
        routes[("GET", files_url)].append(
            self._draft_files_collection(
                file_state="approved",
                final_configuration=True,
            )
        )
        reserve_url = f"{root_url}/pids/doi"
        error_body = json.dumps(
            {
                "status": 400,
                "message": "A validation error occurred.",
                "errors": [
                    {
                        "field": "pids.doi",
                        "messages": ["A PID already exists for type doi"],
                    }
                ],
            }
        ).encode("utf-8")
        routes[("POST", reserve_url)] = [
            urllib.error.HTTPError(
                reserve_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        ]
        result, opener, _ = self._execute(routes)
        self.assertEqual(result.exact_version_doi, NEW_DOI)
        requests = [
            item for item in opener.requests if item["url"] == reserve_url
        ]
        self.assertEqual(len(requests), 1)

    def test_unrecognized_doi_reservation_error_fails_closed(self) -> None:
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
        )
        base = "https://zenodo.org/api"
        root_url = f"{base}/records/{DRAFT_ID}/draft"
        final = routes[("GET", root_url)][1]
        assert isinstance(final, dict)
        final.pop("doi", None)
        final.pop("pids", None)
        reserve_url = f"{root_url}/pids/doi"
        error_body = json.dumps(
            {
                "status": 400,
                "errors": [
                    {
                        "field": "metadata.title",
                        "messages": ["A validation error occurred."],
                    }
                ],
            }
        ).encode("utf-8")
        routes[("POST", reserve_url)] = [
            urllib.error.HTTPError(
                reserve_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(error_body),
            )
        ]
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionRequestError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials(
                            "stage3b-local-simulation-value"
                        )
                    )
                ).prepare(self.plan)
        self.assertEqual(
            sum(item["url"] == reserve_url for item in opener.requests),
            1,
        )

    def test_conflicting_doi_representations_fail_closed(self) -> None:
        routes = self._routes()
        base = "https://zenodo.org/api"
        root_url = f"{base}/records/{DRAFT_ID}/draft"
        final = routes[("GET", root_url)][1]
        assert isinstance(final, dict)
        final["pids"] = {
            "doi": {"identifier": "10.5281/zenodo.39999999"}
        }
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionFamilyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        self.assertFalse(
            any(
                str(item["url"]).endswith("/draft/pids/doi")
                for item in opener.requests
            )
        )

    def test_doi_reservation_rejects_arbitrary_draft_provider_and_body(self) -> None:
        kind = production_transport_module._RequestKind.RESERVE_DRAFT_DOI
        for method, path in (
            ("POST", f"/api/records/{DRAFT_ID}/draft/pids/datacite"),
            ("PUT", f"/api/records/{DRAFT_ID}/draft/pids/doi"),
        ):
            with self.subTest(method=method, path=path):
                with self.assertRaises(ProductionSafetyError):
                    production_transport_module._BoundProductionRequest(
                        kind,
                        method,
                        path,
                    )

        requests = (
            production_transport_module._BoundProductionRequest(
                kind,
                "POST",
                "/api/records/99999999/draft/pids/doi",
            ),
            production_transport_module._BoundProductionRequest(
                kind,
                "POST",
                f"/api/records/{DRAFT_ID}/draft/pids/doi",
                json_body={"doi": NEW_DOI},
            ),
        )
        for request in requests:
            routes = self._routes()
            opener = _ScriptedOpener(routes)
            with patch("urllib.request.build_opener", return_value=opener):
                transport = UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
                transport.read_family(self.plan)
                transport.open_new_version_draft(self.plan)
                with self.assertRaises(ProductionSafetyError):
                    transport._send(request)
            self.assertFalse(
                any(
                    str(item["url"]).endswith("/draft/pids/doi")
                    for item in opener.requests
                )
            )

    def test_root_draft_can_omit_files_when_dedicated_readback_is_complete(self) -> None:
        result, opener, _ = self._execute(
            self._routes(
                initial_file_state="empty",
                include_root_files=False,
            )
        )
        self.assertTrue(result.validation["complete"])
        files_url = f"https://zenodo.org/api/records/{DRAFT_ID}/draft/files"
        self.assertEqual(
            sum(item["method"] == "GET" and item["url"] == files_url for item in opener.requests),
            3,
        )

    def test_live_root_files_array_defers_to_valid_dedicated_collection(self) -> None:
        for root_files in ([], True, "file-state", 1, None):
            with self.subTest(root_type=type(root_files).__name__):
                routes = self._routes(
                    initial_file_state="empty",
                    include_root_files=False,
                )
                root_url = f"https://zenodo.org/api/records/{DRAFT_ID}/draft"
                initial = routes[("GET", root_url)][0]
                assert isinstance(initial, dict)
                initial["files"] = root_files
                result, _, _ = self._execute(routes)
                self.assertTrue(result.validation["complete"])

    def test_non_object_root_files_never_supply_file_state_evidence(self) -> None:
        malformed = self._draft_files_collection(file_state="empty")
        del malformed["entries"]
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
            initial_dedicated_files=malformed,
        )
        root_url = f"https://zenodo.org/api/records/{DRAFT_ID}/draft"
        initial = routes[("GET", root_url)][0]
        assert isinstance(initial, dict)
        initial["files"] = [self._approved_file_entry()]
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        self.assertFalse(
            any(
                "/draft/files" in str(item["url"])
                and item["method"] != "GET"
                for item in opener.requests
            )
        )

    def test_recognized_root_collection_rejects_dedicated_contradiction(self) -> None:
        contradictory = self._draft_files_collection(file_state="approved")
        routes = self._routes(
            initial_file_state="empty",
            initial_dedicated_files=contradictory,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        self.assertFalse(
            any(
                "/draft/files" in str(item["url"])
                and item["method"] != "GET"
                for item in opener.requests
            )
        )

    def test_malformed_dedicated_collection_fails_with_root_array(self) -> None:
        with self.assertRaises(ProductionSafetyError):
            production_transport_module._normalized_draft_files(
                [],
                [],
                expected_draft_id=DRAFT_ID,
            )

    def test_explicit_empty_dedicated_file_collection_is_valid_initial_state(self) -> None:
        empty = self._draft_files_collection(file_state="empty")
        result, _, _ = self._execute(
            self._routes(
                initial_file_state="empty",
                include_root_files=False,
                initial_dedicated_files=empty,
            )
        )
        self.assertTrue(result.validation["complete"])

    def test_missing_dedicated_file_entries_fail_before_draft_mutation(self) -> None:
        missing = self._draft_files_collection(file_state="empty")
        del missing["entries"]
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
            initial_dedicated_files=missing,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        draft_mutations = [
            item
            for item in opener.requests
            if item["method"] in {"PUT", "DELETE"}
            or (
                item["method"] == "POST"
                and "/actions/newversion" not in str(item["url"])
            )
        ]
        self.assertEqual(draft_mutations, [])

    def test_disabled_dedicated_file_state_fails_before_upload(self) -> None:
        disabled = self._draft_files_collection(file_state="empty")
        disabled["enabled"] = False
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
            initial_dedicated_files=disabled,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        self.assertFalse(
            any(
                "/draft/files" in str(item["url"])
                and item["method"] in {"POST", "PUT", "DELETE"}
                for item in opener.requests
            )
        )

    def test_dedicated_file_readback_draft_identity_mismatch_fails(self) -> None:
        wrong = self._draft_files_collection(
            file_state="empty",
            draft_id="99999999",
        )
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
            initial_dedicated_files=wrong,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).prepare(self.plan)
        self.assertFalse(
            any(
                "/draft/files" in str(item["url"])
                and item["method"] != "GET"
                for item in opener.requests
            )
        )

    def test_uploaded_file_is_reloaded_before_metadata_save(self) -> None:
        result, opener, _ = self._execute(
            self._routes(
                initial_file_state="empty",
                include_root_files=False,
            )
        )
        self.assertTrue(result.validation["complete"])
        files_url = f"https://zenodo.org/api/records/{DRAFT_ID}/draft/files"
        metadata_url = f"https://zenodo.org/api/records/{DRAFT_ID}/draft"
        completed_index = next(
            index
            for index, item in enumerate(opener.requests)
            if item["method"] == "POST"
            and str(item["url"]).endswith(
                f"/{self.plan.archival_copy.archival_filename}/commit"
            )
        )
        reload_index = next(
            index
            for index, item in enumerate(opener.requests)
            if index > completed_index
            and item["method"] == "GET"
            and item["url"] == files_url
        )
        metadata_index = next(
            index
            for index, item in enumerate(opener.requests)
            if item["method"] == "PUT" and item["url"] == metadata_url
        )
        self.assertLess(completed_index, reload_index)
        self.assertLess(reload_index, metadata_index)

    def test_preserved_recovery_resumes_without_current_or_newversion_request(self) -> None:
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            result = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            ).resume(self.plan, self._recovery())
        self.assertFalse(result.new_version_created)
        self.assertEqual(result.recovery.draft_id, DRAFT_ID)
        self.assertFalse(
            any(
                "/actions/newversion" in str(item["url"])
                or item["url"]
                == f"https://zenodo.org/api/deposit/depositions/{SOURCE_ID}"
                for item in opener.requests
            )
        )

    def test_recovery_creation_draft_id_mismatch_fails_before_draft_read(self) -> None:
        recovery = self._recovery()
        creation = copy.deepcopy(recovery.creation_result)
        creation["id"] = 99999999
        conflicting = ProductionDraftRecovery(
            draft_id=recovery.draft_id,
            record_id=recovery.record_id,
            edit_url=recovery.edit_url,
            preview_url=recovery.preview_url,
            creation_result=creation,
        )
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).resume(self.plan, conflicting)
        self.assertTrue(
            all("/deposit/depositions/" not in str(item["url"]) for item in opener.requests)
        )

    def test_recovery_wrong_family_readback_fails_without_draft_mutation(self) -> None:
        wrong = self._legacy_draft(concept_doi="10.5281/zenodo.99999999")
        routes = self._routes(
            initial_file_state="empty",
            include_root_files=False,
            legacy_initial=wrong,
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProductionSafetyError):
                ProductionDraftExecutor(
                    UrllibProductionDraftTransport(
                        RuntimeProductionCredentials("stage3b-local-simulation-value")
                    )
                ).resume(self.plan, self._recovery())
        self.assertFalse(
            any(
                item["method"] in {"PUT", "DELETE"}
                or (
                    item["method"] == "POST"
                    and "/actions/newversion" not in str(item["url"])
                )
                for item in opener.requests
            )
        )

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

    def test_live_relation_family_readback_matches_the_validated_plan(self) -> None:
        latest = _live_relation_member(
            copy.deepcopy(self.family["latest"]),
            include_latest_marker=True,
        )
        members = [
            _live_relation_member(
                copy.deepcopy(item),
                include_latest_marker=True,
            )
            for item in self.family["members"]
        ]
        base = "https://zenodo.org/api"
        routes = {
            ("GET", f"{base}/records/{SOURCE_ID}"): [latest],
            ("GET", f"{base}/records/{SOURCE_ID}/versions"): [
                {"hits": {"hits": members}}
            ],
        }
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            observation = transport.read_family(self.plan)
        self.assertNotIn("latest_relation_record", observation)
        self.assertEqual(
            [item["url"] for item in opener.requests],
            [
                f"{base}/records/{SOURCE_ID}",
                f"{base}/records/{SOURCE_ID}/versions",
            ],
        )

    def test_fixed_latest_relation_is_read_when_markers_are_absent(self) -> None:
        latest = _live_relation_member(
            copy.deepcopy(self.family["latest"]),
            include_latest_marker=False,
        )
        members = [
            _live_relation_member(
                copy.deepcopy(item),
                include_latest_marker=False,
            )
            for item in self.family["members"]
        ]
        base = "https://zenodo.org/api"
        latest_relation_url = f"{base}/records/{SOURCE_ID}/versions/latest"
        routes = {
            ("GET", f"{base}/records/{SOURCE_ID}"): [latest],
            ("GET", f"{base}/records/{SOURCE_ID}/versions"): [
                {"hits": {"hits": members}}
            ],
            ("GET", latest_relation_url): [copy.deepcopy(latest)],
        }
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            observation = transport.read_family(self.plan)
        self.assertEqual(
            observation["latest_relation_record"]["id"],
            SOURCE_ID,
        )
        self.assertEqual(opener.requests[-1]["url"], latest_relation_url)

    def test_latest_relation_redirect_boundary_admits_only_the_exact_record(self) -> None:
        boundary = production_transport_module._ProductionRedirectBoundary()
        request = production_transport_module.urllib.request.Request(
            f"https://zenodo.org/api/records/{SOURCE_ID}/versions/latest",
            method="GET",
        )
        exact = boundary.redirect_request(
            request,
            None,
            301,
            "Moved Permanently",
            {},
            f"https://zenodo.org/api/records/{SOURCE_ID}",
        )
        self.assertIsNotNone(exact)
        self.assertEqual(
            exact.full_url,
            f"https://zenodo.org/api/records/{SOURCE_ID}",
        )
        for hostile in (
            f"https://example.invalid/api/records/{SOURCE_ID}",
            "https://zenodo.org/api/records/99999999",
        ):
            with self.subTest(hostile=hostile):
                self.assertIsNone(
                    boundary.redirect_request(
                        request,
                        None,
                        301,
                        "Moved Permanently",
                        {},
                        hostile,
                    )
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
                executor.resume(self.plan, self._recovery())
            with self.assertRaises(ProductionSafetyError):
                transport.open_new_version_draft(self.plan)
            with self.assertRaises(ProductionSafetyError):
                transport.resume_recovered_draft(self.plan, self._recovery())

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

    def test_dedicated_files_request_cannot_select_another_draft_or_path(self) -> None:
        routes = self._routes()
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            transport = UrllibProductionDraftTransport(
                RuntimeProductionCredentials("stage3b-local-simulation-value")
            )
            transport.read_family(self.plan)
            transport.open_new_version_draft(self.plan)
            for path in (
                "/api/records/99999999/draft/files",
                f"/api/records/{DRAFT_ID}/files",
                f"https://example.invalid/api/records/{DRAFT_ID}/draft/files",
            ):
                with self.subTest(path=path):
                    with self.assertRaises(ProductionSafetyError):
                        request = production_transport_module._BoundProductionRequest(
                            production_transport_module._RequestKind.READ_DRAFT_FILES,
                            "GET",
                            path,
                        )
                        transport._send(request)
        self.assertEqual(opener.requests[-1]["method"], "POST")
        self.assertIn("/actions/newversion", str(opener.requests[-1]["url"]))

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
            with self.assertRaises(ProductionSafetyError):
                transport.reserve_bound_draft_doi(self.plan)
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
                "reload_bound_draft_files",
                "resume_recovered_draft",
                "delete_inherited_archival_file",
                "upload_approved_archival_file",
                "save_approved_metadata",
                "reserve_bound_draft_doi",
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
                        "status": "completed",
                    }
                },
                "default_preview": filename,
                "order": [filename],
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

    def test_prepared_21869733_readback_skips_file_and_metadata_rewrites(self) -> None:
        draft_id = "21869733"
        concept_doi = self.plan.family.concept_doi
        exact_doi = "10.5281/zenodo.39999998"
        expected_metadata = self.plan.metadata_payload["metadata"]
        filename = self.plan.archival_copy.archival_filename

        def legacy_metadata() -> dict[str, object]:
            return {
                "title": expected_metadata["title"],
                "publisher": expected_metadata["publisher"],
                "publication_date": expected_metadata["publication_date"],
                "creators": [
                    {"name": "Aelion Kannon", "affiliation": None}
                ],
                "contributors": [
                    {
                        "name": "🔦 Lumen",
                        "affiliation": None,
                        "type": "Researcher",
                    },
                    {
                        "name": "⚮ Liora",
                        "affiliation": None,
                        "type": "Researcher",
                    },
                ],
                "description": expected_metadata["description"],
                "keywords": [
                    item["subject"] for item in expected_metadata["subjects"]
                ],
                "version": "v9",
                "resource_type": {
                    "title": "Report",
                    "type": "publication",
                    "subtype": "report",
                },
                "license": {"id": "cc-by-4.0"},
                "language": "eng",
                "access_right": "open",
                "related_identifiers": [
                    {
                        "identifier": "https://zenetism.aelionkannon.chatgpt.site",
                        "relation": "isDocumentedBy",
                        "resource_type": "other",
                        "scheme": "url",
                    }
                ],
                "custom": copy.deepcopy(
                    self.plan.metadata_payload["custom_fields"]
                ),
            }

        def draft(*, reserved: bool) -> dict[str, object]:
            value: dict[str, object] = {
                "id": draft_id,
                "recid": draft_id,
                "conceptdoi": concept_doi,
                "parent": {"pids": {"doi": {"identifier": concept_doi}}},
                "metadata": legacy_metadata(),
                "files": [],
                "access": None,
                "custom_fields": None,
                "submitted": False,
                "state": "unsubmitted",
                "status": "draft",
                "is_published": False,
            }
            if reserved:
                value["pids"] = {"doi": {"identifier": exact_doi}}
            return value

        entry = {
            "key": filename,
            "checksum": f"md5:{self.plan.archival_copy.checksums.md5}",
            "size": self.plan.archival_copy.checksums.byte_size,
            "status": "completed",
        }

        def files() -> dict[str, object]:
            return {
                "id": draft_id,
                "enabled": True,
                "entries": [copy.deepcopy(entry)],
                "default_preview": filename,
                "order": [],
                "links": {
                    "self": (
                        f"https://zenodo.org/api/records/{draft_id}/draft/files"
                    )
                },
            }

        family = _two_state_family_observation(self.manifest)
        base = "https://zenodo.org/api"
        legacy_url = f"{base}/deposit/depositions/{draft_id}"
        root_url = f"{base}/records/{draft_id}/draft"
        files_url = f"{root_url}/files"
        routes = {
            ("GET", f"{base}/records/{self.plan.source_record_id}"): [
                copy.deepcopy(family["latest"])
            ],
            ("GET", f"{base}/records/{self.plan.source_record_id}/versions"): [
                {"hits": {"hits": copy.deepcopy(family["members"])}}
            ],
            ("GET", legacy_url): [
                draft(reserved=False),
                draft(reserved=False),
                draft(reserved=True),
            ],
            ("GET", root_url): [
                draft(reserved=False),
                draft(reserved=False),
                draft(reserved=True),
            ],
            ("GET", files_url): [files(), files(), files()],
            ("POST", f"{root_url}/pids/doi"): [{}],
        }
        recovery = ProductionDraftRecovery(
            draft_id=draft_id,
            record_id=None,
            edit_url=f"https://zenodo.org/uploads/{draft_id}",
            preview_url=f"https://zenodo.org/records/{draft_id}?preview=1",
            creation_result={
                "id": int(draft_id),
                "conceptrecid": concept_doi.rsplit(".", 1)[-1],
                "created": "2026-08-10T08:27:58.542028+00:00",
                "modified": "2026-08-10T08:27:58.729012+00:00",
                "state": "unsubmitted",
                "submitted": False,
                "latest_draft": f"{base}/deposit/depositions/{draft_id}",
            },
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            result = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            ).resume(self.plan, recovery)
        self.assertEqual(result.exact_version_doi, exact_doi)
        self.assertFalse(result.validation["complete"])
        self.assertFalse(result.new_version_created)
        mutations = [
            item
            for item in opener.requests
            if item["method"] in {"POST", "PUT", "DELETE"}
        ]
        self.assertEqual(
            [(item["method"], item["url"]) for item in mutations],
            [("POST", f"{root_url}/pids/doi")],
        )

    def test_production_draft_21869733_recovery_resumes_without_newversion(self) -> None:
        draft_id = "21869733"
        concept_doi = self.plan.family.concept_doi
        concept_record_id = concept_doi.rsplit(".", 1)[-1]
        family = _two_state_family_observation(self.manifest)

        def draft(version: str) -> dict[str, object]:
            return {
                "id": draft_id,
                "recid": draft_id,
                "conceptdoi": concept_doi,
                "parent": {"pids": {"doi": {"identifier": concept_doi}}},
                "metadata": {"conceptdoi": concept_doi, "version": version},
                "submitted": False,
                "state": "unsubmitted",
                "status": "draft",
                "is_published": False,
            }

        initial = draft("v8")
        initial["files"] = []
        final = copy.deepcopy(self.plan.metadata_payload)
        exact_doi = f"10.5281/zenodo.{draft_id}"
        final.update(
            {
                "id": draft_id,
                "recid": draft_id,
                "doi": exact_doi,
                "pids": {"doi": {"identifier": exact_doi}},
                "parent": {"pids": {"doi": {"identifier": concept_doi}}},
                "submitted": False,
                "state": "unsubmitted",
                "status": "draft",
                "is_published": False,
            }
        )
        final["files"] = []
        filename = self.plan.archival_copy.archival_filename
        approved_entry = {
            "key": filename,
            "checksum": f"md5:{self.plan.archival_copy.checksums.md5}",
            "size": self.plan.archival_copy.checksums.byte_size,
            "status": "completed",
        }

        def file_collection(
            entries: list[dict[str, object]],
            *,
            final_configuration: bool,
        ) -> dict[str, object]:
            return {
                "id": draft_id,
                "enabled": True,
                "entries": entries,
                "default_preview": filename if final_configuration else None,
                "order": [filename] if final_configuration else [],
                "links": {
                    "self": (
                        f"https://zenodo.org/api/records/{draft_id}/draft/files"
                    )
                },
            }

        base = "https://zenodo.org/api"
        routes = {
            ("GET", f"{base}/records/{self.plan.source_record_id}"): [
                copy.deepcopy(family["latest"])
            ],
            ("GET", f"{base}/records/{self.plan.source_record_id}/versions"): [
                {"hits": {"hits": copy.deepcopy(family["members"])}}
            ],
            ("GET", f"{base}/deposit/depositions/{draft_id}"): [
                draft("v8"),
                draft("v9"),
            ],
            ("GET", f"{base}/records/{draft_id}/draft"): [initial, final],
            ("GET", f"{base}/records/{draft_id}/draft/files"): [
                file_collection([], final_configuration=False),
                file_collection([approved_entry], final_configuration=False),
                file_collection([approved_entry], final_configuration=True),
            ],
            ("POST", f"{base}/records/{draft_id}/draft/files"): [{}],
            ("PUT", f"{base}/records/{draft_id}/draft/files/{filename}/content"): [
                {}
            ],
            ("POST", f"{base}/records/{draft_id}/draft/files/{filename}/commit"): [
                {}
            ],
            ("PUT", f"{base}/records/{draft_id}/draft"): [{}],
        }
        recovery = ProductionDraftRecovery(
            draft_id=draft_id,
            record_id=None,
            edit_url=f"https://zenodo.org/uploads/{draft_id}",
            preview_url=f"https://zenodo.org/records/{draft_id}?preview=1",
            creation_result={
                "id": int(draft_id),
                "conceptrecid": concept_record_id,
                "created": "2026-08-10T08:27:58.542028+00:00",
                "modified": "2026-08-10T08:27:58.729012+00:00",
                "state": "unsubmitted",
                "submitted": False,
                "latest_draft": (
                    f"{base}/deposit/depositions/{draft_id}"
                ),
            },
        )
        opener = _ScriptedOpener(routes)
        with patch("urllib.request.build_opener", return_value=opener):
            result = ProductionDraftExecutor(
                UrllibProductionDraftTransport(
                    RuntimeProductionCredentials("stage3b-local-simulation-value")
                )
            ).resume(self.plan, recovery)
        self.assertEqual(result.recovery.draft_id, draft_id)
        self.assertFalse(result.new_version_created)
        self.assertTrue(result.validation["complete"])
        self.assertFalse(
            any("/actions/newversion" in str(item["url"]) for item in opener.requests)
        )


if __name__ == "__main__":
    unittest.main()
