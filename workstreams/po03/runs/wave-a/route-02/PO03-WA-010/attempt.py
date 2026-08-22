#!/usr/bin/env python3
"""Fail closed before compilation when selected-source bytes mismatch their hash."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


def verify_selected(selection: dict[str, Any], root: Path) -> tuple[int, dict[str, Any]]:
    relative = selection.get("path")
    expected = selection.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        return 2, {"code": "SELECTION_RECORD_INVALID", "state": "REJECTED"}
    source = root / relative
    if not source.is_file():
        return 2, {"code": "SELECTED_SOURCE_MISSING", "path": relative, "state": "REJECTED"}
    payload = source.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        return 3, {
            "actual_sha256": actual,
            "code": "SELECTED_HASH_MISMATCH",
            "expected_sha256": expected,
            "path": relative,
            "state": "REJECTED",
        }
    return 0, {
        "capsule": {"bytes": len(payload), "path": relative, "sha256": actual},
        "state": "COMPILED",
    }


class HashMismatchTests(unittest.TestCase):
    def test_mutated_selected_bytes_fail_closed_without_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selected.md"
            source.write_text("approved bytes\n", encoding="utf-8")
            frozen = hashlib.sha256(source.read_bytes()).hexdigest()
            source.write_text("tampered bytes\n", encoding="utf-8")
            code, report = verify_selected({"path": "selected.md", "sha256": frozen}, root)
            self.assertEqual(3, code)
            self.assertEqual("SELECTED_HASH_MISMATCH", report["code"])
            self.assertEqual("REJECTED", report["state"])
            self.assertNotIn("capsule", report)

    def test_matching_selected_bytes_compile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "selected.md"
            source.write_bytes(b"stable bytes\n")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            code, report = verify_selected({"path": "selected.md", "sha256": digest}, root)
            self.assertEqual(0, code)
            self.assertEqual("COMPILED", report["state"])
            self.assertEqual(digest, report["capsule"]["sha256"])


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HashMismatchTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"adversarial_mismatch": "REJECTED", "disposition": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("test")
    check = subparsers.add_parser("check")
    check.add_argument("--selection", type=Path, required=True)
    check.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    code, report = verify_selected(json.loads(args.selection.read_text(encoding="utf-8")), args.root)
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
