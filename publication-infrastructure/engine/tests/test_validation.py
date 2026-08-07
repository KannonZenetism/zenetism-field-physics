from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from zenetism_engine.validation import validate_manifest

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "zenetism-in-plain-language-v2.json"
)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reference = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_reference_vector_known_values(self) -> None:
        manifest = self.reference
        self.assertEqual(manifest["zenodo"]["exact_version_doi"], "10.5281/zenodo.21830364")
        self.assertEqual(manifest["zenodo"]["concept_doi"], "10.5281/zenodo.21174438")
        self.assertEqual(manifest["zenodo"]["archival_filename"], "zenetism-in-plain-language_v2.md")
        self.assertEqual(manifest["zenodo"]["publication_date"], "2026-07-03")
        self.assertEqual(manifest["github"]["sha256"], "174a984a83ff342af0cb14e64fb61215e05ec31e865ae7592142eb87fd48c1f8")
        self.assertEqual(manifest["github"]["md5"], "ea3b7e4230d7c43940657c6a1116075c")
        self.assertEqual(manifest["zenodo"]["record_revision"], 3)
        self.assertEqual(manifest["zenodo"]["target_version"], "v2")
        self.assertNotEqual(manifest["zenodo"]["record_revision"], manifest["zenodo"]["target_version"])

    def test_exact_reference_manifest_passes(self) -> None:
        report = validate_manifest(self.reference, copy.deepcopy(self.reference))
        self.assertTrue(report.passed)

    def test_missing_governed_field_fails_closed(self) -> None:
        expected = copy.deepcopy(self.reference)
        del expected["zenodo"]["publication_date"]
        report = validate_manifest(expected, self.reference)
        self.assertFalse(report.passed)
        item = next(item for item in report.results if item.field == "zenodo.publication_date")
        self.assertEqual(item.status, "fail")
        self.assertIn("missing from manifest", item.reason)

    def test_missing_retrieved_version_does_not_fall_back_to_revision(self) -> None:
        observed = copy.deepcopy(self.reference)
        observed["zenodo"]["target_version"] = None
        observed["zenodo"]["record_revision"] = 2
        report = validate_manifest(self.reference, observed)
        self.assertFalse(report.passed)
        item = next(
            item for item in report.results
            if item.field == "invariant.document_version_is_explicit_vN"
        )
        self.assertEqual(item.status, "fail")

    def test_mismatch_and_keyword_order_fail_closed(self) -> None:
        observed = copy.deepcopy(self.reference)
        observed["zenodo"]["concept_doi"] = "10.5281/zenodo.999"
        observed["keywords"][0], observed["keywords"][1] = (
            observed["keywords"][1],
            observed["keywords"][0],
        )
        report = validate_manifest(self.reference, observed)
        self.assertFalse(report.passed)
        failures = {item.field for item in report.results if item.status == "fail"}
        self.assertIn("zenodo.concept_doi", failures)
        self.assertIn("keywords", failures)


if __name__ == "__main__":
    unittest.main()
