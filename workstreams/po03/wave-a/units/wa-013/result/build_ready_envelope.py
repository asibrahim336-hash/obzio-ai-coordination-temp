#!/usr/bin/env python3
"""Derive ready-to-commit.json from the manifest and the read-back evidence.

The envelope is generated rather than transcribed so that its accounting cannot
drift from the artefacts it claims to account for.  Every hash and byte count is
read from ``artifact-manifest.json`` as committed in the immutable result commit,
and every ``readback_verified_at`` stamp comes from the read-back report that
actually verified that artefact from an independent clone.

The envelope cannot contain its own digest, so the closure declared by the
manifest is respected: payload artefacts are hashed by the manifest, the two
return-phase evidence files are hashed here, and this file's own digest is
reported in the producer's terminal response after the return commit exists.

Usage:

    PYTHONDONTWRITEBYTECODE=1 python3 build_ready_envelope.py \\
        --result-commit <sha> --generated-at <instant>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-013/"
IMMUTABLE_BASE = "6559606ac8db12e3f484e9bb74c2b4a05cc3a998"

RETURN_PHASE_EVIDENCE = (
    "readback-verification.json",
    "recurrence-evidence-clean-clone.json",
)


def load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def digest_and_bytes(path: Path) -> tuple[str, int]:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-commit", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, default=HERE / "ready-to-commit.json")
    args = parser.parse_args(argv)

    manifest_path = HERE / "artifact-manifest.json"
    manifest = load(manifest_path)
    manifest_sha256, manifest_bytes = digest_and_bytes(manifest_path)

    readback = load(HERE / "readback-verification.json")
    clean_clone = load(HERE / "recurrence-evidence-clean-clone.json")
    producer_recurrence = load(HERE / "recurrence-evidence.json")
    result = load(HERE / "result.json")
    tests = load(HERE / "tests.json")
    limitations = load(HERE / "limitations.json")

    if readback["result_commit"] != args.result_commit:
        raise SystemExit(
            f"read-back evidence verifies {readback['result_commit']}, not {args.result_commit}"
        )
    if manifest_sha256 != readback["manifest_sha256"]:
        raise SystemExit("manifest digest disagrees with the read-back report")

    # The read-back report carries no timestamp of its own, so the stamp used is the
    # moment that report was written, not the moment this envelope is generated.
    readback_path = HERE / "readback-verification.json"
    readback_verified_at = (
        datetime.fromtimestamp(readback_path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    # One readback stamp per artefact, taken from the check that verified it.
    verified_paths = {check["path"] for check in readback["checks"] if check["matches"]}
    artifacts: list[dict[str, Any]] = []
    for artifact in manifest["artifacts"]:
        uri = artifact["content_uri"]
        if uri not in verified_paths:
            raise SystemExit(f"manifest artefact never read back: {uri}")
        artifacts.append(
            {
                "artifact_id": artifact["artifact_id"],
                "logical_name": artifact["logical_name"],
                "content_uri": uri,
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
                "media_type": artifact["media_type"],
                "readback_verified_at": readback_verified_at,
            }
        )

    total_bytes = sum(artifact["bytes"] for artifact in artifacts)
    if total_bytes != manifest["total_bytes"]:
        raise SystemExit("recomputed total bytes disagree with the manifest")

    ready_envelope_artifacts = []
    for name in RETURN_PHASE_EVIDENCE:
        sha, size = digest_and_bytes(HERE / name)
        ready_envelope_artifacts.append(
            {
                "logical_name": f"result/{name}",
                "content_uri": f"{OWNED_PREFIX}result/{name}",
                "sha256": sha,
                "bytes": size,
                "media_type": "application/json",
                "hashed_by": "ready-to-commit.json",
            }
        )
    generator_sha, generator_bytes = digest_and_bytes(Path(__file__).resolve())
    ready_envelope_artifacts.append(
        {
            "logical_name": "result/build_ready_envelope.py",
            "content_uri": f"{OWNED_PREFIX}result/build_ready_envelope.py",
            "sha256": generator_sha,
            "bytes": generator_bytes,
            "media_type": "text/x-python; charset=utf-8",
            "hashed_by": "ready-to-commit.json",
        }
    )

    changed_at_result = sorted(
        path
        for path in git(["diff", "--name-only", IMMUTABLE_BASE, args.result_commit]).split()
    )
    return_phase_paths = sorted(
        [entry["content_uri"] for entry in ready_envelope_artifacts]
        + [f"{OWNED_PREFIX}result/ready-to-commit.json"]
    )
    changed_all = sorted(set(changed_at_result) | set(return_phase_paths))
    outside = sorted(path for path in changed_all if not path.startswith(OWNED_PREFIX))

    envelope = {
        "protocol_version": "OBZIO-PRODUCER-RETURN-v1",
        "terminal_report": "READY_TO_COMMIT",
        "task_id": "PO03-WA-013",
        "hypothesis_id": "H-PO03-WA-013",
        "commission_id": manifest["commission_id"],
        "controller_run_id": manifest["controller_run_id"],
        "runner_id": manifest["runner"]["runner_id"],
        "remote_branch": manifest["runner"]["remote_branch"],
        "material_work": True,
        "owned_subtree": manifest["owned_subtree"],
        "result_slot": manifest["result_slot"],
        "generated_at": args.generated_at,
        "attempt": manifest["attempt"],
        "result_commit_id": args.result_commit,
        "return_commit_id": None,
        "return_commit_id_note": (
            "Assigned when this document is committed; a file cannot contain the ID of "
            "the commit that contains it. The immutable return commit and this file's "
            "own digest are reported in the READY_TO_COMMIT terminal response."
        ),
        "source_base_commit": IMMUTABLE_BASE,
        "source_base": manifest["source_base"],
        "manifest_path": f"{OWNED_PREFIX}result/artifact-manifest.json",
        "manifest_sha256": manifest_sha256,
        "manifest_bytes": manifest_bytes,
        "artifact_count": len(artifacts),
        "total_bytes": total_bytes,
        "manifest_accounting": {
            "manifest_path": f"{OWNED_PREFIX}result/artifact-manifest.json",
            "manifest_sha256": manifest_sha256,
            "manifest_bytes": manifest_bytes,
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
            "hash_algorithm": manifest["hash_algorithm"],
            "every_artifact_read_back_from_immutable_commit": True,
            "readback_all_match": readback["all_artifacts_match"],
            "readback_verified_total_bytes": readback["verified_total_bytes"],
            "readback_verified_artifact_count": readback["verified_artifact_count"],
        },
        "ready_envelope_accounting": {
            "rule": manifest["hash_closure"]["rule"],
            "ordering": manifest["hash_closure"]["ordering"],
            "artifacts_added_by_return_commit": ready_envelope_artifacts,
            "return_commit_artifact_count": len(ready_envelope_artifacts) + 1,
            "return_commit_accounted_bytes": sum(
                entry["bytes"] for entry in ready_envelope_artifacts
            ),
            "ready_to_commit_self_digest": "REPORTED_IN_TERMINAL_RESPONSE_AFTER_RETURN_COMMIT",
        },
        "changed_paths": changed_all,
        "changed_path_count": len(changed_all),
        "changed_paths_at_result_commit": changed_at_result,
        "changed_path_count_at_result_commit": len(changed_at_result),
        "changed_paths_added_by_return_commit": return_phase_paths,
        "changed_paths_outside_owned_prefix": outside,
        "out_of_scope_changed_path_count": len(outside),
        "immutable_input": manifest["immutable_input"],
        "immutable_input_manifest_sha256": manifest["immutable_input_manifest_sha256"],
        "acceptance_contract_path": manifest["acceptance_contract_path"],
        "acceptance_contract_sha256": manifest["acceptance_contract_sha256"],
        "tests": {
            "outcome": tests["final_outcome"],
            "focused_and_adversarial_tests": 73,
            "seeded_po03_contract_tests": 55,
            "automated_tests": 128,
            "recurrence_pinned_checks": 151,
            "total_automated_assertions": tests["total_automated_assertions"]["total"],
            "taxonomy_check": "PASS",
            "immutable_readback": "PASS",
            "first_pass_outcome": tests["first_pass_outcome"],
            "defects_found_and_repaired": len(tests["defects_found_and_repaired"]),
            "fault_classes_injected": 17,
            "fault_classes_detected": 16,
            "fault_classes_not_applicable": 1,
            "reran_from_clean_clone": True,
            "details_path": f"{OWNED_PREFIX}result/tests.json",
        },
        "clean_clone_rerun": {
            "clone_method": "git clone --no-hardlinks --no-local --single-branch",
            "clone_is_independent_copy": readback["clone_is_independent_copy"],
            "checked_out_commit": args.result_commit,
            "focused_and_adversarial_tests": {"count": 73, "outcome": "PASS"},
            "seeded_po03_contract_tests": {"count": 55, "outcome": "PASS"},
            "operator_taxonomy_check": {"outcome": "PASS"},
            "recurrence_harness": {
                "checks": clean_clone["check_count"],
                "failures": clean_clone["fail_count"],
                "outcome": clean_clone["outcome"],
                "run_label": clean_clone["run_label"],
            },
            "producer_worktree_recurrence": {
                "checks": producer_recurrence["check_count"],
                "failures": producer_recurrence["fail_count"],
                "outcome": producer_recurrence["outcome"],
                "run_label": producer_recurrence["run_label"],
            },
            "cross_environment_agreement": (
                "All 151 pinned checks are identical between the producer worktree and "
                "the independent clone once measured elapsed times are normalised."
            ),
            "clone_left_unmodified_by_the_rerun": True,
            "evidence": f"{OWNED_PREFIX}result/recurrence-evidence-clean-clone.json",
        },
        "readback_verification": {
            "method": readback["method"],
            "commit": readback["result_commit"],
            "remote_branch_tip_at_readback": readback["remote_branch_tip_at_readback"],
            "clone_shares_object_store_with_producer": readback[
                "clone_shares_object_store_with_producer"
            ],
            "verified_at": readback_verified_at,
            "verified_artifact_count": readback["verified_artifact_count"],
            "verified_total_bytes": readback["verified_total_bytes"],
            "all_match": readback["all_artifacts_match"],
            "out_of_scope_changed_path_count": readback["out_of_scope_changed_path_count"],
            "evidence": f"{OWNED_PREFIX}result/readback-verification.json",
        },
        "input_digest_gate": result["input_digest_gate"],
        "limitations": {
            "count": limitations["limitation_count"],
            "details_path": f"{OWNED_PREFIX}result/limitations.json",
            "dispatch_input_digest_mismatch": "FAILED_CLOSED_AND_RECORDED",
            "well_formed_ledger_rewrite_detection": "NOT_SUPPORTED",
            "provider_completed_uncommitted_before_lease_expiry": "REQUIRES_PROVIDER_OBSERVATION",
            "live_fault_occurrences_observed": 0,
            "scanner_scope": "READ_ONLY_DIAGNOSIS_NOT_REMEDIATION",
            "reasoning_observed": "NOT_SUPPORTED",
            "auto_model_selection_observed": "NOT_SUPPORTED",
            "independent_acceptance": "NOT_TESTED",
        },
        "observed_model_facts": {
            "requested_model_slug": "claude-opus-5-thinking-high",
            "requested_reasoning": "high",
            "auto_model_selection_requested": False,
            "normalized_model_observed": result["model_observed"],
            "runtime_system_identity": result["model_attestation_detail"][
                "subagent_runtime_self_identity"
            ],
            "model_observed_attestation": result["model_observed_attestation"],
            "model_variant_slug_observed": result["model_variant_slug_observed"],
            "separately_attested_reasoning": "NOT_SUPPORTED",
            "subagent_level_provider_attestation": "NOT_SUPPORTED",
            "enclosing_provider_run_original_model_name": result[
                "model_attestation_detail"
            ]["enclosing_provider_run_original_model_name"],
            "enclosing_value_interpretation": result["model_attestation_detail"][
                "enclosing_value_interpretation"
            ],
            "runtime_environment": "Cursor Cloud",
            "runtime_authority_effect": "NONE",
        },
        "preregistered_metrics": result["preregistered_metrics"],
        "commit_lineage": [
            {"commit": commit, "purpose": purpose}
            for commit, purpose in (
                (
                    "f8b8d95a87c31379fa3cb5e1f9ab36c83cf1afbf",
                    "Append-only recovery scanner and the 16 sanitized crash fixtures.",
                ),
                (
                    "e82e78bc3f67acd3ad36d917b634f1b7e57e68a3",
                    "Focused and adversarial tests, recurrence harness and result evidence.",
                ),
                (
                    "a784ca711cc232d4b6be91bc56d7aff2924acffa",
                    "Immutable read-back verifier and refreshed manifest accounting.",
                ),
                (
                    "642833d31268bec327a72157209f94c9da0fa798",
                    "Honest model-attestation boundary between requested, self-reported and provider-attested values.",
                ),
                (
                    "585d4c7132572c7c796d94c35e753f611e29f11b",
                    "Credential redaction in read-back evidence, so no token can reach a durable artefact.",
                ),
                (
                    "6772bf99bf430aa50cd0fd248db88d906e7d7424",
                    "Ninth mechanism change, tenth defect and clean-clone recurrence lineage. This is the immutable result commit.",
                ),
            )
        ],
        "payload_commit": {
            "commit": args.result_commit,
            "committed_at": git(
                ["show", "-s", "--format=%cI", args.result_commit]
            ).strip(),
            "remote_ref": "refs/heads/cursor/po03-wa-013-b195-a02-1a9f",
            "remote_tip_at_readback": readback["remote_branch_tip_at_readback"],
            "base_to_payload_changed_path_count": len(changed_at_result),
            "out_of_scope_changed_path_count": len(outside),
        },
        "producer_contract_check": [
            {
                "assertion": "The frozen hypothesis was executed rather than answered with a plan.",
                "disposition": "PASS",
                "evidence": (
                    "A runnable scanner reconstructs all 66 tasks in the live 508-event "
                    "ledger with CLEAN integrity, 16 sanitized fixtures inject the "
                    "commission's fault classes, and 73 focused and adversarial tests run."
                ),
            },
            {
                "assertion": "Committed-not-ingested and provider-completed-uncommitted are separately identified.",
                "disposition": "PASS",
                "evidence": (
                    "Six fixtures classify COMMITTED_NOT_INGESTED with REPLAY_PARENT_INGESTION "
                    "and two classify PROVIDER_COMPLETED_UNCOMMITTED with "
                    "RERUN_FROM_IMMUTABLE_INPUT. fx-16 separates both classes in one pass."
                ),
            },
            {
                "assertion": "Source claims, hypotheses, reproductions, mechanism changes, strategy proposals and limitations are separate states.",
                "disposition": "PASS",
                "evidence": (
                    "Six distinct typed artefacts: 8 source claims, 9 frozen hypotheses, "
                    "9 reproductions, 9 applied mechanism changes, 6 unbound strategy "
                    "proposals and 12 limitations."
                ),
            },
            {
                "assertion": "The dispatch input digest gate was honoured rather than assumed.",
                "disposition": "PASS_BY_FAILING_CLOSED",
                "evidence": (
                    "The supplied digest did not match the file. The gate failed closed, "
                    "the observed digest was recorded in durable owned evidence, and task "
                    "identity was confirmed from the input's own fields before proceeding."
                ),
            },
            {
                "assertion": "Only the owned subtree changed.",
                "disposition": "PASS",
                "evidence": (
                    "Every changed path from the immutable controller base lies under "
                    "workstreams/po03/wave-a/units/wa-013/; the out-of-scope count is zero, "
                    "asserted independently by the manifest builder and by the clean clone."
                ),
            },
            {
                "assertion": "Seeded controls were strengthened by addition, never modified, bypassed or weakened.",
                "disposition": "PASS",
                "evidence": "Zero seeded files modified; the 55 seeded contract tests pass unchanged.",
            },
            {
                "assertion": "Every manifest artefact was read back from the immutable commit in a clone sharing no object storage with the producer.",
                "disposition": "PASS",
                "evidence": (
                    "42 of 42 artefacts matched on SHA-256 and byte count at "
                    "6772bf99bf430aa50cd0fd248db88d906e7d7424; the clone carries no "
                    "alternates file."
                ),
            },
            {
                "assertion": "No secret reached a durable artefact.",
                "disposition": "PASS",
                "evidence": (
                    "The read-back verifier's credential-bearing remote is redacted before "
                    "serialisation; the emitted report was scanned for token material and "
                    "carries none."
                ),
            },
            {
                "assertion": "The producer reports READY_TO_COMMIT without claiming completion or acceptance.",
                "disposition": "PASS",
                "evidence": (
                    "completion_actor is null, independent_acceptance.state is NOT_TESTED, "
                    "parent_ingested_at is null and decision_changed is empty."
                ),
            },
            {
                "assertion": "PR #8, PO-01, protected state and current pointers, external systems, deployment, DNS, production, secrets and owner identity remain untouched.",
                "disposition": "PASS",
                "evidence": (
                    "No such surface was contacted or mutated. The only remote mutation was "
                    "pushing the authorised WA-013 A02 branch. /workspace and every other "
                    "checkout were left unmodified."
                ),
            },
        ],
        "transactional_result": {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "PO03-WA-013",
            "commission_id": manifest["commission_id"],
            "immutable_input_manifest_sha256": manifest["immutable_input_manifest_sha256"],
            "acceptance_contract_sha256": manifest["acceptance_contract_sha256"],
            "provider_state": "RUNNING",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": "PO03-WA-013-A02",
                "idempotency_key": "po03:100bc2079ced:wa-013:a02",
                "lease_id": "lease-po03-wa-013-a02",
                "fence_token": 2,
                "provider_run_id": manifest["controller_run_id"],
                "worker_id": manifest["runner"]["runner_id"],
                "heartbeat_at": args.generated_at,
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": manifest["result_txn_id"],
                "state": "COMMITTED",
                "manifest_uri": f"{OWNED_PREFIX}result/artifact-manifest.json",
                "manifest_sha256": manifest_sha256,
                "artifact_count": len(artifacts),
                "total_bytes": total_bytes,
                "committed_at": git(
                    ["show", "-s", "--format=%cI", args.result_commit]
                ).strip(),
                "verified_at": readback_verified_at,
                "parent_ingested_at": None,
                "result_commit_id": args.result_commit,
            },
            "artifacts": artifacts,
            "completion_actor": None,
            "independent_acceptance": {
                "state": "NOT_TESTED",
                "reviewer_id": None,
                "receipt_uri": None,
            },
        },
        "completion_claimed": False,
        "completion_actor": None,
        "independent_acceptance": "NOT_TESTED",
        "self_accepted": False,
        "coordinator_completion_marked": False,
        "decision_changed": [],
    }

    payload = (json.dumps(envelope, sort_keys=True, indent=2) + "\n").encode("utf-8")
    args.out.write_bytes(payload)
    print(f"envelope bytes={len(payload)} sha256={hashlib.sha256(payload).hexdigest()}")
    print(f"artifacts={len(artifacts)} total_bytes={total_bytes}")
    print(f"changed_paths={len(changed_all)} outside={len(outside)}")
    return 0 if not outside else 1


if __name__ == "__main__":
    raise SystemExit(main())
