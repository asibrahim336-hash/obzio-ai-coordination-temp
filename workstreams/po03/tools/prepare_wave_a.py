#!/usr/bin/env python3
"""Deterministically pre-register PO-03 Wave A material attempts.

The generator is intentionally dependency-free. It freezes 64 distinct,
falsifiable tasks and writes every transaction input, lease, result slot,
ownership grant, outbox entry, and CREATED/LEASED event before delegation.
It is idempotent and refuses to write outside workstreams/po03.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CREATED_AT = "2026-08-22T07:13:11Z"
LEASE_EXPIRES_AT = "2026-08-22T13:13:11Z"
COMMISSION_ID = "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001"
CONTROLLER_RUN_ID = "bc-b1956656-b897-4889-aeab-82c4556c1a9f"
COMMISSION_COMMIT = "552b12eacee637716451492a98980fb0da19ff3e"
PROTOCOL_ANCESTOR = "100bc2079cedc193af3524234ab833cc9f9f4669"
ACCEPTANCE_REL = "control/acceptance/wave-a-material-v1.json"
EXPECTED_ACCEPTANCE_SHA = "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a"
MATERIAL_TASK_RE = re.compile(r"^PO03-WA-\d{3}$")
FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

SOURCE_HASHES = {
    "commission_sha256": "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
    "transactional_schema_sha256": "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
    "wave_schema_sha256": "5278cb6bc4e7f41a5d513d4a00427a1ed199a21459025c7fa96fb97d56439360",
    "validator_sha256": "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
    "seed_tests_sha256": "401a684c0a2d3817d08a76044a331f0f241b16d687d2dd12d9ea0f31612dc112",
    "workflow_sha256": "427949c07d93fe69bea6485a91ca58c4297be21759e6b0b00a0e5cc9f450c7cb",
}


def task(
    number: int,
    group: str,
    function: str,
    title: str,
    hypothesis: str,
    executable_output: str,
) -> dict[str, Any]:
    return {
        "number": number,
        "task_id": f"PO03-WA-{number:03d}",
        "hypothesis_id": f"H-PO03-WA-{number:03d}",
        "group": group,
        "standing_function": function,
        "title": title,
        "falsifiable_hypothesis": hypothesis,
        "required_executable_output": executable_output,
    }


TASKS = [
    task(1, "engineering", "current-plan-engineering", "Path-scope guard", "A base-SHA-aware changed-path guard can reject every write outside the PO-03 allowlist, including a deliberate fixture, without false positives on allowed changes.", "A dependency-free guard, automated tests, and an out-of-allowlist rejection fixture."),
    task(2, "engineering", "current-plan-engineering", "Current-source compiler", "A repository-native compiler can resolve current versus superseded sources from explicit pointers and fail closed on ambiguity.", "Compiler CLI, fixtures for current/superseded/ambiguous sources, and tests."),
    task(3, "engineering", "clean-runtime-reproduction", "Clean-clone runtime harness", "The PO-03 suite can execute from a clean clone with no warm checkout, uncommitted files, SW memory, or /tmp dependency.", "Clean-clone harness, contamination assertions, and recurrence test."),
    task(4, "engineering", "current-plan-engineering", "Manifest provenance verifier", "A content manifest can prove complete SHA-256, byte, source-commit, and changed-path coverage and detect one omitted artifact.", "Manifest verifier CLI, valid and omission fixtures, and tests."),
    task(5, "engineering", "current-plan-engineering", "Disposition and transport-debris detector", "Repository debris and superseded transport artifacts can be classified without deleting unique evidence.", "Detector, disposition schema, representative fixtures, and tests."),
    task(6, "reproduction", "clean-runtime-reproduction", "Immutable PO-01 claim reproducer", "PO-01 pack claims can be checked from immutable commits without branch mutation or producer narrative.", "Read-only reproduction harness, sanitized fixture, and frozen discrepancy report."),
    task(7, "engineering", "clean-runtime-reproduction", "Portable-path scanner", "Absolute, home-relative, /tmp, and checkout-specific paths can be detected with negligible false positives in declared portable artifacts.", "Scanner CLI, positive/negative fixtures, and tests."),
    task(8, "engineering", "clean-runtime-reproduction", "Hidden-state dependency detector", "A two-checkout differential run can expose dependencies on untracked files, environment leakage, or warm caches.", "Differential runner, hidden-state fixtures, and deterministic tests."),
    task(9, "engineering", "current-plan-engineering", "Bounded source capsule builder", "Hash-bounded source capsules can admit only task-relevant files while retaining sufficient evidence for recurrence.", "Capsule builder, budget enforcement, manifest, and tests."),
    task(10, "engineering", "current-plan-engineering", "Changed-path enforcement engine", "Ownership grants plus deny globs can prevent overlapping subordinate writes before commit.", "Ownership validator, overlap and deny fixtures, and tests."),
    task(11, "engineering", "current-plan-engineering", "Deterministic manifest generator", "Repeated manifest compilation over identical bytes produces byte-identical output independent of traversal order.", "Generator, shuffled-order fixture, reproducibility test."),
    task(12, "engineering", "operating-system-recovery", "Transactional state-machine engine", "An executable state machine can reject skipped, regressive, worker-completed, and stale-fence transitions.", "State machine library/CLI, transition matrix, and tests."),
    task(13, "engineering", "operating-system-recovery", "Append-only recovery scanner", "A scanner can reconstruct current task state from events and identify committed-not-ingested and provider-completed-uncommitted units.", "Recovery scanner, crash fixtures, and tests."),
    task(14, "engineering", "operating-system-recovery", "Lease and fencing store", "Monotonic fence tokens prevent an expired worker from committing after ownership transfer.", "Lease/fence implementation, stale-worker concurrency fixture, and tests."),
    task(15, "engineering", "operating-system-recovery", "Transactional outbox replay", "Duplicate and lost callbacks can replay without duplicate task transitions or external effects.", "Outbox processor, duplicate/lost callback fixtures, and tests."),
    task(16, "engineering", "operating-system-recovery", "Transition fault-injection harness", "Every transaction transition can survive pre/post-write, process-loss, and callback-loss injection without false completion.", "Fault injector, transition matrix runner, and tests."),
    task(17, "strategy", "zero-base-strategy", "Zero-base architecture candidates", "At least three independently reasoned repository-factory architectures expose materially different safety/throughput trade-offs under one frozen simulation.", "Executable simulator with three candidates and preregistered comparison."),
    task(18, "strategy", "zero-base-strategy", "Safety-throughput frontier challenge", "Increasing concurrency without proportional verification capacity creates a measurable false-green or recovery penalty.", "Queue/verification simulation, threshold cases, and evidence-backed disposition."),
    task(19, "strategy", "successor-generation", "Topology benchmark candidates", "Centralized, sharded, and event-sourced coordination topologies produce distinguishable accepted-throughput and recovery outcomes.", "Three executable topology candidates and matched benchmark."),
    task(20, "evaluation", "independent-evaluation", "Blind strategy review harness", "Criteria frozen before anonymized candidate ingestion reduce producer-identity bias and catch one seeded attractive false claim.", "Blind review harness, seeded case, and tests."),
    task(21, "strategy", "open-discovery", "Open opportunity scanner", "Repository evidence can identify useful unnamed work by scoring recurring defects, missing recurrence tests, and high-leverage gaps.", "Opportunity scanner, scoring fixture, and ranked machine-readable output."),
    task(22, "strategy", "zero-base-strategy", "Stage-gate alternative benchmark", "An evidence-triggered gate outperforms narrative readiness gates on false promotion without reducing accepted throughput.", "Executable gate comparison and seeded false-readiness cases."),
    task(23, "research", "frontier-research-reproduction", "Cursor worktree isolation claim", "Cursor's documented worktree isolation properties hold under branch switching, concurrent writes, and controller-checkout guard tests.", "Frozen source claims, sanitized reproduction, executable probe, and disposition."),
    task(24, "research", "frontier-research-reproduction", "GitHub Actions clean-environment claim", "A clean Actions runner exposes hidden local-state assumptions that a warm checkout misses.", "Current official-source claim, local sanitized reproduction, CI-equivalent harness, and disposition."),
    task(25, "research", "frontier-research-reproduction", "Git immutable readback claim", "Fetch plus git-show at an immutable commit detects branch-tip movement and preserves exact artifact bytes.", "Claim capsule, branch-movement reproduction, readback verifier, and tests."),
    task(26, "research", "frontier-research-reproduction", "Content-addressed provenance method", "Content-addressed artifact identity detects a manifest substitution that path-only provenance accepts.", "Current sources, substitution reproduction, mechanism candidate, and tests."),
    task(27, "research", "frontier-research-reproduction", "Transactional outbox method", "A transactional outbox model recovers a lost dispatch callback without double-applying its result.", "Current sources, executable lost-callback reproduction, and mechanism disposition."),
    task(28, "research", "frontier-research-reproduction", "Lease fencing method", "Fencing tokens reject stale completion after lease transfer where expiry timestamps alone fail.", "Current sources, executable race reproduction, and mechanism disposition."),
    task(29, "research", "frontier-research-reproduction", "Fault-injection workflow method", "Systematic transition fault injection finds at least one false-completion path missed by happy-path tests.", "Current sources, sanitized fault reproduction, and recurrence test."),
    task(30, "research", "model-context-evaluation", "Context capsule efficiency", "Hash-bounded task-specific context matches full-tree correctness with lower admitted bytes on a frozen suite.", "Current methods, paired executable evaluation, and result."),
    task(31, "research", "independent-evaluation", "Repository-agent benchmark design", "Holdout mutation cases distinguish substantive repository engineering from plausible narrative completion.", "Current benchmark sources, executable mini-suite, and seeded false-green case."),
    task(32, "research", "independent-evaluation", "Hidden-test leakage resistance", "Evaluator-held generated cases catch hard-coded producer behavior without disclosing exact fixtures.", "Current methods, generator, leaky producer fixture, and result."),
    task(33, "research", "operating-system-recovery", "Workflow concurrency cancellation", "Cancellation semantics can orphan a committed result unless reconciliation scans immutable branches.", "Current official-source claim, executable cancellation model, and recovery disposition."),
    task(34, "research", "current-plan-engineering", "Supply-chain attestation method", "A minimal repository-native attestation binds source commit, tool version, command, and artifact digest strongly enough to detect one tamper.", "Current sources, attestation prototype, tamper fixture, and tests."),
    task(35, "evaluation", "model-tool-evaluation", "Cross-model disagreement harness", "Blind comparison across Opus and Sol outputs identifies actionable disagreement rather than stylistic variance.", "Anonymizer, rubric engine, synthetic model outputs, and tests."),
    task(36, "evaluation", "model-tool-evaluation", "Matched model allocation evaluation", "Task-class matched evaluation can justify or refuse model-routing exceptions without using cost as a downgrade rule.", "Paired evaluation harness, frozen tasks, and routing disposition."),
    task(37, "evaluation", "model-context-evaluation", "Prompt capsule admission control", "Explicit token/byte/source budgets reject irrelevant context while preserving all acceptance-critical files.", "Admission controller, over-budget fixture, and tests."),
    task(38, "evaluation", "model-context-evaluation", "Context waste metric", "Admitted-but-unused source bytes can be estimated reproducibly from declared evidence references.", "Metric implementation, reference fixtures, and limitations."),
    task(39, "evaluation", "independent-evaluation", "Hidden-case generator", "Grammar-based mutation produces valid novel contract cases that kill at least one seeded weak validator.", "Generator, seeded weak validator, mutation score, and tests."),
    task(40, "evaluation", "independent-evaluation", "False-green adversarial suite", "Provider-completed, missing-artifact, stale-fence, and partial-push cases are rejected despite plausible success narratives.", "Adversarial fixtures, executable assertions, and result."),
    task(41, "evaluation", "independent-evaluation", "Independent pack qualification", "A producer-neutral pack qualifier can reproduce required claims solely from immutable bytes and criteria.", "Qualifier, sanitized pack fixture, and acceptance receipt."),
    task(42, "evaluation", "semantic-contract-improvement", "Contract mutation testing", "Mutation operators over required fields and transition invariants expose gaps in the seeded dependency-free validator.", "Mutation runner, surviving mutants report, and at least one tested repair candidate."),
    task(43, "evaluation", "semantic-contract-improvement", "State-machine property testing", "Generated transition sequences establish no path to COMPLETED without commit and ingestion.", "Dependency-free sequence generator, invariant oracle, and tests."),
    task(44, "evaluation", "model-tool-evaluation", "Runtime capability probe", "Observed provider capabilities can be separated from configured intent without manufacturing unsupported model, token, or cost data.", "Capability probe, NOT_SUPPORTED handling, and tests."),
    task(45, "semantics", "semantic-contract-improvement", "Ontology linter", "Canonical task, attempt, result, provider, and acceptance concepts can be linted to prevent state conflation.", "Ontology schema/linter, conflation fixtures, and tests."),
    task(46, "semantics", "semantic-contract-improvement", "Supersession graph validator", "Acyclic explicit supersession with one current target prevents stale launch surfaces and detects split currentness.", "Graph validator, cycle/split fixtures, and tests."),
    task(47, "semantics", "semantic-contract-improvement", "Authority-runtime separation check", "Machine validation can detect provider/runtime labels improperly used as authority or durable institutional identity.", "Checker, positive/negative fixtures, and tests."),
    task(48, "metrics", "operating-system-measurement", "Work-unit metric schema", "A strict schema can cover every counted unit while preserving NOT_SUPPORTED instead of fabricated timing, token, and cost values.", "Metric schema/validator, complete and invented-value fixtures, and tests."),
    task(49, "metrics", "operating-system-measurement", "Cycle and recovery measurement", "Event-ledger timestamps can derive queue, active, review, and recovery durations without producer self-report.", "Metric compiler, event fixtures, and tests."),
    task(50, "metrics", "operating-system-recovery", "Path collision detector", "Owned-glob intersection plus changed-path evidence detects potential and actual collisions before ingestion.", "Collision detector, overlapping/non-overlapping fixtures, and tests."),
    task(51, "metrics", "operating-system-recovery", "Orphan and duplicate scanner", "Registry/outbox/result reconciliation detects orphan tasks, duplicate callbacks, and duplicate result commits idempotently.", "Scanner, fault fixtures, and tests."),
    task(52, "metrics", "operating-system-recovery", "Provider completion classifier", "Provider completion can never imply Obzio completion when commit, readback, or parent-ingestion evidence is absent.", "Classifier, complete state matrix, and tests."),
    task(53, "successor", "successor-generation", "Executable G0 reconstruction", "The pre-amendment controller reconstructed from immutable seed behavior permits at least one known false-completion fixture.", "Executable G0 adapter, frozen fixture, and measured baseline."),
    task(54, "successor", "successor-generation", "Executable G1 factory", "The transactional high-scale factory rejects G0 false completion while retaining successful durable results.", "Executable G1 adapter, same frozen fixture, and measured result."),
    task(55, "successor", "successor-generation", "G2 compiler", "Accepted G1 failure lessons can compile into executable configuration/code changes with preserved lineage.", "Successor compiler, three lesson fixtures, and generated G2 candidate."),
    task(56, "successor", "successor-generation", "Frozen public suite", "One public suite can compare G0/G1/G2 without generation-specific exceptions.", "Versioned executable suite, manifest, and baseline outputs."),
    task(57, "successor", "successor-generation", "Evaluator-held holdout generator", "Held-out fault compositions detect overfitting to the public suite while remaining reproducible from a private seed commitment.", "Holdout generator, seed commitment, and sample evaluator receipt."),
    task(58, "successor", "successor-generation", "Generation comparison engine", "Preregistered metrics can establish or refuse successor lift with no critical-correctness regression.", "Comparison engine, synthetic generation outputs, and tests."),
    task(59, "successor", "successor-generation", "Lesson-to-live-change tracker", "Every claimed lesson can be traced to an executable change, recurrence test, and disposition.", "Lineage tracker, unimplemented-lesson fixture, and tests."),
    task(60, "successor", "successor-generation", "Route disposition engine", "RETAIN/DELETE/SUPERSEDE/RETEST/REJECT decisions can preserve lineage and prevent silently active superseded routes.", "Disposition engine, conflicting-route fixtures, and tests."),
    task(61, "discovery", "open-discovery", "Portability hazard miner", "Repository-native static and execution evidence can discover portability hazards not named in the commission.", "Hazard miner, at least one novel sanitized fixture, and findings with tests."),
    task(62, "discovery", "open-discovery", "Failure-trace clusterer", "Normalized failure signatures can group repeated custody/recovery defects without collapsing distinct root causes.", "Dependency-free clusterer, trace corpus, and tests."),
    task(63, "discovery", "open-discovery", "External-method intake classifier", "Source claims can be kept distinct from hypotheses, reproductions, mechanism changes, and strategy proposals by validation.", "State classifier, invalid-transition fixtures, and tests."),
    task(64, "discovery", "open-discovery", "Novel clean-clone stress case", "A generated checkout perturbation reveals at least one hidden assumption beyond the seeded /tmp and uncommitted-file cases.", "Perturbation generator, sanitized reproduction, and recurrence test."),
]


FIRST_COHORT = {1, 2, 3, 12, 16, 23, 24, 25}
DISPATCH_ORDER = [1, 2, 3, 12, 16, 23, 24, 25] + [
    number for number in range(1, 65) if number not in FIRST_COHORT
]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _resolve_exact_commit(root: Path, value: str, label: str) -> str:
    if not FULL_COMMIT_RE.fullmatch(value):
        raise ValueError(f"{label} must be a full lowercase 40-character commit SHA")
    result = _git(root, "rev-parse", "--verify", f"{value}^{{commit}}")
    resolved = result.stdout.strip()
    if result.returncode != 0 or resolved != value:
        detail = result.stderr.strip() or "object did not resolve exactly"
        raise ValueError(f"{label} is not an exact resolvable commit: {value}: {detail}")
    return resolved


def validate_git_provenance(
    root: Path = ROOT,
    protocol_ancestor: str = PROTOCOL_ANCESTOR,
    commission_commit: str = COMMISSION_COMMIT,
) -> None:
    """Fail closed before generation unless both pins are real and related."""
    ancestor = _resolve_exact_commit(root, protocol_ancestor, "protocol ancestor")
    commission = _resolve_exact_commit(root, commission_commit, "commission commit")
    ancestry = _git(root, "merge-base", "--is-ancestor", ancestor, commission)
    if ancestry.returncode == 1:
        raise ValueError(
            f"protocol ancestor {ancestor} is not an ancestor of commission commit {commission}"
        )
    if ancestry.returncode != 0:
        detail = ancestry.stderr.strip() or "git ancestry check failed"
        raise ValueError(f"unable to validate protocol ancestry: {detail}")


def _write(relative: str, value: Any) -> str:
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"refusing out-of-scope write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(value)
    path.write_bytes(data)
    return _sha(data)


def _read_json(relative: str) -> Any:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _read_jsonl(relative: str) -> list[dict[str, Any]]:
    path = ROOT / relative
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(relative: str, rows: list[dict[str, Any]]) -> None:
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"refusing out-of-scope write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    validate_git_provenance()
    if len(TASKS) != 64 or {item["number"] for item in TASKS} != set(range(1, 65)):
        raise ValueError("Wave A must contain exactly 64 uniquely numbered tasks")

    acceptance_path = ROOT / ACCEPTANCE_REL
    acceptance_sha = _sha(acceptance_path.read_bytes())
    if acceptance_sha != EXPECTED_ACCEPTANCE_SHA:
        raise ValueError(f"acceptance hash mismatch: {acceptance_sha}")

    order_index = {number: index for index, number in enumerate(DISPATCH_ORDER)}
    portfolio_tasks: list[dict[str, Any]] = []
    for item in TASKS:
        enriched = dict(item)
        enriched["dispatch_order"] = order_index[item["number"]] + 1
        enriched["cohort"] = order_index[item["number"]] // 8 + 1
        enriched["model_slug"] = (
            "claude-opus-5-thinking-high"
            if enriched["dispatch_order"] % 2
            else "gpt-5.6-sol-xhigh"
        )
        enriched["reasoning"] = "high" if enriched["model_slug"].startswith("claude") else "xhigh"
        enriched["runner"] = "best-of-n-runner"
        portfolio_tasks.append(enriched)

    portfolio = {
        "schema_version": "1.0",
        "wave_id": "PO03-WAVE-A",
        "commission_id": COMMISSION_ID,
        "created_at": CREATED_AT,
        "count": 64,
        "cohort_size": 8,
        "cohort_count": 8,
        "retained_dispatch_route": "best-of-n-runner isolated git worktree",
        "heterogeneous_families": ["claude-opus-5", "gpt-5.6-sol"],
        "not_supported_families": ["gemini-3.1-pro", "composer-2.5"],
        "acceptance_contract": {
            "path": f"workstreams/po03/{ACCEPTANCE_REL}",
            "sha256": acceptance_sha,
        },
        "tasks": sorted(portfolio_tasks, key=lambda item: item["number"]),
        "decision_changed": [],
    }
    portfolio_sha = _write("control/wave-a-portfolio.json", portfolio)

    material_registry: list[dict[str, Any]] = []
    material_outbox: list[dict[str, Any]] = []
    material_owners: list[dict[str, Any]] = []
    material_events: list[dict[str, Any]] = []
    active_leases: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}

    for item in portfolio_tasks:
        number = item["number"]
        task_id = item["task_id"]
        slug = f"wa-{number:03d}"
        attempt_id = f"{task_id}-A01"
        idempotency_key = f"po03:{PROTOCOL_ANCESTOR[:7]}:{slug}:a01"
        lease_id = f"lease-po03-{slug}-a01"
        owned_glob = f"workstreams/po03/wave-a/units/{slug}/**"
        result_slot = f"workstreams/po03/wave-a/units/{slug}/result/"
        first_return_seed = number in FIRST_COHORT
        immutable_input = {
            "protocol_version": "OBZIO-IMMUTABLE-TASK-INPUT-v1",
            "task_id": task_id,
            "hypothesis_id": item["hypothesis_id"],
            "commission_id": COMMISSION_ID,
            "wave_id": "PO03-WAVE-A",
            "controller_run_id": CONTROLLER_RUN_ID,
            "created_at": CREATED_AT,
            "portfolio": {
                "path": "workstreams/po03/control/wave-a-portfolio.json",
                "sha256": portfolio_sha,
                "dispatch_order": item["dispatch_order"],
                "cohort": item["cohort"],
            },
            "source_base": {
                "repository": "github.com/asibrahim336-hash/obzio-ai-coordination-temp",
                "commission_commit": COMMISSION_COMMIT,
                "minimum_protocol_ancestor": PROTOCOL_ANCESTOR,
                **SOURCE_HASHES,
            },
            "acceptance_contract": {
                "path": f"workstreams/po03/{ACCEPTANCE_REL}",
                "sha256": acceptance_sha,
            },
            "assignment": {
                "group": item["group"],
                "standing_function": item["standing_function"],
                "title": item["title"],
                "falsifiable_hypothesis": item["falsifiable_hypothesis"],
                "required_executable_output": item["required_executable_output"],
                "first_substantive_return_seed": first_return_seed,
                "minimum_current_method_hypotheses": 2 if first_return_seed else 0,
                "minimum_sanitized_reproductions": 1 if first_return_seed else 0,
                "mechanism_change_or_rejection_required": first_return_seed,
            },
            "configuration": {
                "subagent_type": "best-of-n-runner",
                "execution_environment": "isolated-git-worktree",
                "model_slug": item["model_slug"],
                "reasoning": item["reasoning"],
                "auto_model_selection": False,
                "material_work": True,
                "context_policy": "bounded-hashed-source-capsule",
            },
            "ownership": {
                "allowed_write_globs": [owned_glob],
                "result_slot": result_slot,
                "remote_branch_prefix": f"cursor/po03-{slug}-b195-",
                "read_only_globs": [
                    "workstreams/po03/COMMISSION.md",
                    "workstreams/po03/contracts/**",
                    "workstreams/po03/control/**",
                    "workstreams/po03/tools/**",
                    "workstreams/po03/tests/**",
                    "packs/**",
                    "modules/operators/**",
                    "_transport/**",
                    "modules/work_unit_contract/**",
                ],
                "prohibited_globs": [
                    "state/**",
                    "dispatch/**",
                    ".cursor/environment.json",
                    "receipts/po01/**",
                    "workstreams/po01/**",
                ],
            },
            "attempt": {
                "attempt_id": attempt_id,
                "idempotency_key": idempotency_key,
                "lease_id": lease_id,
                "fence_token": 1,
                "lease_expires_at": LEASE_EXPIRES_AT,
                "checkpoint_seq": 0,
            },
            "producer_return_contract": {
                "only_permitted_terminal_report": "READY_TO_COMMIT",
                "required_fields": [
                    "task_id",
                    "hypothesis_id",
                    "runner_id",
                    "model_observed",
                    "remote_branch",
                    "result_commit_id",
                    "return_commit_id",
                    "manifest_path",
                    "manifest_sha256",
                    "artifact_count",
                    "total_bytes",
                    "changed_files",
                    "tests",
                    "limitations",
                ],
            },
            "preregistered_metrics": [
                "wall_time",
                "test_count",
                "first_pass_outcome",
                "artifact_count",
                "artifact_bytes",
                "source_claim_count",
                "reproduction_count",
                "mechanism_change_count",
                "defects",
                "rework",
                "provider_block",
                "collision",
                "recovery_events",
            ],
            "decision_changed": [],
        }
        input_rel = f"control/inputs/wave-a/{slug}.json"
        input_sha = _write(input_rel, immutable_input)
        input_hashes[task_id] = input_sha

        result_record = {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": task_id,
            "commission_id": COMMISSION_ID,
            "immutable_input_manifest_sha256": input_sha,
            "acceptance_contract_sha256": acceptance_sha,
            "provider_state": "UNKNOWN",
            "obzio_state": "LEASED",
            "attempt": {
                "attempt_id": attempt_id,
                "idempotency_key": idempotency_key,
                "lease_id": lease_id,
                "fence_token": 1,
                "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
                "worker_id": "PENDING_PROVIDER_ASSIGNMENT",
                "heartbeat_at": None,
                "checkpoint_seq": 0,
            },
            "result_transaction": {
                "result_txn_id": f"txn-po03-{slug}-a01",
                "state": "RESERVED",
                "manifest_uri": None,
                "manifest_sha256": None,
                "artifact_count": 0,
                "total_bytes": 0,
                "committed_at": None,
                "verified_at": None,
                "parent_ingested_at": None,
                "result_commit_id": None,
            },
            "artifacts": [],
            "completion_actor": None,
            "independent_acceptance": {
                "state": "NOT_TESTED",
                "reviewer_id": None,
                "receipt_uri": None,
            },
        }
        _write(f"control/results/wave-a/{slug}.json", result_record)

        material_registry.append(
            {
                "task_id": task_id,
                "parent_id": "PO03-WAVE-A",
                "function": item["standing_function"],
                "group": item["group"],
                "material": True,
                "hypothesis_id": item["hypothesis_id"],
                "immutable_input_uri": f"workstreams/po03/{input_rel}",
                "immutable_input_manifest_sha256": input_sha,
                "acceptance_contract_uri": f"workstreams/po03/{ACCEPTANCE_REL}",
                "acceptance_contract_sha256": acceptance_sha,
                "model_requested": item["model_slug"],
                "reasoning_requested": item["reasoning"],
                "environment_requested": "best-of-n isolated git worktree",
                "owned_paths": [owned_glob],
                "result_slot": result_slot,
                "idempotency_key": idempotency_key,
                "lease_id": lease_id,
                "fence_token": 1,
                "lease_expires_at": LEASE_EXPIRES_AT,
                "provider_run_id": "PENDING_PROVIDER_ASSIGNMENT",
                "provider_state": "UNKNOWN",
                "obzio_state": "LEASED",
                "checkpoint_seq": 0,
                "dispatch_order": item["dispatch_order"],
                "cohort": item["cohort"],
                "created_at": CREATED_AT,
                "updated_at": CREATED_AT,
                "independent_acceptance": "NOT_TESTED",
            }
        )
        material_outbox.append(
            {
                "outbox_id": f"outbox-po03-{slug}-dispatch-a01",
                "task_id": task_id,
                "operation": "DISPATCH_MATERIAL",
                "idempotency_key": idempotency_key,
                "fence_token": 1,
                "payload_uri": f"workstreams/po03/{input_rel}",
                "payload_sha256": input_sha,
                "state": "PENDING",
                "attempts": 0,
                "created_at": CREATED_AT,
                "last_attempt_at": None,
                "delivered_at": None,
                "cohort": item["cohort"],
            }
        )
        material_owners.append(
            {
                "task_id": task_id,
                "lease_id": lease_id,
                "fence_token": 1,
                "owned_globs": [owned_glob],
                "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
            }
        )
        active_leases.append(
            {
                "task_id": task_id,
                "lease_id": lease_id,
                "fence_token": 1,
                "expires_at": LEASE_EXPIRES_AT,
                "state": "LEASED",
                "cohort": item["cohort"],
            }
        )

    existing_events = [
        row for row in _read_jsonl("control/events/ledger.jsonl")
        if not MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
    ]
    next_seq = max((int(row["event_seq"]) for row in existing_events), default=0) + 1
    for item in sorted(portfolio_tasks, key=lambda value: value["dispatch_order"]):
        task_id = item["task_id"]
        number = item["number"]
        slug = f"wa-{number:03d}"
        input_sha = input_hashes[task_id]
        idempotency_key = f"po03:{PROTOCOL_ANCESTOR[:7]}:{slug}:a01"
        lease_id = f"lease-po03-{slug}-a01"
        material_events.append(
            {
                "event_id": f"evt-po03-{slug}-{next_seq:04d}",
                "event_seq": next_seq,
                "task_id": task_id,
                "from_state": None,
                "to_state": "CREATED",
                "actor": f"controller:{CONTROLLER_RUN_ID}",
                "at": CREATED_AT,
                "fence_token": 1,
                "immutable_input_manifest_sha256": input_sha,
                "idempotency_key": idempotency_key,
            }
        )
        next_seq += 1
        material_events.append(
            {
                "event_id": f"evt-po03-{slug}-{next_seq:04d}",
                "event_seq": next_seq,
                "task_id": task_id,
                "from_state": "CREATED",
                "to_state": "LEASED",
                "actor": f"controller:{CONTROLLER_RUN_ID}",
                "at": CREATED_AT,
                "fence_token": 1,
                "lease_id": lease_id,
                "lease_expires_at": LEASE_EXPIRES_AT,
                "idempotency_key": idempotency_key,
            }
        )
        next_seq += 1
    _write_jsonl("control/events/ledger.jsonl", existing_events + material_events)

    existing_registry = [
        row for row in _read_jsonl("control/work-unit-registry.jsonl")
        if not MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
    ]
    _write_jsonl(
        "control/work-unit-registry.jsonl",
        existing_registry + sorted(material_registry, key=lambda row: row["dispatch_order"]),
    )

    existing_outbox = [
        row for row in _read_jsonl("control/outbox.jsonl")
        if not MATERIAL_TASK_RE.fullmatch(str(row.get("task_id", "")))
    ]
    _write_jsonl(
        "control/outbox.jsonl",
        existing_outbox + sorted(material_outbox, key=lambda row: (row["cohort"], row["task_id"])),
    )

    path_ownership = _read_json("control/path-ownership.json")
    path_ownership["subordinate_owners"] = [
        owner for owner in path_ownership["subordinate_owners"]
        if not MATERIAL_TASK_RE.fullmatch(str(owner.get("task_id", "")))
    ] + sorted(material_owners, key=lambda owner: owner["task_id"])
    _write("control/path-ownership.json", path_ownership)

    recovery = _read_json("control/recovery-state.json")
    recovery["scanned_at"] = CREATED_AT
    recovery["last_event_seq"] = next_seq - 1
    recovery["active_leases"] = sorted(active_leases, key=lambda lease: lease["task_id"])
    recovery["pending_outbox"] = [
        row["outbox_id"] for row in sorted(material_outbox, key=lambda row: (row["cohort"], row["task_id"]))
    ]
    recovery["wave_a"] = {
        "state": "LEASED_QUEUED_COHORTS",
        "registered": 64,
        "active_provider_runs": 0,
        "observed_safe_concurrency": "PENDING_SATURATION",
        "next_dispatch_cohort": 1,
        "portfolio_sha256": portfolio_sha,
    }
    _write("control/recovery-state.json", recovery)

    scale_ladder = {
        "schema_version": "1.0",
        "recorded_at": CREATED_AT,
        "wave_a": {
            "required_attempts": 64,
            "registered_attempts": 64,
            "cohort_size": 8,
            "cohorts": 8,
            "active_concurrency_target": "MAXIMUM_SAFE_OBSERVED",
            "retained_route": "best-of-n-runner isolated git worktree",
            "status": "REGISTERED_NOT_YET_COUNTED",
            "counting_rule": "Only terminal durable substantive results with immutable locators count.",
        },
        "wave_b": {
            "required_attempts": 128,
            "gate": "Wave A zero false completion, zero result loss, and zero path collision",
            "status": "NOT_YET",
        },
        "decision_changed": [],
    }
    _write("evidence/scale-ladder.json", scale_ladder)

    print(
        json.dumps(
            {
                "wave_id": "PO03-WAVE-A",
                "registered": len(material_registry),
                "portfolio_sha256": portfolio_sha,
                "acceptance_sha256": acceptance_sha,
                "last_event_seq": next_seq - 1,
                "first_cohort": [f"PO03-WA-{number:03d}" for number in DISPATCH_ORDER[:8]],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
