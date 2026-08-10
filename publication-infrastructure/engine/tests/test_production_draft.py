from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from zenetism_engine.cli import main, parser
from zenetism_engine.errors import (
    ManifestApprovalError,
    ProductionFamilyError,
    ProductionPlanError,
    ProductionSafetyError,
    ProductionValidationError,
)
from zenetism_engine.production_boundary import (
    ZenodoEnvironment,
    environment_descriptor,
    production_environment,
)
from zenetism_engine.production_draft import (
    LocalProductionDraftSession,
    ProductionDraftIntent,
    ProductionDraftPlanner,
    ProductionFamilySnapshot,
)
from zenetism_engine.production_validation import (
    ArchitectProductionVisualConfirmation,
    validate_production_metadata,
)
from zenetism_engine.sandbox_verification import (
    PASSED_API,
    PASSED_VISUAL,
    VISUAL_VERIFICATION_REQUIRED,
)

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "publication-infrastructure/engine"
MANIFEST_PATH = (
    ROOT
    / "publication-infrastructure/manifests/zenetism-in-plain-language-v2.json"
)
TWO_STATE_MANIFEST_PATH = (
    ROOT
    / "publication-infrastructure/manifests/prose-formatting-reference-v9.json"
)
REGISTRY_PATH = ROOT / "publication-infrastructure/zenetism-publication-registry.csv"
PACKAGE = ENGINE / "zenetism_engine"
LIVE_FAMILY_PATH = ENGINE / "tests/prose_formatting_reference_v8_live_family.json"


