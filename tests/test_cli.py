"""Offline subprocess checks for the installed/module command-line contract."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cognitive_architecture


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="cognition-cli-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = self.root / "state"
        self.env = os.environ.copy()
        # Resolve the same package under test, including when run from sources.
        self.env["PYTHONPATH"] = str(Path(cognitive_architecture.__file__).resolve().parent.parent)
        # Output JSON must remain usable on legacy Windows console encodings.
        self.env["PYTHONIOENCODING"] = "ascii"

    def write_json(self, name, value, encoding="utf-8"):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding=encoding)
        return str(path)

    def invoke(self, *args):
        process = subprocess.run(
            [sys.executable, "-m", "cognitive_architecture", *map(str, args)],
            cwd=self.root, env=self.env, capture_output=True, timeout=20,
        )
        self.assertEqual(process.stderr, b"", process.stderr.decode("utf-8", errors="replace"))
        return process.returncode, json.loads(process.stdout.decode("utf-8"))

    def task(self, **changes):
        value = {"objective": "Measure a supplied text", "operation": "text_stats",
                 "input": "hello world", "checks": [{"kind": "nonempty"}]}
        value.update(changes)
        return self.write_json("task.json", value)

    def test_offline_task_cache_and_status_checkpoint(self):
        path = self.task()
        code, first = self.invoke("run", path, "--store", self.store)
        self.assertEqual(code, 0)
        self.assertEqual(first["status"], "accepted")
        self.assertEqual(first["calls"], 0)
        self.assertFalse(first["cache_hit"])
        code, second = self.invoke("run", path, "--store", self.store)
        self.assertEqual(code, 0)
        self.assertTrue(second["cache_hit"])
        code, state = self.invoke("status", first["run_id"], "--store", self.store)
        self.assertEqual(code, 0)
        self.assertEqual(state["run_id"], first["run_id"])
        self.assertEqual(state["status"], "accepted")
        self.assertNotIn("output", state)
        self.assertNotIn("objective", state)

    def test_failed_acceptance_is_nonzero_and_checkpointed(self):
        path = self.task(checks=[{"kind": "json_equals", "path": ["words"], "value": 99}])
        code, result = self.invoke("run", path, "--store", self.store)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["checks"][0]["passed"])
        self.assertFalse((self.store / "cache").exists())
        code, state = self.invoke("status", result["run_id"], "--store", self.store)
        self.assertEqual(code, 2)
        self.assertEqual(state["status"], "needs_review")

    def test_unconfigured_model_is_blocked_without_calls(self):
        path = self.task(operation="model")
        code, result = self.invoke("run", path, "--store", self.store)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["calls"], 0)

    def test_utf8_bom_input_and_ascii_stdout_preserve_unicode(self):
        text = "cáscara, núcleo, 日本語 🥚"
        path = self.write_json("entrada.json", {
            "objective": "Verificar UTF-8", "operation": "sha256", "input": text,
            "checks": [{"kind": "json_equals", "path": ["sha256"],
                        "value": hashlib.sha256(text.encode("utf-8")).hexdigest()}],
        }, encoding="utf-8-sig")
        code, result = self.invoke("run", path, "--store", self.store)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "accepted")

    def test_graph_is_unicode_safe_bounded_and_validated(self):
        path = self.write_json("graph.json", {"entry": "a", "nodes": {
            "a": {"content": "núcleo 🥚", "edges": ["b"]},
            "b": {"content": "cáscara", "edges": ["a"]},
        }})
        code, result = self.invoke("graph", path, "--max-nodes", "1", "--max-chars", "12")
        self.assertEqual(code, 0)
        self.assertEqual(result["visited"], ["a"])
        self.assertLessEqual(len(result["text"]), 12)
        self.assertTrue(result["truncated"])
        code, result = self.invoke("graph", path, "--max-nodes", "10")
        self.assertEqual(code, 0)
        self.assertIn("núcleo 🥚", result["text"])
        self.assertFalse(result["truncated"])
        bad = self.write_json("badgraph.json", {"nodes": {"a": {"edges": ["missing"]}}})
        code, result = self.invoke("graph", bad)
        self.assertEqual((code, result["status"]), (2, "error"))

    def test_graph_can_be_attached_to_an_offline_task(self):
        graph = self.write_json("graph.json", {"nodes": {"a1": {"content": "Evidence"}}})
        code, result = self.invoke("run", self.task(), "--graph", graph, "--store", self.store)
        self.assertEqual(code, 0)
        self.assertEqual(result["calls"], 0)

    def test_invalid_and_missing_run_ids_are_safe_errors(self):
        for run_id in ("../task", "a" * 31, "G" * 32, "a" * 32):
            with self.subTest(run_id=run_id):
                code, result = self.invoke("status", run_id, "--store", self.store)
                self.assertEqual((code, result["status"]), (2, "error"))

    def test_malformed_task_json_schema_and_missing_files(self):
        malformed = self.root / "malformed.json"
        malformed.write_text('{"secret": "DO_NOT_ECHO",', encoding="utf-8")
        for path in (malformed, self.write_json("list.json", []),
                     self.write_json("invalid.json", {"objective": "Incomplete"}),
                     self.root / "missing.json"):
            with self.subTest(path=path):
                code, result = self.invoke("run", path, "--store", self.store)
                self.assertEqual((code, result["status"]), (2, "error"))
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result))
        self.assertFalse(self.store.exists())

    def test_malformed_configuration_is_rejected_without_echo(self):
        task = self.task()
        configs = [[], {"secret": "DO_NOT_ECHO"}, {"limits": {"max_calls": -1}},
                   {"codex": {"unknown": "DO_NOT_ECHO"}}, {"jev": {}},
                   {"models": "cheap"}, {"jev": {"connector": "python"}}]
        for index, config in enumerate(configs):
            with self.subTest(config=config):
                path = self.write_json(f"config-{index}.json", config)
                code, result = self.invoke("run", task, "--config", path, "--store", self.store)
                self.assertEqual((code, result["status"]), (2, "error"))
                self.assertNotIn("DO_NOT_ECHO", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
