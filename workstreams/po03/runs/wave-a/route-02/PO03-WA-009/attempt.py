#!/usr/bin/env python3
"""Resolve one current source from explicit pointer and disposition evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def resolve_current(pointer: dict[str, Any], disposition: dict[str, Any], root: Path) -> dict[str, Any]:
    if pointer.get("status") != "CURRENT":
        raise ValueError("POINTER_NOT_CURRENT")
    selected = pointer.get("selected_path")
    if not isinstance(selected, str) or not selected:
        raise ValueError("SELECTED_PATH_INVALID")
    matches = [item for item in disposition.get("objects", []) if item.get("path") == selected]
    if len(matches) != 1 or matches[0].get("disposition") != "CURRENT":
        raise ValueError("SELECTED_DISPOSITION_NOT_CURRENT")
    root = root.resolve()
    candidate = (root / selected).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("SOURCE_ESCAPES_ROOT") from exc
    if not candidate.is_file():
        raise ValueError("SELECTED_SOURCE_MISSING")
    payload = candidate.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != pointer.get("selected_sha256"):
        raise ValueError("SELECTED_HASH_MISMATCH")
    return {
        "capsule_version": "PO03-CURRENT-SOURCE-v1",
        "selected": {
            "bytes": len(payload),
            "content_utf8": payload.decode("utf-8"),
            "path": selected,
            "sha256": digest,
        },
        "selection_evidence": {
            "disposition": matches[0]["disposition"],
            "disposition_id": disposition.get("disposition_id"),
            "pointer_id": pointer.get("pointer_id"),
        },
    }


class CurrentResolutionTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        old = root / "sources/launch-v1.md"
        current = root / "sources/launch-v2.md"
        old.parent.mkdir()
        old.write_text("superseded instructions\n", encoding="utf-8")
        current.write_text("current instructions\n", encoding="utf-8")
        pointer = {
            "pointer_id": "PTR-SANITIZED-2",
            "status": "CURRENT",
            "selected_path": "sources/launch-v2.md",
            "selected_sha256": hashlib.sha256(current.read_bytes()).hexdigest(),
        }
        disposition = {
            "disposition_id": "DSP-SANITIZED-1",
            "objects": [
                {"path": "sources/launch-v1.md", "disposition": "SUPERSEDED"},
                {"path": "sources/launch-v2.md", "disposition": "CURRENT"},
            ],
        }
        return pointer, disposition

    def test_resolves_exactly_the_explicit_current_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pointer, disposition = self.fixture(Path(directory))
            result = resolve_current(pointer, disposition, Path(directory))
            self.assertEqual("sources/launch-v2.md", result["selected"]["path"])
            self.assertEqual("current instructions\n", result["selected"]["content_utf8"])
            self.assertNotIn("superseded", result["selected"]["content_utf8"])

    def test_rejects_pointer_disposition_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pointer, disposition = self.fixture(Path(directory))
            disposition["objects"][1]["disposition"] = "SUPERSEDED"
            with self.assertRaisesRegex(ValueError, "SELECTED_DISPOSITION_NOT_CURRENT"):
                resolve_current(pointer, disposition, Path(directory))


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CurrentResolutionTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"disposition": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("test")
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--pointer", type=Path, required=True)
    compile_parser.add_argument("--disposition", type=Path, required=True)
    compile_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    pointer = json.loads(args.pointer.read_text(encoding="utf-8"))
    disposition = json.loads(args.disposition.read_text(encoding="utf-8"))
    print(canonical(resolve_current(pointer, disposition, args.root)).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
