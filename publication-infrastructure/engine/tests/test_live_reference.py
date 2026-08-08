from __future__ import annotations

import os
import unittest

from zenetism_engine.manifest import build_manifest, retrieve_observation


@unittest.skipUnless(
    os.environ.get("ZENETISM_RUN_LIVE_TESTS") == "1",
    "set ZENETISM_RUN_LIVE_TESTS=1 to query public GitHub and Zenodo interfaces",
)
class LiveReferenceTests(unittest.TestCase):
    def test_completed_plain_language_v2_cycle(self) -> None:
        manifest = build_manifest(
            retrieve_observation(
                repository="KannonZenetism/zenetism-field-physics",
                branch="main",
                directory="the-zenetist-canon/introductory-orientation",
                canonical_filename="zenetism-in-plain-language.md",
                zenodo_identifier="10.5281/zenodo.21830364",
            )
        )
        self.assertEqual(manifest["zenodo"]["exact_version_doi"], "10.5281/zenodo.21830364")
        self.assertEqual(manifest["zenodo"]["concept_doi"], "10.5281/zenodo.21174438")
        self.assertEqual(manifest["zenodo"]["target_version"], "v2")
        self.assertEqual(manifest["zenodo"]["record_revision"], 3)
        self.assertEqual(manifest["zenodo"]["archival_filename"], "zenetism-in-plain-language_v2.md")
        self.assertEqual(manifest["zenodo"]["publication_date"], "2026-07-03")
        self.assertEqual(manifest["github"]["byte_size"], 13414)
        self.assertEqual(manifest["github"]["sha256"], "174a984a83ff342af0cb14e64fb61215e05ec31e865ae7592142eb87fd48c1f8")
        self.assertEqual(manifest["github"]["md5"], "ea3b7e4230d7c43940657c6a1116075c")
        self.assertEqual(manifest["comparison"]["payload_status"], "matching")
        family = manifest["zenodo"]["version_family"]
        self.assertEqual([item["version_label"] for item in family], ["v1", "v2"])
        self.assertEqual([item["record_revision"] for item in family], [3, 3])


if __name__ == "__main__":
    unittest.main()
