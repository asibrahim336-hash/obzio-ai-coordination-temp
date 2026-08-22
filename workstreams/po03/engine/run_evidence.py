#!/usr/bin/env python3
"""Produce the durable run evidence that accompanies each a1 result.

A result document names artifacts and hashes; it does not by itself show that
anything ran.  This tool is the mechanism that records execution: it runs the
real command, captures the real output and exit status, and writes a summary
whose hash the result document then pins.  Nothing here is hand-written, so a
run summary cannot describe a run that did not happen.

Usage::

    python3 -I workstreams/po03/engine/run_evidence.py tamper-campaign \\
        --out workstreams/po03/control/units/a1/a1-u01-run-summary.json

    python3 -I workstreams/po03/engine/run_evidence.py record-run \\
        --unit a1-u02 --out <path> -- python3 -I -m unittest ...
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

PO03_ROOT = Path(__file__).resolve().parents[1]
if str(PO03_ROOT) not in sys.path:
    sys.path.insert(0, str(PO03_ROOT))

from engine.canonical import atomic_write_json, sha256_text, utc_now  # noqa: E402
from engine.tamper import run_campaign  # noqa: E402

OUTPUT_BUDGET = 40000
SCRATCH_ROOT = PO03_ROOT / "engine" / "_scratch"


def _runtime_binding() -> dict[str, object]:
    """Runtime facts are execution evidence, never a source of authority."""
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "isolated_mode": bool(sys.flags.isolated),
        "third_party_imports": [],
    }


def _bounded(text: str) -> dict[str, object]:
    digest = sha256_text(text)
    if len(text) <= OUTPUT_BUDGET:
        return {"bytes": len(text.encode("utf-8")), "sha256": digest, "truncated": False, "text": text}
    half = OUTPUT_BUDGET // 2
    return {
        "bytes": len(text.encode("utf-8")),
        "sha256": digest,
        "truncated": True,
        "head": text[:half],
        "tail": text[-half:],
    }


def cmd_tamper_campaign(args: argparse.Namespace) -> int:
    workdir = SCRATCH_ROOT / f"run-evidence-tamper-{int(time.time())}"
    started = time.time()
    try:
        result = run_campaign(
            workdir,
            mutations=args.mutations,
            distinct_target=args.distinct,
            min_per_class=args.min_per_class,
            seed=args.seed,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    elapsed = time.time() - started
    summary = {
        "unit_id": "a1-u01",
        "worker_id": "po03-worker-a1",
        "recorded_at": utc_now(),
        "mechanism": "workstreams/po03/engine/tamper.py::run_campaign",
        "invocation": {
            "mutations_requested": args.mutations,
            "distinct_target": args.distinct,
            "min_per_class": args.min_per_class,
            "seed": args.seed,
        },
        "wall_seconds": round(elapsed, 3),
        "runtime_binding": _runtime_binding(),
        "campaign": result.as_dict(),
        "acceptance_check": {
            "at_least_1000_distinct_mutations": result.distinct_signatures >= 1000,
            "detection_rate_is_100_percent": result.mutations_applied == result.detected,
            "zero_false_positives_on_clean_ledgers": not result.false_positives,
            "every_tamper_class_exercised": all(s["applied"] > 0 for s in result.per_class.values()),
        },
        "scratch_under_tmp": False,
    }
    summary["verdict"] = "PASS" if all(summary["acceptance_check"].values()) else "FAIL"
    digest = atomic_write_json(Path(args.out), summary)
    print(f"wrote {args.out} sha256={digest} verdict={summary['verdict']}")
    return 0 if summary["verdict"] == "PASS" else 1


def cmd_record_run(args: argparse.Namespace) -> int:
    if not args.command:
        raise SystemExit("record-run needs a command after --")
    started = time.time()
    completed = subprocess.run(
        args.command, cwd=str(PO03_ROOT.parents[1]), capture_output=True, text=True, check=False
    )
    elapsed = time.time() - started
    summary = {
        "unit_id": args.unit,
        "worker_id": "po03-worker-a1",
        "recorded_at": utc_now(),
        "command": args.command,
        "command_string": " ".join(args.command),
        "cwd": "<repository root>",
        "exit_code": completed.returncode,
        "wall_seconds": round(elapsed, 3),
        "runtime_binding": _runtime_binding(),
        "stdout": _bounded(completed.stdout),
        "stderr": _bounded(completed.stderr),
        "assertion": args.assertion,
        "verdict": "PASS" if completed.returncode == 0 else "FAIL",
    }
    digest = atomic_write_json(Path(args.out), summary)
    print(f"wrote {args.out} sha256={digest} exit={completed.returncode} verdict={summary['verdict']}")
    return 0 if completed.returncode == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PO-03 cohort a1 run-evidence recorder")
    sub = parser.add_subparsers(dest="command_name", required=True)

    campaign = sub.add_parser("tamper-campaign", help="run the ledger tamper campaign and record it")
    campaign.add_argument("--out", required=True)
    campaign.add_argument("--mutations", type=int, default=1050)
    campaign.add_argument("--distinct", type=int, default=1000)
    campaign.add_argument("--min-per-class", dest="min_per_class", type=int, default=25)
    campaign.add_argument("--seed", type=int, default=20260822)
    campaign.set_defaults(func=cmd_tamper_campaign)

    record = sub.add_parser("record-run", help="run a command and record its exact output")
    record.add_argument("--unit", required=True)
    record.add_argument("--out", required=True)
    record.add_argument("--assertion", default="")
    record.add_argument("command", nargs=argparse.REMAINDER)
    record.set_defaults(func=cmd_record_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
