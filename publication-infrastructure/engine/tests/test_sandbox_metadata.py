from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from zenetism_engine.archival import prepare_archival_copy
from zenetism_engine.errors import ManifestApprovalError
from zenetism_engine.sandbox_metadata import serialize_sandbox_draft

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "publication-infrastructure/manifests/zenetism-in-plain-language-v2.json"


class SandboxMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.archival = prepare_archival_copy(cls.manifest, repository_root=ROOT)
        cls.package = serialize_sandbox_draft(cls.manifest, cls.archival)

    def test_archival_copy_changes_only_the_filename(self) -> None:
        source = (ROOT / self.manifest["github"]["path"]).read_bytes()
        self.assertEqual(self.archival.payload, source)
        self.assertEqual(self.archival.archival_filename, "zenetism-in-plain-language_v2.md")
        self.assertEqual(self.archival.checksums.byte_size, len(source))
        self.assertEqual(self.archival.checksums.sha256, self.manifest["github"]["sha256"])
        self.assertEqual(self.archival.checksums.md5, self.manifest["github"]["md5"])

    def test_metadata_preserves_exact_approved_values(self) -> None:
        metadata = self.package.saved_payload["metadata"]
        self.assertNotIn("pids", self.package.create_payload)
        self.assertFalse(self.package.audit_summary()["existing_doi_supplied"])
        self.assertEqual(metadata["publication_date"], "2026-07-03")
        self.assertEqual(metadata["version"], "v2")
        self.assertEqual(metadata["copyright"], "2026 Aelion Kannon")
        self.assertEqual(
            self.package.saved_payload["custom_fields"]["code:codeRepository"],
            self.manifest["repository_url"],
        )
        self.assertEqual(
            [item["subject"] for item in metadata["subjects"]], self.manifest["keywords"]
        )
        self.assertEqual(metadata["description"], self.manifest["description"]["rendered_html"])
        self.assertEqual(
            metadata["related_identifiers"][0],
            {
                "identifier": self.manifest["site_relation"]["identifier"],
                "scheme": "url",
                "relation_type": {"id": "isdocumentedby"},
                "resource_type": {"id": "other"},
            },
        )
        self.assertEqual(
            self.package.saved_payload["files"]["default_preview"],
            self.archival.archival_filename,
        )

    def test_creator_and_contributor_conventions_are_exact(self) -> None:
        metadata = self.package.saved_payload["metadata"]
        creator = metadata["creators"][0]["person_or_org"]
        self.assertEqual(
            creator,
            {"type": "personal", "family_name": "Aelion Kannon", "given_name": ""},
        )
        self.assertEqual(
            [item["role"]["id"] for item in metadata["contributors"]],
            ["researcher", "researcher"],
        )

    def test_short_standard_and_series_descriptions_are_not_rewritten(self) -> None:
        for form in ("Short", "Standard", "Series"):
            manifest = copy.deepcopy(self.manifest)
            exact_html = f"<p>{form} description with <code>exact content</code>.</p>"
            manifest["description"] = {"form": form, "rendered_html": exact_html}
            package = serialize_sandbox_draft(manifest, self.archival)
            with self.subTest(form=form):
                self.assertEqual(package.description_form, form)
                self.assertEqual(package.saved_payload["metadata"]["description"], exact_html)

    def test_document_version_cannot_fall_back_to_record_revision(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["zenodo"]["target_version"] = manifest["zenodo"]["record_revision"]
        with self.assertRaises(ManifestApprovalError):
            serialize_sandbox_draft(manifest, self.archival)

    def test_missing_or_mismatched_manifest_values_fail_closed(self) -> None:
        missing = copy.deepcopy(self.manifest)
        del missing["zenodo"]["publication_date"]
        with self.assertRaises(ManifestApprovalError):
            prepare_archival_copy(missing, repository_root=ROOT)

        mismatched = copy.deepcopy(self.manifest)
        mismatched["github"]["sha256"] = "0" * 64
        with self.assertRaises(ManifestApprovalError):
            prepare_archival_copy(mismatched, repository_root=ROOT)

        wrong_repository_url = copy.deepcopy(self.manifest)
        wrong_repository_url["repository_url"] = "https://github.com/example/repository"
        with self.assertRaises(ManifestApprovalError):
            serialize_sandbox_draft(wrong_repository_url, self.archival)


if __name__ == "__main__":
    unittest.main()
