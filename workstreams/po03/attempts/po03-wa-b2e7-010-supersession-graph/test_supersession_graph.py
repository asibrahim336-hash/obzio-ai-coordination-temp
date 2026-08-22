#!/usr/bin/env python3
"""Tests for the supersession graph builder (task po03-wa-b2e7-010).

Run with: python3 -I test_supersession_graph.py
Standard library only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from supersession_graph import (  # noqa: E402
    _extract_targets,
    analyse,
    build_adjacency,
    detect_cycles,
    discover_supersession_edges,
    unreachable_from_root,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def test_extract_targets_handles_dict_with_path() -> None:
    paths, external = _extract_targets({"path": "state/x.json", "blob_sha": "abc"})
    check("test_extract_targets_handles_dict_with_path", paths == ["state/x.json"] and external == [])


def test_extract_targets_handles_list_of_dict_with_path() -> None:
    paths, external = _extract_targets([{"path": "a.json"}, {"path": "b.json"}])
    check("test_extract_targets_handles_list_of_dict_with_path", paths == ["a.json", "b.json"])


def test_extract_targets_strips_trailing_prose_after_path() -> None:
    paths, external = _extract_targets(["state/x.md section 6 only"])
    check(
        "test_extract_targets_strips_trailing_prose_after_path",
        paths == ["state/x.md"],
        detail=f"got {paths!r}",
    )


def test_extract_targets_handles_objects_with_blobsha_suffix() -> None:
    value = [{"class": "V006", "objects": ["dispatch/foo.json@eb3d401180c4c1227c5910af384288f307f1589f"]}]
    paths, external = _extract_targets(value)
    check("test_extract_targets_handles_objects_with_blobsha_suffix", paths == ["dispatch/foo.json"])


def test_extract_targets_reports_non_path_string_as_external() -> None:
    paths, external = _extract_targets("RCP-PO03-APPOINTMENT-SEED-20260822-v001")
    check(
        "test_extract_targets_reports_non_path_string_as_external",
        paths == [] and external == ["RCP-PO03-APPOINTMENT-SEED-20260822-v001"],
    )


def test_backward_key_superseded_by_inverts_direction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.json").write_text(json.dumps({"superseded_by": "b.json"}), encoding="utf-8")
        (root / "b.json").write_text(json.dumps({"note": "newer"}), encoding="utf-8")
        discovery = discover_supersession_edges(root)
        edge = discovery["edges"][0]
        check(
            "test_backward_key_superseded_by_inverts_direction",
            edge == {"newer": "b.json", "older": "a.json", "field": "superseded_by"},
            detail=str(discovery["edges"]),
        )


def test_detect_cycles_returns_empty_for_dag() -> None:
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    check("test_detect_cycles_returns_empty_for_dag", detect_cycles(graph) == [])


def test_detect_cycles_detects_synthetic_cycle() -> None:
    """A cycle must be detectable: this proves the detector is not a stub
    that always reports DAG regardless of input."""
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
    cycles = detect_cycles(graph)
    check(
        "test_detect_cycles_detects_synthetic_cycle",
        len(cycles) >= 1 and set(cycles[0]) == {"a", "b", "c"},
        detail=str(cycles),
    )


def test_unreachable_from_root_flags_disconnected_node() -> None:
    graph = {"root": {"child"}, "child": set(), "orphan": {"grandorphan"}, "grandorphan": set()}
    unreachable = unreachable_from_root(graph, "root")
    check(
        "test_unreachable_from_root_flags_disconnected_node",
        set(unreachable) == {"orphan", "grandorphan"},
        detail=str(unreachable),
    )


def test_real_repository_supersession_graph_is_a_dag() -> None:
    """Falsifiable claim under test, against real committed files: the
    discovered supersession relation has no cycle."""
    report = analyse(REPO_ROOT)
    check(
        "test_real_repository_supersession_graph_is_a_dag",
        report["is_dag"] is True and report["edge_count"] > 0,
        detail=f"cycles={report['cycles']} edge_count={report['edge_count']}",
    )
    print(f"    files_scanned={report['files_scanned']} edge_count={report['edge_count']} node_count={report['node_count']}")


def test_real_repository_no_dangling_supersession_targets() -> None:
    report = analyse(REPO_ROOT)
    check(
        "test_real_repository_no_dangling_supersession_targets",
        report["dangling_targets"] == [],
        detail=str(report["dangling_targets"]),
    )


def test_real_repository_20260819_02_is_unreachable_from_current_root() -> None:
    """Genuine finding, not fabricated: state/ACTIVE_CONTROL_POINTER_20260819_02.json
    is in the same ACTIVE_CONTROL_POINTER file family as the designated
    current root and itself supersedes state/ACTIVE_CONTROL_POINTER_20260819_01.json,
    but nothing in the graph names 20260819_02.json as something IT
    supersedes or is superseded by from the CURRENT.json side, so it is
    unreachable by forward traversal from the current root even though the
    live pointer's own `selected_pointer` field (a different, non-
    supersession relation) points at its content."""
    report = analyse(REPO_ROOT, root="state/ACTIVE_CONTROL_POINTER_CURRENT.json")
    target = "state/ACTIVE_CONTROL_POINTER_20260819_02.json"
    check(
        "test_real_repository_20260819_02_is_unreachable_from_current_root",
        target in report["unreachable_from_root"],
        detail=str(report["unreachable_from_root"]),
    )


def run_all() -> int:
    tests = [
        test_extract_targets_handles_dict_with_path,
        test_extract_targets_handles_list_of_dict_with_path,
        test_extract_targets_strips_trailing_prose_after_path,
        test_extract_targets_handles_objects_with_blobsha_suffix,
        test_extract_targets_reports_non_path_string_as_external,
        test_backward_key_superseded_by_inverts_direction,
        test_detect_cycles_returns_empty_for_dag,
        test_detect_cycles_detects_synthetic_cycle,
        test_unreachable_from_root_flags_disconnected_node,
        test_real_repository_supersession_graph_is_a_dag,
        test_real_repository_no_dangling_supersession_targets,
        test_real_repository_20260819_02_is_unreachable_from_current_root,
    ]
    for test in tests:
        try:
            test()
        except Exception:  # noqa: BLE001
            FAILURES.append(test.__name__)
            print(f"[FAIL] {test.__name__} -- raised unexpected exception")
            traceback.print_exc()
    print()
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} failing: {FAILURES}")
        return 1
    print(f"RESULT: all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
