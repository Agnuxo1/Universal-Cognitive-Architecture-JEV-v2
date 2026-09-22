"""Bounded retrieval from a directed graph of untrusted, inert text data.

No node is executed or treated as an instruction. A route trace records node
identifiers only: it is neither a reasoning transcript nor a coverage proof.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import re
from types import MappingProxyType
from typing import Any, Mapping


class GraphError(ValueError):
    """The graph, route, or retrieval request is invalid."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise GraphError("Node IDs must be 1–64 ASCII letters, digits, underscores or hyphens, starting with a letter or digit")
    return value


@dataclass(frozen=True)
class Node:
    label: str
    content: str
    edges: tuple[str, ...]
    # Store canonical JSON, avoiding mutable aliases to the supplied metadata.
    metadata_json: str = "{}"

    @property
    def metadata(self) -> dict[str, Any]:
        """Return a fresh copy of the optional inert metadata."""
        return json.loads(self.metadata_json)


class Graph:
    """A validated finite graph. Construct through :meth:`from_dict`."""

    def __init__(self, nodes: Mapping[str, Node], entry: str):
        self._nodes = MappingProxyType(dict(nodes))
        self._entry = entry

    @property
    def nodes(self) -> Mapping[str, Node]:
        return self._nodes

    @property
    def entry(self) -> str:
        return self._entry

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Graph:
        """Validate ``nodes`` and an optional ``entry`` without interpreting text.

        Every node has optional string label/content, a list of destination IDs,
        and optional JSON-object metadata. Unknown fields are rejected so that
        typos cannot silently discard content. Default entry is the smallest ID
        in lexical order. Edge list order defines deterministic BFS order.
        """
        if not isinstance(data, dict) or set(data) - {"nodes", "entry"}:
            raise GraphError("Graph must be an object containing nodes and optional entry")
        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            raise GraphError("nodes must be a nonempty object")
        nodes: dict[str, Node] = {}
        for node_id, raw in raw_nodes.items():
            _identifier(node_id)
            if not isinstance(raw, dict) or set(raw) - {"label", "content", "edges", "metadata"}:
                raise GraphError(f"Invalid node fields for {node_id}")
            label, content = raw.get("label", node_id), raw.get("content", "")
            if not isinstance(label, str) or not isinstance(content, str):
                raise GraphError(f"label and content must be strings for {node_id}")
            edges = raw.get("edges", [])
            if not isinstance(edges, list):
                raise GraphError(f"edges must be a list for {node_id}")
            for destination in edges:
                _identifier(destination)
            if len(edges) != len(set(edges)):
                raise GraphError(f"Duplicate edges for {node_id}")
            metadata = raw.get("metadata", {})
            if not isinstance(metadata, dict):
                raise GraphError(f"metadata must be an object for {node_id}")
            try:
                metadata_json = json.dumps(metadata, ensure_ascii=True, allow_nan=False, sort_keys=True)
            except (TypeError, ValueError, RecursionError) as exc:
                raise GraphError(f"metadata must be finite JSON data for {node_id}") from exc
            nodes[node_id] = Node(label, content, tuple(edges), metadata_json)
        for node_id, node in nodes.items():
            for destination in node.edges:
                if destination not in nodes:
                    raise GraphError(f"Unknown destination {destination!r} from {node_id!r}")
        entry = _identifier(data.get("entry", min(nodes)))
        if entry not in nodes:
            raise GraphError(f"Unknown entry {entry!r}")
        return cls(nodes, entry)

    def context(self, start: str | None = None, max_nodes: int = 4,
                max_chars: int = 4000) -> dict[str, Any]:
        """Return bounded BFS text, included node IDs, and a truncation flag.

        Character limits count Python Unicode characters, including headers and
        separators, not tokens or UTF-8 bytes. A final node may be partial and is
        then included in ``visited``. Zero budgets yield empty truncated context.
        Disconnected nodes are not visited and do not imply truncation. Metadata
        is deliberately excluded from the retrieved text.
        """
        for name, budget in (("max_nodes", max_nodes), ("max_chars", max_chars)):
            if type(budget) is not int or budget < 0:
                raise GraphError(f"{name} must be a nonnegative integer")
        start = self.entry if start is None else _identifier(start)
        if start not in self.nodes:
            raise GraphError(f"Unknown start {start!r}")
        queue = deque([start])
        discovered = {start}
        visited: list[str] = []
        chunks: list[str] = []
        size = 0
        partial = False
        while queue and len(visited) < max_nodes and size < max_chars:
            node_id = queue.popleft()
            node = self.nodes[node_id]
            separator = "\n\n" if visited else ""
            record = f"[{node_id}] {node.label}\n{node.content}"
            remaining = max_chars - size
            # Do not emit a separator alone and claim a node was included.
            if remaining <= len(separator):
                queue.appendleft(node_id)
                break
            chunk = (separator + record)[:remaining]
            chunks.append(chunk)
            size += len(chunk)
            visited.append(node_id)
            for destination in node.edges:
                if destination not in discovered:
                    discovered.add(destination)
                    queue.append(destination)
            if len(chunk) < len(separator) + len(record):
                partial = True
                break
        return {"text": "".join(chunks), "visited": visited,
                "truncated": partial or bool(queue)}

    def trace(self, route: list[str] | tuple[str, ...]) -> list[str]:
        """Validate a nonempty directed walk and return its identifiers.

        The walk may start at any node, revisit nodes, and omit other branches.
        It attests only adjacency in this graph, never reasoning correctness.
        """
        if not isinstance(route, (list, tuple)):
            raise GraphError("route must be a nonempty list or tuple of node IDs")
        result = list(route)
        if not result:
            raise GraphError("route must be nonempty")
        for node_id in result:
            _identifier(node_id)
            if node_id not in self.nodes:
                raise GraphError(f"Unknown route node {node_id!r}")
        for origin, destination in zip(result, result[1:]):
            if destination not in self.nodes[origin].edges:
                raise GraphError(f"No directed edge from {origin!r} to {destination!r}")
        return result
