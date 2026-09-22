import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cognitive_architecture.providers import CodexProvider, JEVRouter, ProviderError


def completed(events=None, *, code=0, raw=None):
    data = raw if raw is not None else "\n".join(json.dumps(event, ensure_ascii=False) for event in events or [])
    return subprocess.CompletedProcess([], code, data.encode("utf-8"), b"private-secret-stderr")


GOOD = [{"type": "item.completed", "item": {"type": "agent_message", "text": "Solución útil"}},
        {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 5, "cached_input_tokens": 3}}]


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.provider = CodexProvider("codex.exe")

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_utf8_structured_success_and_safe_arguments(self, run):
        run.return_value = completed(GOOD)
        result = self.provider.run("Comprueba café $(echo secret)", "datos", "user-model")
        self.assertEqual(result.text, "Solución útil")
        self.assertEqual((result.input_tokens, result.output_tokens, result.cached_tokens), (20, 5, 3))
        args = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertIn("read-only", args)
        self.assertIn("--ephemeral", args)
        self.assertEqual(args[-1], "-")
        self.assertNotIn("Comprueba", " ".join(args))
        self.assertIn("café", kwargs["input"].decode("utf-8"))
        self.assertFalse(kwargs["shell"])
        self.assertFalse(kwargs["text"])
        self.assertFalse(Path(kwargs["cwd"]).exists())

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_missing_final_or_completion_is_not_success(self, run):
        for events in ([GOOD[0]], [GOOD[1]], [], [{"type": "thread.started"}]):
            run.return_value = completed(events)
            with self.subTest(events=events), self.assertRaises(ProviderError):
                self.provider.run("task", "", "model")

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_failure_after_message_never_leaks(self, run):
        run.return_value = completed(GOOD + [{"type": "turn.failed", "error": {"message": "secret-api-key"}}])
        with self.assertRaises(ProviderError) as caught:
            self.provider.run("task", "", "model")
        self.assertNotIn("secret", str(caught.exception))

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_timeout_is_safe(self, run):
        run.side_effect = subprocess.TimeoutExpired(["secret-argument"], 120, stderr=b"secret")
        with self.assertRaises(ProviderError) as caught:
            self.provider.run("task", "", "model")
        self.assertEqual(str(caught.exception), "Provider timed out.")
        self.assertTrue(caught.exception.__suppress_context__)

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_nonzero_and_raw_output_rejected(self, run):
        for response in (completed(GOOD, code=1), completed(raw="private-secret-output"),
                         completed(raw="[]"), completed(raw="null")):
            run.return_value = response
            with self.subTest(response=response), self.assertRaises(ProviderError) as caught:
                self.provider.run("task", "", "model")
            self.assertNotIn("private-secret", str(caught.exception))

    @patch("cognitive_architecture.providers.shutil.which", return_value=None)
    def test_missing_executable(self, which):
        with self.assertRaises(ProviderError):
            CodexProvider().run("task", "", "model")

    def test_windows_wrapper_resolves_node_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / "node_modules/@openai/codex/bin/codex.js"
            entry.parent.mkdir(parents=True)
            entry.write_text("// fixture", encoding="utf-8")
            with patch("cognitive_architecture.providers.shutil.which", return_value="node.exe"):
                self.assertEqual(CodexProvider(str(Path(directory) / "codex.cmd"))._command(),
                                 ["node.exe", str(entry)])


class JEVTests(unittest.TestCase):
    def setUp(self):
        self.router = JEVRouter(["python", "-m", "jev_orchestrator.connection"])

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_normalizes_real_connector_shape_and_cleans_temp(self, run):
        captured = {}
        def fake(args, **kwargs):
            state = Path(args[args.index("--state-file") + 1])
            questions = Path(args[args.index("--questions-file") + 1])
            captured["state"] = state
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {"objective": "español"})
            self.assertEqual(json.loads(questions.read_text())["action"]["type"], "choice")
            self.assertFalse(kwargs["shell"])
            return completed(raw=json.dumps({"status": "connected", "model": "jev-test",
                "account": "private", "answers": {"action": {"value": "second_opinion", "confidence": .8}},
                "usage": {"input_tokens": 8, "output_tokens": 1}}))
        run.side_effect = fake
        result = self.router.decide({"objective": "español"})
        self.assertEqual(result["action"], "second_opinion")
        self.assertEqual(result["provider_model"], "jev-test")
        self.assertEqual(result["usage"]["input_tokens"], 8)
        self.assertNotIn("account", result)
        self.assertFalse(captured["state"].exists())

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_invalid_decisions_fail_closed(self, run):
        for payload in ({"status": "blocked", "error": "secret"}, [],
                        {"status": "connected", "answers": {"action": {"value": "execute"}}},
                        {"status": "connected", "answers": {"action": {"value": "single", "confidence": float("nan")}}}):
            run.return_value = completed(raw=json.dumps(payload))
            with self.subTest(payload=payload), self.assertRaises(ProviderError) as caught:
                self.router.decide({})
            self.assertNotIn("secret", str(caught.exception))

    @patch("cognitive_architecture.providers.subprocess.run")
    def test_timeout_safe_and_explicit_cwd(self, run):
        run.side_effect = subprocess.TimeoutExpired(["private"], 45)
        with tempfile.TemporaryDirectory() as directory:
            router = JEVRouter(["python", "-m", "jev_orchestrator.connection"], cwd=directory)
            with self.assertRaises(ProviderError):
                router.decide({})
            self.assertEqual(run.call_args.kwargs["cwd"], str(Path(directory).resolve()))

    def test_reject_shell_wrappers(self):
        with self.assertRaises(ValueError):
            JEVRouter(["connect_jev.bat"])


if __name__ == "__main__":
    unittest.main()
