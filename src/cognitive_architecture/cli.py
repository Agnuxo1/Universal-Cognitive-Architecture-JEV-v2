"""Portable JSON command line. Network access requires an explicit config."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .engine import Engine, Limits
from .graph import Graph
from .providers import CodexProvider, JEVRouter
from .storage import Store


def read_object(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def make_engine(config, store):
    allowed = {"models", "limits", "codex", "jev"}
    if set(config) - allowed:
        raise ValueError("Unknown configuration keys")
    provider = router = None
    if "codex" in config:
        provider = CodexProvider(**config["codex"])
    if "jev" in config:
        router = JEVRouter(**config["jev"])
    return Engine(Store(store), provider, router, config.get("models"), Limits(**config.get("limits", {})))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cognitive Architecture v2: verified external workflows")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a task; offline unless a provider is configured")
    run.add_argument("task")
    run.add_argument("--config")
    run.add_argument("--store", default=".cognition")
    run.add_argument("--graph", help="Optional inert knowledge graph JSON")
    graph = commands.add_parser("graph", help="Validate and retrieve bounded graph context")
    graph.add_argument("file")
    graph.add_argument("--max-nodes", type=int, default=4)
    graph.add_argument("--max-chars", type=int, default=4000)
    status = commands.add_parser("status", help="Read a local factual checkpoint by run ID")
    status.add_argument("run_id")
    status.add_argument("--store", default=".cognition")
    args = parser.parse_args(argv)
    try:
        if args.command == "graph":
            result = Graph.from_dict(read_object(args.file)).context(max_nodes=args.max_nodes, max_chars=args.max_chars)
        elif args.command == "status":
            if len(args.run_id) != 32 or any(c not in "0123456789abcdef" for c in args.run_id):
                raise ValueError("Invalid run ID")
            result = read_object(Path(args.store) / "runs" / (args.run_id + ".json"))
        else:
            config = read_object(args.config) if args.config else {}
            task = read_object(args.task)
            if args.graph:
                retrieved = Graph.from_dict(read_object(args.graph)).context()
                task["context"] = str(task.get("context", "")) + "\nGRAPH DATA:\n" + retrieved["text"]
                task["graph_nodes"] = retrieved["visited"]
            result = make_engine(config, args.store).run(task)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result.get("status", "accepted") == "accepted" else 2
    except (ValueError, OSError, TypeError):
        # Invalid configuration may contain credentials: never echo its contents.
        print(json.dumps({"status": "error", "error": "Invalid input, configuration, or inaccessible file"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
