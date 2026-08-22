#!/usr/bin/env python3
"""Verify that immutable PO-03 dispatches still resolve their frozen source bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DISPATCH_DIR = "workstreams/po03/control/dispatch"
CONTROL_PLANE_PATH = "workstreams/po03/tools/control_plane.py"
RESULT_EMITTER_PATH = "workstreams/po03/tools/make_result.py"
DEFAULT_UNITS = ("a9-u01", "a9-u02", "a9-u03", "a9-u04")
MANIFEST_FIELDS = (
    "unit_id",
    "commission_id",
    "wave_id",
    "cohort_id",
    "function_id",
    "hypothesis",
    "acceptance",
    "owner",
    "owned_paths",
    "model",
    "result_slot",
    "source_hashes",
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_hashes(root: Path, source_hashes: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative, expected in sorted(source_hashes.items()):
        target = root / relative
        if not target.is_file():
            rows.append(
                {
                    "path": relative,
                    "expected_sha256": expected,
                    "observed_sha256": None,
                    "state": "MISSING",
                }
            )
            continue
        observed = sha256_file(target)
        rows.append(
            {
                "path": relative,
                "expected_sha256": expected,
                "observed_sha256": observed,
                "state": "CURRENT" if observed == expected else "DRIFTED",
            }
        )
    return rows


def verify_dispatch(root: Path, unit_id: str) -> dict[str, Any]:
    relative = f"{DISPATCH_DIR}/{unit_id}.json"
    target = root / relative
    dispatch = json.loads(target.read_text(encoding="utf-8"))
    manifest = {field: dispatch[field] for field in MANIFEST_FIELDS}
    observed_manifest_hash = sha256_bytes(canonical(manifest).encode("utf-8"))
    observed_acceptance_hash = sha256_bytes(
        canonical(dispatch["acceptance"]).encode("utf-8")
    )
    sources = verify_source_hashes(root, dispatch["source_hashes"])
    states = {row["state"] for row in sources}
    capsule_state = (
        "MISSING"
        if "MISSING" in states
        else "DRIFTED"
        if "DRIFTED" in states
        else "CURRENT"
    )
    return {
        "unit_id": unit_id,
        "dispatch_path": relative,
        "dispatch_sha256": sha256_file(target),
        "immutable_manifest": {
            "expected_sha256": dispatch["immutable_input_manifest_sha256"],
            "observed_sha256": observed_manifest_hash,
            "state": (
                "CURRENT"
                if observed_manifest_hash == dispatch["immutable_input_manifest_sha256"]
                else "DRIFTED"
            ),
        },
        "acceptance_contract": {
            "expected_sha256": dispatch["acceptance_contract_sha256"],
            "observed_sha256": observed_acceptance_hash,
            "state": (
                "CURRENT"
                if observed_acceptance_hash == dispatch["acceptance_contract_sha256"]
                else "DRIFTED"
            ),
        },
        "capsule_state": capsule_state,
        "sources": sources,
    }


def _function_slice(source: str, function_name: str, next_name: str) -> str:
    start_marker = f"def {function_name}("
    end_marker = f"def {next_name}("
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0:
        return ""
    return source[start:] if end < 0 else source[start:end]


def build_report(
    root: Path = REPO_ROOT, unit_ids: tuple[str, ...] = DEFAULT_UNITS
) -> dict[str, Any]:
    dispatches = [verify_dispatch(root, unit_id) for unit_id in unit_ids]
    control_source = (root / CONTROL_PLANE_PATH).read_text(encoding="utf-8")
    emitter_source = (root / RESULT_EMITTER_PATH).read_text(encoding="utf-8")
    ingest_source = _function_slice(control_source, "ingest_result", "cmd_ingest")
    source_rows = [source for dispatch in dispatches for source in dispatch["sources"]]
    unique_drift = {
        (row["path"], row["expected_sha256"], row["observed_sha256"])
        for row in source_rows
        if row["state"] == "DRIFTED"
    }
    unique_missing = {
        (row["path"], row["expected_sha256"])
        for row in source_rows
        if row["state"] == "MISSING"
    }
    aggregate_state = (
        "MISSING"
        if unique_missing
        else "DRIFTED"
        if unique_drift
        else "CURRENT"
    )
    return {
        "artifact_id": "PO03-A9-SOURCE-CAPSULE-CLOSURE-v001",
        "unit_id": "a9-u03",
        "opportunity": {
            "name": "worker-side source-capsule closure gate",
            "discovery": "The commission freezes source hashes, but no named Wave A unit or current result path re-hashes those source bytes before a worker emits a valid committed result.",
            "implemented_effect": "This read-only preflight distinguishes an intact dispatch document from CURRENT, DRIFTED or MISSING source bytes without rewriting immutable dispatch evidence.",
            "inside_allowlist": True,
            "proposal_only": False,
        },
        "current_mechanism_probe": {
            "control_plane_path": CONTROL_PLANE_PATH,
            "control_plane_sha256": sha256_file(root / CONTROL_PLANE_PATH),
            "result_emitter_path": RESULT_EMITTER_PATH,
            "result_emitter_sha256": sha256_file(root / RESULT_EMITTER_PATH),
            "ingest_compares_dispatch_manifest_reference": (
                'result_doc["immutable_input_manifest_sha256"]'
                in ingest_source
                and 'dispatch["immutable_input_manifest_sha256"]' in ingest_source
            ),
            "ingest_rehashes_dispatch_sources": "source_hashes" in ingest_source,
            "result_emitter_rehashes_dispatch_sources": "source_hashes" in emitter_source,
        },
        "aggregate_state": aggregate_state,
        "summary": {
            "dispatches_checked": len(dispatches),
            "source_references_checked": len(source_rows),
            "drifted_source_references": sum(
                row["state"] == "DRIFTED" for row in source_rows
            ),
            "missing_source_references": sum(
                row["state"] == "MISSING" for row in source_rows
            ),
            "unique_drifted_paths": sorted(row[0] for row in unique_drift),
            "unique_missing_paths": sorted(row[0] for row in unique_missing),
            "intact_dispatch_manifests": sum(
                row["immutable_manifest"]["state"] == "CURRENT" for row in dispatches
            ),
            "intact_acceptance_contracts": sum(
                row["acceptance_contract"]["state"] == "CURRENT" for row in dispatches
            ),
        },
        "dispatches": dispatches,
        "operating_disposition": {
            "state": "IMPLEMENTED_AND_TESTED",
            "active_wave_effect": "REPORT_ONLY_NO_RESTART_NO_DISPATCH_REWRITE",
            "strict_mode": "returns exit code 3 when any source is DRIFTED or MISSING",
        },
        "strategy_restarted": False,
        "decision_changed": [],
    }


def strict_exit_code(report: dict[str, Any]) -> int:
    return 0 if report["aggregate_state"] == "CURRENT" else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--unit", action="append", dest="units")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workstreams/po03/strategy/source-capsule-report.json"),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    unit_ids = tuple(args.units) if args.units else DEFAULT_UNITS
    report = build_report(root, unit_ids)
    output = args.output if args.output.is_absolute() else root / args.output
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"WROTE {output.relative_to(root)} units={report['summary']['dispatches_checked']} "
        f"state={report['aggregate_state']} "
        f"drift={report['summary']['drifted_source_references']} "
        f"missing={report['summary']['missing_source_references']} decision_changed=[]"
    )
    return strict_exit_code(report) if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
