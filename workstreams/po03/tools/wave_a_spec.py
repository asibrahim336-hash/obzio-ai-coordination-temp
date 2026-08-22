#!/usr/bin/env python3
"""Deterministically compile the frozen Wave A work-unit catalogue.

Sixty-four counted attempts across the ten standing functions.  Every unit owns
one falsifiable hypothesis, one disjoint subtree, one exact frontier model and
one durable result slot, so path collision is impossible by construction and
the controller remains the only writer of shared PO-03 paths.

Unit identifiers carry the controller run suffix so a concurrently executing
sibling controller cannot collide with this catalogue.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SUFFIX = "b2e7"
ATTEMPT_ROOT = "workstreams/po03/attempts"

# Cohort -> (function, exact model configuration, reasoning control)
COHORTS: dict[str, tuple[str, str, str]] = {
    "c1": ("portable-runtime-and-clean-clone-reproduction", "gpt-5.6-sol-xhigh", "xhigh"),
    "c2": ("current-source-and-supersession-compilation", "claude-sonnet-5-thinking-xhigh", "xhigh"),
    "c3": ("operator-pack-qualification-and-po01-reproduction", "gpt-5.6-sol-xhigh", "xhigh"),
    "c4": ("manifest-provenance-and-changed-path-enforcement", "claude-opus-5-thinking-high", "high"),
    "c5": ("repository-disposition-and-transport-debris", "gpt-5.6-luna-high", "high"),
    "c6": ("transactional-recovery-and-fault-injection", "claude-opus-5-thinking-high", "high"),
    "c7": ("frontier-research-reproduction-and-mechanism-change", "gpt-5.6-sol-xhigh", "xhigh"),
    "c8": ("operating-measurement-evaluation-and-successor", "claude-opus-5-thinking-high", "high"),
}

# (sequence, cohort, slug, falsifiable hypothesis, required executable deliverable)
UNITS: list[tuple[int, str, str, str, str]] = [
    # --- C1 portable runtime and clean-clone reproduction ---
    (1, "c1", "clean-clone-runner",
     "The complete PO-03 suite executes from a fresh clone of an immutable commit with no warm checkout, no provider memory, no /tmp dependency and no uncommitted files.",
     "A runner that clones the repository at an immutable SHA into a caller-supplied directory, executes the discovered PO-03 tests in a child process, and fails closed if the working tree is dirty or any required input is absent."),
    (2, "c1", "hidden-state-detector",
     "A suite that silently depends on uncommitted working-tree state can be detected mechanically rather than by inspection.",
     "A detector that compares a run against the committed tree with a run against a pristine export of the same commit and reports any behavioural divergence as hidden-state dependence."),
    (3, "c1", "nonportable-path-detector",
     "Absolute paths, home-relative paths and machine-specific roots baked into committed PO-03 artifacts are mechanically detectable.",
     "A scanner over committed PO-03 text artifacts that flags absolute filesystem paths, user home references, worktree paths and /tmp references, with an allowlist for deliberate documentation."),
    (4, "c1", "process-boundary-isolation",
     "PO-03 mechanisms carry no cross-invocation in-process state, so a fresh interpreter reproduces identical results.",
     "A harness that runs each mechanism twice in separate interpreter processes with -I and compares canonical outputs byte for byte."),
    (5, "c1", "deterministic-rerun-equivalence",
     "Two independent clean clones of the same immutable commit produce byte-identical canonical outputs.",
     "A double-clone differential runner that normalises timestamps out of canonical output and asserts byte equality, reporting exactly which fields are legitimately non-deterministic."),
    (6, "c1", "interpreter-flag-portability",
     "The PO-03 suite passes under isolated interpreter flags with no third-party packages available.",
     "A matrix runner over python -I and python -I -S that proves the suite is dependency-free and records any import that escapes the standard library."),
    (7, "c1", "network-independence",
     "The PO-03 suite completes with no network egress, so no gate silently depends on a remote fetch.",
     "A runner that executes the suite with network access denied in the child environment and classifies each failure as genuine network dependence or unrelated."),
    (8, "c1", "warm-checkout-adversarial",
     "A gate that only passes because of a warm checkout must be caught by the clean-clone runner rather than reported green.",
     "A deliberately warm-checkout-dependent fixture plus the assertion that the clean-clone runner fails on it, proving the runner has real detection power and is not vacuous."),

    # --- C2 current-source and supersession compilation ---
    (9, "c2", "current-source-compiler",
     "The current operator route can be compiled mechanically from repository pointers rather than inferred from filenames.",
     "A compiler that resolves operations/README.md and the active pointer chain into an explicit ordered current-source set, failing closed when a pointer is missing or unreadable."),
    (10, "c2", "supersession-graph",
     "Supersession relationships across instruction and state files form a directed acyclic graph, and any cycle is a defect.",
     "A supersession graph builder over committed supersedes/superseded_by relations with cycle detection and unreachable-node reporting."),
    (11, "c2", "alias-resolution",
     "Colloquial actor aliases can be resolved to a durable function and appointment, or explicitly refused, without global text replacement.",
     "An alias resolver that maps prohibited routing aliases to function/appointment identifiers, permits them only inside alias, runtime or provenance fields, and reports unresolved aliases as evidence."),
    (12, "c2", "currentness-gate-reproduction",
     "The repository currentness check is reproducible from an immutable commit and its verdict is stable.",
     "A read-only reproduction harness that executes the existing taxonomy currentness script against pinned commits and records verdict, exit code and output hash without modifying any checked surface."),
    (13, "c2", "launch-surface-classifier",
     "Launch surfaces and evidence-only files are mechanically separable, so a superseded file cannot be mistaken for a launch file.",
     "A classifier that partitions instruction-bearing files into launch surface, evidence and ambiguous, and fails closed on ambiguous files lacking an explicit disposition."),
    (14, "c2", "pointer-conflict-adversarial",
     "Two pointers claiming currentness for the same function is a detectable conflict rather than a silent last-writer-wins.",
     "Adversarial fixtures with conflicting and dangling pointers plus assertions that the compiler refuses to emit a current route."),
    (15, "c2", "disposition-completeness",
     "Every superseded file either carries an explicit disposition or is reported as an open defect.",
     "A completeness checker over superseded files that emits a precise list of missing dispositions and never silently deletes or rewrites the underlying evidence."),
    (16, "c2", "semantic-state-contract",
     "The operator state vocabulary can be expressed as an enforceable contract so undefined states cannot enter committed state files.",
     "A state-contract schema plus validator for the operator-system vocabulary used by PO-03, with tests proving an undefined state is rejected."),

    # --- C3 operator-pack qualification and PO-01 reproduction ---
    (17, "c3", "pack-qualification-engine",
     "Operator-pack completeness claims can be independently qualified from an immutable commit without trusting producer narrative.",
     "A qualification engine that reads a pack manifest at a pinned SHA and reports declared-versus-present files, hashes and byte counts as an evidence table."),
    (18, "c3", "missing-file-detection",
     "A pack that declares files it does not contain is detected rather than accepted.",
     "Missing-file detection over pinned pack commits with a synthetic pack fixture proving the detector fires."),
    (19, "c3", "manifest-gap-detection",
     "Files present but undeclared, and declarations without hashes, are both manifest gaps and both detectable.",
     "Bidirectional manifest gap detection reporting undeclared-present and declared-unhashed entries separately."),
    (20, "c3", "pack-nonportable-paths",
     "Pack contents that assume a specific machine or transport layout are detectable before qualification.",
     "A pack-scoped non-portability scanner reporting absolute paths, transport-relative assumptions and unresolvable internal references."),
    (21, "c3", "process-boundary-failure",
     "A pack that only qualifies inside its producing process is detectable by re-qualifying across a process boundary.",
     "A cross-process re-qualification harness that compares in-process and subprocess qualification verdicts and reports divergence."),
    (22, "c3", "po01-claim-reproduction",
     "PO-01 pack claims are reproducible, or refutable, strictly from immutable commits with zero contact or mutation.",
     "A read-only reproduction ledger over pinned PO-01 commits recording each claim, the reproduction attempt, the observed result and an explicit PASS, FAIL, NOT_YET or NOT_SUPPORTED verdict."),
    (23, "c3", "isolated-repair-candidate",
     "A PO-01 defect can be converted into a frozen test and an isolated PO-03 repair candidate without ever touching a PO-01 namespace.",
     "A generator that emits a frozen failing test plus an integration-ready patch candidate held entirely inside the PO-03 namespace, with an assertion that no PO-01 path is written."),
    (24, "c3", "forged-completeness-adversarial",
     "A pack forged to look complete must fail qualification, proving the engine is not merely reading self-reported status.",
     "An adversarial forged-pack fixture whose self-declared completeness contradicts its bytes, plus the assertion that qualification refuses it."),

    # --- C4 manifest, provenance and changed-path enforcement ---
    (25, "c4", "manifest-generator-verifier",
     "Every committed PO-03 artifact is covered by a manifest entry with a matching hash and byte count, and any gap fails closed.",
     "A manifest generator and verifier pair producing MANIFEST-format output with complete hash and byte coverage, failing on any uncovered or mismatched file."),
    (26, "c4", "provenance-chain",
     "Every counted result traces back to its immutable task input and acceptance contract by hash.",
     "A provenance walker that links result documents to their capsule input and acceptance hashes and reports any unrooted artifact."),
    (27, "c4", "changed-path-rejection-fixture",
     "The path-scope guard has real rejection power, demonstrated by a deliberate out-of-allowlist mutation fixture.",
     "A CI-callable fixture that stages a mutation outside the PO-03 allowlist and asserts the guard rejects it with a non-zero exit, alongside the in-allowlist control that passes."),
    (28, "c4", "path-guard-hardening",
     "The path-scope guard resists traversal, symlink, unicode and case-variation evasion.",
     "Hardened guard cases covering .. traversal, absolute paths, backslashes, NUL, unicode confusables, trailing-dot and case-variant spellings of allowlisted prefixes."),
    (29, "c4", "hash-coverage-completeness",
     "Hash and byte-count coverage over counted artifacts is total, so a partially hashed result cannot be counted.",
     "A coverage assertion that enumerates counted artifacts and refuses any result whose manifest omits a hash or byte count."),
    (30, "c4", "tamper-evidence",
     "Mutating a committed artifact after the fact breaks the manifest and the event hash chain.",
     "A tamper test that mutates a committed artifact and asserts both manifest verification and event-chain verification fail."),
    (31, "c4", "clean-ci-suite-gate",
     "The complete PO-03 suite runs in a clean GitHub Actions environment with no repository-local state.",
     "A workflow definition staged for controller installation that runs the aggregate suite, the path-scope guard and the rejection fixture in a clean runner."),
    (32, "c4", "omitted-file-adversarial",
     "A manifest that omits a real file must fail verification rather than report success.",
     "An adversarial omitted-entry fixture plus the assertion that verification fails closed."),

    # --- C5 repository disposition and transport-debris detection ---
    (33, "c5", "disposition-compiler",
     "Every changed PO-03 route can carry exactly one of RETAIN, DELETE, SUPERSEDE, RETEST or REJECT with preserved lineage.",
     "A disposition compiler that assigns and validates one decision per route, enforces lineage continuity and refuses a decision that orphans its predecessor."),
    (34, "c5", "transport-debris-detector",
     "Transport debris left by prior packaging runs is mechanically detectable and distinguishable from live surfaces.",
     "A debris detector over transport and packaging directories that classifies each artifact as live, debris or unresolved, strictly read-only outside the PO-03 namespace."),
    (35, "c5", "orphan-route-detector",
     "A file that no current pointer routes to is an orphan and must be reported rather than assumed current.",
     "An orphan detector that computes pointer reachability and reports unreachable instruction and state files."),
    (36, "c5", "renamed-clone-detector",
     "Renamed clones and duplicated summaries are detectable by content, so they cannot be counted as substantive units.",
     "A content-similarity detector over committed artifacts that flags near-duplicate and renamed-clone pairs with their hashes."),
    (37, "c5", "legacy-alias-census",
     "Prohibited routing aliases can be censused as evidence without any global replacement.",
     "A census that records every legacy alias occurrence with file, line and surrounding field, and explicitly asserts that no replacement was performed."),
    (38, "c5", "lineage-preservation",
     "A supersession that loses its predecessor lineage is a defect and is detectable.",
     "A lineage preservation checker asserting every SUPERSEDE decision names a resolvable predecessor."),
    (39, "c5", "unique-evidence-deletion-guard",
     "Deleting the only copy of depended-upon evidence is refused rather than performed.",
     "A guard that refuses deletion of any artifact that is both unique by content hash and referenced by a current pointer, with tests for both the refusal and the permitted-duplicate case."),
    (40, "c5", "silent-deletion-adversarial",
     "A silent deletion of unique evidence must be caught by the guard, proving it is not advisory.",
     "An adversarial fixture attempting silent unique-evidence deletion plus the assertion that the guard fails closed."),

    # --- C6 transactional recovery and fault injection ---
    (41, "c6", "session-loss-injection",
     "A worker process or session lost mid-flight leaves no false completion and the unit is resumable from immutable input.",
     "Fault injection that kills a worker at each state transition and asserts the recovery scanner marks the unit resumable with no COMPLETED state."),
    (42, "c6", "lost-callback-replay",
     "A lost return message is replayed from durable state rather than losing the result.",
     "A replay test proving a committed-but-unreported result is recovered by scanning durable evidence, with the recovered result ingested exactly once."),
    (43, "c6", "partial-and-commit-failure",
     "A partial write, a pre-commit failure and a post-commit failure each leave a recoverable state and never a false completion.",
     "Injection of truncated writes and failures immediately before and after commit, asserting atomicity of the immutable files and correct recovery classification."),
    (44, "c6", "push-failure-injection",
     "A failure before or after push is distinguishable and recoverable, and a pushed-but-unreported result is not lost.",
     "Injection around the push boundary asserting the result is recovered from the remote when the local report was lost."),
    (45, "c6", "stale-lease-fencing",
     "An expired or superseded worker cannot commit after ownership transfers.",
     "Lease-expiry and fencing tests asserting a stale fence token is refused at ingestion and the transferred holder succeeds."),
    (46, "c6", "duplicate-callback-idempotence",
     "A duplicated callback is harmless and cannot double-count a unit or a metric row.",
     "Idempotence tests asserting repeated ingestion of an identical result produces exactly one registry effect and one metric row."),
    (47, "c6", "corrupt-artifact-recovery",
     "A corrupt or missing artifact is refused at ingestion and routed to recovery rather than accepted.",
     "Corruption and absence injection asserting refusal, RECOVERY_REQUIRED classification and a rerun from immutable input."),
    (48, "c6", "provider-runtime-loss-and-code2-fixture",
     "Entire provider-runtime loss produces PROVIDER_COMPLETED_UNCOMMITTED, never COMPLETED, and the lost PO-02 Code-2 return is a permanent fault fixture rather than a deliverable.",
     "A provider-loss injection plus a frozen PO-02 Code-2 fixture asserting the state is PROVIDER_COMPLETED_UNCOMMITTED, UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES and NOT_ACCEPTED, and that no founder relay is required for recovery."),

    # --- C7 frontier research, reproduction and mechanism change ---
    (49, "c7", "hypothesis-register",
     "At least twelve current external method claims can be stated as falsifiable hypotheses with frozen source identity and a preregistered refutation condition.",
     "A hypothesis register of at least twelve current-method hypotheses, each with source, claim, frozen refutation condition and hash, plus a validator refusing any non-falsifiable entry."),
    (50, "c7", "reproduction-context-admission",
     "Bounded hashed context capsules outperform indiscriminate context dumping on a sanitized Obzio workload.",
     "A measured reproduction comparing bounded-capsule admission against full-dump admission on a sanitized workload, reporting the metric, the effect and an explicit accept or reject."),
    (51, "c7", "reproduction-verifier-first",
     "Freezing acceptance criteria before producer output measurably reduces false-green acceptance.",
     "A reproduction that runs matched accept-after and accept-before-freeze arms over seeded defective results and reports false-green rates."),
    (52, "c7", "reproduction-independent-review",
     "Blind adversarial review by a different model family detects defects that same-family review misses.",
     "A reproduction with seeded defects reviewed blind by two different exposed families, reporting detection rates per family and their disagreement."),
    (53, "c7", "reproduction-outbox-durability",
     "A transactional outbox with read-back verification eliminates the lost-result class that cost the PO-02 Code-2 return.",
     "A reproduction contrasting report-only return with outbox-plus-readback under injected loss, reporting recovered-result fractions for both arms."),
    (54, "c7", "reproduction-checkpoint-granularity",
     "Monotonic checkpointing reduces rework after induced failure relative to all-or-nothing attempts.",
     "A reproduction measuring rework cost across checkpoint granularities under identical injected failures."),
    (55, "c7", "reproduction-scale-versus-acceptance",
     "Raising attempt concurrency without proportional recovery and acceptance capacity degrades independently accepted throughput.",
     "A reproduction sweeping concurrency against fixed acceptance capacity and reporting accepted throughput and escaped-defect rate per level."),
    (56, "c7", "mechanism-change-and-recurrence",
     "At least two reproduced findings can change the live PO-03 mechanism and be locked by recurrence tests that fail if the change regresses.",
     "Two independently supported live mechanism changes staged for controller promotion, each with a recurrence test that fails when the change is reverted, plus an evidence-backed rejection of at least one tempting-but-unsupported change."),

    # --- C8 operating measurement, evaluation and successor generation ---
    (57, "c8", "metric-collection-harness",
     "Every counted unit yields exactly one metric row with no invented values, using NOT_SUPPORTED where the provider exposes nothing.",
     "A metric collection harness emitting one row per counted unit against the frozen metric definitions, with a validator refusing fabricated values and requiring NOT_SUPPORTED plus an observed boundary."),
    (58, "c8", "derived-metrics",
     "Independently accepted throughput, first-pass acceptance, false-green rate, recovery time and coordination overhead are computable from the recorded rows alone.",
     "A derived-metrics computation over the recorded rows with tests on synthetic fixtures of known value, refusing to emit any metric whose inputs are absent."),
    (59, "c8", "adversarial-hidden-cases",
     "Hidden evaluator-held cases detect defects that producer-authored tests miss.",
     "An adversarial hidden-case generator plus the measured detection differential between producer tests and hidden cases on seeded defects."),
    (60, "c8", "blind-review-harness",
     "A reviewer that receives frozen criteria without producer conclusions reaches a different and better-calibrated verdict than one that sees the narrative.",
     "A blind-review harness that strips producer conclusions, records criteria hashes before disclosure, and reports verdict divergence between blind and narrative-exposed arms."),
    (61, "c8", "g0-reconstruction",
     "The pre-amendment controller can be reconstructed from immutable source and measured on the frozen suite.",
     "An executable G0 reconstruction from pinned pre-amendment sources with its measured results on the frozen suite and evaluator-held novel cases."),
    (62, "c8", "g1-packaging",
     "The current transactional factory is executable from a clean clone and measurable on the same frozen suite as G0.",
     "An executable G1 package plus its measured results on the identical frozen suite and holdout cases."),
    (63, "c8", "g2-successor",
     "A successor compiled from G1 failures and accepted lessons outperforms G1 on preregistered metrics with no quality regression.",
     "An executable G2 successor with its lineage to specific G1 failures, its measured results, and an explicit refusal to claim lift absent evidence."),
    (64, "c8", "generation-comparison",
     "Compounding is either demonstrated by measured lift on preregistered metrics with no quality regression, or honestly recorded as NOT_YET.",
     "A generation comparison over G0, G1 and G2 on the frozen suite plus evaluator-held novel cases, emitting a wave-compounding receipt that validates against the seeded schema and states PASS or NOT_YET with exact evidence."),
]


PROMPT_TEMPLATE = """You are executing Obzio work unit `{task_id}` as a subordinate producer under commission {commission}.
You are NOT the coordinator. You may only report READY_TO_COMMIT. You must never set Obzio COMPLETED and must never accept your own work.

