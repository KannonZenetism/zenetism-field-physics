from __future__ import annotations

import copy
import unittest

from zenetism_engine.hashing import calculate_checksums
from zenetism_engine.http import HttpResponse
from zenetism_engine.zenodo import ZenodoClient, record_id_from_identifier


class FakeHttp:
    def __init__(self, record: dict, family: dict, payload: bytes) -> None:
        self.record = record
        self.family = family
        self.payload = payload

    def get_json(self, url: str, *, headers=None):
        value = self.family if url.endswith("/versions") else self.record
        return copy.deepcopy(value), HttpResponse(b"{}", url, {})

    def get(self, url: str, *, headers=None):
        return HttpResponse(self.payload, url, {})


def record_without_version(*, revision: int = 2) -> tuple[dict, dict, bytes]:
    payload = b"abc"
    md5 = calculate_checksums(payload).md5
    record = {
        "id": "22",
        "is_published": True,
        "status": "published",
        "revision_id": revision,
        "links": {"versions": "https://zenodo.test/api/records/22/versions"},
        "pids": {"doi": {"identifier": "10.5281/zenodo.22"}},
        "parent": {"id": "11", "pids": {"doi": {"identifier": "10.5281/zenodo.11"}}},
        "versions": {"index": 2, "is_latest": True},
        "files": {
            "default_preview": "paper.md",
            "entries": {
                "paper.md": {
                    "key": "paper.md",
                    "size": len(payload),
                    "checksum": f"md5:{md5}",
                    "links": {"content": "https://zenodo.test/paper.md"},
                }
            },
        },
        "metadata": {
            "title": "Paper",
            "publication_date": "2026-01-01",
            "description": "<p>Text.</p>",
            "creators": [],
            "contributors": [],
            "subjects": [],
            "related_identifiers": [],
            "rights": [],
            "languages": [],
            "resource_type": {},
        },
        "custom_fields": {},
        "ui": {"access_status": {"id": "open"}},
    }
    member = {
        "id": "22",
        "revision_id": revision,
        "pids": {"doi": {"identifier": "10.5281/zenodo.22"}},
        "metadata": {},
        "versions": {"index": 2, "is_latest": True},
    }
    return record, {"hits": {"hits": [member]}}, payload


class ZenodoTests(unittest.TestCase):
    def test_record_revision_never_becomes_document_version(self) -> None:
        record, family, payload = record_without_version(revision=2)
        observed = ZenodoClient(FakeHttp(record, family, payload)).fetch_published_record("22")
        self.assertEqual(observed.record_revision, 2)
        self.assertIsNone(observed.version_label)
        self.assertIsNone(observed.version_family[0].version_label)

    def test_version_and_revision_remain_separate_when_both_exist(self) -> None:
        record, family, payload = record_without_version(revision=3)
        record["metadata"]["version"] = "v2"
        family["hits"]["hits"][0]["metadata"]["version"] = "v2"
        observed = ZenodoClient(FakeHttp(record, family, payload)).fetch_published_record("22")
        self.assertEqual(observed.version_label, "v2")
        self.assertEqual(observed.record_revision, 3)

    def test_doi_and_url_identifier_parsing(self) -> None:
        self.assertEqual(record_id_from_identifier("10.5281/zenodo.21830364"), "21830364")
        self.assertEqual(record_id_from_identifier("https://zenodo.org/records/21830364"), "21830364")


if __name__ == "__main__":
    unittest.main()
