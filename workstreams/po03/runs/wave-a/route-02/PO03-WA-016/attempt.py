#!/usr/bin/env python3
"""Reproduce a canonical current-source compilation hash through a clean clone."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode()


def compile_repository(root: Path) -> tuple[bytes, str]:
    pointer = json.loads((root / "pointer.json").read_text(encoding="utf-8"))
    dispositions = json.loads((root / "dispositions.json").read_text(encoding="utf-8"))
    selected_path = pointer["selected_path"]
    records = [item for item in dispositions["objects"] if item["path"] == selected_path]
    if pointer.get("status") != "CURRENT" or len(records) != 1 or records[0].get("standing") != "CURRENT":
        raise ValueError("CURRENT_SELECTION_INVALID")
    payload = (root / selected_path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != pointer["selected_sha256"]:
        raise ValueError("CURRENT_SELECTION_HASH_MISMATCH")
    capsule = canonical(
        {
            "capsule_version": "PO03-REPRODUCIBLE-CURRENT-v1",
            "selected": {"bytes": len(payload), "path": selected_path, "sha256": digest},
            "source_text_utf8": payload.decode("utf-8"),
        }
    )
    return capsule, hashlib.sha256(capsule).hexdigest()


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def clean_clone_reproduction() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        sandbox = Path(directory)
        source = sandbox / "source"
        clone = sandbox / "clean-clone"
        source.mkdir()
        git(source, "init", "--initial-branch=main")
        git(source, "config", "user.name", "Sanitized Fixture")
        git(source, "config", "user.email", "fixture@example.invalid")
        sources = source / "sources"
        sources.mkdir()
        (sources / "v1.md").write_text("superseded fixture\n", encoding="utf-8")
        (sources / "v2.md").write_text("portable current fixture\n", encoding="utf-8")
        selected_sha = hashlib.sha256((sources / "v2.md").read_bytes()).hexdigest()
        (source / "pointer.json").write_bytes(
            canonical({"pointer_id": "PTR-PORTABLE", "selected_path": "sources/v2.md", "selected_sha256": selected_sha, "status": "CURRENT"})
        )
        (source / "dispositions.json").write_bytes(
            canonical(
                {
                    "objects": [
                        {"path": "sources/v1.md", "standing": "SUPERSEDED"},
                        {"path": "sources/v2.md", "standing": "CURRENT"},
                    ]
                }
            )
        )
        git(source, "add", ".")
        git(source, "commit", "-m", "sanitized current-source fixture")
        source_capsule, source_hash = compile_repository(source)
        subprocess.check_call(("git", "clone", "--no-local", str(source), str(clone)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clone_capsule, clone_hash = compile_repository(clone)
        return {
            "byte_identical": source_capsule == clone_capsule,
            "clean_clone_hash": clone_hash,
            "clean_clone_head": git(clone, "rev-parse", "HEAD"),
            "source_hash": source_hash,
            "state": "PASS" if source_capsule == clone_capsule and source_hash == clone_hash else "FAIL",
        }


class CleanCloneCompilationTests(unittest.TestCase):
    def test_clean_clone_produces_identical_capsule_bytes_and_hash(self) -> None:
        report = clean_clone_reproduction()
        self.assertEqual("PASS", report["state"])
        self.assertTrue(report["byte_identical"])
        self.assertEqual(report["source_hash"], report["clean_clone_hash"])


def self_test() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CleanCloneCompilationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = clean_clone_reproduction()
    report.update({"disposition": "PASS" if result.wasSuccessful() and report["state"] == "PASS" else "FAIL", "tests_run": result.testsRun})
    print(json.dumps(report, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("test", "compile"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.command == "test":
        return self_test()
    if args.root is None:
        parser.error("compile requires --root")
    capsule, digest = compile_repository(args.root)
    print(json.dumps({"capsule_sha256": digest, "capsule_utf8": capsule.decode("utf-8")}, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
