#!/usr/bin/env python3
"""Compile exact immutable provenance for repository sources read by WA-009."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


BASE_COMMIT = "affc82b35e6205010fda90f9914a97e467294a44"
REPOSITORY = "asibrahim336-hash/obzio-ai-coordination-temp"

SOURCES: tuple[tuple[str, str, str], ...] = (
    ("AGENTS.md", "governing-route", "Repository-wide operating constraints."),
    ("operations/README.md", "governing-route", "Current operator entry point."),
    (
        "state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md",
        "governing-route",
        "First governing source in the active instruction stack.",
    ),
    (
        "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
        "governing-route",
        "Current programme pointer and continuing execution state.",
    ),
    (
        "state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md",
        "governing-route",
        "Function-over-runtime and continuity correction.",
    ),
    (
        "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json",
        "governing-route",
        "Current durable function, appointment, commission and authority IDs.",
    ),
    (
        "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
        "governing-route",
        "Canonical active instruction resolution order.",
    ),
    (
        "instructions/functions/strategic-operations-orchestration/CURRENT.md",
        "governing-route",
        "Current function mandate, permission and boundaries.",
    ),
    (
        "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl",
        "governing-route",
        "Active authority envelope and explicit boundaries.",
    ),
    (
        "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl",
        "governing-route",
        "Active appointment and historical alias disposition.",
    ),
    (
        "state/operator-system/COMMISSION_REGISTER.jsonl",
        "governing-route",
        "Continuing full-scale commission routing.",
    ),
    (
        "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl",
        "governing-route",
        "Replaceable runtime binding with no authority effect.",
    ),
    (
        "dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md",
        "governing-route",
        "Current additive correction in the instruction stack.",
    ),
    (
        "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md",
        "governing-route",
        "Current versus superseded instruction treatment.",
    ),
    (
        "templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md",
        "governing-route",
        "Cold-start routing and currentness pass conditions.",
    ),
    (
        "workstreams/po03/COMMISSION.md",
        "frozen-task-control",
        "PO-03 collision boundary and substantive execution contract.",
    ),
    (
        "workstreams/po03/control/inputs/wave-a/wa-009-a02.json",
        "frozen-task-control",
        "Exact A02 hypothesis, ownership, model request and fence token 2.",
    ),
    (
        "workstreams/po03/control/acceptance/wave-a-material-v1.json",
        "frozen-task-control",
        "Producer-neutral Wave A acceptance criteria.",
    ),
    (
        "workstreams/po03/contracts/transactional-result.schema.json",
        "seeded-control",
        "Transactional result wire contract.",
    ),
    (
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "seeded-control",
        "Wave compounding wire contract.",
    ),
    (
        "workstreams/po03/tools/validate_contracts.py",
        "seeded-control",
        "Dependency-free seeded contract validator.",
    ),
    (
        "workstreams/po03/tests/test_validate_contracts.py",
        "seeded-control",
        "Seeded adversarial contract tests.",
    ),
    (
        "workstreams/po03/control/reviews/wave-a/wa-009-a02-provenance-supersession.json",
        "attempt-provenance",
        "A01 fencing and corrected A02 protocol ancestry.",
    ),
    (
        "workstreams/po03/control/results/wave-a/wa-009.json",
        "attempt-provenance",
        "Controller-reserved A02 transactional result.",
    ),
    (
        "workstreams/po03/control/inputs/wave-a/wa-009.json",
        "attempt-provenance",
        "Fenced A01 input retained only as superseded evidence.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-012/compile_source_capsule.py",
        "non-governing-example",
        "Prior bounded-source provenance implementation examined as a pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-012/source-capsule.json",
        "non-governing-example",
        "Prior source-capsule evidence envelope examined as a pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-012/artifact-manifest.json",
        "non-governing-example",
        "Prior non-recursive artifact accounting pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-012/ready-to-commit.json",
        "non-governing-example",
        "Prior producer return envelope pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-002/result/artifact-manifest.json",
        "non-governing-example",
        "Prior artifact hash-closure pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-002/result/ready-to-commit.json",
        "non-governing-example",
        "Prior result/return commit separation pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-025/result/artifact-manifest.json",
        "non-governing-example",
        "Prior immutable-readback manifest pattern.",
    ),
    (
        "workstreams/po03/wave-a/units/wa-025/result/ready-to-commit.json",
        "non-governing-example",
        "Prior transactional producer return pattern.",
    ),
)


def _git(repo: Path, *arguments: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout.strip() if text else completed.stdout


def compile_claims(repo: Path) -> dict[str, Any]:
    if _git(repo, "rev-parse", f"{BASE_COMMIT}^{{commit}}") != BASE_COMMIT:
        raise RuntimeError("immutable controller base is unavailable")
    claims: list[dict[str, Any]] = []
    for path, category, use in SOURCES:
        content = _git(repo, "show", f"{BASE_COMMIT}:{path}", text=False)
        assert isinstance(content, bytes)
        blob = _git(repo, "rev-parse", f"{BASE_COMMIT}:{path}")
        assert isinstance(blob, str)
        claims.append(
            {
                "bytes": len(content),
                "category": category,
                "git_blob_sha1": blob,
                "immutable_url": (
                    f"https://github.com/{REPOSITORY}/blob/{BASE_COMMIT}/{path}"
                ),
                "path": path,
                "read_commit": BASE_COMMIT,
                "sha256": hashlib.sha256(content).hexdigest(),
                "use": use,
            }
        )
    return {
        "decision_changed": [],
        "exclusions": [
            {
                "disposition": "NOT_READ_NOT_REQUIRED_FOR_HYPOTHESIS",
                "scope": "v010 immutable payload, command and manifest bytes",
                "reason": (
                    "Current routing and hash-pinned execution state were resolved "
                    "without admitting the large launch payload into this task capsule."
                ),
            },
            {
                "disposition": "PROHIBITED_AND_UNTOUCHED",
                "scope": "PO-01, PR #8, secrets, deployment and external effects",
                "reason": "Explicit immutable task boundary.",
            },
            {
                "disposition": "NOT_SUPPORTED",
                "scope": "external method sources",
                "reason": (
                    "No external method claim was required or retrieved; the unit "
                    "tests a repository-native engineering hypothesis."
                ),
            },
        ],
        "protocol_version": "OBZIO-SOURCE-CLAIMS-v1",
        "repository": f"github.com/{REPOSITORY}",
        "separation": {
            "hypothesis": "result/hypothesis.json",
            "mechanism_change": "result/mechanism-change.json",
            "reproduction": "result/reproduction.json",
            "strategy_proposals": "result/strategy-proposals.json",
        },
        "source_claim_count": len(claims),
        "sources_read": claims,
        "task_id": "PO03-WA-009",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    claims = compile_claims(args.repo.resolve())
    payload = json.dumps(claims, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
