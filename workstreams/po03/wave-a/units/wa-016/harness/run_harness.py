#!/usr/bin/env python3
"""Entry point: run the whole harness and write this unit's evidence.

    python -I -m harness.run_harness --write

Writes only inside this unit's owned subtree.  Every number in the emitted
evidence comes from a run performed by this invocation; nothing is transcribed
by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

UNIT_ROOT = Path(__file__).resolve().parents[1]
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

from harness import custody_invariants, fuzz, input_resolvability, reproductions, research  # noqa: E402
from harness import transition_matrix as tm  # noqa: E402
from harness.naive_machine import MUTANTS  # noqa: E402
from harness.durable_io import canonical_json, sha256_bytes  # noqa: E402
from harness.seeded import acceptance_contract, control_digests, repository_root, task_input  # noqa: E402

EVIDENCE_DIR = UNIT_ROOT / "evidence"

FUZZ_CASES = 2000
FUZZ_MAX_FAULTS = 4


def collect(*, fuzz_cases: int = FUZZ_CASES, fuzz_max_faults: int = FUZZ_MAX_FAULTS) -> dict[str, Any]:
    """Run every executable component and return the raw evidence."""
    started = time.time()
    repo = repository_root()
    matrix = tm.run_matrix()
    mutants = [
        {
            "mutant": name,
            "defect": description,
            "summary": {
                k: v
                for k, v in tm.run_matrix(store_cls=cls).items()
                if k not in {"rows", "inapplicable"}
            },
        }
        for name, cls, description in MUTANTS
    ]
    campaign = fuzz.run_campaign(fuzz_cases, max_faults=fuzz_max_faults)
    comparison = fuzz.compare_with_exhaustive(matrix, campaign)
    repro = reproductions.run_all(repo)
    contract, contract_sha = acceptance_contract(repo)
    evidence = {
        "repository_root": str(repo),
        "task_input": task_input(repo),
        "acceptance_contract_sha256": contract_sha,
        "acceptance_contract_assertions": len(contract["required_assertions"]),
        "seeded_controls": [
            {
                "name": d.name,
                "path": d.relative_path,
                "observed_sha256": d.observed_sha256,
                "pinned_sha256": d.pinned_sha256,
                "matches_pin": d.matches_pin,
                "bytes": d.bytes,
            }
            for d in control_digests(repo)
        ],
        "matrix": matrix,
        "mutants": mutants,
        "fuzz_campaign": campaign,
        "fuzz_comparison": comparison,
        "reproductions": repro,
        "validator_gaps": custody_invariants.measure_gaps(),
        "input_resolvability": input_resolvability.check_wave_a(repo),
        "wall_time_seconds": round(time.time() - started, 3),
    }
    evidence["hypotheses"] = research.evaluate(evidence)
    evidence["mechanism_changes"] = research.resolve_mechanisms(evidence)
    return evidence


def _write(path: Path, payload: Any) -> dict[str, Any]:
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(UNIT_ROOT)), "sha256": sha256_bytes(data), "bytes": len(data)}


def write_evidence(evidence: dict[str, Any], target: Path | None = None) -> list[dict[str, Any]]:
    """Write the evidence files this unit owns.

    ``target`` exists so the write-containment test can exercise this function
    without overwriting the evidence of the full campaign that result.json
    reports.
    """
    directory = target or EVIDENCE_DIR
    written = [
        _write(directory / "transition-matrix.json", evidence["matrix"]),
        _write(
            directory / "fault-matrix-summary.json",
            {
                "machine": evidence["matrix"]["machine"],
                "cell_count": evidence["matrix"]["cell_count"],
                "transitions_covered": evidence["matrix"]["transitions_covered"],
                "fault_kinds_covered": evidence["matrix"]["fault_kinds_covered"],
                "cells_with_violations": evidence["matrix"]["cells_with_violations"],
                "false_completions": evidence["matrix"]["false_completions"],
                "rows_digest": evidence["matrix"]["rows_digest"],
                "final_state_histogram": {
                    state: sum(1 for r in evidence["matrix"]["rows"] if r["final_obzio_state"] == state)
                    for state in sorted({r["final_obzio_state"] for r in evidence["matrix"]["rows"]})
                },
                "inapplicable_cell_count": len(evidence["matrix"]["inapplicable"]),
                "harness_wall_time_seconds": evidence["wall_time_seconds"],
                "mutants": evidence["mutants"],
                "fuzz_campaign": {k: v for k, v in evidence["fuzz_campaign"].items() if k != "failing_cases"},
                "fuzz_comparison": evidence["fuzz_comparison"],
            },
        ),
        _write(directory / "reproduction-ledger.json", evidence["reproductions"]),
        _write(
            directory / "source-claims.json",
            {
                "retrieved_at": research.RETRIEVED_AT,
                "retrieval_method": research.RETRIEVAL_METHOD,
                "external": list(research.EXTERNAL_SOURCE_CLAIMS),
                "repository": list(research.REPOSITORY_SOURCE_CLAIMS),
                "seeded_controls_observed": evidence["seeded_controls"],
            },
        ),
        _write(directory / "hypotheses.json", evidence["hypotheses"]),
        _write(directory / "mechanism-changes.json", evidence["mechanism_changes"]),
        _write(directory / "validator-gap-analysis.json", evidence["validator_gaps"]),
        _write(directory / "frozen-input-resolvability.json", evidence["input_resolvability"]),
    ]
    return written


def summarise(evidence: dict[str, Any]) -> dict[str, Any]:
    matrix = evidence["matrix"]
    return {
        "matrix_cells": matrix["cell_count"],
        "matrix_violations": matrix["cells_with_violations"],
        "false_completions": matrix["false_completions"],
        "transitions": len(matrix["transitions_covered"]),
        "fault_kinds": len(matrix["fault_kinds_covered"]),
        "mutants_detected": sum(1 for m in evidence["mutants"] if m["summary"]["cells_with_violations"] > 0),
        "fuzz_cases": evidence["fuzz_campaign"]["case_count"],
        "fuzz_safety_violations": evidence["fuzz_campaign"]["cases_with_safety_violations"],
        "reproductions": {r["reproduction_id"]: r["verdict"] for r in evidence["reproductions"]},
        "hypotheses": {h["hypothesis_id"]: h["outcome"] for h in evidence["hypotheses"]},
        "mechanism_dispositions": {m["mechanism_id"]: m["disposition"] for m in evidence["mechanism_changes"]},
        "wall_time_seconds": evidence["wall_time_seconds"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO03-WA-016 transition fault-injection harness")
    parser.add_argument("--write", action="store_true", help="write evidence files into the owned subtree")
    parser.add_argument("--fuzz-cases", type=int, default=FUZZ_CASES)
    parser.add_argument("--fuzz-max-faults", type=int, default=FUZZ_MAX_FAULTS)
    args = parser.parse_args(argv)

    evidence = collect(fuzz_cases=args.fuzz_cases, fuzz_max_faults=args.fuzz_max_faults)
    summary = summarise(evidence)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.write:
        written = write_evidence(evidence)
        print(json.dumps({"evidence_written": written}, indent=2, sort_keys=True))
    failed = (
        evidence["matrix"]["cells_with_violations"] > 0
        or evidence["fuzz_campaign"]["cases_with_safety_violations"] > 0
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
