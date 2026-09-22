"""Content-addressed, integrity checked local result storage."""
from __future__ import annotations
import hashlib
import json
import math
import re
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical(value)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @staticmethod
    def _identifier(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Unsafe storage identifier")
        return value

    def get(self, key: str, ttl: float) -> str | None:
        self._identifier(key)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("Invalid cache TTL")
        try:
            record = json.loads((self.root / "cache" / (key + ".json")).read_text(encoding="utf-8"))
            created = record["created"]
            if isinstance(created, bool) or not isinstance(created, (int, float)) or not math.isfinite(created):
                return None
            age = time.time() - created
            if age < 0 or age > ttl or record["key"] != key:
                return None
            text = record["text"]
            if not isinstance(text, str) or fingerprint(text) != record["digest"]:
                return None
            return text
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, key: str, text: str) -> None:
        self._identifier(key)
        atomic_json(self.root / "cache" / (key + ".json"),
                    {"key": key, "text": text, "digest": fingerprint(text), "created": time.time()})

    def checkpoint(self, run_id: str, state: dict) -> None:
        self._identifier(run_id)
        # Only caller-constructed metadata is stored here; no model transcript.
        atomic_json(self.root / "runs" / (run_id + ".json"), state)
