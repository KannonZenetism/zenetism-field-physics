from __future__ import annotations

import unittest
from types import SimpleNamespace

from zenetism_engine.comparison import compare_payloads
from zenetism_engine.hashing import calculate_checksums


class ComparisonTests(unittest.TestCase):
    def _surface(self, payload: bytes):
        return SimpleNamespace(payload=payload, checksums=calculate_checksums(payload))

    def test_byte_identical_payloads_match(self) -> None:
        result = compare_payloads(self._surface(b"same"), self._surface(b"same"))
        self.assertTrue(result.matches)
        self.assertEqual(result.sha256_status, "matching")
        self.assertEqual(result.md5_status, "matching")

    def test_different_payloads_are_not_rewritten_or_normalized(self) -> None:
        github = self._surface(b"line\n")
        zenodo = self._surface(b"line\r\n")
        result = compare_payloads(github, zenodo)
        self.assertFalse(result.matches)
        self.assertEqual(result.payload_status, "differing")
        self.assertEqual(github.payload, b"line\n")
        self.assertEqual(zenodo.payload, b"line\r\n")


if __name__ == "__main__":
    unittest.main()
