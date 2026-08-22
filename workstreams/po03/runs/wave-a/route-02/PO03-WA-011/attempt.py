#!/usr/bin/env python3
"""Select by evidence only; filename resemblance has zero routing weight."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


def select_without_name_heuristics(pointer: dict[str, Any], inventory: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    selected_path = pointer.get("selected_path")
    selected = [record for record in inventory if record.get("path") == selected_path]
    if len(selected) != 1:
        raise ValueError("EXPLICIT_SELECTION_UNRESOLVED")
    if selected[0].get("standing") != "CURRENT":
        raise ValueError("EXPLICIT_SELECTION_NOT_CURRENT")
    path = root / str(selected_path)
    if not path.is_file():
        raise ValueError("EXPLICIT_SELECTION_BYTES_MISSING")
    rejected = sorted(
        (
            {"path": str(record.get("path")), "reason": "NOT_EXPLICITLY_SELECTED", "standing": record.get("standing")}
            for record in inventory
            if record.get("path") != selected_path
        ),
        key=lambda item: item["path"],
    )
    return {
        "algorithm": "EXPLICIT_POINTER_AND_STANDING_ONLY",
        "filename_similarity_considered": False,
        "rejected_candidates": rejected,
        "selected_path": selected_path,
        "selected_text": path.read_text(encoding="utf-8"),
    }


class FilenameSimilarityTests(unittest.TestCase):
    def test_current_looking_superseded_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CURRENT_SOURCE_FINAL_v99.md").write_text("stale trap\n", encoding="utf-8")
            (root / "memo-7.dat").write_text("selected current\n", encoding="utf-8")
            inventory = [
                {"path": "CURRENT_SOURCE_FINAL_v99.md", "standing": "SUPERSEDED"},
                {"path": "memo-7.dat", "standing": "CURRENT"},
            ]
            report = select_without_name_heuristics({"selected_path": "memo-7.dat"}, inventory, root)
            self.assertEqual("memo-7.dat", report["selected_path"])
            self.assertFalse(report["filename_similarity_considered"])
            self.assertEqual("NOT_EXPLICITLY_SELECTED", report["rejected_candidates"][0]["reason"])
            self.assertNotIn("stale trap", report["selected_text"])

    def test_missing_explicit_target_does_not_fallback_to_similar_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "current-source-copy.md").write_text("fallback trap\n", encoding="utf-8")
            inventory = [{"path": "current-source-copy.md", "standing": "SUPERSEDED"}]
            with self.assertRaisesRegex(ValueError, "EXPLICIT_SELECTION_UNRESOLVED"):
                select_without_name_heuristics({"selected_path": "current-source.md"}, inventory, root)


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FilenameSimilarityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"disposition": "PASS" if result.wasSuccessful() else "FAIL", "similarity_weight": 0, "tests_run": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("test")
    run = subparsers.add_parser("resolve")
    run.add_argument("--pointer", type=Path, required=True)
    run.add_argument("--inventory", type=Path, required=True)
    run.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    pointer = json.loads(args.pointer.read_text(encoding="utf-8"))
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    print(json.dumps(select_without_name_heuristics(pointer, inventory, args.root), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
