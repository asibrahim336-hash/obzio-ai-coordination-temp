#!/usr/bin/env python3
"""Record each generation's run transcript into the committed tree.

A score is only evidence if the run that produced it can be re-executed and
compared.  Each transcript is the verbatim stdout of that generation's own entry
point, prefixed by the exact command, and ``--check`` re-runs every command and
fails on any difference.  Nothing is kept outside the repository and no
transcript carries a timestamp, so the artifact and the act of reproducing it
are the same thing.

    python3 -I workstreams/po03/successor/record_transcripts.py --write
    python3 -I workstreams/po03/successor/record_transcripts.py --check
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
TRANSCRIPTS = PO03 / "successor" / "transcripts"

RUNS = {
    "g0": "workstreams/po03/successor/g0/run.py",
    "g1": "workstreams/po03/successor/g1/run.py",
    "g2": "workstreams/po03/successor/g2/run.py",
}

# One transcript per generation per suite.  Splitting them keeps each file stable
# once written: a unit's recorded artifact hash stays valid instead of shifting
# every time a later suite lands.
SUITES = ("public", "holdout")


def transcript(entry_point: str, suite: str) -> str:
    command = f"python3 -I {entry_point} --suite {suite}"
    completed = subprocess.run(
        [sys.executable, "-I", entry_point, "--suite", suite],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    body = completed.stdout
    if completed.stderr.strip():
        body += "\n--- stderr ---\n" + completed.stderr
    return f"$ {command}\n{body}exit_code={completed.returncode}\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--generation", choices=sorted(RUNS), action="append")
    parser.add_argument("--suite", choices=SUITES, action="append")
    args = parser.parse_args()

    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    generations = args.generation or sorted(RUNS)
    suites = args.suite or list(SUITES)
    failures = 0
    for generation in generations:
        entry_point = RUNS[generation]
        if not (REPO_ROOT / entry_point).is_file():
            print(f"SKIP {generation}: {entry_point} is not in the tree")
            continue
        for suite in suites:
            target = TRANSCRIPTS / f"{generation}-{suite}.txt"
            text = transcript(entry_point, suite)
            if args.check:
                if not target.is_file() or target.read_text(encoding="utf-8") != text:
                    print(f"DRIFTED {target}: re-running the entry point produced different output")
                    failures += 1
                else:
                    print(f"REPRODUCED {target}")
            else:
                target.write_text(text, encoding="utf-8")
                print(f"WROTE {target}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
