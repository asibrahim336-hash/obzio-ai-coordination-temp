#!/usr/bin/env python3
"""Traverse pointer graphs and emit a machine-readable cycle trace."""

from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path
from typing import Any


def trace_pointer_graph(graph: dict[str, dict[str, str]], start: str) -> tuple[int, dict[str, Any]]:
    visited: dict[str, int] = {}
    ordered: list[str] = []
    trace: list[dict[str, Any]] = []
    current = start
    while True:
        if current in visited:
            cycle = ordered[visited[current] :] + [current]
            return 4, {
                "code": "POINTER_CYCLE",
                "cycle": cycle,
                "cycle_entry_step": visited[current],
                "start": start,
                "state": "REJECTED",
                "trace": trace,
            }
        visited[current] = len(ordered)
        ordered.append(current)
        node = graph.get(current)
        if not isinstance(node, dict):
            return 2, {"code": "POINTER_NODE_MISSING", "node": current, "state": "REJECTED", "trace": trace}
        kind = node.get("kind")
        target = node.get("target")
        trace.append({"from": current, "kind": kind, "step": len(trace), "to": target})
        if kind == "source":
            return 0, {"selected_source": target, "state": "RESOLVED", "trace": trace}
        if kind != "pointer" or not isinstance(target, str):
            return 2, {"code": "POINTER_EDGE_INVALID", "node": current, "state": "REJECTED", "trace": trace}
        current = target


class PointerCycleTests(unittest.TestCase):
    def test_three_node_cycle_has_closed_machine_trace(self) -> None:
        graph = {
            "PTR-A": {"kind": "pointer", "target": "PTR-B"},
            "PTR-B": {"kind": "pointer", "target": "PTR-C"},
            "PTR-C": {"kind": "pointer", "target": "PTR-A"},
        }
        code, report = trace_pointer_graph(graph, "PTR-A")
        self.assertEqual(4, code)
        self.assertEqual("POINTER_CYCLE", report["code"])
        self.assertEqual(["PTR-A", "PTR-B", "PTR-C", "PTR-A"], report["cycle"])
        self.assertEqual(3, len(report["trace"]))
        json.dumps(report)

    def test_acyclic_chain_resolves_source(self) -> None:
        graph = {
            "PTR-A": {"kind": "pointer", "target": "PTR-B"},
            "PTR-B": {"kind": "source", "target": "sources/current.md"},
        }
        code, report = trace_pointer_graph(graph, "PTR-A")
        self.assertEqual(0, code)
        self.assertEqual("sources/current.md", report["selected_source"])


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PointerCycleTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"cycle_trace": ["PTR-A", "PTR-B", "PTR-C", "PTR-A"], "disposition": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("test", "trace"))
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--start")
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    if args.graph is None or args.start is None:
        parser.error("trace requires --graph and --start")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    code, report = trace_pointer_graph(graph, args.start)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
