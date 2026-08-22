#!/usr/bin/env python3
"""Run tests against controlled source mutations and expose false greens."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_mutations(root: Path, mutations_path: Path, command: str) -> dict:
    mutations = json.loads(mutations_path.read_text(encoding="utf-8"))
    if not isinstance(mutations, list) or not mutations:
        raise ValueError("mutation file must contain a non-empty array")
    results = []
    for mutation in mutations:
        for field in ("id", "path", "old", "new"):
            if not isinstance(mutation.get(field), str) or not mutation[field]:
                raise ValueError(f"mutation missing non-empty {field}")
        # Keep mutation state inside the evaluator worktree as required by the
        # review boundary; the temporary directory is removed after each case.
        with tempfile.TemporaryDirectory(prefix=".po03-fg-", dir=root) as scratch_name:
            scratch = Path(scratch_name) / "tree"
            shutil.copytree(root, scratch)
            target = scratch / mutation["path"]
            original = target.read_text(encoding="utf-8")
            occurrences = original.count(mutation["old"])
            if occurrences != 1:
                raise ValueError(
                    f"{mutation['id']}: expected one match, found {occurrences}"
                )
            target.write_text(
                original.replace(mutation["old"], mutation["new"], 1),
                encoding="utf-8",
            )
            completed = subprocess.run(
                shlex.split(command),
                cwd=scratch,
                capture_output=True,
                text=True,
                check=False,
            )
            results.append(
                {
                    "id": mutation["id"],
                    "path": mutation["path"],
                    "exit_code": completed.returncode,
                    "tests_passed_after_mutation": completed.returncode == 0,
                    "false_green": completed.returncode == 0,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
    return {
        "mutation_count": len(results),
        "false_green_count": sum(item["false_green"] for item in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mutations", type=Path, required=True)
    parser.add_argument("--test-command", required=True)
    args = parser.parse_args()
    report = run_mutations(args.root.resolve(), args.mutations.resolve(), args.test_command)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
