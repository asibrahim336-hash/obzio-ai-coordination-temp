#!/usr/bin/env python3
"""Build a supersession graph from committed repository files and check it.

FALSIFIABLE HYPOTHESIS (task po03-wa-b2e7-010-supersession-graph):
    Supersession relationships across instruction and state files form a
    directed acyclic graph, and any cycle is a defect.

This module scans committed JSON/JSONL files for any key whose name
contains "supersed" (case-insensitive: supersedes, supersedes_pointer,
superseded_pointer, supersedes_as_live_pointer, superseded_by,
superseded_evidence_chain, superseded_and_held_evidence,
preserved_superseded_evidence, superseded_before_dispatch(ed),
blocked_superseded_unsent, supersedes_receipt, ...). It normalises every
value shape it actually finds in this repository into directed edges
`(newer_file, older_file)` meaning "newer_file supersedes older_file", then
runs cycle detection (DFS with a recursion-stack) and reachability
analysis from a designated current root.

Only reading. Never writes to, deletes, or rewrites any scanned file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# Field names on the *older* side of the relation: the file carrying this key
# is the one being superseded, and its value names the *newer* file.
BACKWARD_KEYS = {"superseded_by"}

# Everything else containing "supersed" is treated as forward: the file
# carrying the key is the *newer* one, and the value names older file(s)/
# evidence it supersedes. This covers every forward-style key actually
# observed in this repository (supersedes, supersedes_pointer,
# superseded_pointer, supersedes_as_live_pointer, superseded_evidence_chain,
# superseded_and_held_evidence, preserved_superseded_evidence,
# superseded_before_dispatch(ed), blocked_superseded_unsent,
# supersedes_receipt, ...).

_PATH_LIKE_RE = re.compile(r"^([\w\-./]+\.(?:json|jsonl|md))\b")


def _path_like(text: str) -> str | None:
    """Return the leading repo-relative-looking path in `text`, or None.

    Handles free-text annotations such as
    '<path>.json section 6 only' or '<path>.md immediate owner action only'
    by matching only the leading path token, and returns None for bare
    identifiers with no path separator (e.g. receipt/snapshot IDs), which
    are reported separately as external (non-file) references.
    """
    text = text.strip()
    match = _PATH_LIKE_RE.match(text)
    if match:
        return match.group(1)
    return None


def _extract_targets(value: Any) -> tuple[list[str], list[str]]:
    """Return (resolved_paths, external_references) found inside one
    supersession-field value, regardless of which of the observed shapes
    (dict-with-path, list-of-dict-with-path, list-of-string,
    list-of-dict-with-objects, plain string) it takes."""
    paths: list[str] = []
    external: list[str] = []

    def handle_scalar(item: Any) -> None:
        if isinstance(item, str):
            resolved = _path_like(item)
            if resolved:
                paths.append(resolved)
            else:
                external.append(item)

    def handle_object_string(item: str) -> None:
        # "path@blobsha" entries inside superseded_and_held_evidence.objects
        head = item.split("@", 1)[0]
        resolved = _path_like(head)
        if resolved:
            paths.append(resolved)
        else:
            external.append(item)

    if isinstance(value, dict):
        if "path" in value and isinstance(value["path"], str):
            paths.append(value["path"])
        elif "objects" in value and isinstance(value["objects"], list):
            for obj in value["objects"]:
                if isinstance(obj, str):
                    handle_object_string(obj)
        else:
            handle_scalar(json.dumps(value))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                sub_paths, sub_external = _extract_targets(item)
                paths.extend(sub_paths)
                external.extend(sub_external)
            else:
                handle_scalar(item)
    elif isinstance(value, str):
        handle_scalar(value)

    return paths, external


def discover_supersession_edges(repo_root: Path, scan_glob: str = "**/*.json*") -> dict[str, Any]:
    """Scan every committed .json/.jsonl file under repo_root for supersession
    keys and return normalised edges plus bookkeeping (skipped/unparsable
    files, external non-file references, and per-source raw hits)."""
    repo_root = Path(repo_root)
    edges: list[dict[str, str]] = []
    external_references: list[dict[str, str]] = []
    scanned = 0
    unparsable: list[str] = []

    for file_path in sorted(repo_root.glob(scan_glob)):
        if not file_path.is_file():
            continue
        if ".git" in file_path.parts:
            continue
        rel = file_path.relative_to(repo_root).as_posix()
        scanned += 1
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            unparsable.append(rel)
            continue

        if file_path.suffix == ".jsonl":
            records: list[Any] = []
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    unparsable.append(rel)
        else:
            try:
                records = [json.loads(text)]
            except json.JSONDecodeError:
                unparsable.append(rel)
                records = []

        for record in records:
            if not isinstance(record, dict):
                continue
            for key, value in record.items():
                if "supersed" not in key.lower():
                    continue
                paths, external = _extract_targets(value)
                direction_backward = key.lower() in BACKWARD_KEYS
                for target in paths:
                    if direction_backward:
                        edge = {"newer": target, "older": rel, "field": key}
                    else:
                        edge = {"newer": rel, "older": target, "field": key}
                    edges.append(edge)
                for ext in external:
                    external_references.append({"source": rel, "field": key, "reference": ext})

    return {
        "edges": edges,
        "external_references": external_references,
        "files_scanned": scanned,
        "unparsable_files": unparsable,
    }


def build_adjacency(edges: Iterable[dict[str, str]]) -> dict[str, set[str]]:
    """newer -> {older, older, ...} adjacency (forward = toward the past)."""
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge["newer"], set()).add(edge["older"])
        graph.setdefault(edge["older"], set())
    return graph


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return every simple cycle found via DFS with a recursion stack.
    An empty list means the graph is a DAG."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for neighbour in graph.get(node, ()):
            if color.get(neighbour, WHITE) == WHITE:
                visit(neighbour)
            elif color.get(neighbour) == GRAY:
                idx = stack.index(neighbour)
                cycles.append(stack[idx:] + [neighbour])
        stack.pop()
        color[node] = BLACK

    for node in list(graph):
        if color[node] == WHITE:
            visit(node)
    return cycles


def unreachable_from_root(graph: dict[str, set[str]], root: str) -> list[str]:
    """Nodes with at least one edge (incoming or outgoing) that are not
    reachable by following forward (newer -> older) edges from `root`."""
    reached: set[str] = set()
    frontier = [root] if root in graph else []
    while frontier:
        node = frontier.pop()
        if node in reached:
            continue
        reached.add(node)
        frontier.extend(graph.get(node, ()))

    all_nodes = set(graph.keys())
    return sorted(all_nodes - reached)


def dangling_targets(graph: dict[str, set[str]], repo_root: Path) -> list[str]:
    repo_root = Path(repo_root)
    dangling = []
    for node in graph:
        if not (repo_root / node).is_file():
            dangling.append(node)
    return sorted(dangling)


def analyse(repo_root: Path, root: str = "state/ACTIVE_CONTROL_POINTER_CURRENT.json") -> dict[str, Any]:
    discovery = discover_supersession_edges(repo_root)
    graph = build_adjacency(discovery["edges"])
    cycles = detect_cycles(graph)
    unreachable = unreachable_from_root(graph, root) if root in graph else sorted(graph.keys())
    dangling = dangling_targets(graph, repo_root)
    return {
        "files_scanned": discovery["files_scanned"],
        "unparsable_files": discovery["unparsable_files"],
        "edge_count": len(discovery["edges"]),
        "node_count": len(graph),
        "edges": discovery["edges"],
        "external_references": discovery["external_references"],
        "is_dag": not cycles,
        "cycles": cycles,
        "root": root,
        "root_present_in_graph": root in graph,
        "unreachable_from_root": unreachable,
        "dangling_targets": dangling,
    }


def main(argv: list[str] | None = None) -> int:
    default_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(default_root))
    parser.add_argument("--root", default="state/ACTIVE_CONTROL_POINTER_CURRENT.json")
    args = parser.parse_args(argv)
    report = analyse(Path(args.repo_root), args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["is_dag"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