def _family_member(
    *,
    record_id: str,
    exact_doi: str,
    version: str,
    family_index: int,
    is_latest: bool,
    concept_doi: str,
    title: str = "Inherited title must be replaced",
) -> dict[str, object]:
    return {
        "id": record_id,
        "recid": record_id,
        "doi": exact_doi,
        "metadata": {
            "doi": exact_doi,
            "conceptdoi": concept_doi,
            "version": version,
            "title": title,
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
        record_id="21830364",
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


def _intent() -> dict[str, str]:
    return {
        "route": "new-version",
        "record_key": "zenetism-in-plain-language",
        "next_version": "v3",
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


def _simulated_draft(
    *, draft_id: str = "30000001", concept_doi: str = "10.5281/zenodo.21174438"
) -> dict[str, object]:
    return {
        "id": draft_id,
        "recid": draft_id,
        "conceptdoi": concept_doi,
        "status": "new_version_draft",
        "state": "unsubmitted",
        "submitted": False,
        "is_published": False,
        "created": "2026-08-08T12:00:00+00:00",
        "updated": "2026-08-08T12:00:00+00:00",
    }


class ProductionDraftSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.two_state_manifest = json.loads(
            TWO_STATE_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.live_family = json.loads(LIVE_FAMILY_PATH.read_text(encoding="utf-8"))

    def setUp(self) -> None:
        self.planner = ProductionDraftPlanner()

    def plan(
        self,
        *,
        manifest: dict[str, object] | None = None,
        family: dict[str, object] | None = None,
        intent: dict[str, object] | None = None,
        registry_path: Path = REGISTRY_PATH,
    ):
        selected_manifest = manifest if manifest is not None else self.manifest
        selected_family = (
            family
            if family is not None
            else _family_observation(selected_manifest)
        )
        return self.planner.plan(
            selected_manifest,
            repository_root=ROOT,
            registry_path=registry_path,
            family_observation=selected_family,
            intent=intent if intent is not None else _intent(),
        )

    def plan_two_state(
        self,
        *,
        manifest: dict[str, object] | None = None,
        family: dict[str, object] | None = None,
        registry_path: Path = REGISTRY_PATH,
    ):
        selected_manifest = (
            manifest if manifest is not None else self.two_state_manifest
        )
        return self.planner.plan(
            selected_manifest,
            repository_root=ROOT,
            registry_path=registry_path,
            family_observation=(
                family
                if family is not None
                else _two_state_family_observation(selected_manifest)
            ),
            intent={
                "route": "new-version",
                "record_key": "prose-formatting-reference",
                "next_version": "v9",
            },
        )

    def legacy_v9_readback(self) -> tuple[dict[str, object], dict[str, object]]:
        plan = self.plan_two_state()
        expected = copy.deepcopy(plan.metadata_payload)
        metadata = expected["metadata"]
        filename = plan.archival_copy.archival_filename
        observed: dict[str, object] = {
            "access": None,
            "custom_fields": None,
            "metadata": {
                "title": metadata["title"],
                "publisher": "Zenodo",
                "publication_date": metadata["publication_date"],
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
                "description": metadata["description"],
                "keywords": [
                    item["subject"] for item in metadata["subjects"]
                ],
                "version": metadata["version"],
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
                "custom": {
                    "code:codeRepository": (
                        "https://github.com/KannonZenetism/"
                        "zenetism-field-physics/tree/main/"
                        "the-zenetist-canon/canonical-stabilization"
                    )
                },
            },
            "files": {
                "enabled": True,
                "entries": {
                    filename: {
                        "key": filename,
                        "status": "completed",
                        "size": plan.archival_copy.checksums.byte_size,
                        "checksum": f"md5:{plan.archival_copy.checksums.md5}",
                    }
                },
                "default_preview": filename,
                "order": [],
            },
        }
        return expected, observed

    def test_production_and_sandbox_identities_are_structurally_distinct(self) -> None:
        sandbox = environment_descriptor(ZenodoEnvironment.SANDBOX)
        production = environment_descriptor(ZenodoEnvironment.PRODUCTION)
        self.assertNotEqual(sandbox, production)
        self.assertNotEqual(sandbox.origin, production.origin)
        self.assertEqual(production, production_environment())

    def test_arbitrary_host_injection_fails(self) -> None:
        for value in (
            "https://zenodo.org",
            "https://example.invalid",
            "production.example.invalid",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ProductionSafetyError):
                    ZenodoEnvironment.parse(value)
        with self.assertRaises(ProductionSafetyError):
            environment_descriptor("production")  # type: ignore[arg-type]

    def test_production_mode_cannot_be_activated_by_an_arbitrary_url(self) -> None:
        options = parser().parse_args(
            [
                "production-draft-plan",
                "--manifest",
                str(MANIFEST_PATH),
                "--repository-root",
                str(ROOT),
                "--registry",
                str(REGISTRY_PATH),
                "--family-observation",
                "family.json",
                "--intent",
                "intent.json",
            ]
        )
        self.assertFalse(hasattr(options, "host"))
        self.assertFalse(hasattr(options, "url"))
        self.assertFalse(hasattr(options, "execute"))

    def test_arbitrary_production_record_selection_fails(self) -> None:
        proposed = {**_intent(), "record_id": "99999999"}
        with self.assertRaises(ProductionSafetyError):
            ProductionDraftIntent.from_object(proposed)

    def test_missing_manifest_identity_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        del manifest["zenodo"]["concept_doi"]
        with self.assertRaises(ManifestApprovalError):
            self.plan(manifest=manifest, family=_family_observation(self.manifest))

    def test_missing_family_identity_fails(self) -> None:
        family = _family_observation(self.manifest)
        del family["members"]
        with self.assertRaises(ProductionFamilyError):
            self.plan(family=family)

    def test_duplicate_manifest_family_member_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["zenodo"]["version_family"].append(
            copy.deepcopy(manifest["zenodo"]["version_family"][0])
        )
        with self.assertRaises(ProductionFamilyError) as context:
            self.plan(
                manifest=manifest,
                family=_family_observation(self.manifest),
            )
        self.assertIn("duplicate production family member", str(context.exception))

    def test_duplicated_manifest_member_identity_does_not_collapse(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        duplicate = copy.deepcopy(manifest["zenodo"]["version_family"][0])
        duplicate["record_revision"] = 99
        manifest["zenodo"]["version_family"].append(duplicate)
        with self.assertRaises(ProductionFamilyError) as context:
            self.plan(
                manifest=manifest,
                family=_family_observation(self.manifest),
            )
        self.assertIn("duplicate production family member", str(context.exception))

    def test_contradictory_manifest_latest_markers_fail(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["zenodo"]["version_family"][0]["is_latest"] = True
        with self.assertRaises(ProductionFamilyError) as context:
            self.plan(
                manifest=manifest,
                family=_family_observation(self.manifest),
            )
        self.assertIn("exactly one latest", str(context.exception))

    def test_incorrect_manifest_latest_member_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["zenodo"]["version_family"][0]["is_latest"] = True
        manifest["zenodo"]["version_family"][1]["is_latest"] = False
        with self.assertRaises(ProductionFamilyError) as context:
            self.plan(
                manifest=manifest,
                family=_family_observation(self.manifest),
            )
        self.assertIn("contradicts its current record identity", str(context.exception))

    def test_missing_registry_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.csv"
            with self.assertRaises(ProductionPlanError):
                self.plan(registry_path=missing)

    def test_registry_identity_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "registry.csv"
            text = REGISTRY_PATH.read_text(encoding="utf-8").replace(
                "published reference cycle", "unreviewed"
            )
            changed.write_text(text, encoding="utf-8")
            with self.assertRaises(ProductionPlanError):
                self.plan(registry_path=changed)

    def test_two_state_v8_to_v9_package_passes_planning(self) -> None:
        plan = self.plan_two_state()
        baseline = self.two_state_manifest["published_baseline"]
        candidate = self.two_state_manifest["candidate"]
        self.assertNotEqual(
            baseline["github"]["sha256"],
            candidate["github"]["sha256"],
        )
        self.assertEqual(plan.source_record_id, "21843931")
        self.assertEqual(plan.family.latest.version_label, "v8")
        self.assertEqual(plan.intent.next_version, "v9")
        self.assertEqual(
            plan.archival_copy.archival_filename,
            "prose-formatting-reference_v9.md",
        )
        self.assertEqual(
            plan.archival_copy.checksums.sha256,
            candidate["github"]["sha256"],
        )
        self.assertFalse(plan.as_dict()["final_release_action_available"])

    def test_two_state_candidate_description_takes_approved_standard_form(self) -> None:
        package = self.two_state_manifest["candidate"]["description"]
        description = package["rendered_html"]
        self.assertEqual(package["word_count"], 160)
        self.assertIn(
            "It also establishes cadence conformance where explicitly determined",
            description,
        )
        self.assertNotIn("It also governs cadence conformance", description)
        self.assertIn("<strong>Document class:</strong>", description)
        self.assertIn("<strong>Companion to:</strong>", description)
        self.assertIn(
            "<code>canonical-compositional-stabilization-protocol.md</code>",
            description,
        )
        self.assertNotIn(
            "<em>Canonical Compositional Stabilization Protocol &mdash; "
            "Mathematical / LaTeX Formatting Reference</em>",
            description,
        )
        self.assertIn(
            "Canonical file: <code>prose-formatting-reference.md</code>.",
            description,
        )
        self.assertNotIn("OpenTimestamps", description)

    def test_live_inveniordm_version_relation_family_passes_planning(self) -> None:
        family = copy.deepcopy(self.live_family)
        snapshot = ProductionFamilySnapshot.from_object(family)
        self.assertEqual(
            [item.family_index for item in snapshot.members],
            list(range(1, 9)),
        )
        self.assertEqual(snapshot.latest.record_id, "21843931")
        self.assertEqual(snapshot.latest.version_label, "v8")
        self.assertTrue(snapshot.latest.is_latest)
        plan = self.plan_two_state(family=family)
        self.assertEqual(plan.family.as_dict(), snapshot.as_dict())

    def test_live_relation_parent_must_match_the_concept_identity(self) -> None:
        family = copy.deepcopy(self.live_family)
        relation = family["members"][0]["metadata"]["relations"]["version"][0]
        relation["parent"]["pid_value"] = "99999999"
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("parent differs", str(context.exception))

    def test_conflicting_legacy_and_live_relation_indices_fail(self) -> None:
        family = copy.deepcopy(self.live_family)
        family["latest"]["versions"] = {"index": 99, "is_latest": True}
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("conflicting family-index", str(context.exception))

    def test_conflicting_legacy_and_live_latest_markers_fail(self) -> None:
        family = copy.deepcopy(self.live_family)
        family["latest"]["versions"] = {"index": 8, "is_latest": False}
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("conflicting latest-state", str(context.exception))

    def test_duplicate_live_version_relation_entries_fail(self) -> None:
        family = copy.deepcopy(self.live_family)
        relations = family["latest"]["metadata"]["relations"]["version"]
        relations.append(copy.deepcopy(relations[0]))
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("exactly one entry", str(context.exception))

    def test_hostile_live_latest_relation_fails(self) -> None:
        family = copy.deepcopy(self.live_family)
        family["latest"]["links"]["latest"] = (
            "https://example.invalid/api/records/21843931/versions/latest"
        )
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("fixed production identity", str(context.exception))

    def test_absent_live_relation_index_evidence_fails(self) -> None:
        family = copy.deepcopy(self.live_family)
        del family["latest"]["metadata"]["relations"]["version"][0]["index"]
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("missing or unsupported fields", str(context.exception))

    def test_absent_latest_evidence_fails(self) -> None:
        family = copy.deepcopy(self.live_family)
        del family["latest"]["metadata"]["relations"]["version"][0]["is_last"]
        for item in family["members"]:
            del item["metadata"]["relations"]["version"][0]["is_last"]
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("latest-state evidence", str(context.exception))

    def test_fixed_latest_relation_reconciles_absent_markers(self) -> None:
        family = copy.deepcopy(self.live_family)
        del family["latest"]["metadata"]["relations"]["version"][0]["is_last"]
        for item in family["members"]:
            del item["metadata"]["relations"]["version"][0]["is_last"]
        family["latest_relation_record"] = copy.deepcopy(family["latest"])
        snapshot = ProductionFamilySnapshot.from_object(family)
        self.assertEqual(snapshot.latest.record_id, "21843931")
        self.assertEqual(
            [item.record_id for item in snapshot.members if item.is_latest],
            ["21843931"],
        )

    def test_fixed_latest_relation_mismatch_fails(self) -> None:
        family = copy.deepcopy(self.live_family)
        del family["latest"]["metadata"]["relations"]["version"][0]["is_last"]
        for item in family["members"]:
            del item["metadata"]["relations"]["version"][0]["is_last"]
        relation_record = copy.deepcopy(family["latest"])
        relation_record["doi"] = "10.5281/zenodo.99999999"
        family["latest_relation_record"] = relation_record
        with self.assertRaises(ProductionFamilyError) as context:
            ProductionFamilySnapshot.from_object(family)
        self.assertIn("latest relation differs", str(context.exception))

    def test_two_state_published_baseline_payload_mismatch_fails(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        manifest["published_baseline"]["github"]["sha256"] = "0" * 64
        with self.assertRaises(ProductionPlanError) as context:
            self.plan_two_state(
                manifest=manifest,
                family=_two_state_family_observation(self.two_state_manifest),
            )
        self.assertIn("baseline GitHub and Zenodo", str(context.exception))

    def test_two_state_published_family_mismatch_fails(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        manifest["published_baseline"]["zenodo"]["exact_version_doi"] = (
            "10.5281/zenodo.99999999"
        )
        with self.assertRaises(ProductionFamilyError):
            self.plan_two_state(
                manifest=manifest,
                family=_two_state_family_observation(self.two_state_manifest),
            )

    def test_two_state_candidate_must_match_approved_github_identity(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        candidate = manifest["candidate"]
        candidate["github"]["sha256"] = "1" * 64
        candidate["production_identity"]["archival_sha256"] = "1" * 64
        with self.assertRaises(ManifestApprovalError):
            self.plan_two_state(manifest=manifest)

    def test_two_state_baseline_candidate_identity_collapse_fails(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        baseline = manifest["published_baseline"]["github"]
        candidate = manifest["candidate"]
        candidate["github"]["byte_size"] = baseline["byte_size"]
        candidate["github"]["sha256"] = baseline["sha256"]
        candidate["github"]["md5"] = baseline["md5"]
        candidate["production_identity"]["archival_byte_size"] = baseline[
            "byte_size"
        ]
        candidate["production_identity"]["archival_sha256"] = baseline["sha256"]
        candidate["production_identity"]["archival_md5"] = baseline["md5"]
        with self.assertRaises(ProductionPlanError) as context:
            self.plan_two_state(manifest=manifest)
        self.assertIn("payload identities collapsed", str(context.exception))

    def test_two_state_site_relation_transition_is_explicit(self) -> None:
        original = copy.deepcopy(self.two_state_manifest)
        plan = self.plan_two_state(manifest=original)
        self.assertIsNone(original["published_baseline"]["site_relation"])
        self.assertEqual(original["published_baseline"]["related_identifiers"], [])
        related = plan.metadata_payload["metadata"]["related_identifiers"]
        self.assertEqual(
            related,
            [
                {
                    "identifier": "https://zenetism.aelionkannon.chatgpt.site",
                    "scheme": "url",
                    "relation_type": {"id": "isdocumentedby"},
                    "resource_type": {"id": "other"},
                }
            ],
        )

    def test_two_state_unapproved_site_relation_transition_fails(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        manifest["candidate"]["site_relation"]["identifier"] = (
            "https://example.invalid"
        )
        manifest["candidate"]["related_identifiers"][0]["identifier"] = (
            "https://example.invalid"
        )
        with self.assertRaises(ProductionPlanError) as context:
            self.plan_two_state(manifest=manifest)
        self.assertIn("Site-relation transition", str(context.exception))

    def test_two_state_contradictory_historical_site_state_fails(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        manifest["published_baseline"]["site_relation"] = copy.deepcopy(
            manifest["candidate"]["site_relation"]
        )
        with self.assertRaises(ProductionPlanError) as context:
            self.plan_two_state(manifest=manifest)
        self.assertIn("absence is contradictory", str(context.exception))

    def test_two_state_registry_transition_must_match_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "registry.csv"
            text = REGISTRY_PATH.read_text(encoding="utf-8").replace(
                "absent — v9 conformance prepared",
                "validated",
            )
            changed.write_text(text, encoding="utf-8")
            with self.assertRaises(ProductionPlanError) as context:
                self.plan_two_state(registry_path=changed)
            self.assertIn("published baseline", str(context.exception))

    def test_concept_doi_mismatch_fails(self) -> None:
        family = _family_observation(self.manifest)
        family["concept_doi"] = "10.5281/zenodo.99999999"
        with self.assertRaises(ProductionFamilyError):
            self.plan(family=family)

    def test_previous_exact_version_mismatch_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["zenodo"]["previous_version_doi"] = "10.5281/zenodo.99999999"
        with self.assertRaises(ProductionFamilyError):
            self.plan(manifest=manifest, family=_family_observation(self.manifest))

    def test_contradictory_doi_representations_fail(self) -> None:
        family = _family_observation(self.manifest)
        family["latest"]["metadata"]["doi"] = "10.5281/zenodo.99999999"
        with self.assertRaises(ProductionFamilyError):
            self.plan(family=family)

    def test_ambiguous_family_selection_fails(self) -> None:
        family = _family_observation(self.manifest)
        family["members"].append(copy.deepcopy(family["members"][0]))
        with self.assertRaises(ProductionFamilyError):
            self.plan(family=family)

    def test_wrong_family_record_selection_fails(self) -> None:
        family = _family_observation(self.manifest)
        family["latest"]["id"] = "99999999"
        family["latest"]["recid"] = "99999999"
        family["members"][1]["id"] = "99999999"
        family["members"][1]["recid"] = "99999999"
        with self.assertRaises(ProductionFamilyError):
            self.plan(family=family)

    def test_standalone_deposit_fallback_is_rejected(self) -> None:
        proposed = {**_intent(), "route": "standalone"}
        with self.assertRaises(ProductionSafetyError):
            self.plan(intent=proposed)

    def test_approved_new_version_family_flow_succeeds_in_simulation(self) -> None:
        result = self.plan().as_dict()
        self.assertEqual(result["status"], "local_plan_only")
        self.assertEqual(result["source_record_id"], "21830364")
        self.assertEqual(
            result["new_version_path"],
            "/deposit/depositions/21830364/actions/newversion",
        )
        self.assertFalse(result["production_network_enabled"])
        self.assertFalse(result["standalone_deposit_available"])
        self.assertFalse(result["final_release_action_available"])
        self.assertEqual(
            result["terminal_state"],
            "stop_for_architect_review_before_publication",
        )

    def test_inherited_metadata_is_not_trusted(self) -> None:
        result = self.plan().as_dict()
        self.assertEqual(
            result["metadata_payload"]["metadata"]["title"],
            self.manifest["zenodo"]["metadata"]["title"],
        )
        self.assertIn(
            "title",
            result["inherited_metadata_differences"],
        )
        self.assertEqual(
            result["metadata_policy"],
            "replace_inherited_values_from_approved_manifest",
        )

    def test_archival_filename_payload_and_checksums_remain_exact(self) -> None:
        plan = self.plan()
        expected_bytes = (
            ROOT / self.manifest["github"]["path"]
        ).read_bytes()
        self.assertEqual(
            plan.archival_copy.archival_filename,
            "zenetism-in-plain-language_v3.md",
        )
        self.assertEqual(plan.archival_copy.payload, expected_bytes)
        self.assertEqual(
            plan.archival_copy.checksums.sha256,
            self.manifest["github"]["sha256"],
        )
        self.assertEqual(
            plan.archival_copy.checksums.md5,
            self.manifest["github"]["md5"],
        )
        self.assertEqual(
            plan.metadata_payload["files"]["default_preview"],
            "zenetism-in-plain-language_v3.md",
        )

    def test_recovery_identity_survives_simulated_partial_failure(self) -> None:
        session = LocalProductionDraftSession(self.plan())
        draft = {
            "id": "30000001",
            "created": "2026-08-08T12:00:00+00:00",
        }
        draft["Authorization"] = False
        with self.assertRaises(ProductionPlanError) as context:
            session.fail_after_creation(draft)
        recovery = context.exception.recovery
        self.assertIsNotNone(recovery)
        assert recovery is not None
        self.assertEqual(recovery["draft_id"], "30000001")
        self.assertIsNone(recovery["record_id"])
        self.assertEqual(
            recovery["edit_url"], "https://zenodo.org/uploads/30000001"
        )
        self.assertEqual(
            recovery["preview_url"],
            "https://zenodo.org/records/30000001?preview=1",
        )
        self.assertEqual(session.creation_count, 1)
        serialized = json.dumps(recovery)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("credential", serialized.casefold())

        stations = [item.station for item in session.plan.operations]
        self.assertLess(
            stations.index("preserve_recovery_identity"),
            stations.index("reserve_new_exact_version_doi"),
        )
        self.assertLess(
            stations.index("preserve_recovery_identity"),
            stations.index("replace_inherited_metadata"),
        )

    def test_resume_continues_same_draft_and_does_not_create_another(self) -> None:
        session = LocalProductionDraftSession(self.plan())
        draft = _simulated_draft()
        recovery = session.preserve_created_draft(draft)
        result = session.resume(draft, draft_id=recovery.draft_id)
        self.assertEqual(result["creation_count"], 1)
        self.assertFalse(result["second_draft_created"])
        self.assertEqual(session.creation_count, 1)
        with self.assertRaises(ProductionSafetyError):
            session.preserve_created_draft(draft)

    def test_resume_rejects_different_or_published_draft(self) -> None:
        session = LocalProductionDraftSession(self.plan())
        draft = _simulated_draft()
        session.preserve_created_draft(draft)
        with self.assertRaises(ProductionSafetyError):
            session.resume(_simulated_draft(draft_id="30000002"), draft_id="30000002")
        published = _simulated_draft()
        published["is_published"] = True
        with self.assertRaises(ProductionSafetyError):
            session.resume(published, draft_id="30000001")

    def test_live_legacy_creator_mapping_passes_exact_identity(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.creators"], PASSED_API)

    def test_live_legacy_contributor_mapping_preserves_order_and_type(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.contributors"], PASSED_API)
        changed = copy.deepcopy(observed)
        changed["metadata"]["contributors"].reverse()
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, changed, draft_id="21869733"
            )

    def test_live_legacy_repository_url_mapping_requires_exact_path(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(
            states["custom_fields.code:codeRepository"], PASSED_API
        )
        changed = copy.deepcopy(observed)
        changed["metadata"]["custom"]["code:codeRepository"] = (
            "https://github.com/KannonZenetism/zenetism-field-physics"
        )
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, changed, draft_id="21869733"
            )

    def test_live_legacy_keywords_require_exact_count_and_order(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.subjects"], PASSED_API)
        changed = copy.deepcopy(observed)
        changed["metadata"]["keywords"][0:2] = reversed(
            changed["metadata"]["keywords"][0:2]
        )
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, changed, draft_id="21869733"
            )

    def test_live_legacy_site_relation_mapping_passes_exact_identity(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.related_identifiers"], PASSED_API)
        changed = copy.deepcopy(observed)
        changed["metadata"]["related_identifiers"][0]["relation"] = "isPartOf"
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, changed, draft_id="21869733"
            )

    def test_conflicting_modern_and_legacy_metadata_fails_closed(self) -> None:
        expected, observed = self.legacy_v9_readback()
        observed["custom_fields"] = {
            "code:codeRepository": "https://example.invalid/conflict"
        }
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, observed, draft_id="21869733"
            )

    def test_one_completed_file_accepts_explicit_default_with_empty_order(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["files.default_preview"], PASSED_API)
        self.assertEqual(states["files.order"], PASSED_API)

    def test_nonempty_file_order_must_match_and_foreign_order_fails(self) -> None:
        expected, observed = self.legacy_v9_readback()
        observed["files"]["order"] = copy.deepcopy(expected["files"]["order"])
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["files.order"], PASSED_API)
        observed["files"]["order"] = ["foreign.md"]
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, observed, draft_id="21869733"
            )

    def test_live_legacy_readback_retains_copyright_visual_channel(self) -> None:
        expected, observed = self.legacy_v9_readback()
        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(
            states["metadata.copyright"], VISUAL_VERIFICATION_REQUIRED
        )
        self.assertFalse(report.complete)

    def test_v9_publisher_is_explicit_and_api_validated(self) -> None:
        expected, observed = self.legacy_v9_readback()
        self.assertEqual(expected["metadata"]["publisher"], "Zenodo")

        missing_manifest = copy.deepcopy(self.two_state_manifest)
        del missing_manifest["candidate"]["metadata"]["publisher"]
        with self.assertRaises(ProductionPlanError):
            self.plan_two_state(
                manifest=missing_manifest,
                family=self.live_family,
            )

        report = validate_production_metadata(
            expected, observed, draft_id="21869733"
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.publisher"], PASSED_API)

        missing = copy.deepcopy(observed)
        del missing["metadata"]["publisher"]
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, missing, draft_id="21869733"
            )

        incorrect = copy.deepcopy(observed)
        incorrect["metadata"]["publisher"] = "Aelion Kannon"
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                expected, incorrect, draft_id="21869733"
            )

    def test_external_publisher_continuation_must_remain_explicit(self) -> None:
        manifest = copy.deepcopy(self.two_state_manifest)
        baseline_metadata = manifest["published_baseline"]["zenodo"]["metadata"]
        candidate_metadata = manifest["candidate"]["metadata"]
        baseline_metadata["publisher"] = "External Academic Press"
        candidate_metadata["publisher"] = "External Academic Press"
        plan = ProductionDraftPlanner().plan(
            manifest,
            repository_root=ROOT,
            registry_path=REGISTRY_PATH,
            family_observation=self.live_family,
            intent={
                "route": "new-version",
                "record_key": "prose-formatting-reference",
                "next_version": "v9",
            },
        )
        self.assertEqual(
            plan.metadata_payload["metadata"]["publisher"],
            "External Academic Press",
        )

        candidate_metadata["publisher"] = "Zenodo"
        with self.assertRaises(ProductionPlanError):
            ProductionDraftPlanner().plan(
                manifest,
                repository_root=ROOT,
                registry_path=REGISTRY_PATH,
                family_observation=self.live_family,
                intent={
                    "route": "new-version",
                    "record_key": "prose-formatting-reference",
                    "next_version": "v9",
                },
            )

    def test_api_visible_validation_remains_fail_closed(self) -> None:
        expected = {
            "metadata": {"title": "Approved title", "copyright": "2026 Aelion Kannon"}
        }
        observed = {"metadata": {"copyright": "2026 Aelion Kannon"}}
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(expected, observed, draft_id="30000001")

        with self.assertRaises(ProductionValidationError):
            validate_production_metadata({}, {}, draft_id="30000001")

    def test_ui_only_field_requires_visual_verification_without_inference(self) -> None:
        expected = {
            "metadata": {"title": "Approved title", "copyright": "2026 Aelion Kannon"}
        }
        observed = {"metadata": {"title": "Approved title"}}
        report = validate_production_metadata(
            expected,
            observed,
            draft_id="30000001",
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.title"], PASSED_API)
        self.assertEqual(
            states["metadata.copyright"], VISUAL_VERIFICATION_REQUIRED
        )
        self.assertFalse(report.complete)

    def test_explicit_visual_confirmation_completes_validation(self) -> None:
        expected = {
            "metadata": {"title": "Approved title", "copyright": "2026 Aelion Kannon"}
        }
        observed = {"metadata": {"title": "Approved title"}}
        confirmation = ArchitectProductionVisualConfirmation.from_object(
            {
                "environment": "production",
                "draft_id": "30000001",
                "confirmed_by": "architect",
                "verification_channel": "visual",
                "fields": {"metadata.copyright": "2026 Aelion Kannon"},
            }
        )
        report = validate_production_metadata(
            expected,
            observed,
            draft_id="30000001",
            architect_visual_confirmation=confirmation,
        )
        states = {item.field: item.state for item in report.fields}
        self.assertEqual(states["metadata.title"], PASSED_API)
        self.assertEqual(states["metadata.copyright"], PASSED_VISUAL)
        self.assertTrue(report.complete)

    def test_complete_planned_payload_requires_every_verification_channel(self) -> None:
        expected = copy.deepcopy(self.plan().metadata_payload)
        observed = copy.deepcopy(expected)
        del observed["metadata"]["copyright"]
        confirmation = ArchitectProductionVisualConfirmation.from_object(
            {
                "environment": "production",
                "draft_id": "30000001",
                "confirmed_by": "architect",
                "verification_channel": "visual",
                "fields": {
                    "metadata.copyright": expected["metadata"]["copyright"]
                },
            }
        )
        report = validate_production_metadata(
            expected,
            observed,
            draft_id="30000001",
            architect_visual_confirmation=confirmation,
        )
        self.assertTrue(report.complete)
        self.assertTrue(
            all(
                item.state in {PASSED_API, PASSED_VISUAL}
                for item in report.fields
            )
        )

    def test_incorrect_visual_confirmation_fails(self) -> None:
        confirmation = ArchitectProductionVisualConfirmation.from_object(
            {
                "environment": "production",
                "draft_id": "30000001",
                "confirmed_by": "architect",
                "verification_channel": "visual",
                "fields": {"metadata.copyright": "Incorrect"},
            }
        )
        with self.assertRaises(ProductionValidationError):
            validate_production_metadata(
                {"metadata": {"copyright": "2026 Aelion Kannon"}},
                {"metadata": {}},
                draft_id="30000001",
                architect_visual_confirmation=confirmation,
            )

    def test_visual_channel_rejects_api_verifiable_fields(self) -> None:
        with self.assertRaises(ProductionValidationError):
            ArchitectProductionVisualConfirmation.from_object(
                {
                    "environment": "production",
                    "draft_id": "30000001",
                    "confirmed_by": "architect",
                    "verification_channel": "visual",
                    "fields": {"metadata.title": "Approved title"},
                }
            )

    def test_production_network_access_is_not_required(self) -> None:
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("production planning attempted network access"),
        ):
            result = self.plan().as_dict()
        self.assertFalse(result["production_network_enabled"])

    def test_cli_plan_reads_only_local_inputs_and_no_environment_credential(self) -> None:
        family = _family_observation(self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory)
            family_path = location / "family.json"
            intent_path = location / "intent.json"
            audit_path = location / "audit.json"
            family_path.write_text(json.dumps(family), encoding="utf-8")
            intent_path.write_text(json.dumps(_intent()), encoding="utf-8")
            output = io.StringIO()
            errors = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("production planning attempted network access"),
            ), redirect_stdout(output), redirect_stderr(errors):
                status = main(
                    [
                        "production-draft-plan",
                        "--manifest",
                        str(MANIFEST_PATH),
                        "--repository-root",
                        str(ROOT),
                        "--registry",
                        str(REGISTRY_PATH),
                        "--family-observation",
                        str(family_path),
                        "--intent",
                        str(intent_path),
                        "--audit",
                        str(audit_path),
                    ]
                )
            self.assertEqual(status, 0, errors.getvalue())
            result = json.loads(output.getvalue())
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(result, audit)
            self.assertFalse(result["credentials_requested"])
            self.assertFalse(result["credentials_loaded"])
            self.assertNotIn("Authorization", json.dumps(result))

    def test_no_final_release_operation_or_generic_request_escape_hatch_exists(self) -> None:
        plan = self.plan().as_dict()
        operations = json.dumps(plan["operations"]).casefold()
        self.assertNotIn("actions/publish", operations)
        self.assertNotIn('"publish"', operations)
        self.assertFalse(hasattr(LocalProductionDraftSession, "request"))
        self.assertFalse(hasattr(LocalProductionDraftSession, "execute"))

        cli_options = parser().format_help().casefold()
        self.assertNotIn("production-publish", cli_options)
        production_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("production_*.py"))
        ).casefold()
        self.assertNotIn("/actions/publish", production_sources)
        self.assertNotIn("/actions/edit", production_sources)
        self.assertNotIn("/actions/discard", production_sources)
        self.assertNotIn("def request(", production_sources)


if __name__ == "__main__":
    unittest.main()
