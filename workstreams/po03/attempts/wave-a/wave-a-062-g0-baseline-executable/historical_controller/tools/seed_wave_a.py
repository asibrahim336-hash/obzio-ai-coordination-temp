#!/usr/bin/env python3
"""Seed immutable Wave A custody inputs before any material delegation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any


_FACTORY_PATH = Path(__file__).with_name("transactional_factory.py")
_FACTORY_SPEC = importlib.util.spec_from_file_location("transactional_factory", _FACTORY_PATH)
assert _FACTORY_SPEC is not None and _FACTORY_SPEC.loader is not None
factory = importlib.util.module_from_spec(_FACTORY_SPEC)
_FACTORY_SPEC.loader.exec_module(factory)


WAVE_ID = "PO03-WAVE-A-20260822"
COMMISSION_ID = factory.COMMISSION_ID

# Every entry is intentionally a distinct falsifiable work unit, rather than a
# renamed inventory task.  The controller gives each unit a unique result slot.
TASKS: tuple[dict[str, str], ...] = (
    {
        "id": "wave-a-001-source-lock-reproduction",
        "function": "current-plan-engineering",
        "hypothesis": "The source-lock receipt can be independently regenerated from the pinned base without producer narrative.",
        "request": "Implement a hermetic source-lock regeneration check with a fixture proving a changed source hash is detected.",
    },
    {
        "id": "wave-a-002-clean-clone-smoke",
        "function": "current-plan-engineering",
        "hypothesis": "The PO-03 validator suite can run in a fresh checkout using only Python standard library dependencies.",
        "request": "Build a clean-clone smoke harness and a fixture that rejects hidden checkout state.",
    },
    {
        "id": "wave-a-003-currentness-compiler",
        "function": "current-plan-engineering",
        "hypothesis": "Current sources can be compiled from explicit pointers while excluding superseded evidence.",
        "request": "Prototype a pointer-driven currentness compiler and test a superseded-pointer exclusion case.",
    },
    {
        "id": "wave-a-004-manifest-completeness",
        "function": "current-plan-engineering",
        "hypothesis": "A result manifest can prove every declared artifact exists, hashes correctly, and is within owned paths.",
        "request": "Implement a manifest-completeness checker and fault fixtures for missing, altered, and out-of-scope artifacts.",
    },
    {
        "id": "wave-a-005-portable-path-audit",
        "function": "current-plan-engineering",
        "hypothesis": "Absolute paths and /tmp dependencies can be mechanically detected before a result is retained.",
        "request": "Implement a portable-path audit with positive and negative fixtures.",
    },
    {
        "id": "wave-a-006-pack-claim-freeze",
        "function": "current-plan-engineering",
        "hypothesis": "PO-01 pack claims can be frozen as read-only assertions without using producer narrative as proof.",
        "request": "Create a read-only immutable-commit claim freeze format and tests for absent pack evidence.",
    },
    {
        "id": "wave-a-007-pack-qualification-probe",
        "function": "current-plan-engineering",
        "hypothesis": "Independent pack qualification can distinguish absent source, non-portable paths, and manifest gaps.",
        "request": "Create a qualification probe with fixtures for each failure classification.",
    },
    {
        "id": "wave-a-008-transport-debris-detector",
        "function": "current-plan-engineering",
        "hypothesis": "Repository transport debris can be detected without deleting evidence.",
        "request": "Implement a non-destructive transport-debris classifier with reproducible fixtures.",
    },
    {
        "id": "wave-a-009-supersession-graph",
        "function": "current-plan-engineering",
        "hypothesis": "Source lineage can be represented as a directed graph that rejects cycles and ambiguous active nodes.",
        "request": "Implement a supersession graph validator with cycle and ambiguity tests.",
    },
    {
        "id": "wave-a-010-allowlist-git-diff",
        "function": "current-plan-engineering",
        "hypothesis": "A path-scope gate can reject every PO-03 collision-boundary escape from a git diff.",
        "request": "Adversarially test the scope gate against rename, deletion, workflow, and non-PO-03 path cases.",
    },
    {
        "id": "wave-a-011-clean-runtime-env",
        "function": "current-plan-engineering",
        "hypothesis": "The executable mechanisms do not depend on shell aliases, warm caches, or private environment variables.",
        "request": "Create an environment-sanitization reproduction and record every observed portability failure.",
    },
    {
        "id": "wave-a-012-receipt-readback",
        "function": "current-plan-engineering",
        "hypothesis": "A receipt can be validated only after a second process reopens artifacts by immutable locator.",
        "request": "Implement a read-back receipt checker with corruption and missing-artifact fixtures.",
    },
    {
        "id": "wave-a-013-zero-base-control-challenge",
        "function": "strategy-challenge",
        "hypothesis": "An append-only event ledger is preferable to mutable status files for recovery under lost callbacks.",
        "request": "Generate a counterproposal, define measurable tradeoffs, and implement a falsifying fixture.",
    },
    {
        "id": "wave-a-014-lease-design-challenge",
        "function": "strategy-challenge",
        "hypothesis": "Fence tokens prevent stale workers from making an accepted result visible after reassignment.",
        "request": "Adversarially challenge the fence design and produce an executable stale-worker test.",
    },
    {
        "id": "wave-a-015-custody-sink-alternatives",
        "function": "strategy-challenge",
        "hypothesis": "Controller ingestion and per-task remote branches have distinct failure modes that can be measured.",
        "request": "Compare the two custody mechanisms using a concrete failure matrix and an executable decision test.",
    },
    {
        "id": "wave-a-016-result-schema-challenge",
        "function": "strategy-challenge",
        "hypothesis": "Schema-only validation leaves exploitable semantic gaps that executable invariants must close.",
        "request": "Find at least one schema-valid but semantically invalid result and add a regression case.",
    },
    {
        "id": "wave-a-017-controller-single-point",
        "function": "strategy-challenge",
        "hypothesis": "A controller restart can reconstruct active state solely from append-only events.",
        "request": "Build a restart reconstruction experiment and characterize unrecoverable information.",
    },
    {
        "id": "wave-a-018-queue-saturation-policy",
        "function": "strategy-challenge",
        "hypothesis": "A fixed-size batch does not necessarily maximize independently accepted throughput under a provider cap.",
        "request": "Define a measurable saturation policy and a simulation fixture for queued cohorts.",
    },
    {
        "id": "wave-a-019-context-admission",
        "function": "strategy-challenge",
        "hypothesis": "Hashed source capsules reduce context waste without decreasing reproducibility.",
        "request": "Design a paired capsule-admission experiment with objective acceptance assertions.",
    },
    {
        "id": "wave-a-020-successor-retention-rule",
        "function": "strategy-challenge",
        "hypothesis": "RETAIN/DELETE/SUPERSEDE/RETEST/REJECT dispositions can be mechanically checked for lineage completeness.",
        "request": "Implement a disposition completeness checker and adversarial fixtures.",
    },
    {
        "id": "wave-a-021-official-cursor-capability",
        "function": "frontier-research",
        "hypothesis": "Current official capability documentation can be converted into a testable runtime-allocation rule.",
        "request": "Research current official runtime documentation, cite exact claims, and create a bounded allocation hypothesis.",
    },
    {
        "id": "wave-a-022-agent-recovery-postmortems",
        "function": "frontier-research",
        "hypothesis": "Published agent failure postmortems reveal recurrent result-loss mechanisms reproducible in the factory.",
        "request": "Collect current sources, extract falsifiable failure claims, and propose one sanitized reproduction.",
    },
    {
        "id": "wave-a-023-worktree-isolation-method",
        "function": "frontier-research",
        "hypothesis": "Isolated worktrees reduce path collision risk compared with shared checkout delegation.",
        "request": "Research documented worktree isolation behavior and define a collision reproduction.",
    },
    {
        "id": "wave-a-024-hermetic-python-method",
        "function": "frontier-research",
        "hypothesis": "Dependency-free validation reduces clean-runtime failure modes relative to package-dependent checks.",
        "request": "Research and compare hermetic Python test techniques, then produce a reproduction plan.",
    },
    {
        "id": "wave-a-025-provenance-standard-method",
        "function": "frontier-research",
        "hypothesis": "Content-addressed manifests can detect result tampering across independent readers.",
        "request": "Research provenance practice and produce a concrete tamper-detection hypothesis.",
    },
    {
        "id": "wave-a-026-event-sourcing-method",
        "function": "frontier-research",
        "hypothesis": "Event sourcing patterns provide useful recovery semantics without a permanent architecture decision.",
        "request": "Research event-sourcing recovery guarantees and identify one bounded implementation lesson.",
    },
    {
        "id": "wave-a-027-idempotency-patterns",
        "function": "frontier-research",
        "hypothesis": "Idempotency-key patterns can prevent duplicate callback effects in a file-backed controller.",
        "request": "Research durable idempotency approaches and generate a collision test hypothesis.",
    },
    {
        "id": "wave-a-028-fencing-patterns",
        "function": "frontier-research",
        "hypothesis": "Fencing tokens have known edge cases that should appear in fault fixtures.",
        "request": "Research fencing edge cases and translate one into a local regression reproduction.",
    },
    {
        "id": "wave-a-029-model-routing-evidence",
        "function": "frontier-research",
        "hypothesis": "Model selection should be driven by matched workload evidence rather than provider claims.",
        "request": "Research a current model-routing method and pre-register a matched PO-03 evaluation.",
    },
    {
        "id": "wave-a-030-agent-evaluation-method",
        "function": "frontier-research",
        "hypothesis": "Evaluator-held cases reduce producer self-certification false greens.",
        "request": "Research evaluator-held test methods and design a hidden-case protocol compatible with PO-03.",
    },
    {
        "id": "wave-a-031-reproducible-research-method",
        "function": "frontier-research",
        "hypothesis": "A source card with direct experience, date, conflict, and validity horizon is more actionable than a summary.",
        "request": "Create a source-card schema and test its rejection of incomplete evidence.",
    },
    {
        "id": "wave-a-032-successor-compilation-method",
        "function": "frontier-research",
        "hypothesis": "Successor generation can be tested as an executable comparison rather than a narrative claim.",
        "request": "Research executable successor-comparison approaches and create a measurable local hypothesis.",
    },
    {
        "id": "wave-a-033-lost-callback-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "A lost provider callback leaves the task recoverable from immutable input and ledger state.",
        "request": "Implement a lost-callback fault injection and assert recovery classification.",
    },
    {
        "id": "wave-a-034-partial-write-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "A partial artifact write cannot be accepted after manifest read-back verification.",
        "request": "Implement a partial-write fault fixture and assert rejection.",
    },
    {
        "id": "wave-a-035-precommit-failure-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "A failure before result commit remains non-complete and becomes replayable.",
        "request": "Implement a pre-commit failure reproduction with expected state transition evidence.",
    },
    {
        "id": "wave-a-036-postcommit-failure-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "A failure after result commit but before parent ingestion preserves a recoverable committed result.",
        "request": "Implement a post-commit failure reproduction and recovery assertion.",
    },
    {
        "id": "wave-a-037-stale-lease-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "A stale lease cannot advance a result after a higher fence token is issued.",
        "request": "Implement a stale-lease reproduction and invariant test.",
    },
    {
        "id": "wave-a-038-duplicate-callback-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "Duplicate callback delivery is idempotent and cannot duplicate a result effect.",
        "request": "Implement a duplicate-callback reproduction with a deterministic duplicate assertion.",
    },
    {
        "id": "wave-a-039-corrupt-artifact-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "Artifact corruption after staging is detected by hash and byte-count verification.",
        "request": "Implement a corruption reproduction and verify terminal non-acceptance.",
    },
    {
        "id": "wave-a-040-provider-loss-reproduction",
        "function": "controlled-reproduction",
        "hypothesis": "Entire provider-runtime loss produces recovery-required state without falsely completing a unit.",
        "request": "Implement a provider-loss reproduction with deterministic recovery output.",
    },
    {
        "id": "wave-a-041-schema-adversarial-review",
        "function": "independent-evaluation",
        "hypothesis": "The result contract has no path from provider completion to Obzio completion without durable evidence.",
        "request": "Perform blind adversarial review of the contract and add one exploit regression if found.",
    },
    {
        "id": "wave-a-042-event-ledger-adversarial-review",
        "function": "independent-evaluation",
        "hypothesis": "The event hash chain exposes tampering, reordering, and deleted intermediate events.",
        "request": "Perform independent ledger tampering tests and record each observed failure mode.",
    },
    {
        "id": "wave-a-043-path-scope-adversarial-review",
        "function": "independent-evaluation",
        "hypothesis": "The scope guard rejects modified, added, copied, renamed, and deleted out-of-allowlist paths.",
        "request": "Generate hidden path cases and independently evaluate the scope guard.",
    },
    {
        "id": "wave-a-044-clean-clone-adversarial-review",
        "function": "independent-evaluation",
        "hypothesis": "A clean checkout fails closed when required generated evidence is absent.",
        "request": "Design a clean-checkout adversarial test that detects local hidden artifacts.",
    },
    {
        "id": "wave-a-045-manifest-adversarial-review",
        "function": "independent-evaluation",
        "hypothesis": "Manifest validation rejects duplicated logical identifiers, missing files, and hash substitution.",
        "request": "Generate independent adversarial manifest cases with expected dispositions.",
    },
    {
        "id": "wave-a-046-acceptance-separation-review",
        "function": "independent-evaluation",
        "hypothesis": "A producer cannot self-accept through ID aliasing or endpoint fields.",
        "request": "Adversarially test producer/reviewer separation and add a regression if necessary.",
    },
    {
        "id": "wave-a-047-metrics-false-green-review",
        "function": "independent-evaluation",
        "hypothesis": "Metric rows cannot claim unavailable data or conceal false-complete events.",
        "request": "Review metric schema assumptions and create false-green fixtures.",
    },
    {
        "id": "wave-a-048-successor-holdout-review",
        "function": "independent-evaluation",
        "hypothesis": "A successor cannot claim lift without evaluator-held novel cases and no quality regression.",
        "request": "Create a holdout acceptance protocol and adversarial no-lift fixture.",
    },
    {
        "id": "wave-a-049-claude-gpt-routing-pair",
        "function": "model-runtime-evaluation",
        "hypothesis": "Two exposed frontier families exhibit measurable disagreement on the same custody invariant workload.",
        "request": "Define and execute a paired, blinded model-routing evaluation design.",
    },
    {
        "id": "wave-a-050-reasoning-level-pair",
        "function": "model-runtime-evaluation",
        "hypothesis": "Highest exposed reasoning improves selected PO-03 correctness metrics enough to justify default use.",
        "request": "Define a frozen paired reasoning-level evaluation without treating cost as a downgrade trigger.",
    },
    {
        "id": "wave-a-051-context-capsule-pair",
        "function": "model-runtime-evaluation",
        "hypothesis": "Bounded source capsules preserve task accuracy better than indiscriminate tree context.",
        "request": "Create a paired context-admission evaluation protocol and expected result artifact.",
    },
    {
        "id": "wave-a-052-tool-route-pair",
        "function": "model-runtime-evaluation",
        "hypothesis": "Native repository tools and raw shell routes have distinguishable reproducibility properties.",
        "request": "Create a tool-route comparison with strict evidence and failure criteria.",
    },
    {
        "id": "wave-a-053-worktree-topology-pair",
        "function": "model-runtime-evaluation",
        "hypothesis": "Unique-worktree ownership reduces concurrent collision incidence versus shared-write topology.",
        "request": "Specify a measurable topology comparison and collision fixture.",
    },
    {
        "id": "wave-a-054-provider-capacity-observation",
        "function": "model-runtime-evaluation",
        "hypothesis": "Observed safe concurrency can be recorded without treating an undocumented cap as a capability fact.",
        "request": "Implement a capacity-observation record format and a no-invented-ceiling test.",
    },
    {
        "id": "wave-a-055-task-state-ontology",
        "function": "semantic-state-contract",
        "hypothesis": "Provider state and Obzio custody state remain semantically distinct across every terminal path.",
        "request": "Create an ontology consistency checker and ambiguity fixtures.",
    },
    {
        "id": "wave-a-056-result-lineage-ontology",
        "function": "semantic-state-contract",
        "hypothesis": "Each artifact can be traced from immutable input through result commit to independent disposition.",
        "request": "Implement a lineage relation model and a missing-parent rejection case.",
    },
    {
        "id": "wave-a-057-source-authority-ontology",
        "function": "semantic-state-contract",
        "hypothesis": "Source authority, recency, reproducibility, and operating effect can be represented without conflation.",
        "request": "Create a source-authority schema and test contradictory-source handling.",
    },
    {
        "id": "wave-a-058-disposition-ontology",
        "function": "semantic-state-contract",
        "hypothesis": "Every changed route receives one explicit disposition with lineage and evidence.",
        "request": "Implement a disposition ontology check and incomplete-lineage fixtures.",
    },
    {
        "id": "wave-a-059-metric-row-integrity",
        "function": "operating-system-measurement",
        "hypothesis": "One metric row per counted unit can detect missing, duplicate, and unmeasured work.",
        "request": "Implement metric-row integrity checks with failure fixtures.",
    },
    {
        "id": "wave-a-060-recovery-scanner-integrity",
        "function": "operating-system-measurement",
        "hypothesis": "A recovery scanner identifies every nonterminal unit and does not silently classify it complete.",
        "request": "Extend recovery scanning with fault fixtures for every in-flight custody state.",
    },
    {
        "id": "wave-a-061-coordination-overhead-metric",
        "function": "operating-system-measurement",
        "hypothesis": "Coordination overhead can be measured without inventing unavailable timing or cost values.",
        "request": "Define an honest coordination-overhead metric and NOT_SUPPORTED test cases.",
    },
    {
        "id": "wave-a-062-g0-baseline-executable",
        "function": "successor-compilation",
        "hypothesis": "A reconstructed G0 controller can be executed on a frozen public suite with explicit limitations.",
        "request": "Create an executable G0 baseline harness and fixture for unavailable baseline evidence.",
    },
    {
        "id": "wave-a-063-g1-factory-executable",
        "function": "successor-compilation",
        "hypothesis": "The transactional factory G1 has mechanically stronger recovery properties than the frozen G0 baseline.",
        "request": "Create an executable G1 comparison harness and metric contract.",
    },
    {
        "id": "wave-a-064-g2-successor-compiler",
        "function": "successor-compilation",
        "hypothesis": "G2 can be compiled only from accepted G1 lessons and can refuse a lift claim when evidence is absent.",
        "request": "Implement a G2 lesson-admission gate and no-evidence refusal test.",
    },
)


def _write_exact(path: Path, value: Any) -> str:
    data = factory.canonical_json(value)
    if path.exists():
        existing = path.read_bytes()
        if existing != data:
            raise factory.FactoryError(f"immutable source already differs: {path}")
    else:
        factory._atomic_write(path, data)
    return factory.sha256_bytes(data)


def _source_hashes(repo_root: Path) -> dict[str, str]:
    sources = (
        "workstreams/po03/COMMISSION.md",
        "workstreams/po03/contracts/transactional-result.schema.json",
        "workstreams/po03/contracts/wave-compounding.schema.json",
        "workstreams/po03/tools/validate_contracts.py",
        "workstreams/po03/tools/transactional_factory.py",
        "workstreams/po03/tools/check_path_scope.py",
        "workstreams/po03/tests/test_validate_contracts.py",
        "workstreams/po03/tests/test_transactional_factory.py",
        "workstreams/po03/tests/test_path_scope.py",
        ".github/workflows/po03-contracts.yml",
    )
    return {source: factory.sha256_file(repo_root / source) for source in sources}


def _model_for(index: int) -> tuple[str, str]:
    if index % 2:
        return ("claude-opus-5-thinking-high", "high")
    return ("gpt-5.6-sol-xhigh", "xhigh")


def seed(repo_root: Path, run_id: str, branch: str, head_sha: str) -> dict[str, Any]:
    if len(TASKS) != 64 or len({task["id"] for task in TASKS}) != 64:
        raise factory.FactoryError("Wave A must contain exactly 64 unique substantive tasks")
    os.chdir(repo_root)
    control = repo_root / "workstreams" / "po03" / "control"
    source_hashes = _source_hashes(repo_root)
    source_lock = {
        "schema_version": "PO03-SOURCE-LOCK-v1",
        "commission_id": COMMISSION_ID,
        "wave_id": WAVE_ID,
        "repository": "asibrahim336-hash/obzio-ai-coordination-temp",
        "branch": branch,
        "base_head_sha": head_sha,
        "source_sha256": source_hashes,
    }
    _write_exact(repo_root / "workstreams/po03/evidence/source-lock.json", source_lock)
    _write_exact(
        repo_root / "workstreams/po03/evidence/criteria-freeze.json",
        {
            "schema_version": "PO03-CRITERIA-FREEZE-v1",
            "commission_id": COMMISSION_ID,
            "wave_id": WAVE_ID,
            "frozen_before_producer_narratives": True,
            "criteria": [
                "unique falsifiable hypothesis",
                "owned PO-03 path only",
                "immutable input and acceptance hashes",
                "synthetic canary write/read-back before material execution",
                "manifested artifact and executable test",
                "controller ingestion before COMPLETED",
                "independent acceptance by a distinct producer",
            ],
        },
    )
    _write_exact(
        control / "model-capability-register.json",
        {
            "schema_version": "PO03-MODEL-CAPABILITY-v1",
            "observed_at": factory.utc_now(),
            "controller_runtime": {
                "provider": "Cursor Cloud",
                "run_id": run_id,
                "observed_model": "gpt-5.6-terra-max-fast",
            },
            "selector_observation": {
                "claude-opus-5-thinking-high": {
                    "status": "SUPPORTED",
                    "reasoning": "high",
                    "allocation": "lead and independent production",
                },
                "gpt-5.6-sol-xhigh": {
                    "status": "SUPPORTED",
                    "reasoning": "xhigh",
                    "allocation": "independent challenger and production",
                },
                "gemini-3.1-pro": {
                    "status": "NOT_SUPPORTED",
                    "reason": "not exposed by the current native subordinate selector",
                },
                "composer-2.5": {
                    "status": "NOT_SUPPORTED",
                    "reason": "not exposed by the current native subordinate selector",
                },
            },
            "default_policy": "Exact exposed frontier configurations only; Auto is not used.",
        },
    )
    _write_exact(
        repo_root / "workstreams/po03/control/path-ownership.json",
        {
            "schema_version": "PO03-PATH-OWNERSHIP-v1",
            "controller_owned_paths": [
                "workstreams/po03/control/",
                "workstreams/po03/metrics/",
                "workstreams/po03/evidence/",
                "workstreams/po03/research/",
                "workstreams/po03/successor/",
                "receipts/po03/",
                ".github/workflows/po03-*.yml",
            ],
            "subordinate_rule": "Each subordinate owns only its listed result slot in an isolated worktree; it must not write a shared path.",
            "tasks": {
                task["id"]: {
                    "owned_path": f"workstreams/po03/results/wave-a/{task['id']}/",
                    "result_slot": f"workstreams/po03/results/wave-a/{task['id']}/",
                }
                for task in TASKS
            },
        },
    )
    _write_exact(
        repo_root / "workstreams/po03/metrics/metric-definitions.json",
        {
            "schema_version": "PO03-METRICS-v1",
            "unit_required_fields": [
                "task_id",
                "parent_id",
                "function",
                "runtime",
                "model",
                "reasoning",
                "input_sha256",
                "acceptance_sha256",
                "queue_time",
                "active_time",
                "wall_time",
                "checkpoints",
                "result_commit",
                "readback",
                "independent_disposition",
                "recovery_events",
                "collision_events",
            ],
            "unavailable_value": "NOT_SUPPORTED",
            "false_completion_definition": "provider completion or summary without an independently read-back durable result commit",
        },
    )
    _write_exact(
        repo_root / "workstreams/po03/evidence/scale-ladder.json",
        {
            "schema_version": "PO03-SCALE-LADDER-v1",
            "wave_a": {"required_substantive_attempts": 64, "state": "REGISTERED_NOT_DISPATCHED"},
            "wave_b": {"required_substantive_attempts": 128, "state": "NOT_YET"},
            "growth_rule": "Scale only after independently observed zero false completion, zero result loss, and zero path collision.",
        },
    )
    _write_exact(
        repo_root / "workstreams/po03/evidence/model-allocation-and-exceptions.json",
        {
            "schema_version": "PO03-MODEL-ALLOCATION-v1",
            "allocation": [
                {
                    "task_id": task["id"],
                    "model": _model_for(index)[0],
                    "reasoning": _model_for(index)[1],
                }
                for index, task in enumerate(TASKS, start=1)
            ],
            "exceptions": [
                {
                    "family": "gemini-3.1-pro",
                    "state": "NOT_SUPPORTED",
                    "evidence": "not exposed by the current native subordinate selector",
                },
                {
                    "family": "composer-2.5",
                    "state": "NOT_SUPPORTED",
                    "evidence": "not exposed by the current native subordinate selector",
                },
            ],
        },
    )

    seeded: list[str] = []
    for index, task in enumerate(TASKS, start=1):
        task_id = task["id"]
        result_slot = f"workstreams/po03/results/wave-a/{task_id}/"
        model, reasoning = _model_for(index)
        input_path = repo_root / "workstreams/po03/control/inputs/wave-a" / f"{task_id}.json"
        acceptance_path = repo_root / "workstreams/po03/control/acceptance/wave-a" / f"{task_id}.json"
        _write_exact(
            input_path,
            {
                "protocol_version": "OBZIO-WORK-UNIT-v1",
                "commission_id": COMMISSION_ID,
                "wave_id": WAVE_ID,
                "task_id": task_id,
                "function": task["function"],
                "hypothesis": task["hypothesis"],
                "execution_request": task["request"],
                "source_capsule_sha256": source_hashes,
                "model": model,
                "reasoning": reasoning,
                "owned_path": result_slot,
                "result_slot": result_slot,
                "constraints": [
                    "No PO-01 interaction or mutation.",
                    "No writes outside the unique owned path.",
                    "No external outreach, spend, account permission, secret, protected, or strategy-binding act.",
                    "Run the registered canary before material output.",
                    "Return only READY_TO_COMMIT after artifacts and tests are durable.",
                ],
            },
        )
        _write_exact(
            acceptance_path,
            {
                "protocol_version": "OBZIO-ACCEPTANCE-CONTRACT-v1",
                "task_id": task_id,
                "must_prove": [
                    "The stated hypothesis has a falsifiable outcome.",
                    "At least one durable artifact is within the owned result slot.",
                    "A reproducible command or test outcome is recorded.",
                    "A complete result manifest provides byte counts and SHA-256 values.",
                    "Limitations and negative outcomes are explicit.",
                    "No false completion or out-of-allowlist write is claimed.",
                ],
                "independent_acceptance": "A different frontier-family reviewer evaluates the producer result after controller ingestion.",
            },
        )
        if not (control / "events" / f"{task_id}.jsonl").exists():
            factory.create_task(
                control,
                task_id=task_id,
                immutable_input=input_path.relative_to(repo_root),
                acceptance_contract=acceptance_path.relative_to(repo_root),
                model=model,
                reasoning=reasoning,
                owned_path=result_slot,
                result_slot=result_slot,
                idempotency_key=f"{task_id}:attempt-1",
                provider_run_id=f"pending-allocation:{task_id}",
                worker_id=f"subordinate:{task_id}",
            )
        seeded.append(task_id)

    _write_exact(
        control / "recovery-state.json",
        {
            "schema_version": "PO03-RECOVERY-STATE-v1",
            "wave_id": WAVE_ID,
            "recorded_at": factory.utc_now(),
            "registered_tasks": len(seeded),
            "states": {"CREATED": len(seeded)},
            "recovery_required": [],
            "provider_completed_uncommitted_fixture": "PO-02 Code-2 packaging return",
            "provider_completed_uncommitted_state": "UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES / NOT_ACCEPTED",
        },
    )
    _write_exact(
        repo_root / "receipts/po03/2026-08-22/amendment-activation.json",
        {
            "receipt_type": "PO03-AMENDMENT-ACTIVATION-v1",
            "commission_id": COMMISSION_ID,
            "amendment_id": "AMD-COM-PO03-COMPOUNDING-FACTORY-20260822-v002",
            "decision_changed": [],
            "head_sha_before_activation": head_sha,
            "run_id": run_id,
            "branch": branch,
            "transactional_protocol": "ACTIVATED",
            "wave_a_registered": len(seeded),
            "dispatch_state": "AWAITING_SUBORDINATE_CANARY",
            "source_lock_sha256": factory.sha256_file(
                repo_root / "workstreams/po03/evidence/source-lock.json"
            ),
        },
    )
    return {"wave_id": WAVE_ID, "seeded_tasks": seeded, "source_lock": source_lock}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--head-sha")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    head_sha = args.head_sha or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()
    try:
        result = seed(repo_root, args.run_id, args.branch, head_sha)
    except (factory.FactoryError, OSError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(json.dumps({"wave_id": result["wave_id"], "seeded_tasks": len(result["seeded_tasks"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
