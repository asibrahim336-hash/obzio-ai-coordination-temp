#!/usr/bin/env python3
"""Compile the consolidated recovery fault matrix for cohort c6.

Every row comes from an injection report that was actually produced by running a
component in this cohort, never from a narrative.  Each source file is recorded
with its SHA-256, its byte count and, when it is already committed, its Git blob
id, so the controller can verify the matrix against durable bytes.

    python3 -I fault_matrix.py --write

writes recovery-fault-matrix.json and recovery-fault-matrix.md into this unit's
subtree.  Without --write it prints the matrix to standard output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ATTEMPTS = HERE.parent
REPO_ROOT = HERE.parents[3]

UNITS = (
    "po03-wa-b2e7-041-session-loss-injection",
    "po03-wa-b2e7-042-lost-callback-replay",
    "po03-wa-b2e7-043-partial-and-commit-failure",
    "po03-wa-b2e7-044-push-failure-injection",
    "po03-wa-b2e7-045-stale-lease-fencing",
    "po03-wa-b2e7-046-duplicate-callback-idempotence",
    "po03-wa-b2e7-047-corrupt-artifact-recovery",
    "po03-wa-b2e7-048-provider-runtime-loss-and-code2-fixture",
)
RECORD_NAMES = ("defect-record.json", "observation-record.json")


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def git_blob_id(path: Path) -> str | None:
    completed = subprocess.run(
        ("git", "rev-parse", f"HEAD:{repo_relative(path)}"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def source_record(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {
        "path": repo_relative(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "git_blob_id": git_blob_id(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def behaviour_index(unit: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Map fault class to the curated observation text recorded for it."""
    index: dict[str, str] = {}
    sources: list[dict[str, Any]] = []
    for name in RECORD_NAMES:
        path = ATTEMPTS / unit / name
        if not path.is_file():
            continue
        sources.append(source_record(path))
        record = load_json(path)
        for entry in record.get("fault_classes", []):
            if isinstance(entry, dict) and "fault_class" in entry:
                index[entry["fault_class"]] = entry.get("observed_behaviour", "")
        if "fault_injected" in record and "observed_behaviour" in record:
            observed = record["observed_behaviour"]
            index[record["fault_injected"]] = (
                "; ".join(observed) if isinstance(observed, list) else str(observed)
            )
    return index, sources


def summarise(observed: Any) -> str:
    """Compact fallback description drawn from the machine-recorded observation."""
    if not isinstance(observed, dict):
        return json.dumps(observed)[:400]
    parts = []
    for key, value in sorted(observed.items()):
        if isinstance(value, (str, int, float, bool)) or value is None:
            parts.append(f"{key}={value}")
        elif isinstance(value, list) and len(value) <= 6:
            parts.append(f"{key}={json.dumps(value)}")
    return "; ".join(parts)[:600]


def unit_rows(unit: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    report_path = ATTEMPTS / unit / "injection-report.json"
    sources = [source_record(report_path)]
    report = load_json(report_path)
    index, record_sources = behaviour_index(unit)
    sources.extend(record_sources)

    entries = report.get("results")
    if entries is None:
        entries = [
            {
                "fault_class": report["injection"],
                "injected_at_state_transition": report.get("injected_at_state"),
                "observed": report.get("observed", {}),
                "verdict": report["verdict"],
            }
        ]
    rows = []
    for entry in entries:
        fault_class = entry["fault_class"]
        rows.append(
            {
                "source_unit": unit,
                "fault_class": fault_class,
                "injected_at_state_transition": entry.get("injected_at_state_transition"),
                "observed_behaviour": index.get(fault_class) or summarise(entry.get("observed")),
                "verdict": entry["verdict"],
            }
        )
    return rows, sources


def build_matrix() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    unit_verdicts: dict[str, str] = {}
    false_completions = 0
    for unit in UNITS:
        unit_rows_, unit_sources = unit_rows(unit)
        rows.extend(unit_rows_)
        sources.extend(unit_sources)
        report = load_json(ATTEMPTS / unit / "injection-report.json")
        unit_verdicts[unit] = report["verdict"]
        false_completions += int(report.get("false_completions_observed", 0) or 0)
        if report.get("false_completion_observed"):
            false_completions += 1

    defects = []
    for unit in UNITS:
        path = ATTEMPTS / unit / "defect-record.json"
        if path.is_file():
            record = load_json(path)
            defects.append(
                {
                    "defect_id": record["defect_id"],
                    "source_unit": unit,
                    "verdict": record["verdict"],
                    "severity": record.get("severity"),
                    "cohort_bar_clause_breached": record.get("cohort_bar_clause_breached"),
                    "repair_candidate": record["repair_candidate"]["path"],
                    "adopted_by_live_mechanism": record["repair_candidate"]["adopted_by_live_mechanism"],
                }
            )

    verdict_counts: dict[str, int] = {}
    for row in rows:
        verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1

    return {
        "matrix_version": "PO03-C6-RECOVERY-FAULT-MATRIX-v1",
        "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
        "cohort": "c6",
        "function": "transactional-recovery-and-fault-injection",
        "compiled_by": "po03-wa-b2e7-041-session-loss-injection producer",
        "compiled_from": "injection reports produced by executing each unit's component",
        "units": list(UNITS),
        "unit_verdicts": unit_verdicts,
        "fault_class_rows": len(rows),
        "verdict_counts": verdict_counts,
        "false_completions_observed": false_completions,
        "rows": rows,
        "defects": defects,
        "sources": sources,
        "producer_may_not_accept_own_work": True,
        "obzio_state_claim": "READY_TO_COMMIT",
        "decision_changed": [],
    }


def render_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# PO-03 cohort c6 recovery fault matrix",
        "",
        f"Commission: {matrix['commission_id']}",
        f"Function: {matrix['function']}",
        f"Fault class rows: {matrix['fault_class_rows']}",
        f"False completions observed: {matrix['false_completions_observed']}",
        "",
        "| Unit | Fault class | Injected at state transition | Verdict |",
        "| --- | --- | --- | --- |",
    ]
    for row in matrix["rows"]:
        unit = row["source_unit"].replace("po03-wa-b2e7-", "")
        lines.append(
            f"| {unit} | {row['fault_class']} | {row['injected_at_state_transition']} | {row['verdict']} |"
        )
    lines.extend(["", "## Defects with staged repair candidates", ""])
    for defect in matrix["defects"]:
        lines.append(
            f"- `{defect['defect_id']}` ({defect['verdict']}, {defect['severity']}) — "
            f"repair candidate `{defect['repair_candidate']}`, adopted: {defect['adopted_by_live_mechanism']}"
        )
    lines.extend(["", "## Observed behaviour per fault class", ""])
    for row in matrix["rows"]:
        lines.append(f"- **{row['fault_class']}** ({row['verdict']}): {row['observed_behaviour']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    matrix = build_matrix()
    if arguments.write:
        (HERE / "recovery-fault-matrix.json").write_bytes(
            (json.dumps(matrix, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        (HERE / "recovery-fault-matrix.md").write_bytes(render_markdown(matrix).encode("utf-8"))
        print(
            json.dumps(
                {
                    "fault_class_rows": matrix["fault_class_rows"],
                    "verdict_counts": matrix["verdict_counts"],
                    "false_completions_observed": matrix["false_completions_observed"],
                    "defects": len(matrix["defects"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    json.dump(matrix, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
