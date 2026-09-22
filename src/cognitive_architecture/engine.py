"""Bounded orchestration. Provider advice can never bypass a local gate."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import time
import uuid
from typing import Any
from . import __version__
from .storage import Store, canonical, fingerprint


@dataclass(frozen=True)
class Limits:
    max_calls: int = 4
    max_seconds: float = 180
    max_context_chars: int = 8000
    max_observed_tokens: int = 30000
    cache_ttl_seconds: float = 86400

    def __post_init__(self):
        for name in ("max_calls", "max_context_chars", "max_observed_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(name + " must be a positive integer")
        for name in ("max_seconds", "cache_ttl_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(name + " must be positive and finite")


def validate_task(task: dict) -> None:
    if not isinstance(task, dict) or not isinstance(task.get("objective"), str) or not task["objective"].strip():
        raise ValueError("Task needs a non-empty objective")
    if len(task["objective"]) > 16000:
        raise ValueError("Objective exceeds 16000 characters")
    operation = task.get("operation", "model")
    if operation not in {"model", "sha256", "text_stats", "json_summary"}:
        raise ValueError("Unsupported operation")
    if not isinstance(task.get("context", ""), str):
        raise ValueError("Context must be text")
    if operation in {"sha256", "text_stats"} and not isinstance(task.get("input"), str):
        raise ValueError("Operation requires a string input")
    checks = task.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Explicit acceptance checks are required")
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in {"nonempty", "contains", "excludes", "json_equals"}:
            raise ValueError("Unknown acceptance check")
        if check["kind"] in {"contains", "excludes"} and (not isinstance(check.get("value"), str) or not check["value"]):
            raise ValueError("Text checks require a non-empty value")
        if check["kind"] == "json_equals" and ("value" not in check or not isinstance(check.get("path", []), list) or not all(isinstance(x, (str,int)) and not isinstance(x,bool) for x in check.get("path", []))):
            raise ValueError("json_equals requires value and a path list")
    if task.get("collaboration", "auto") not in {"auto", "single", "second_opinion", "thinktank"}:
        raise ValueError("Unknown collaboration mode")
    canonical(task)  # Reject NaN and non-JSON values before side effects.


def verify(text: str, checks: list[dict]) -> list[dict]:
    results = []
    for index, check in enumerate(checks):
        kind = check["kind"]
        passed = False
        try:
            if kind == "nonempty":
                passed = bool(text.strip())
            elif kind == "contains":
                passed = check["value"] in text
            elif kind == "excludes":
                passed = check["value"] not in text
            elif kind == "json_equals":
                value = json.loads(text)
                for key in check.get("path", []):
                    value = value[key]
                passed = canonical(value) == canonical(check["value"])
        except (ValueError, TypeError, KeyError, IndexError):
            passed = False
        results.append({"index": index, "kind": kind, "passed": passed})
    return results


def deterministic(task: dict) -> str:
    operation, data = task["operation"], task.get("input")
    if operation == "sha256":
        return canonical({"sha256": hashlib.sha256(data.encode("utf-8")).hexdigest()})
    if operation == "text_stats":
        return canonical({"characters": len(data), "utf8_bytes": len(data.encode("utf-8")), "words": len(data.split()), "lines": len(data.splitlines())})
    if operation == "json_summary":
        return canonical({"type": type(data).__name__, "items": len(data) if isinstance(data, (dict,list,str)) else None, "sha256": fingerprint(data)})
    raise ValueError("No deterministic operation")


class Engine:
    def __init__(self, store: Store, provider=None, router=None, models: list[str] | None = None, limits: Limits | None = None):
        self.store, self.provider, self.router = store, provider, router
        if models is not None and not isinstance(models, list):
            raise ValueError("models must be a list")
        self.models = models or []
        if any(not isinstance(m, str) or not m.strip() for m in self.models):
            raise ValueError("Model IDs must be non-empty strings")
        self.limits = limits or Limits()

    def run(self, task: dict) -> dict:
        validate_task(task)
        start = time.monotonic()
        run_id = uuid.uuid4().hex
        events: list[dict] = []
        calls = 0
        observed = 0
        unknown_usage = 0
        key = fingerprint({"version": __version__, "task": task, "models": self.models, "limits": asdict(self.limits)})
        text = ""
        gate = []
        mode = task.get("collaboration", "auto")
        context = task.get("context", "")[:self.limits.max_context_chars]
        used_models: list[str] = []

        def elapsed():
            return time.monotonic() - start

        def checkpoint(status: str):
            self.store.checkpoint(run_id, {"schema": 1, "version": __version__, "run_id": run_id,
                "task_fingerprint": fingerprint(task), "cache_key": key, "status": status,
                "calls": calls, "observed_tokens": observed, "unknown_usage_calls": unknown_usage,
                "events": events, "output_digest": fingerprint(text) if text else None,
                "next_action": "inspect_result" if status == "accepted" else "inspect_failed_checks_or_retry"})

        def finish(status: str, cache_hit=False):
            checkpoint(status)
            return {"schema": 1, "version": __version__, "run_id": run_id, "status": status,
                "output": text, "checks": gate, "cache_hit": cache_hit, "calls": calls,
                "observed_tokens": observed, "usage_complete": unknown_usage == 0,
                "unknown_usage_calls": unknown_usage, "models": used_models,
                "elapsed_seconds": round(elapsed(), 6), "events": events}

        def reserve(kind: str) -> bool:
            nonlocal calls
            if calls >= self.limits.max_calls or elapsed() >= self.limits.max_seconds or observed >= self.limits.max_observed_tokens:
                events.append({"event": "budget_exhausted", "kind": kind})
                return False
            calls += 1
            events.append({"event": "call_reserved", "kind": kind, "call": calls})
            checkpoint("running")
            return True

        def usage(inp, out):
            nonlocal observed, unknown_usage
            if type(inp) is int and inp >= 0 and type(out) is int and out >= 0:
                observed += inp + out
            else:
                unknown_usage += 1

        def worker(model: str, instruction: str, compact_context: str) -> str | None:
            if not reserve("worker"):
                return None
            used_models.append(model)
            try:
                result = self.provider.run(instruction, compact_context[:self.limits.max_context_chars], model)
                usage(result.input_tokens, result.output_tokens)
                if not isinstance(result.text, str) or not result.text.strip():
                    events.append({"event": "provider_empty_result"})
                    return None
                return result.text
            except Exception:
                # Never persist provider exception text, request headers, or raw output.
                usage(None, None)
                events.append({"event": "provider_error"})
                return None

        events.append({"event": "task_validated"})
        # Model responses deliberately never use the deterministic result cache.
        if task.get("operation", "model") != "model":
            cached = self.store.get(key, self.limits.cache_ttl_seconds)
            if cached is not None:
                gate = verify(cached, task["checks"])
                if all(item["passed"] for item in gate):
                    text = cached
                    events.append({"event": "cache_revalidated"})
                    return finish("accepted", True)
            text = deterministic(task)
            gate = verify(text, task["checks"])
            if all(item["passed"] for item in gate):
                self.store.put(key, text)
                events.append({"event": "deterministic_verified"})
                return finish("accepted")
            return finish("needs_review")

        if self.provider is None or not self.models:
            events.append({"event": "model_backend_not_configured"})
            return finish("blocked")
        if mode == "auto":
            mode = "single"
            if self.router is not None:
                if not reserve("router"):
                    return finish("budget_exhausted")
                route_usage_recorded = False
                try:
                    decision = self.router.decide({"objective": task["objective"], "context": context,
                        "checks": task["checks"], "constraints": ["Bounded calls", "Evidence gate mandatory", "Model agreement is advisory"],
                        "remaining_calls": self.limits.max_calls - calls})
                    route_usage = decision.get("usage") or {}
                    usage(route_usage.get("input_tokens"), route_usage.get("output_tokens"))
                    route_usage_recorded = True
                    mode = decision.get("action")
                    if mode not in {"single", "second_opinion", "thinktank", "defer"}:
                        raise ValueError("Invalid route")
                    events.append({"event": "jev_route", "action": mode})
                    if mode == "defer":
                        return finish("needs_review")
                except Exception:
                    if not route_usage_recorded:
                        usage(None, None)
                    events.append({"event": "router_unavailable"})
                    return finish("blocked")
        required = {"single": 1, "second_opinion": 3, "thinktank": 3}[mode]
        if self.limits.max_calls - calls < required:
            events.append({"event": "insufficient_panel_budget", "required_calls": required})
            return finish("budget_exhausted")
        first = worker(self.models[0], task["objective"], context)
        if first is None:
            return finish("blocked" if calls < self.limits.max_calls else "budget_exhausted")
        text = first
        if mode in {"second_opinion", "thinktank"}:
            # Independent view sees original evidence, never the first answer.
            peer = worker(self.models[0], task["objective"] + "\nGive an independent assessment; identify uncertainties.", context)
            if peer is None:
                return finish("needs_review")
            quarter = max(1, self.limits.max_context_chars // 4)
            synthesis_context = ("EVIDENCE:\n" + context[:quarter] + "\nVIEW A:\n" + first[:quarter] + "\nVIEW B:\n" + peer[:quarter])
            synthesized = worker(self.models[0], task["objective"] + "\nCritique the two views against evidence and return one final answer. Agreement is not proof.", synthesis_context)
            if synthesized is None:
                return finish("needs_review")
            text = synthesized
            events.append({"event": "panel_synthesized", "mode": mode})
        gate = verify(text, task["checks"])
        for model in self.models[1:]:
            if all(item["passed"] for item in gate):
                break
            events.append({"event": "failed_gate_escalation", "failed_checks": [x["index"] for x in gate if not x["passed"]]})
            part = self.limits.max_context_chars // 3
            retry_context = "EVIDENCE:\n" + context[:part] + "\nPREVIOUS ANSWER:\n" + text[:part] + "\nFAILED CHECKS:\n" + canonical(gate)[:part]
            revised = worker(model, task["objective"] + "\nRevise the previous answer against the supplied evidence and acceptance criteria.\nCHECK SPECIFICATIONS:\n" + canonical(task["checks"]), retry_context)
            if revised is None:
                break
            text = revised
            gate = verify(text, task["checks"])
        if elapsed() > self.limits.max_seconds or observed > self.limits.max_observed_tokens:
            events.append({"event": "budget_overrun_observed"})
            return finish("budget_exhausted")
        return finish("accepted" if all(item["passed"] for item in gate) else "needs_review")
