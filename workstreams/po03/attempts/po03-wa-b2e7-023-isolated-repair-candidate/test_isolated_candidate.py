#!/usr/bin/env python3
"""Prove the frozen failure and candidate repair on an isolated tree copy."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PINNED = "1e6f53c323f8326d12af213557082a3665991f19"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
CANDIDATE = HERE / "candidate"


def git(*args: str) -> bytes:
    return subprocess.run(
        ("git", *args), cwd=REPO, check=True, capture_output=True
    ).stdout


def materialize_packs(destination: Path) -> None:
    listing = git("ls-tree", "-r", "--name-only", "-z", PINNED, "--", "packs")
    for raw_path in listing.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode()
        body = git("cat-file", "blob", f"{PINNED}:{path}")
        target = destination / Path(path).relative_to("packs")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def main() -> int:
    generated = subprocess.run(
        (
            sys.executable,
            "-I",
            str(HERE / "generate_candidate.py"),
            "--repo",
            str(REPO),
            "--output-dir",
            str(CANDIDATE),
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    generation = json.loads(generated.stdout)
    assert generation["missing_count"] == 5
    assert generation["po01_path_writes"] == []
    assert all("po01" not in path.lower() for path in generation["written_paths"])

    with tempfile.TemporaryDirectory(prefix=".isolated-pack-copy-", dir=HERE) as temp:
        pack_root = Path(temp) / "packs"
        materialize_packs(pack_root)
        frozen_command = (
            sys.executable,
            "-I",
            str(CANDIDATE / "frozen_test_missing_spine.py"),
            "--pack-root",
            str(pack_root),
        )
        before = subprocess.run(frozen_command, check=False, capture_output=True, text=True)
        assert before.returncode != 0
        assert "missing declared runtime files" in before.stderr

        repaired = subprocess.run(
            (
                sys.executable,
                "-I",
                str(CANDIDATE / "repair_candidate.py"),
                "--pack-root",
                str(pack_root),
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        repair = json.loads(repaired.stdout)
        assert len(repair["written"]) == 5
        after = subprocess.run(frozen_command, check=True, capture_output=True, text=True)
        after_report = json.loads(after.stdout)
        assert after_report["missing"] == []

    evidence = {
        "generation": generation,
        "frozen_failure_returncode": before.returncode,
        "frozen_failure_stderr": before.stderr.strip(),
        "repair_on_isolated_copy": repair,
        "post_repair_frozen_test": after_report,
        "po01_path_writes": [],
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print("test_isolated_candidate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