FUNCTION: {function}
FALSIFIABLE HYPOTHESIS: {hypothesis}
REQUIRED EXECUTABLE DELIVERABLE: {deliverable}

OWNED SUBTREE (the only path you may create or modify): {slot}/
Place your executable component, its tests, its result document and its artifact manifest inside that subtree. Tests must be named test_*.py and must run under `python -I` with no third-party packages.

A result counts only if it carries a falsifiable hypothesis, an executable component, tests or reproduction evidence, an artifact manifest with SHA-256 hashes and byte counts, and a durable commit that another process reads back by immutable object id. A plan, an inventory, a renamed clone, a duplicated summary or a narrative does not count. If the hypothesis is refuted, record the refutation as the result; a truthful negative is a valid counted outcome and an invented positive is a hard failure.

PROHIBITED: any write outside the owned subtree; any contact with or mutation of PO-01 branches, paths, PRs or artifacts; any write to packs/**, modules/**, _transport/**, state/**, dispatch/**, .cursor/environment.json, PR #8 or branch cursor/setup-dev-environment-b5ce; any merge, promotion or force-push; any modification of workstreams/po03/control/**, workstreams/po03/evidence/**, workstreams/po03/metrics/**, receipts/po03/** or another unit's subtree; treating /tmp as evidence; inventing a metric, a hash, a model identity or a provider capability."""


def build_spec(run_id: str, head_sha: str) -> dict:
    units = []
    for sequence, cohort, slug, hypothesis, deliverable in UNITS:
        function, model, reasoning = COHORTS[cohort]
        task_id = f"po03-wa-{SUFFIX}-{sequence:03d}-{slug}"
        slot = f"{ATTEMPT_ROOT}/{task_id}"
        acceptance = {
            "acceptance_version": "PO03-WAVE-A-UNIT-ACCEPTANCE-v1",
            "task_id": task_id,
            "cohort": cohort,
            "function": function,
            "falsifiable_hypothesis": hypothesis,
            "required_deliverable": deliverable,
            "criteria": [
                "executable component exists inside the owned subtree and runs under python -I",
                "tests or reproduction evidence execute and their outcome is recorded verbatim",
                "artifact manifest lists every artifact with SHA-256 and exact byte count",
                "result document conforms to OBZIO-TRANSACTIONAL-RESULT-v1",
                "result is committed and read back by a different process from an immutable object id",
                "hypothesis receives an explicit PASS, FAIL, NOT_YET, NOT_SUPPORTED or OWNER_BLOCKED verdict",
                "a refuted hypothesis is recorded as a refutation rather than restated as success",
                "no value, hash, metric or provider capability is invented",
            ],
            "forbidden": [
                "writes outside the owned subtree",
                "PO-01 contact or mutation",
                "PR #8 mutation",
                "merge, promotion or force-push",
                "worker-set COMPLETED or self-acceptance",
                "treating /tmp or provider memory as durable evidence",
            ],
            "decision_changed": [],
        }
        units.append(
            {
                "task_id": task_id,
                "cohort": cohort,
                "function": function,
                "model": model,
                "reasoning": reasoning,
                "hypothesis": hypothesis,
                "deliverable": deliverable,
                "owned_paths": [f"{slot}/**"],
                "result_slot": slot,
                "lease_seconds": 14400,
                "acceptance": acceptance,
                "prompt": PROMPT_TEMPLATE.format(
                    task_id=task_id,
                    commission="COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
                    function=function,
                    hypothesis=hypothesis,
                    deliverable=deliverable,
                    slot=slot,
                ),
            }
        )
    return {
        "spec_version": "PO03-WAVE-A-SPEC-v1",
        "wave": "A",
        "run_id": run_id,
        "controller_head_sha": head_sha,
        "unit_count": len(units),
        "cohorts": {
            cohort: {"function": function, "exact_model": model, "reasoning": reasoning}
            for cohort, (function, model, reasoning) in COHORTS.items()
        },
        "collision_policy": "one disjoint owned subtree per unit; controller is the only writer of shared paths",
        "decision_changed": [],
        "units": units,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    spec = build_spec(args.run_id, args.head_sha)
    if len({unit["task_id"] for unit in spec["units"]}) != len(spec["units"]):
        raise ValueError("duplicate task ids in Wave A catalogue")
    if len({unit["result_slot"] for unit in spec["units"]}) != len(spec["units"]):
        raise ValueError("duplicate result slots in Wave A catalogue")
    payload = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    Path(args.out).write_text(payload, encoding="utf-8")
    print(json.dumps({"units": spec["unit_count"], "out": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
