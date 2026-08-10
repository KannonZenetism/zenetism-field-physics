from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from zenetism_engine.registry import REGISTRY_FIELDS, registry_row, update_registry
from zenetism_engine.validation import validate_manifest

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "manifests"
    / "zenetism-in-plain-language-v2.json"
)
OPERATIONAL_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "zenetism-publication-registry.csv"
)


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.report = validate_manifest(cls.manifest, cls.manifest).as_dict()

    def test_registry_requires_passing_validation(self) -> None:
        failed = {"passed": False}
        with self.assertRaises(ValueError):
            registry_row(
                self.manifest,
                failed,
                verification_date="2026-08-07",
                architect_approval_state="held",
                notes="",
            )

    def test_registry_writes_v2_fields_and_updates_by_canonical_filename(self) -> None:
        row = registry_row(
            self.manifest,
            self.report,
            verification_date="2026-08-07",
            architect_approval_state="published reference cycle",
            notes="reference",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            update_registry(path, row)
            row["notes"] = "verified again"
            update_registry(path, row)
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames or ()), REGISTRY_FIELDS)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["latest_version_doi"], "10.5281/zenodo.21830364")
            self.assertEqual(rows[0]["notes"], "verified again")

    def test_prose_formatting_reference_registry_records_published_v9(self) -> None:
        with OPERATIONAL_REGISTRY.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        matches = [
            row
            for row in rows
            if row["canonical_filename"] == "prose-formatting-reference.md"
        ]
        self.assertEqual(len(matches), 1)
        row = matches[0]
        self.assertEqual(row["latest_version_label"], "v9")
        self.assertEqual(
            row["latest_version_doi"],
            "10.5281/zenodo.21869733",
        )
        self.assertEqual(
            row["zenodo_archival_filename"],
            "prose-formatting-reference_v9.md",
        )
        self.assertEqual(
            row["zenodo_checksum"],
            "md5:dd7608313d2fb7747e2c70d483aa906a",
        )
        self.assertEqual(row["site_relation_status"], "validated")
        self.assertEqual(
            row["architect_approval_state"],
            "published — post-publication verified",
        )


if __name__ == "__main__":
    unittest.main()
