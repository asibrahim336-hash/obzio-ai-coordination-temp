#!/usr/bin/env python3
"""Classify missing selected bytes separately from retained superseded evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


def classify_sources(selected_path: str, dispositions: list[dict[str, str]], root: Path) -> tuple[int, dict[str, Any]]:
    selected = root / selected_path
    superseded = []
    for record in dispositions:
        if record.get("standing") == "SUPERSEDED":
            path = root / record["path"]
            superseded.append(
                {
                    "bytes_present": path.is_file(),
                    "eligible_for_fallback": False,
                    "path": record["path"],
                    "standing": "SUPERSEDED",
                }
            )
    superseded.sort(key=lambda item: item["path"])
    if not selected.is_file():
        return 5, {
            "code": "MISSING_SELECTED_BYTES",
            "selected_path": selected_path,
            "selected_state": "MISSING",
            "state": "REJECTED",
            "superseded_evidence": superseded,
        }
    payload = selected.read_bytes()
    return 0, {
        "selected": {
            "bytes": len(payload),
            "path": selected_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "selected_state": "PRESENT",
        "state": "COMPILED",
        "superseded_evidence": superseded,
    }


class MissingSelectedBytesTests(unittest.TestCase):
    def test_missing_selected_is_not_replaced_by_present_superseded_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "v1.md").write_text("retained old evidence\n", encoding="utf-8")
            records = [
                {"path": "v1.md", "standing": "SUPERSEDED"},
                {"path": "v2.md", "standing": "CURRENT"},
            ]
            code, report = classify_sources("v2.md", records, root)
            self.assertEqual(5, code)
            self.assertEqual("MISSING_SELECTED_BYTES", report["code"])
            self.assertEqual("MISSING", report["selected_state"])
            self.assertTrue(report["superseded_evidence"][0]["bytes_present"])
            self.assertFalse(report["superseded_evidence"][0]["eligible_for_fallback"])
            self.assertNotIn("selected", report)

    def test_present_selected_compiles_while_superseded_remains_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "v1.md").write_text("old\n", encoding="utf-8")
            (root / "v2.md").write_text("current\n", encoding="utf-8")
            records = [{"path": "v1.md", "standing": "SUPERSEDED"}]
            code, report = classify_sources("v2.md", records, root)
            self.assertEqual(0, code)
            self.assertEqual("COMPILED", report["state"])
            self.assertEqual("SUPERSEDED", report["superseded_evidence"][0]["standing"])


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MissingSelectedBytesTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"disposition": "PASS" if result.wasSuccessful() else "FAIL", "missing_code": "MISSING_SELECTED_BYTES", "tests_run": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("test", "classify"))
    parser.add_argument("--selected")
    parser.add_argument("--dispositions", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    if args.selected is None or args.dispositions is None or args.root is None:
        parser.error("classify requires --selected, --dispositions, and --root")
    records = json.loads(args.dispositions.read_text(encoding="utf-8"))
    code, report = classify_sources(args.selected, records, args.root)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
