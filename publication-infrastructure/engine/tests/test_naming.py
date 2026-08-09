from __future__ import annotations

import unittest

from zenetism_engine.errors import FilenameError
from zenetism_engine.naming import (
    archival_filename,
    require_document_version,
    validate_archival_filename,
)


class NamingTests(unittest.TestCase):
    def test_archival_conversion(self) -> None:
        self.assertEqual(archival_filename("filename.md", "v12"), "filename_v12.md")

    def test_metadata_revision_cannot_substitute_for_document_version(self) -> None:
        for revision in (2, 3, "2", "revision-2"):
            with self.subTest(revision=revision), self.assertRaises(FilenameError):
                require_document_version(revision)

    def test_upload_copy_suffixes_are_rejected(self) -> None:
        for suffix in (1, 5, 9):
            observed = f"filename_v2 ({suffix}).md"
            with self.subTest(filename=observed), self.assertRaises(FilenameError):
                validate_archival_filename("filename.md", "v2", observed)
            canonical = f"filename ({suffix}).md"
            with self.subTest(filename=canonical), self.assertRaises(FilenameError):
                archival_filename(canonical, "v2")

    def test_exact_archival_name_is_required(self) -> None:
        with self.assertRaises(FilenameError):
            validate_archival_filename("filename.md", "v2", "filename.md")


if __name__ == "__main__":
    unittest.main()
