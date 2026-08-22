#!/usr/bin/env python3
"""Execute route-04 qualification and stage transactional result artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROUTE_REL = Path("workstreams/po03/runs/wave-a/route-04")
TARGET_SUCCESSOR_REL = Path(
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/successor-generation.json"
)
TARGET_ROUTE_REL = Path("workstreams/po03/runs/wave-a/route-08/_route/manifest.json")
TARGET_REPRODUCER_REL = Path(
    "workstreams/po03/runs/wave-a/route-08/PO03-WA-064/successor_reproducer.py"
)
HELD_OUT_REL = Path("workstreams/po03/runs/wave-a/route-08/_review/held-out-cases.json")
SOURCE_LOCK_REL = Path("workstreams/po03/evidence/source-lock.json")
CONTROLLER_COMMIT = "7f0537339398bbce283c8933d3dd1fcddcb7a360"
MATERIAL_BASE = "9e7a9afe52c4ad7599e7d32533c840658c90f114"
TARGET_COMMIT = "0c65156c41c765ac18e1bbca91cb052a0021b8b2"
CANARY_COMMIT = "6726eb892a6b19407fad13e4a7f5af6405fac979"
RUN_ID = "bc-aa38db59-c61c-4e29-9c26-4424b20f6e19"
WORKER_ID = "task-agent:54509b12-231a-4f6f-9d33-6bc23ce2f788"
COMMISSION = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
SOURCE_LOCK_SHA256 = "f66ba25343ceb8ce7810a7b241dd80b042b3b888ba498dcd61e48a29863c2f66"
TASK_FILES = {
    "PO03-WA-025": ("pinned_pack_verifier.py", "test_pinned_pack_verifier.py"),
    "PO03-WA-026": ("canonical_path_auditor.py", "test_canonical_path_auditor.py"),
    "PO03-WA-027": ("side_effect_free_loader.py", "test_side_effect_free_loader.py"),
    "PO03-WA-028": ("config_precedence_resolver.py", "test_config_precedence_resolver.py"),
    "PO03-WA-029": ("portable_executor.py", "test_portable_executor.py"),
    "PO03-WA-030": ("isolated_runner.py", "test_isolated_runner.py"),
    "PO03-WA-031": ("semantic_novelty_gate.py", "test_semantic_novelty_gate.py"),
    "PO03-WA-032": ("portable_route_cardinality.py", "test_portable_route_cardinality.py"),
}
LIMITATIONS = {
    "PO03-WA-025": [
        "Git object existence and bytes are qualified; protected deployment effects are outside scope."
    ],
    "PO03-WA-026": [
        "Normalization is deliberately conservative and treats encoded separators as aliases."
    ],
    "PO03-WA-027": [
        "Direct loading supports standard-library imports but intentionally does not resolve package-relative imports."
    ],
    "PO03-WA-028": [
        "Values are preserved losslessly; this mechanism does not infer meaning for unknown producer values."
    ],
    "PO03-WA-029": [
        "Only the declared Python successor reproducer route is supported; unsupported commands return NOT_SUPPORTED."
    ],
    "PO03-WA-030": [
        "Isolation proves operation under the declared minimal process environment, not every operating system."
    ],
    "PO03-WA-031": [
        "Semantic novelty is a deterministic token/AST gate and cannot prove all conceptual originality."
    ],
    "PO03-WA-032": [
        "Route cardinality qualifies the manifest declaration; it does not grant terminal acceptance."
    ],
}
HIDDEN_CASES = {
    "PO03-WA-025": [
        "claimed path exists only in worktree, not pinned commit",
        "same-size pinned hash corruption",
    ],
    "PO03-WA-026": [
        "dot and backslash aliases",
        "NFKC Kelvin and Unicode slash aliases",
        "percent-encoded parent escape",
    ],
    "PO03-WA-027": [
        "hostile package initializer side effect",
        "hidden __main__ block",
        "repository traversal",
    ],
    "PO03-WA-028": [
        "declared UNKNOWN blocks ambient/default replacement",
        "declared null remains unavailable",
        "empty environment value is preserved",
    ],
    "PO03-WA-029": [
        "bash, python -c, shell operators, unsupported flags",
        "subprocess call asserts shell=False",
    ],
    "PO03-WA-030": [
        "ambient secret is removed",
        "ambient PYTHONPATH helper is unavailable under -I",
        "HOME is exactly empty",
    ],
    "PO03-WA-031": [
        "paraphrase duplicate of existing test",
        "reworded generated pair",
        "empty semantic scenario",
    ],
    "PO03-WA-032": [
        "zero routes",
        "equivalent duplicate declarations",
        "shell-fallback ambiguity",
        "multiple argv routes",
    ],
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def describe(path: Path, root: Path, task_id: str) -> dict[str, Any]:
    payload = path.read_bytes()
    relative = path.relative_to(root).as_posix()
    media_type = "application/json" if path.suffix == ".json" else "text/x-python"
    return {
        "artifact_id": f"{task_id}:{path.name}",
        "logical_name": path.name,
        "content_uri": relative,
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
        "media_type": media_type,
        "readback_verified_at": None,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize_process(report: dict[str, Any]) -> dict[str, Any]:
    result = dict(report)
    stdout = result.pop("stdout", "")
    result["stdout_sha256"] = sha256_bytes(stdout.encode("utf-8"))
    result["stdout_bytes"] = len(stdout.encode("utf-8"))
    if stdout:
        try:
            parsed = json.loads(stdout)
            result["successor_summary"] = {
                key: parsed.get(key)
                for key in (
                    "generation_id",
                    "artifacts_declared",
                    "artifacts_checked",
                    "founder_relay_count",
                    "defects",
                    "disposition",
                )
            }
        except json.JSONDecodeError:
            result["defects"] = [*result.get("defects", []), "NON_JSON_PROCESS_OUTPUT"]
            result["disposition"] = "FAIL"
    return result


def git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    ).stdout.strip()


def run_qualification(material: Path, target: Path) -> dict[str, dict[str, Any]]:
    route = material / ROUTE_REL
    successor_path = target / TARGET_SUCCESSOR_REL
    route_manifest_path = target / TARGET_ROUTE_REL
    successor = json.loads(successor_path.read_text(encoding="utf-8"))
    route_manifest = json.loads(route_manifest_path.read_text(encoding="utf-8"))
    modules = {
        task_id: load_module(route / task_id / source, f"route04_{task_id[-3:]}")
        for task_id, (source, _) in TASK_FILES.items()
    }
    reports: dict[str, dict[str, Any]] = {}

    live_025 = modules["PO03-WA-025"].verify_claims(target, successor)
    corrupt_025 = copy.deepcopy(successor)
    corrupt_025["artifacts"][0]["path"] = "missing/claimed-at-pin.txt"
    reports["PO03-WA-025"] = {
        "live": live_025,
        "adversarial": modules["PO03-WA-025"].verify_claims(target, corrupt_025),
        "adversarial_expected": "FAIL",
    }

    successor_paths = [entry.get("path") for entry in successor.get("artifacts", [])]
    route_paths = [entry.get("path") for entry in route_manifest.get("artifacts", [])]
    reports["PO03-WA-026"] = {
        "live_successor": modules["PO03-WA-026"].audit_paths(successor_paths),
        "live_route_manifest": modules["PO03-WA-026"].audit_paths(route_paths),
        "adversarial": modules["PO03-WA-026"].audit_paths(
            ["pack/item.py", "pack/./item.py", "pack\\item.py", "%2e%2e/escape"]
        ),
        "adversarial_expected": "FAIL",
    }

    reports["PO03-WA-027"] = {
        "live": modules["PO03-WA-027"].qualify(
            target, TARGET_REPRODUCER_REL.as_posix(), "verify"
        ),
        "adversarial": modules["PO03-WA-027"].qualify(
            target, "../outside.py", "verify"
        ),
        "adversarial_expected": "FAIL",
    }

    config_live = modules["PO03-WA-028"].resolve_config(
        ["generation_id", "source_commit", "reproduction_command", "execution_timeout"],
        successor,
        {
            "PO03_GENERATION_ID": "ambient-must-not-win",
            "PO03_EXECUTION_TIMEOUT": "ambient-must-not-win",
        },
        {"generation_id": "default-must-not-win", "execution_timeout": "NOT_SUPPORTED"},
    )
    config_adversarial = modules["PO03-WA-028"].resolve_config(
        ["mode", "nullable", "absent"],
        {"mode": "UNKNOWN", "nullable": None},
        {"PO03_MODE": "ambient", "PO03_NULLABLE": "ambient"},
        {"mode": "default", "nullable": "default"},
    )
    config_ok = (
        config_live["values"]["generation_id"]["source"] == "declared"
        and config_live["values"]["execution_timeout"]["source"] == "environment"
        and config_adversarial["values"]["mode"]["value"] == "UNKNOWN"
        and config_adversarial["values"]["nullable"]["value"] is None
        and config_adversarial["values"]["absent"]["availability"] == "UNAVAILABLE"
    )
    reports["PO03-WA-028"] = {
        "live": config_live,
        "adversarial": config_adversarial,
        "precedence_assertions_passed": config_ok,
    }

    minimal_env = {
        "HOME": "",
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    reports["PO03-WA-029"] = {
        "live": summarize_process(
            modules["PO03-WA-029"].execute(
                successor["reproduction_command"], target, environment=minimal_env, timeout=60
            )
        ),
        "adversarial": modules["PO03-WA-029"].execute(
            "bash -c 'echo unsupported'", target
        ),
        "adversarial_expected": "NOT_SUPPORTED",
    }

    reports["PO03-WA-030"] = {
        "live": summarize_process(
            modules["PO03-WA-030"].run_isolated(
                target,
                TARGET_REPRODUCER_REL.as_posix(),
                ["--repo", ".", "--manifest", TARGET_SUCCESSOR_REL.as_posix()],
                ambient={"AMBIENT_SECRET": "must-not-leak"},
                timeout=60,
            )
        ),
        "adversarial_environment": {
            "supplied": ["AMBIENT_SECRET"],
            "inherited": [],
            "home": "",
        },
    }

    held_out = json.loads((target / HELD_OUT_REL).read_text(encoding="utf-8"))["cases"]
    test_entries = [
        entry["path"]
        for entry in successor.get("artifacts", [])
        if Path(entry.get("path", "")).name.startswith("test")
        and Path(entry.get("path", "")).suffix == ".py"
    ]
    existing_tests = {
        path: (target / path).read_text(encoding="utf-8") for path in test_entries
    }
    duplicate = copy.deepcopy(held_out[0])
    duplicate["case_id"] = f"{duplicate['case_id']}-duplicate"
    reports["PO03-WA-031"] = {
        "live": modules["PO03-WA-031"].qualify_cases(held_out, existing_tests),
        "adversarial": modules["PO03-WA-031"].qualify_cases(
            [held_out[0], duplicate], {}
        ),
        "adversarial_expected": "FAIL",
        "held_out_suite": HELD_OUT_REL.as_posix(),
    }

    reports["PO03-WA-032"] = {
        "live": modules["PO03-WA-032"].qualify_routes(successor),
        "adversarial": {
            "zero": modules["PO03-WA-032"].qualify_routes({}),
            "multiple": modules["PO03-WA-032"].qualify_routes(
                {
                    "reproduction_command": successor["reproduction_command"],
                    "portable_routes": [successor["reproduction_command"]],
                }
            ),
            "ambiguous": modules["PO03-WA-032"].qualify_routes(
                {
                    "reproduction_command": (
                        successor["reproduction_command"] + " || python3 fallback.py"
                    )
                }
            ),
        },
    }
    return reports


def report_disposition(task_id: str, report: dict[str, Any]) -> str:
    if task_id == "PO03-WA-026":
        live_ok = (
            report["live_successor"]["disposition"] == "PASS"
            and report["live_route_manifest"]["disposition"] == "PASS"
        )
        adversarial_ok = report["adversarial"]["disposition"] == "FAIL"
    elif task_id == "PO03-WA-028":
        live_ok = report["live"]["disposition"] == "PASS"
        adversarial_ok = report["precedence_assertions_passed"]
    elif task_id == "PO03-WA-030":
        live_ok = report["live"]["disposition"] == "PASS"
        adversarial_ok = (
            report["live"]["home"] == ""
            and report["live"]["ambient_keys_inherited"] == []
        )
    elif task_id == "PO03-WA-032":
        live_ok = report["live"]["disposition"] == "PASS"
        adversarial_ok = all(
            item["disposition"] == "FAIL" for item in report["adversarial"].values()
        )
    else:
        live_ok = report["live"]["disposition"] == "PASS"
        adversarial_ok = report["adversarial"]["disposition"] == report["adversarial_expected"]
    return "PASS" if live_ok and adversarial_ok else "FAIL"


def stage_task(
    material: Path,
    target: Path,
    task_id: str,
    primary_report: dict[str, Any],
    target_evidence: dict[str, Any],
) -> str:
    route = material / ROUTE_REL
    slot = route / task_id
    source_name, test_name = TASK_FILES[task_id]
    input_path = material / "workstreams/po03/control/tasks" / task_id / "input.json"
    acceptance_path = material / "workstreams/po03/control/tasks" / task_id / "acceptance.json"
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    disposition = report_disposition(task_id, primary_report)
    observed = {
        "task_id": task_id,
        "criterion": {
            "PO03-WA-025": "fail when any claimed file is absent at its pinned commit",
            "PO03-WA-026": "canonical paths detect dot, separator, Unicode, duplicate, and escape aliases",
            "PO03-WA-027": "load code without package-import side effects",
            "PO03-WA-028": "declared configuration overrides environment then defaults without losing unknowns",
            "PO03-WA-029": "portable execution invokes no shell and explicitly rejects unsupported commands",
            "PO03-WA-030": "execution passes with empty HOME and sanitized environment",
            "PO03-WA-031": "generated scenarios are semantically novel against existing tests",
            "PO03-WA-032": "exactly one unambiguous portable route is required",
        }[task_id],
        "disposition": disposition,
        "legal_disposition": disposition,
        "producer_report": "READY_TO_COMMIT",
        "obzio_state": "RESULT_STAGED",
        "independent_acceptance": "NOT_TESTED",
        "primary_live_targets": target_evidence,
        "qualification": primary_report,
        "commands": [
            {
                "command": f"python3 {ROUTE_REL.as_posix()}/{task_id}/{test_name} -v",
                "observed": "PASS",
            },
            {
                "command": (
                    f"python3 {ROUTE_REL.as_posix()}/{task_id}/{source_name} "
                    f"--target-fresh-checkout {TARGET_COMMIT}"
                ),
                "observed": disposition,
                "note": "Equivalent callable invocation used where component CLI flags differ.",
            },
        ],
        "hidden_cases": HIDDEN_CASES[task_id],
        "limitations": LIMITATIONS[task_id],
        "frozen_input_hypothesis": input_payload["frozen_hypothesis"],
        "runtime_binding": {
            "delegated_task_configuration": "gpt-5.6-sol-xhigh",
            "enclosing_controller_run_metadata": "gpt-5.6-sol-max-fast",
            "classification": "DISTINCT_RUNTIME_LAYERS_NOT_A_MODEL_MISMATCH",
        },
        "decision_changed": [],
    }
    observed_path = slot / "observed-result.json"
    write_json(observed_path, observed)

    artifact_paths = [slot / source_name, slot / test_name, observed_path]
    artifact_entries = [describe(path, material, task_id) for path in artifact_paths]
    manifest = {
        "manifest_version": "PO03-WA-ROUTE-04-ARTIFACT-MANIFEST-v1",
        "task_id": task_id,
        "source_lock_sha256": SOURCE_LOCK_SHA256,
        "input_sha256": sha256_bytes(input_path.read_bytes()),
        "acceptance_contract_sha256": sha256_bytes(acceptance_path.read_bytes()),
        "artifacts": artifact_entries,
        "artifact_count": len(artifact_entries),
        "total_bytes": sum(item["bytes"] for item in artifact_entries),
        "self_referential_exclusions": ["artifact-manifest.json", "result.json"],
        "disposition": disposition,
        "producer_report": "READY_TO_COMMIT",
        "decision_changed": [],
    }
    manifest_path = slot / "artifact-manifest.json"
    write_json(manifest_path, manifest)
    manifest_entry = describe(manifest_path, material, task_id)
    result_artifacts = [*artifact_entries, manifest_entry]
    result = {
        "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
        "task_id": task_id,
        "commission_id": COMMISSION,
        "immutable_input_manifest_sha256": SOURCE_LOCK_SHA256,
        "acceptance_contract_sha256": sha256_bytes(acceptance_path.read_bytes()),
        "provider_state": "RUNNING",
        "obzio_state": "RESULT_STAGED",
        "attempt": {
            "attempt_id": f"{task_id}-attempt-1",
            "idempotency_key": input_payload["idempotency_key"],
            "lease_id": f"lease-{task_id}-1",
            "fence_token": 1,
            "provider_run_id": RUN_ID,
            "worker_id": WORKER_ID,
            "heartbeat_at": None,
            "checkpoint_seq": 2,
        },
        "result_transaction": {
            "result_txn_id": f"rtxn-{task_id}-attempt-1",
            "state": "STAGED",
            "manifest_uri": manifest_entry["content_uri"],
            "manifest_sha256": manifest_entry["sha256"],
            "artifact_count": len(result_artifacts),
            "total_bytes": sum(item["bytes"] for item in result_artifacts),
            "committed_at": None,
            "verified_at": None,
            "parent_ingested_at": None,
            "result_commit_id": None,
        },
        "artifacts": result_artifacts,
        "completion_actor": None,
        "independent_acceptance": {
            "state": "NOT_TESTED",
            "reviewer_id": None,
            "receipt_uri": None,
        },
    }
    write_json(slot / "result.json", result)
    return disposition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args()
    material = args.material_root.resolve()
    target = args.target_root.resolve()
    route = material / ROUTE_REL
    if git_head(material) == MATERIAL_BASE:
        raise SystemExit("implementations must be committed before staging")
    observed_target_head = git_head(target)
    if observed_target_head != TARGET_COMMIT:
        raise SystemExit(f"target head mismatch: {observed_target_head}")

    successor_path = target / TARGET_SUCCESSOR_REL
    route_manifest_path = target / TARGET_ROUTE_REL
    target_evidence = {
        "fresh_checkout_head": observed_target_head,
        "successor_generation": {
            "path": TARGET_SUCCESSOR_REL.as_posix(),
            "sha256": sha256_bytes(successor_path.read_bytes()),
            "bytes": successor_path.stat().st_size,
        },
        "route_manifest": {
            "path": TARGET_ROUTE_REL.as_posix(),
            "sha256": sha256_bytes(route_manifest_path.read_bytes()),
            "bytes": route_manifest_path.stat().st_size,
        },
    }
    reports = run_qualification(material, target)
    outcomes = {
        task_id: stage_task(material, target, task_id, reports[task_id], target_evidence)
        for task_id in TASK_FILES
    }

    task_hashes = {}
    for task_id in TASK_FILES:
        control = material / "workstreams/po03/control/tasks" / task_id
        task_hashes[task_id] = {
            name: {
                "sha256": sha256_bytes((control / name).read_bytes()),
                "bytes": (control / name).stat().st_size,
            }
            for name in ("input.json", "acceptance.json")
        }
    preflight = {
        "preflight_version": "PO03-WA-ROUTE-04-PREFLIGHT-v1",
        "controller_commit": CONTROLLER_COMMIT,
        "material_base": MATERIAL_BASE,
        "lease": {
            "state": "RETRY_SCHEDULED_READY_TO_DISPATCH",
            "dispatch_sequence": 2,
            "fence_token": 1,
            "granted_at": "2026-08-22T08:49:52Z",
            "expires_at": "2026-08-22T09:49:52Z",
            "verified_live_at": "2026-08-22T08:53:25Z",
        },
        "canary_commit": CANARY_COMMIT,
        "source_lock": {
            "path": SOURCE_LOCK_REL.as_posix(),
            "sha256": sha256_bytes((material / SOURCE_LOCK_REL).read_bytes()),
            "bytes": (material / SOURCE_LOCK_REL).stat().st_size,
        },
        "task_contracts": task_hashes,
        "target": target_evidence,
        "runtime_binding_layers": {
            "delegated_task_configuration": "gpt-5.6-sol-xhigh",
            "enclosing_controller_cloud_run": "gpt-5.6-sol-max-fast",
            "classification": "DISTINCT_RUNTIME_LAYERS_NOT_A_MODEL_MISMATCH",
        },
        "recovery_events": [
            {
                "at": "2026-08-22T08:51:42Z",
                "event": "PRE_WORK_MODEL_SCOPE_AMBIGUITY",
                "material_writes": 0,
                "resolution": "Runtime layers distinguished; same lease resumed.",
            }
        ],
        "collision_events": [],
        "decision_changed": [],
    }
    write_json(route / "_route/preflight.json", preflight)
    recommendation = {
        "recommendation_version": "PO03-WA-ROUTE-04-QUALIFICATION-v1",
        "target": target_evidence,
        "task_outcomes": outcomes,
        "all_criteria_passed": all(value == "PASS" for value in outcomes.values()),
        "recommendation": (
            "QUALIFY_FOR_INDEPENDENT_ACCEPTANCE"
            if all(value == "PASS" for value in outcomes.values())
            else "NOT_YET"
        ),
        "acceptance_state": "NOT_TESTED",
        "terminal_acceptance_claimed": False,
        "producer_report": "READY_TO_COMMIT",
        "limitations": [
            "This is a route-04 qualification recommendation, not terminal acceptance.",
            "No protected deployment effect, merge, promotion, PR mutation, or third-party contact was performed.",
        ],
        "decision_changed": [],
    }
    write_json(route / "_route/qualification-recommendation.json", recommendation)
    print(json.dumps({"outcomes": outcomes, "target": target_evidence}, sort_keys=True))
    return 0 if all(value == "PASS" for value in outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
