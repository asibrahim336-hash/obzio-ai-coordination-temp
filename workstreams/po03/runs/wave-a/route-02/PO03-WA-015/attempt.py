#!/usr/bin/env python3
"""Compile a deterministic context capsule from measured admitted bytes only."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


class ContextCapExceeded(Exception):
    def __init__(self, measured: int, cap: int) -> None:
        super().__init__("CONTEXT_CAP_EXCEEDED")
        self.measured = measured
        self.cap = cap


def compile_capsule(records: list[dict[str, Any]], root: Path, max_context_bytes: int) -> dict[str, Any]:
    if not isinstance(max_context_bytes, int) or max_context_bytes < 0:
        raise ValueError("CONTEXT_CAP_INVALID")
    entries: list[dict[str, Any]] = []
    measured = 0
    for record in sorted((item for item in records if item.get("admitted") is True), key=lambda item: item["path"]):
        payload = (root / record["path"]).read_bytes()
        payload.decode("utf-8")
        measured += len(payload)
        if measured > max_context_bytes:
            raise ContextCapExceeded(measured, max_context_bytes)
        entries.append(
            {
                "bytes": len(payload),
                "content_utf8": payload.decode("utf-8"),
                "path": record["path"],
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "capsule_version": "PO03-MEASURED-CONTEXT-v1",
        "entries": entries,
        "max_context_bytes": max_context_bytes,
        "measured_context_bytes": measured,
    }


class MeasuredContextCapsuleTests(unittest.TestCase):
    def test_capsule_contains_only_admitted_measured_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_text("alpha\n", encoding="utf-8")
            (root / "b.md").write_text("SECRET-EXCLUDED-SENTINEL\n", encoding="utf-8")
            records = [
                {"path": "b.md", "admitted": False},
                {"path": "a.md", "admitted": True},
            ]
            capsule = compile_capsule(records, root, max_context_bytes=6)
            encoded = json.dumps(capsule, sort_keys=True)
            self.assertEqual(6, capsule["measured_context_bytes"])
            self.assertEqual(6, capsule["entries"][0]["bytes"])
            self.assertEqual(["a.md"], [item["path"] for item in capsule["entries"]])
            self.assertNotIn("SECRET-EXCLUDED-SENTINEL", encoded)
            self.assertNotIn("b.md", encoded)

    def test_cap_overflow_fails_without_returning_partial_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_bytes(b"1234")
            (root / "b.md").write_bytes(b"5678")
            with self.assertRaises(ContextCapExceeded) as caught:
                compile_capsule(
                    [{"path": "a.md", "admitted": True}, {"path": "b.md", "admitted": True}],
                    root,
                    max_context_bytes=7,
                )
            self.assertEqual(8, caught.exception.measured)
            self.assertEqual(7, caught.exception.cap)


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MeasuredContextCapsuleTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"admitted_bytes": 6, "cap_bytes": 6, "disposition": "PASS" if result.wasSuccessful() else "FAIL", "excluded_sentinel_present": False, "tests_run": result.testsRun}, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("test", "compile"))
    parser.add_argument("--records", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--max-context-bytes", type=int)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    if args.records is None or args.root is None or args.max_context_bytes is None:
        parser.error("compile requires --records, --root, and --max-context-bytes")
    records = json.loads(args.records.read_text(encoding="utf-8"))
    try:
        report = compile_capsule(records, args.root, args.max_context_bytes)
        code = 0
    except ContextCapExceeded as exc:
        report = {"cap_bytes": exc.cap, "code": "CONTEXT_CAP_EXCEEDED", "measured_bytes": exc.measured, "state": "REJECTED"}
        code = 6
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
