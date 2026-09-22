import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cognitive_architecture.engine import Engine, Limits, validate_task, verify
from cognitive_architecture.providers import ProviderResult
from cognitive_architecture.storage import Store


def task(**kwargs):
    return {"objective": "Return a verified answer", "context": "original evidence",
            "checks": [{"kind": "contains", "value": "correct"}], **kwargs}


class FakeProvider:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def run(self, instruction, context, model):
        self.calls.append((instruction, context, model))
        value = next(self.results)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, ProviderResult) else ProviderResult(value, 2, 3, 0, model)


class FakeRouter:
    def __init__(self, action="single", tokens=2, error=None):
        self.action, self.tokens, self.error = action, tokens, error
        self.calls = []

    def decide(self, state):
        self.calls.append(state)
        if self.error:
            raise self.error
        return {"action": self.action, "usage": {"input_tokens": self.tokens, "output_tokens": 0}}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)

    def engine(self, provider=None, **kwargs):
        return Engine(self.store, provider, models=["small", "large"], **kwargs)

    def test_deterministic_cache_and_changes_invalidate(self):
        spec = task(operation="text_stats", input="café", checks=[{"kind": "json_equals", "path": ["characters"], "value": 4}])
        provider = FakeProvider([])
        engine = self.engine(provider)
        first, second = engine.run(spec), engine.run(spec)
        self.assertEqual(first["status"], "accepted")
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["calls"], 0)
        changed = engine.run({**spec, "input": "hola"})
        self.assertFalse(changed["cache_hit"])
        changed_checks = engine.run({**spec, "checks": [{"kind": "nonempty"}]})
        self.assertFalse(changed_checks["cache_hit"])
        self.assertEqual(provider.calls, [])

    def test_corrupt_cache_recomputed(self):
        spec = task(operation="text_stats", input="hi", checks=[{"kind": "nonempty"}])
        engine = self.engine()
        expected = engine.run(spec)["output"]
        cache = next((Path(self.directory.name) / "cache").glob("*.json"))
        cache.write_text("broken", encoding="utf-8")
        result = engine.run(spec)
        self.assertEqual(result["output"], expected)
        self.assertFalse(result["cache_hit"])

    def test_failed_deterministic_gate_never_cached(self):
        result = self.engine().run(task(operation="text_stats", input="hi"))
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse((Path(self.directory.name) / "cache").exists())

    def test_model_results_never_cache_even_when_accepted(self):
        provider = FakeProvider(["correct", "correct"])
        engine = self.engine(provider)
        self.assertEqual(engine.run(task())["status"], "accepted")
        self.assertFalse(engine.run(task())["cache_hit"])
        self.assertEqual(len(provider.calls), 2)
        self.assertFalse((Path(self.directory.name) / "cache").exists())

    def test_panel_gates_exact_synthesis_and_peer_is_independent(self):
        provider = FakeProvider(["wrong-private-view-A", "different-view-B", "correct final"])
        result = self.engine(provider).run(task(collaboration="thinktank"))
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["output"], "correct final")
        self.assertEqual(provider.calls[1][1], "original evidence")
        self.assertNotIn("wrong-private-view-A", provider.calls[1][0] + provider.calls[1][1])
        self.assertIn("wrong-private-view-A", provider.calls[2][1])
        self.assertIn("different-view-B", provider.calls[2][1])

    def test_good_views_cannot_approve_bad_synthesis(self):
        provider = FakeProvider(["correct A", "correct B", "bad synthesis"])
        result = Engine(self.store, provider, models=["one"]).run(task(collaboration="second_opinion"))
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["output"], "bad synthesis")
        self.assertFalse(result["checks"][0]["passed"])

    def test_router_and_every_worker_share_call_limit(self):
        router = FakeRouter()
        provider = FakeProvider(["wrong"])
        result = self.engine(provider, router=router, limits=Limits(max_calls=2)).run(task())
        self.assertEqual(result["calls"], 2)
        self.assertEqual(len(provider.calls), 1)
        self.assertNotEqual(result["status"], "accepted")
        self.assertEqual(router.calls[0]["remaining_calls"], 1)

    def test_panel_preflight_does_not_start_partial_panel(self):
        provider = FakeProvider([])
        result = self.engine(provider, router=FakeRouter("thinktank"), limits=Limits(max_calls=3)).run(task())
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["calls"], 1)
        self.assertEqual(provider.calls, [])

    def test_router_token_limit_blocks_worker(self):
        provider = FakeProvider([])
        result = self.engine(provider, router=FakeRouter(tokens=10), limits=Limits(max_observed_tokens=10)).run(task())
        self.assertNotEqual(result["status"], "accepted")
        self.assertEqual(provider.calls, [])
        self.assertEqual(result["observed_tokens"], 10)

    def test_worker_token_overrun_reported_and_no_escalation(self):
        provider = FakeProvider([ProviderResult("wrong", 20, 10)])
        result = self.engine(provider, limits=Limits(max_observed_tokens=10)).run(task(collaboration="single"))
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(len(provider.calls), 1)

    def test_unknown_usage_not_claimed_complete(self):
        result = self.engine(FakeProvider([ProviderResult("correct")])).run(task())
        self.assertFalse(result["usage_complete"])
        self.assertEqual(result["unknown_usage_calls"], 1)

    def test_failed_provider_and_router_unknown_usage_no_secret_persistence(self):
        for router_failure in (False, True):
            secret = "SECRET-provider-request-header"
            provider = FakeProvider([RuntimeError(secret)])
            router = FakeRouter(error=RuntimeError(secret)) if router_failure else None
            result = self.engine(provider, router=router).run(task())
            self.assertFalse(result["usage_complete"])
            self.assertEqual(result["unknown_usage_calls"], 1)
            self.assertNotIn(secret, json.dumps(result))
            for checkpoint in (Path(self.directory.name) / "runs").glob("*.json"):
                self.assertNotIn(secret, checkpoint.read_text())

    def test_model_context_bounded_and_expensive_tier_only_after_failed_gate(self):
        provider = FakeProvider(["wrong", "correct"])
        result = self.engine(provider, limits=Limits(max_context_chars=80)).run(task(context="E" * 500))
        self.assertEqual(result["status"], "accepted")
        self.assertEqual([c[2] for c in provider.calls], ["small", "large"])
        self.assertTrue(all(len(c[1]) <= 80 for c in provider.calls))

    def test_elapsed_budget_prevents_another_call(self):
        provider = FakeProvider(["wrong"])
        with patch("cognitive_architecture.engine.time.monotonic", side_effect=[0, 0, 100, 100, 100]):
            result = self.engine(provider, limits=Limits(max_seconds=10)).run(task())
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["status"], "budget_exhausted")

    def test_invalid_tasks_fail_before_storage(self):
        examples = [None, {}, task(objective=""), task(operation="delete"), task(context=[]),
                    task(checks=[]), task(checks=[{"kind": "contains", "value": ""}]),
                    task(checks=[{"kind": "json_equals", "path": [True], "value": 1}]),
                    task(collaboration="infinite"), task(extra=float("nan"))]
        for example in examples:
            with self.subTest(example=example), self.assertRaises((ValueError, TypeError)):
                self.engine().run(example)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_limits_reject_invalid_values(self):
        for kwargs in ({"max_calls": 0}, {"max_calls": True}, {"max_context_chars": 1.5},
                       {"max_seconds": float("inf")}, {"cache_ttl_seconds": -1},
                       {"max_observed_tokens": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Limits(**kwargs)

    def test_json_gate_requires_equal_json_types_and_safe_path(self):
        self.assertFalse(verify('{"a":true}', [{"kind": "json_equals", "path": ["a"], "value": 1}])[0]["passed"])
        self.assertFalse(verify('[]', [{"kind": "json_equals", "path": [2], "value": None}])[0]["passed"])


if __name__ == "__main__":
    unittest.main()
