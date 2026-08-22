#!/usr/bin/env python3
"""Compile the exact bounded source capsule read for PO03-WA-012."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


READ_COMMIT = "e56eda6e8e4a4e958795f7157839926d93272b30"
REPOSITORY = "asibrahim336-hash/obzio-ai-coordination-temp"

SOURCES: tuple[tuple[str, str, str | None], ...] = (
    ("operations/README.md", "operator-route", None),
    ("state/ACTIVE_CONTROL_POINTER_CURRENT.json", "operator-route", None),
    (
        "state/FOUNDER_INTENT_CORRECTION_OPERATOR_FUNCTION_TAXONOMY_AND_INSTRUCTION_CONTINUITY_20260819_v001.md",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
        "operator-route",
        None,
    ),
    (
        "instructions/functions/strategic-operations-orchestration/CURRENT.md",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl",
        "operator-route",
        None,
    ),
    (
        "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md",
        "operator-route",
        None,
    ),
    ("templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md", "operator-route", None),
    (
        "state/FOUNDER_CORRECTION_V00X_PHASE_ONE_FULL_SCALE_CHATGPT_OPERATION_20260819_v001.md",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/OPERATOR_APPOINTMENT_REGISTER.jsonl",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/COMMISSION_REGISTER.jsonl",
        "operator-route",
        None,
    ),
    (
        "state/operator-system/RUNTIME_BINDING_REGISTER.jsonl",
        "operator-route",
        None,
    ),
    (
        "dispatch/WORK_THREAD_LAUNCH_CORRECTION_SW_GOOGLE_BOUNDARY_AND_PARALLEL_MODEL_RESEARCH_20260819_v001.md",
        "operator-route",
        None,
    ),
    (
        "state/ACTIVE_CONTROL_POINTER_20260819_02.json",
        "operator-route",
        None,
    ),
    (
        "workstreams/po03/control/inputs/wave-a/wa-012.json",
        "immutable-task-input",
        "be5b7e87e9284b5960468b65f7bdde4192763972231e28afb772f17a98e41fe3",
    ),
    (
        "workstreams/po03/control/acceptance/wave-a-material-v1.json",
        "frozen-acceptance-contract",
        "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
    ),
    (
        "workstreams/po03/COMMISSION.md",
        "commission",
        "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
    ),
    (
        "workstreams/po03/contracts/transactional-result.schema.json",
        "seeded-contract",
        "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
    ),
    (
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "seeded-contract",
        "5278cb6bc4e7f41a5d513d4a00427a1ed199a21459025c7fa96fb97d56439360",
    ),
    (
        "workstreams/po03/tools/validate_contracts.py",
        "seeded-validator",
        "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
    ),
    (
        "workstreams/po03/tests/test_validate_contracts.py",
        "seeded-tests",
        "401a684c0a2d3817d08a76044a331f0f241b16d687d2dd12d9ea0f31612dc112",
    ),
    (
        ".github/workflows/po03-contracts.yml",
        "seeded-workflow",
        "427949c07d93fe69bea6485a91ca58c4297be21759e6b0b00a0e5cc9f450c7cb",
    ),
    (
        "workstreams/po03/control/wave-a-portfolio.json",
        "portfolio",
        "515cf2325bda326471140aa1a294696f02c6c10effc3bae9022d55934c063ebd",
    ),
    (
        "workstreams/po03/tools/prepare_wave_a.py",
        "input-provenance-generator",
        None,
    ),
)


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=text,
    )
    if text:
        return completed.stdout.strip()
    return completed.stdout


def compile_capsule(repo: Path) -> dict[str, Any]:
    resolved = []
    for path, purpose, expected_sha256 in SOURCES:
        data = _git(repo, "show", f"{READ_COMMIT}:{path}", text=False)
        assert isinstance(data, bytes)
        digest = hashlib.sha256(data).hexdigest()
        blob = _git(repo, "rev-parse", f"{READ_COMMIT}:{path}")
        last_change = _git(
            repo,
            "log",
            "-1",
            "--format=%H",
            READ_COMMIT,
            "--",
            path,
        )
        resolved.append(
            {
                "path": path,
                "purpose": purpose,
                "read_commit": READ_COMMIT,
                "last_change_commit": last_change,
                "git_blob_sha1": blob,
                "sha256": digest,
                "bytes": len(data),
                "expected_sha256": expected_sha256,
                "pin_result": (
                    "NOT_APPLICABLE"
                    if expected_sha256 is None
                    else "PASS"
                    if expected_sha256 == digest
                    else "FAIL"
                ),
                "immutable_url": (
                    f"https://github.com/{REPOSITORY}/blob/{READ_COMMIT}/{path}"
                ),
            }
        )
    return {
        "protocol_version": "OBZIO-BOUNDED-SOURCE-CAPSULE-v1",
        "task_id": "PO03-WA-012",
        "repository": f"github.com/{REPOSITORY}",
        "read_commit": READ_COMMIT,
        "source_count": len(resolved),
        "all_declared_pins_match": all(
            item["pin_result"] in {"PASS", "NOT_APPLICABLE"} for item in resolved
        ),
        "sources": resolved,
        "runtime_observation": {
            "source": "cursor-cloud/run-info",
            "runner_id": "bc-b1956656-b897-4889-aeab-82c4556c1a9f",
            "model_observed": "gpt-5.6-sol-max-fast",
            "reasoning_observed": "NOT_SUPPORTED",
            "boundary": (
                "The provider exposed originalModelName but no separate "
                "machine-readable reasoning-level observation."
            ),
        },
        "external_method_sources": {
            "status": "NOT_SUPPORTED",
            "boundary": (
                "The immutable input supplied repository-native frozen sources "
                "but no external method locator. No external claim is inferred."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    capsule = compile_capsule(args.repo.resolve())
    payload = json.dumps(capsule, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if capsule["all_declared_pins_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
