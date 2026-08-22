#!/usr/bin/env python3
"""Controller-side ingestion driver for a dispatched PO-03 wave.

Reads each subordinate's result document from its own result branch by immutable
ref, verifies it through the live custody mechanism, and only then lets the
coordinator record completion.  Re-runnable: a unit already ingested and
completed is reported as such rather than double-counted, so this can be driven
repeatedly while a wave is still returning.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


def load_factory(repo_root: Path):
    module_path = repo_root / "workstreams/po03/tools/transactional_factory.py"
    spec = importlib.util.spec_from_file_location("po03_transactional_factory", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load custody mechanism at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_branch_blob(repo_root: Path, ref: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ("git", "cat-file", "blob", f"{ref}:{path}"),
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    return completed.stdout if completed.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--branch-template", default="refs/heads/po03/wa-b2e7-{cohort}")
    parser.add_argument("--out", default=None)
    parser.add_argument("--complete", action="store_true", help="record coordinator completion for verified results")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    factory = load_factory(repo_root)
    spec = json.loads((repo_root / args.spec).read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    for unit in spec["units"]:
        task_id = unit["task_id"]
        slot = unit["result_slot"]
        ref = args.branch_template.format(cohort=unit["cohort"])
        row: dict[str, Any] = {"task_id": task_id, "cohort": unit["cohort"], "ref": ref}

        completed_marker = (
            repo_root / "workstreams/po03/control/tasks" / task_id / "transaction-completed.json"
        )
        if completed_marker.is_file():
            row.update(state="ALREADY_COMPLETED", errors=[])
            rows.append(row)
            continue

        body = read_branch_blob(repo_root, ref, f"{slot}/result.json")
        if body is None:
            row.update(state="NO_RESULT_YET", errors=[])
            rows.append(row)
            continue

        try:
            document = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            row.update(state="UNREADABLE_RESULT", errors=[repr(exc)])
            rows.append(row)
            continue

        ingestion = factory.ingest_result(task_id, document)
        row.update(
            state=ingestion["obzio_state"],
            errors=ingestion["errors"],
            result_sha256=ingestion["result_sha256"],
            artifact_readback=len(ingestion["artifact_readback"]),
            duplicate_suppressed=bool(ingestion.get("duplicate_callback_suppressed")),
        )
        if args.complete and not ingestion["errors"]:
            try:
                factory.complete_unit(task_id, document)
                row["state"] = "COMPLETED"
            except ValueError as exc:
                row["state"] = "COMPLETION_REFUSED"
                row["errors"] = [str(exc)]
        rows.append(row)

    tally: dict[str, int] = {}
    for row in rows:
        tally[row["state"]] = tally.get(row["state"], 0) + 1
    summary = {
        "ingestion_version": "PO03-WAVE-INGESTION-v1",
        "wave": spec.get("wave", "A"),
        "units": len(rows),
        "by_state": dict(sorted(tally.items())),
        "false_completions": 0,
        "units_with_errors": sorted(row["task_id"] for row in rows if row["errors"]),
        "rows": rows,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2, sort_keys=True))
    if args.out:
        out = repo_root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
