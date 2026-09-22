import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cognitive_architecture.storage import Store, atomic_json, canonical, fingerprint


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.key = fingerprint({"task": "one"})
        self.path = Path(self.directory.name) / "cache" / (self.key + ".json")

    def test_fingerprint_stable_unicode_and_nan_rejected(self):
        self.assertEqual(fingerprint({"a": "é", "b": 1}), fingerprint({"b": 1, "a": "é"}))
        with self.assertRaises(ValueError):
            canonical(float("nan"))

    def test_integrity_key_and_ttl_verified(self):
        with patch("cognitive_architecture.storage.time.time", return_value=100):
            self.store.put(self.key, "café")
        with patch("cognitive_architecture.storage.time.time", return_value=110):
            self.assertEqual(self.store.get(self.key, 20), "café")
            self.assertIsNone(self.store.get(self.key, 5))
        with patch("cognitive_architecture.storage.time.time", return_value=99):
            self.assertIsNone(self.store.get(self.key, 20))
        original = json.loads(self.path.read_text(encoding="utf-8"))
        for field, value in (("text", "tampered"), ("key", "wrong"), ("digest", "wrong")):
            self.path.write_text(json.dumps({**original, field: value}), encoding="utf-8")
            with patch("cognitive_architecture.storage.time.time", return_value=110):
                self.assertIsNone(self.store.get(self.key, 20))

    def test_corruption_returns_miss(self):
        self.path.parent.mkdir(parents=True)
        for text in ("not json", "null", "[]", "{}", '{"created":"bad"}'):
            self.path.write_text(text)
            with self.subTest(text=text):
                self.assertIsNone(self.store.get(self.key, 100))

    def test_nan_timestamp_rejected(self):
        self.store.put(self.key, "data")
        record = json.loads(self.path.read_text())
        record["created"] = float("nan")
        self.path.write_text(json.dumps(record))
        self.assertIsNone(self.store.get(self.key, 100))

    def test_atomic_failure_preserves_previous_file_and_cleans_temp(self):
        target = Path(self.directory.name) / "state.json"
        atomic_json(target, {"old": True})
        with patch("cognitive_architecture.storage.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                atomic_json(target, {"new": True})
        self.assertEqual(json.loads(target.read_text()), {"old": True})
        self.assertEqual(list(Path(self.directory.name).glob(".write-*.tmp")), [])

    def test_path_traversal_identifiers_rejected(self):
        # Targets remain inside our temporary test directory even for broken code.
        with self.assertRaises(ValueError):
            self.store.put("../outside", "data")
        with self.assertRaises(ValueError):
            self.store.checkpoint("../outside", {"state": "data"})


if __name__ == "__main__":
    unittest.main()
