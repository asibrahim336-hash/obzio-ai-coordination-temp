#!/usr/bin/env python3
"""Emit the OE-W4 de-restriction register.

The register is generated rather than hand-written so that the classification set
is reproducible and so that a reviewer can diff the source of a verdict rather
than the rendered JSON. Run:

    python3 tools/build_derestriction_register.py --out DE-RESTRICTION-REGISTER-20260822-v001.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REGISTER_ID = "OE-W4-DERESTRICTION-REGISTER-20260822-v001"
LANE = "OE-W4-PLATFORM-ROLES"
COMMISSION = "COM-CUR-ENV-01-20260822-v001"
BASE_SHA = "3f3ee110cf9b769e60c664f758c437dcc582afd3"

OE = "workstreams/so02/control-plane/operating-environment"
CP = "workstreams/so02/control-plane"

# --------------------------------------------------------------------------
# FOUNDER_BOUND — traceable to direct founder intent. Retained. Not removable.
# --------------------------------------------------------------------------

FOUNDER_BOUND = [
    (
        "FB-01",
        "SW remains paused: not messaged, operated, configured, commissioned or made central without a separate founder reactivation.",
        "role",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#estate-and-runtime-allocation",
        "The founder paused SW before its first message because the available operation was not yet strategically controlled. Recorded as a reversible routing pause, not a rejection of the platform. Cursor may evaluate the eventual reactivation mechanism; it may not initiate contact.",
        "DOCUMENTED",
    ),
    (
        "FB-02",
        "The SO-02 founder browser/setup batch is halted and preserved as historical candidate evidence only.",
        "tooling",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#founder-operating-environment-rolescope-correction",
        "Named in the founder role/scope correction FOUNDER-ROLE-SCOPE-20260822T173520Z and carried in decision_changed. L2 independently re-derived two of the batch's components through a capability-first route; the lane correctly recorded that as a coincidence of conclusions rather than a revival.",
        "DOCUMENTED",
    ),
    (
        "FB-03",
        "For the founder operating environment scope specifically, ChatGPT does not select architecture, prescribe a named stack, or issue a founder setup batch.",
        "role",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#estate-and-runtime-allocation",
        "This limit is scoped by its own founder text to the founder operating environment. It is retained exactly at that width and is not a general statement about what ChatGPT may do. See AI-06 for the unscoped generalisation, which is removed.",
        "DOCUMENTED",
    ),
    (
        "FB-04",
        "Maintain at least ten working ChatGPT projects as supporting research, assurance and continuity lanes with durable return routes.",
        "scope",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#estate-and-runtime-allocation",
        "A floor, not a ceiling. The founder's later statement that ChatGPT can be launched at scale across multiple projects, models, teams and functions confirms the direction of the inequality. See AI-14 for the ceiling that was read into it.",
        "DOCUMENTED",
    ),
    (
        "FB-05",
        "The founder must never perform routine retrieval, monitoring, evidence comparison, merging or coordination that the platforms can do themselves.",
        "role",
        "FOUNDER-AUTHORITY-20260822T2225Z.json#restrictions_removed.specific_derestrictions_applied_now[2]",
        "Stated twice by the founder in different words: 'Do not make the founder a routine relay, monitor, comparison engine or merger' in the operating directives, and 'routine retrieval, monitoring, comparison, merging and coordination must not be sent to him at all' in the derestriction record. This is a prohibition on a class of task, and is a different axis from the volume of founder involvement.",
        "DOCUMENTED",
    ),
    (
        "FB-06",
        "Do not suppress a high-leverage founder action merely to minimise founder involvement; founder workload must not be artificially minimised.",
        "pace",
        "FOUNDER-AUTHORITY-20260822T2225Z.json#restrictions_removed.specific_derestrictions_applied_now[2]",
        "The pair to FB-05 and the reason the touch-point budget was withdrawn: the two axes were being conflated. A genuinely consequential founder decision is not rationed; a routine retrieval is not sent at all.",
        "DOCUMENTED",
    ),
    (
        "FB-07",
        "No provider holds canonical state. The repository is canonical and models and runtimes must remain substitutable.",
        "topology",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#orchestration-topology-and-resumable-surfaces",
        "Independently reinforced by a provider fact: the OpenAI conversation object holds only id, created_at, metadata and object, with metadata capped at 16 pairs of 64/512 characters. The provider's own object cannot hold provenance even if policy allowed it.",
        "DOCUMENTED",
    ),
    (
        "FB-08",
        "Provider memory is never constitutional authority.",
        "topology",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#successors-knowledge-and-governance",
        "Retained. The cold-instance replay test in the L5 programme is an adequate mechanisation of it and is kept.",
        "DOCUMENTED",
    ),
    (
        "FB-09",
        "Never create an exclusive dependency on Cursor or SW.",
        "topology",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#orchestration-topology-and-resumable-surfaces",
        "Retained, and it is the reason the role architecture assigns Cursor a function rather than a monopoly: every role in the W4 architecture names a substitution route.",
        "DOCUMENTED",
    ),
    (
        "FB-10",
        "Record a stable provider URL or exact ID for every surface that must be found again. A display name or 'current conversation' is not a locator. An unexposed surface is recorded NOT_EXPOSED; do not invent one.",
        "evidence",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#orchestration-topology-and-resumable-surfaces",
        "Founder-stated and independently defect-backed: see EC-24, where two alias locators are still live in control-plane.json.",
        "DOCUMENTED",
    ),
    (
        "FB-11",
        "Protected surfaces are untouchable: PO-01, PO-03, MANUS, main, the SO-02 source branch, and PRs #6, #7 and #9.",
        "scope",
        "FOUNDER-AUTHORITY-20260822T2225Z.json#what_this_authority_does_not_alter",
        "Explicitly excluded from the derestriction by the founder in the same record that removed the other limits. L1's decision not to call batch-fetch-details at all, rather than to call it carefully, is the correct reading of this boundary.",
        "DOCUMENTED",
    ),
    (
        "FB-12",
        "No merge, promotion or company-strategy binding follows from operating work.",
        "scope",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#active-execution-controls",
        "Retained without qualification. Role architecture is an operating decision; company strategy is not.",
        "DOCUMENTED",
    ),
    (
        "FB-13",
        "Do not bind a named tool, model or architecture without a founder decision.",
        "tooling",
        f"{CP}/commissions/CURSOR-OPERATING-ENVIRONMENT-01.md#immediate-correction",
        "Retained. Note the asymmetry that keeps this from becoming a stall: recommending, qualifying, dry-running and specifying a named component are all permitted; only binding is reserved.",
        "DOCUMENTED",
    ),
    (
        "FB-14",
        "The founder interface is voice-first: speech intake, semantic strengthening, read-back of consequential interpretation, intent/authority confirmation, typed durable event, delegated execution, consolidated evidence return.",
        "topology",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#founder-interface-and-activation",
        "Retained and load-bearing for the role architecture: it is the reason founder-intent capture is assigned to the platform the founder actually speaks to rather than to the platform that holds the repository.",
        "DOCUMENTED",
    ),
    (
        "FB-15",
        "Every reply or turn must end with a changed live operation or an immediately launchable executable, plus evidence. A register-only, receipt-only, schema-only, test-only or automation-only turn fails.",
        "pace",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#active-execution-controls",
        "Retained, and applied to this lane against itself: the de-restriction register ships with derestrictctl.py, which mechanically detects re-inheritance and did not previously exist.",
        "DOCUMENTED",
    ),
    (
        "FB-16",
        "The deferred disclosure workstream builds nothing now: no disclosure register, schema, scanner, test, branch, Manus control or Cursor change.",
        "scope",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#deferred-disclosure-factory-workstream",
        "Retained. L5's decision to register F-DISCLOSURE as REGISTERED_DEFERRED with an owner and an activation trigger, building nothing, is the correct handling: it holds the gap open so nothing improvises into it.",
        "DOCUMENTED",
    ),
    (
        "FB-17",
        "The earlier Qwen / Kimi / DeepSeek / Grok model allocation is neither silently deleted nor newly bound. Recover its authority and currentness, test exact routes, and discuss any consequential conflict before freezing the design.",
        "tooling",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#estate-and-runtime-allocation",
        "This is an explicit founder non-decision and must be preserved as one. The live evidence sharpens the question rather than answering it: Kimi K3 is about 2.78 trillion parameters and unreachable on any laptop, so 'open weights' and 'runnable by us' select different families.",
        "DOCUMENTED",
    ),
    (
        "FB-18",
        "The Claude browser-extension route is unavailable for the current run. Do not infer that the Claude model or the SW platform is low quality, and do not make a quota refill the default next action.",
        "tooling",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#founder-operating-environment-rolescope-correction",
        "Retained exactly as stated, including the two inferences the founder prohibited.",
        "DOCUMENTED",
    ),
    (
        "FB-19",
        "Secrets are never printed, echoed into argument vectors, or requested in chat. Reuse over duplication.",
        "credential",
        "FOUNDER-AUTHORITY-20260822T2225Z.json#standing_operating_rules_now_in_force.credential_discipline_retained",
        "Explicitly retained inside the derestriction record itself. The reuse-over-duplication half is what makes AI-02 a violation rather than merely an inefficiency.",
        "DOCUMENTED",
    ),
    (
        "FB-20",
        "Self-acceptance of produced evidence is prohibited; provider activity and completion are status, never acceptance.",
        "evidence",
        "FOUNDER-AUTHORITY-20260822T2225Z.json#what_this_authority_does_not_alter",
        "Explicitly excluded from the derestriction. It is also the one control whose value was demonstrated within hours: an independent acceptor refused this programme's own evidence and two defects were reproduced from the refusal.",
        "DOCUMENTED",
    ),
    (
        "FB-21",
        "Spend commitment, identity and secrets, third-party outreach, SW reactivation and programme shape remain founder-held decision classes.",
        "scope",
        "AGENTS.md#7",
        "Restated identically in the repository-wide operator instructions and in the founder's stop-condition list. Functions may compare, cost and recommend inside these classes; only the founder commits.",
        "DOCUMENTED",
    ),
    (
        "FB-22",
        "Cursor is the current strategic operator interface for this scope, not the permanent brain and not the canonical state store.",
        "role",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#estate-and-runtime-allocation",
        "Retained. This constrains Cursor's permanence, not its scale. The founder's separate statement that Cursor is an agent platform rather than one agent is about scale and is not in tension with this.",
        "DOCUMENTED",
    ),
    (
        "FB-23",
        "Nothing is deleted. Superseded files remain evidence; add an explicit disposition rather than removing unique evidence.",
        "evidence",
        "AGENTS.md#9",
        "Repository-wide operator instruction, restated in L4's disposition proposals, which retain 80 abandoned tips and 65 orphaned lease refs as evidence while excluding them from the scale denominator.",
        "DOCUMENTED",
    ),
    (
        "FB-24",
        "Choosing between the competing pointer claims in PR #6 and PR #7 is a founder-bound act, not a compilation result.",
        "scope",
        f"{OE}/l4-currentness-recovery/diagnosis/DIAGNOSIS-L4-20260822-v001.md#what-could-not-be-determined-and-why",
        "The compiler is right to refuse. Both PRs are open against main and rewrite the same pointer files with different bytes, so whichever merges first silently sets currentness for the other.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "FB-25",
        "Stop for explicit boundaries only: third-party outreach, new spend or obligation, secrets or owner identity acts, new external OAuth or account permissions, protected production/security/DNS/deployment mutation, depended-upon permanent deletion, and substantive strategy binding.",
        "scope",
        "AGENTS.md#7",
        "This is the authoritative boundary list and it is deliberately short. Everything not on it proceeds decisively across verified Ahmed/Obzio-owned in-scope surfaces. Several removed constraints in this register are removed precisely because they invented a stop that is not on this list.",
        "DOCUMENTED",
    ),
    (
        "FB-26",
        "Produce a comprehensive staged programme and guide the founder through it incrementally, with a deliberate stop/evaluate gate at each consequential choice point, and discuss consequential alternatives before freezing them.",
        "pace",
        f"{CP}/commissions/CURSOR-OPERATING-ENVIRONMENT-01.md#3-guide-staged-human-implementation",
        "Retained, and distinguished carefully from AI-01: a stop/evaluate gate at a consequential choice point is founder-directed; a gate that blocks unrelated work until an unrelated tranche is evaluated is not.",
        "DOCUMENTED",
    ),
    (
        "FB-27",
        "Return no founder action until the relevant assumptions are verified.",
        "pace",
        f"{CP}/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md#founder-operating-environment-rolescope-correction",
        "Founder-stated, and the rule AI-02 broke. A duplicate credential was requested from the founder without first verifying whether one already existed and whether a route to it was reachable.",
        "DOCUMENTED",
    ),
]

# --------------------------------------------------------------------------
# EARNED_CONTROL — agent-invented, but demonstrably caught a real defect here.
# --------------------------------------------------------------------------

EARNED = [
    (
        "EC-01",
        "Every lane takes its own git worktree at dispatch. Two agents may not share one working tree.",
        "topology",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#1",
        "A live shared-worktree collision. All five OE lanes were subagents in one VM sharing one git repository; L1 and L5 both worked in the shared /workspace checkout whose HEAD was detached at 20:20:34Z. Three commits from two lanes interleaved on that one detached HEAD, so L1's second commit carried an L5 commit as an ancestor. Recovered inside the same run by git worktree add plus cherry-picking only L1's commits.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-l1-cursor-baseline/raw/shared-worktree-collision.txt",
    ),
    (
        "EC-02",
        "A zero exit from git push is not evidence that anything was published. Confirm publication with git ls-remote.",
        "evidence",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#1",
        "The same collision, and the more dangerous half of it. Because a commit on a detached HEAD advances no branch, both lanes' refs stayed at the immutable base and git push -u printed 'Everything up-to-date' and exited 0. A lane trusting that exit code reports READY_TO_COMMIT while the reconciling controller reads an empty branch.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-l1-cursor-baseline/raw/shared-worktree-collision.txt",
    ),
    (
        "EC-03",
        "Manifest material closure: every file in the bundle and every material claim input outside it is manifested, including the read-back record.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#criterion_findings[AC-03]",
        "AC-03 FAIL. Listed-entry hashes, sizes, count and bundle digest all reproduced, but material closure did not: REMOTE-READBACK.json was in the bundle and omitted from the manifest, and the changed workflow, control-plane.json, events.jsonl and runtime-surface-locators.json were material unmanifested claim inputs. An independent acceptor refused the bundle partly for this.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/INDEPENDENT-VERIFICATION-REPORT.json",
    ),
    (
        "EC-04",
        "Read-back is by recomputation against a remotely existing immutable commit, an exact manifest digest and an exact entry set. Assertion-shaped booleans are rejected.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#criterion_findings[AC-05]",
        "AC-05 FAIL. Replacing REMOTE-READBACK.json with a no-network synthetic record naming an all-zero commit, invented transports and a non-manifest path still made the unmodified producer verifier exit 0. A wholly fabricated read-back passed the gate that existed to detect fabrication.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/ADVERSARIAL-TESTS.md",
    ),
    (
        "EC-05",
        "The capacity and interference detector allowlists the states that mean non-interference. ERROR and every other degraded transition counts as interference.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#criterion_findings[AC-08]",
        "AC-08 FAIL. A synthetic IDLE-to-ERROR regression silently passed the producer's detector as ZERO_PO03_CAPACITY_INTERFERENCE while independent strict recomputation returned CAPACITY_INTERFERENCE_FAIL. This lane additionally reproduced that the failure class is live and not hypothetical: one agent on this repository is in ERROR status right now.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/cursor-agent-inventory.json",
    ),
    (
        "EC-06",
        "Independent acceptance is constituted from isolated context, criteria committed before the verdict, a distinct model identity, adversarial tests, evidence custody, and a prohibition on reading the producing run's transcript.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json",
        "The acceptor refused. Criteria were committed at 9a390df3 before the verdict, the lane ran on gpt-5.6-sol-xhigh against a producer on the Claude family, producer_transcript_or_run_events_read is false, and the verdict is REFUSED with six criterion FAILs. Two of those FAILs were then reproduced directly by the root controller against its own tooling. Corroborated a second time by L4, which never read the verdict and landed the same workstream at PROPOSED by mechanical compilation.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/ACCEPTANCE-CRITERIA.json",
    ),
    (
        "EC-07",
        "The producer may not author the acceptance assertions. CI that executes producer-written checks is reproducibility, not independent corroboration.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#criterion_findings[AC-12]",
        "AC-12 FAIL. GitHub Actions independently executed the bytes on another machine, but the producer authored the workflow addition, the verifier, the tests, the manifest scope and the success assertions, and the cited run checked a PR merge ref rather than the receipt's claimed immutable head. The forged read-back accepted locally would also have passed that CI.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/INDEPENDENT-VERIFICATION-REPORT.json",
    ),
    (
        "EC-08",
        "A verdict must not be rewritten after commit. A changed assessment is an additive superseding record that preserves the original.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#post_commit_mutation_rule",
        "This is the control that let a refusal survive being inconvenient. Without it the refusal recorded above could have been amended by the party it refused, and the two reproduced defects would never have entered the record.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/VERDICT.json",
    ),
    (
        "EC-09",
        "Write scope is fenced client-side, per lane, by a refusing hook rather than by prose.",
        "scope",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#5",
        "Reproduced twice over. The gh CLI holds a GitHub App installation token whose administration permission returns 403, so no agent can read, let alone set, branch protection: server-side enforcement of the protected-branch rule is unavailable from inside an agent. And EC-01 shows that a lane can contaminate another lane's branch with an exit code of zero. Client-side refusal is the only enforcement surface that exists here.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-l1-cursor-baseline/raw/",
    ),
    (
        "EC-10",
        "Exactly one shared-state writer. Without a deterministic controller, isolated work continues and shared writes fail closed.",
        "topology",
        f"{CP}/state/control-plane.json#multi_parent_execution_contract",
        "The collision in EC-01 is the instance: two writers on one tree produced a projection whose declared denominator diverged from the actual one. The fail-closed rule is what stops that divergence from being silent.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md",
    ),
    (
        "EC-11",
        "A subordinate lane may return only READY_TO_COMMIT. Provider completion without a committed artifact stays PROVIDER_OBSERVED indefinitely and is reported that way.",
        "evidence",
        f"{OE}/l4-currentness-recovery/diagnosis/DIAGNOSIS-L4-20260822-v001.md#admission-state-per-workstream",
        "WS-V010-FULLSCALE-CHATGPT claims DURABLE and is admitted at PROPOSED. Its payload hashes verify exactly, but its result side names a Supabase registry and three Drive receipts that are not in the canonical store, and the transport is a founder-assisted paste separately recorded as FAILED_NOT_BYTE_IDENTICAL.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l4-currentness-recovery/projection/CURRENT-STATE-PROJECTION-20260822-v001.json",
    ),
    (
        "EC-12",
        "A currentness resolver refuses to answer when competing claims exist. It does not pick the newest, the nearest or the majority.",
        "evidence",
        f"{OE}/l4-currentness-recovery/tools/currentctl.py",
        "Reproduced by this lane against the live estate: validate reports COMPETING_CURRENTNESS_CLAIM=4, and resolve --scope pointer.operator-system refuses with three competing blobs across eight branches. Seven branches agreeing against one is still unresolved, because agreement by copying is not authority.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/currentctl-validate.txt",
    ),
    (
        "EC-13",
        "state/**, operations/**, dispatch/** and modules/work_unit_contract/** are prohibited paths on this branch lineage until pointer reconciliation lands.",
        "scope",
        f"{CP}/state/control-plane.json#global_pointer_state",
        "The same four competing currentness claims. Writing any of those paths from this lineage would silently set global currentness for every branch that inherits it, which is the estate's signature failure rather than a hypothetical one.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/currentctl-validate.txt",
    ),
    (
        "EC-14",
        "Branch existence, file counts, ZIP archives, open pull requests, agent existence, acknowledgements, provider completion and receipt counts cannot advance an admission rung.",
        "evidence",
        f"{OE}/l4-currentness-recovery/ledger/admission-ladder.json",
        "Reproduced live: NON_ADMISSIBLE_EVIDENCE_OFFERED=21 and ADMISSION_OVERCLAIM=8 against the current tree, with eight of sixteen workstreams claiming more than their evidence supports and nothing anywhere reaching DURABLE.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/currentctl-validate.txt",
    ),
    (
        "EC-15",
        "Decision classes are partitioned with exactly one holder each, and programme shape is a reserved class no function may claim.",
        "role",
        f"{OE}/l5-chatgpt-scale/FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json#anti_overlap_mechanism",
        "Reproduced live in both directions. Against the estate: UNDIFFERENTIATED_COMMISSION_OVERLAP=7 and COMMISSION_ID_COLLISION=1, including two commissions asserting whole-operation authority over the same paths with no supersession edge. Against the mechanism: negative tests NT1 and NT2 inject exactly those two failures and the validator rejects both.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/l5-register-checks.txt",
    ),
    (
        "EC-16",
        "A function may not name itself its own acceptance owner, and an assurance container may not host a producing function.",
        "role",
        f"{OE}/l5-chatgpt-scale/scripts/negative_tests_register.py",
        "Negative tests NT3 and NT5 reproduce both rejections. The live instance is AC-12: the producer authored the assertions that graded it, which is self-acceptance wearing a CI badge.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/l5-register-checks.txt",
    ),
    (
        "EC-17",
        "Every admitted function carries a pre-registered falsifier and an exit condition.",
        "role",
        f"{OE}/l5-chatgpt-scale/scripts/check_function_register.py",
        "Negative test NT6 reproduces the rejection of a warrant with no falsifier. The estate-side defect it addresses is recorded by L4 as 'lessons documented without changing the actual mechanism', probed by NonAdmissibleEvidenceTests.test_documented_lesson_that_changes_no_gate_cannot_advance_state.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/l5-register-checks.txt",
    ),
    (
        "EC-18",
        "Lineage, acceptance and coordination state must not live in the Cursor per-run agent store at /cursor/stores/self.",
        "topology",
        f"{OE}/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json#explicitly_not_recommended[0]",
        "Reproduced: the store is a FUSE mount keyed to the run's bcId, only self is mounted, foreign store paths fail to be created with No such file or directory rather than a permission error, and nothing in it is visible to the founder, to CI or to any independent acceptor. The probe cleanup additionally destroyed two pre-existing platform CI deliveries, demonstrating the durability class directly.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-l1-cursor-baseline/raw/store-inspect.txt",
    ),
    (
        "EC-19",
        "Do not add chromeExecutablePath, image, egressMode, egressAllowlist, containerRuntime or build.dockerfileContents to .cursor/environment.json.",
        "tooling",
        f"{OE}/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json#explicitly_not_recommended[1]",
        "Reproduced: the live schema rejects all six under unevaluatedProperties:false, despite Cursor's own bundled skill listing them as common fields. Following the vendor's own documentation here produces an invalid file.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l1-cursor-baseline/CURSOR-OPERATING-BASELINE-REGISTER.json",
    ),
    (
        "EC-20",
        "The cursor-cloud run event log is not an audit trail.",
        "evidence",
        f"{OE}/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json#explicitly_not_recommended[2]",
        "Reproduced: over a run spanning 13:31Z to 20:15Z the event log contained two entries, both pr_created. It records provider-side milestones and nothing about what the agent did, so an operation that treated it as coverage would be claiming an audit it does not have.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l1-cursor-baseline/CURSOR-OPERATING-BASELINE-REGISTER.json",
    ),
    (
        "EC-21",
        "Event subscriptions are a wake-up mechanism, not a durable channel. Addressable retrieval by immutable SHA stays the primary path.",
        "topology",
        f"{OE}/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json#explicitly_not_recommended[3]",
        "Reproduced: list_subscriptions returned zero active subscriptions, so the CI subscription relied on during CUR-01 had already expired or closed, and its deliveries survived only in a per-run store that no later run can address.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l1-cursor-baseline/CURSOR-OPERATING-BASELINE-REGISTER.json",
    ),
    (
        "EC-22",
        "HTTP status is the discriminator for what a GitHub token can do. The X-Accepted-Github-Permissions header and the permissions object on GET /repos are not.",
        "evidence",
        f"{OE}/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json#explicitly_not_recommended[4]",
        "Reproduced: every GET reports '=read' in the header regardless of the token, and GET /repos returns permissions all-false for an installation token that a successful push dry-run proves can write. Both traps produce confident wrong conclusions in opposite directions.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l1-cursor-baseline/CURSOR-OPERATING-BASELINE-REGISTER.json",
    ),
    (
        "EC-23",
        "An unconfirmed transcription must be read back before it enters a durable instruction.",
        "evidence",
        f"{OE}/l2-capability-research/NAME-RESOLUTION.json",
        "The Aircrift/Aircraft seed. It resolved to no real product across GitHub repositories, users and organisations, the Chrome Web Store, npm, PyPI and DNS, and is recorded UNRESOLVED rather than guessed at. An unconfirmed transcription entered a work order and survived several hands unchallenged.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l2-capability-research/NAME-RESOLUTION.json",
    ),
    (
        "EC-24",
        "A locator is a URL or an exact ID. A display alias is not a locator.",
        "evidence",
        f"{OE}/l4-currentness-recovery/tools/currentctl.py",
        "Reproduced live: ALIAS_USED_AS_LOCATOR=2 against the current tree. The CGPT-01 runtime binding still carries provider_locator 'current_project_conversation' and launch_receipt 'current-founder-appointment', neither of which is a path or a stable ID, so the binding is admitted at PROPOSED.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/currentctl-validate.txt",
    ),
    (
        "EC-25",
        "Coordination primitives such as lease and canary refs are never counted as delivered scale.",
        "evidence",
        f"{OE}/l4-currentness-recovery/tools/currentctl.py",
        "Reproduced live: COORDINATION_TOKENS_COUNTED_AS_SCALE=1, with 65 orphaned po03 lease and canary refs that have no trunk ancestry and hold a single file each. They are real recovery evidence and they are not work.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-w4-platform-roles/raw/currentctl-validate.txt",
    ),
    (
        "EC-26",
        "Route paths and model identifiers are discovered at runtime from published indexes, never recalled or guessed, and an exact model is never inferred from an alias.",
        "evidence",
        f"{OE}/l5-chatgpt-scale/OPENAI-API-SURFACE-FINDINGS-20260822-v001.md#0",
        "Reproduced inside L5's own work: a first pass that guessed plausible documentation paths produced 24 404s out of 34, including a conversations retrieval route that does not exist. Guessing would have put a wrong route into an activation programme handed to the founder.",
        "DIRECTLY_REPRODUCED",
        "receipts/so02/2026-08-22/oe-l5-chatgpt-scale/raw/openai-doc-fetch-log.json",
    ),
    (
        "EC-27",
        "As a claim standard, two routes are independent only when they do not share a controller, a failure domain and a custody dependency. Transport diversity is not independence.",
        "evidence",
        f"{OE}/l3-independent-acceptance/VERDICT.json#criterion_findings[AC-07]",
        "AC-06 and AC-07 FAIL. R2 queried the producing run itself while it was still RUNNING, returned zero events, committed neither raw provider artifact, and depends on R1 and GitHub for durable custody. A single compromised producer could manufacture both records. The PASS_TWO_OR_MORE_ROUTES claim was withdrawn as a result. Retained as the standard a claim must meet; see AI-09 for the same requirement used as a gate on work, which is removed.",
        "DIRECTLY_REPRODUCED",
        f"{OE}/l3-independent-acceptance/INDEPENDENT-VERIFICATION-REPORT.json",
    ),
]

# --------------------------------------------------------------------------
# ASSISTANT_IMPOSED — invented by an assistant, no defect evidence. Removed.
# --------------------------------------------------------------------------

REMOVED = [
    (
        "AI-01",
        "Nothing beyond founder tranche 01 may be prescribed until tranche 01 is evaluated.",
        "sequencing",
        f"{OE}/FOUNDER-TRANCHE-01.md:3 and #the-gate-before-tranche-02 (lines 117-125)",
        "Written by the reviewing assistance as a self-imposed stage gate. No defect in this estate is attributable to work proceeding in parallel; the reproduced defects are all evidence-integrity defects, none of which sequencing would have caught.",
        "Tranche-02-class work proceeds immediately for everything that does not rest on a genuinely unverified assumption. Concretely: the platform role architecture, the acceptance constitution, the salvage design and the Cursor configuration application all stop waiting on an unrelated credential answer.",
        "Sequencing is retained only where the dependency is real. The register records, per removed gate, the specific assumption that would have to be unverified for the gate to be legitimate.",
        "DOCUMENTED",
    ),
    (
        "AI-02",
        "The founder must issue a new Cursor API key at cursor.com/dashboard/api and store it as a repository-scoped secret.",
        "credential",
        f"{OE}/FOUNDER-TRANCHE-01.md#oa-a-issue-a-cursor-api-key and {OE}/l1-cursor-baseline/CONTROL-SURFACE-ACTIVATION-PROGRAMME.json#FA-CUR-API-01",
        "The founder states a Cursor API key already exists in Supabase Edge Secrets. Requesting a duplicate is prohibited as wasteful and as a credential-proliferation risk, and it breaks FB-27 by returning a founder action against an unverified assumption. This lane additionally reproduced what the real blocker is: CURSOR_API_KEY is absent from this runtime by name census, and the Supabase MCP namespace that would reach the existing secret is present but reports needsAuth.",
        "The founder action shrinks from creating and scoping a new credential to authorising one already-configured integration. The estate stops accumulating duplicate keys, and the Cursor Agent API route becomes reachable through a credential Obzio already controls.",
        "FB-19 reuse-over-duplication is retained, and the replacement action is recorded as an owner act under FB-25 because authorising an external OAuth integration is on the founder's own stop list.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-03",
        "A per-wave founder touch-point budget sizes tranches, and F-LOAD may reject an over-budget design.",
        "touchpoint",
        f"{OE}/FOUNDER-TRANCHE-01.md:4 and #questions-that-need-your-judgment-ranked (Q7), plus {OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#9 and #14",
        "Withdrawn by the founder as a self-imposed limit. It conflated two different axes: the volume of founder involvement, which must not be artificially minimised, and the class of task sent to the founder, which must never be routine retrieval, monitoring, comparison, merging or coordination.",
        "High-leverage founder decisions are no longer rationed against a budget, and a design is no longer rejected for asking too much of the founder when what it asks is genuinely founder-bound.",
        "F-LOAD is re-specified rather than deleted: it becomes a routine-verb detector that refuses any design whose return route requires the founder to relay, retrieve, compare, merge or monitor, and it holds no cap on decisions. That is FB-05 mechanised, with FB-06 preventing the opposite failure.",
        "DOCUMENTED",
    ),
    (
        "AI-04",
        "The staged Cursor configuration is held outside .cursor/ and remains inert pending an explicit founder act.",
        "sequencing",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#what-to-change and {OE}/l1-cursor-baseline/proposed-cursor-config/APPLY.md",
        "The founder has authorised application on non-protected branches under the granted configure-and-optimise authority. The gate was invented; the underlying observation was not.",
        "Hooks, rules, skills, the environment file and the write-scope guard can be applied on a non-protected branch now. This matters more than any other unlock in the register: L1 reproduced that hooks are the only enforcement surface in this runtime and the repository has none, so every governance rule in the estate is currently prose enforced by nothing.",
        "The reason the staging existed is real and is retained as a scoping rule rather than a gate: Cursor discovers configuration by walking the repository for .cursor/ directories, so applying it on main would bind enforcement architecture estate-wide without a decision. Apply on a non-protected branch, prove the hook refuses a real command, then propose promotion.",
        "DOCUMENTED",
    ),
    (
        "AI-05",
        "MCP integrations are left unauthenticated and treated as out of scope; state the policy now and connect nothing.",
        "tool_exclusion",
        f"{OE}/FOUNDER-TRANCHE-01.md#oa-d-state-the-mcp-policy-connect-nothing and {OE}/l1-cursor-baseline/CONTROL-SURFACE-ACTIVATION-PROGRAMME.json#FA-MCP-OAUTH-01",
        "The founder has ruled this in scope: maximum useful authorised access is the objective, and an unauthenticated integration is a blocker to remove rather than a boundary to respect.",
        "Five MCP namespaces reachable from this runtime report needsAuth and are therefore candidate authorised access rather than out-of-scope: Supabase, Vercel, Cloudflare-bindings, Cloudflare-builds and Cloudflare-observability. The Supabase one is on the critical path, because it is the route to the Cursor API key the founder says already exists.",
        "The allowlist recommendation is retained on its own merits, not as a gate: naming intended servers explicitly is a stronger statement than an empty configuration, and it is compatible with connecting them. The genuine risk L1 identified is also retained and is now a design constraint in the role architecture: a Slack or Linear connector would create a second place where currentness can be asserted, and that is the one connector class to hold until pointer reconciliation lands.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-06",
        "ChatGPT/SO-02 is a supporting function, stated without scope.",
        "role",
        f"{CP}/commissions/CHATGPT-SIR-01.md:8 and {CP}/state/control-plane.json#orchestration_assignment.chatgpt_role_state",
        "The founder's role/scope correction is scoped by its own text to the founder operating environment. The commission document generalises it into an unqualified status claim about the platform. The founder has since said directly that ChatGPT is a platform that can be launched at scale across multiple projects, models, teams and functions.",
        "ChatGPT operates at platform scale: multiple projects beyond the ten-project floor, multiple models, Work agents, connectors, skills and scheduled cadence, with functions that own decision classes rather than only supplying evidence.",
        "FB-03 is retained at its founder-stated width: for the founder operating environment scope specifically, ChatGPT does not select architecture, prescribe a named stack or issue a founder setup batch. Note that control-plane.json already carries the correct scoping in the string FOUNDER_INTENT_..._SUPPORT_FOR_THIS_SCOPE; it is the commission prose that dropped it.",
        "DOCUMENTED",
    ),
    (
        "AI-07",
        "ChatGPT's operating function is evidence review, verification and a founder interface.",
        "role",
        f"{CP}/commissions/CHATGPT-SIR-01.md#owned-functions and {OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#13.2",
        "The founder states directly that ChatGPT must not be reduced to evidence review or a passive founder interface, and names its immediate useful role: discover and verify Ahmed/Obzio's existing accounts, integrations, plugins, connectors, tools and context, and align them so Cursor receives maximum useful authorised access.",
        "ChatGPT takes the estate's discovery and integration function, which is the only function in the whole architecture that matches its actual asymmetry. It is the only surface with the founder's authenticated context and connected tools; no Cursor agent can reach any of it. Discovery targets include which plan the account holds, which connectors exist, whether a GitHub connector is available, and which of the eleven projects correspond to the twelve planned lanes.",
        "Verification work is not taken away from ChatGPT; it is no longer its ceiling. Independent acceptance specifically moves to Cursor for the reasons in AI-18.",
        "DOCUMENTED",
    ),
    (
        "AI-08",
        "One top-level agent, no subagents.",
        "agent",
        f"{CP}/commissions/CURSOR-SCP-01.md#superseding-scoped-appointment (superseded there) and {OE}/GROUP-MANIFEST-OE-20260822-v001.json#topology_authority (recorded not inherited)",
        "The founder scoped this to the completed CUR-01 qualification experiment. It is not a continuing limit, and SO-02 does not impose an architectural one-agent ceiling.",
        "Already exercised: five isolated lanes ran as subagents under one root controller, and this lane is a sixth. What the removal adds now is a re-inheritance probe, because the rule was superseded in three separate documents and could easily be re-read out of any of them.",
        "The controls that made multi-agent operation safe are all retained and are separately classified: EC-01 worktree isolation, EC-09 write-scope fencing, EC-10 single shared-state writer, EC-11 READY_TO_COMMIT-only returns.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-09",
        "Two independent routes must be qualified before useful work proceeds.",
        "sequencing",
        f"{CP}/commissions/CURSOR-SCP-01.md#superseding-scoped-appointment and {CP}/state/control-plane.json#required_end_to_end_evidence.at_least_two_independent_routes_qualified",
        "Superseded by the founder-bound commission, which states that route qualification is necessary before claiming a route works and is not a precondition for the founder-assigned strategic development work. The requirement nevertheless persists as a live boolean in control-plane.json, where it reads as a gate.",
        "Strategic development work proceeds on the one route that survived independent challenge. R1 GitHub immutable-SHA custody is that route and is usable now.",
        "EC-27 retains exactly the same requirement as a claim standard: an aggregate claim of two independent routes still fails unless the routes have separate controllers and failure domains. What is removed is its use as a gate on unrelated work.",
        "DOCUMENTED",
    ),
    (
        "AI-10",
        "Until one non-founder return route is qualified end to end, no wave-one function may produce anything.",
        "sequencing",
        f"{OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#13.5 (step M10)",
        "Directly contradicts founder-bound text: admit each route separately from live end-to-end evidence, but do not make route acceptance a gate to the founder-assigned strategic development work. The lane's own reasoning for M10 is sound as a risk statement and wrong as a gate.",
        "Wave one produces from the first day, with route qualification running beside it rather than in front of it. The risk M10 was protecting against is real and is handled by labelling instead: any function whose only return route is the founder is marked R0-DEGRADED in the register and reported with that label, rather than being prevented from starting.",
        "FB-05 is the real control here and it is retained: a return route that ends in the founder carrying a result is a defect, and it is now visible as one rather than prevented by a stop-the-world gate.",
        "DOCUMENTED",
    ),
    (
        "AI-11",
        "The five mutating cursor-cloud tools, including trigger-environment-build, are excluded from use.",
        "tool_exclusion",
        f"{OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#boundaries-kept and #what-could-not-be-verified-and-exactly-why (row 2)",
        "A lane-brief exclusion, not a founder boundary, and tool exclusions are a class the founder removed. The tool's own contract states that draft builds never become the build new agents boot from, so the blast radius is bounded by design.",
        "The single most consequential unverified finding in L1 becomes testable. This lane reproduced its live symptom independently: environment-info returns environmentJson null with the note that environment.json was found but contained no recognized configuration fields, and the boot binding reports warmFork cold. A draft build with an environmentJson override settles in one call whether the repository file can take effect, which decides whether this estate keeps paying a cold start on every agent run.",
        "Bounded by the tool's own draft semantics and by EC-19, which fixes which fields the live schema will actually accept.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-12",
        "Grant nothing new on GitHub; the agent's read-only installation is the right shape and widening it should probably never happen.",
        "scope",
        f"{OE}/l1-cursor-baseline/CONTROL-SURFACE-ACTIVATION-PROGRAMME.json#FA-GH-ROUTE-01 and {OE}/l1-cursor-baseline/BASELINE-FINDINGS.md#what-the-founder-actually-needs-to-do",
        "A standing recommendation against an option, carrying no defect evidence. The reproduced facts are about what the token currently cannot do, not about harm from widening. Least privilege is a sound default and is not the same as a permanent foreclosure.",
        "Three foreclosed options reopen as live candidates the founder can weigh: Issues as a coordination substrate, which are currently 403 and are the obvious substrate for the conflict objects this architecture needs; Actions secrets verification, without which any activation depending on a secret can only be verified indirectly through a CI job's behaviour; and branch protection, which is the only server-side enforcement of the protected-branch rule and which no agent can currently even read.",
        "The decision remains founder-bound under FB-21 and FB-25, because a GitHub App permission change is an owner act. What is removed is the pre-emptive recommendation that made it not worth asking.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-13",
        "Ask the founder which ChatGPT plan the account holds.",
        "touchpoint",
        f"{OE}/FOUNDER-TRANCHE-01.md#oa-c-answer-one-question and {OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#16 (question 1)",
        "The founder has assigned ChatGPT the role of discovering and verifying Ahmed/Obzio's existing accounts and integrations. The plan is exactly such a fact, and it is visible to the platform that would be asked about it. Sending it to the founder is routine retrieval, which FB-05 prohibits outright.",
        "The fact is retrieved by the platform that already holds it, and everything that branches on it, including whether Workspace Agents and the Compliance API exist for this account, resolves without a founder turn.",
        "Retained as a fallback only: if ChatGPT's discovery function reports the fact as not visible to it, the question returns to the founder with that failure attached, so he is answering a question the platforms genuinely could not.",
        "DOCUMENTED",
    ),
    (
        "AI-14",
        "The ChatGPT estate is eleven operating project slots plus one frozen evidence container.",
        "topology",
        f"{OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#13.2",
        "The founder's floor is at least ten working projects, and he has since said the platform can be launched at scale across multiple projects, models, teams and functions. The slot table derives from separation requirements, which is correct, and then anchors to the observed count of eleven, which is a migration convenience. L5 says so itself and the estate would still have inherited the number.",
        "Project count follows function demand and separation requirements rather than the current inventory. More than twelve is permitted, and a census returning a different number changes the migration rather than the topology.",
        "The separation requirements that generated the slot types are retained in full, including the rule that an assurance container hosts no producing function (EC-16). It is the arithmetic anchor to eleven that is removed.",
        "DOCUMENTED",
    ),
    (
        "AI-15",
        "The salvage function retires when the unswept backlog is zero and new chats arrive already bound.",
        "scope",
        f"{OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#10",
        "The exit condition is unreachable by construction. A founder thinking out loud in a new sidebar chat creates an unbound chat, which is normal and desirable behaviour, so the backlog never reaches zero and the function can never retire. A function with an unreachable exit condition is a permanent function disguised as a temporary one, which is precisely what the exit-condition rule (EC-17) exists to prevent.",
        "Salvage becomes an inexpensive recurring sweep with a rate target rather than a one-off migration with a false ending, and its cost is budgeted as ongoing rather than being discovered later as an overrun.",
        "EC-17's requirement that every function carry an exit condition is retained; this constraint is removed because it failed that requirement rather than despite it.",
        "DOCUMENTED",
    ),
    (
        "AI-16",
        "The adapter boundary and the evaluation suite have to exist before the second execution plane is worth having.",
        "sequencing",
        f"{OE}/l2-capability-research/TOPOLOGY-COMPARISON.md#3 (T5)",
        "A sequencing preference presented as a precondition. Nothing about specifying Plane B's evidence classes, disclosure classes, owner gates or failure semantics depends on the adapter existing.",
        "Plane B design work proceeds in parallel with adapter work, which matters because Plane B is the only plane that can supply authenticated-session operation and that capability is on the critical path for reaching the founder's own surfaces.",
        "The substantive point is retained and re-expressed as an admission rule rather than a schedule: a plane is not qualified until it passes the shared evaluation suite. Specifying a plane and qualifying it are different acts.",
        "DOCUMENTED",
    ),
    (
        "AI-17",
        "The Cursor CLI and ACP route is deferred to later.",
        "sequencing",
        f"{OE}/l1-cursor-baseline/CONTROL-SURFACE-ACTIVATION-PROGRAMME.json#FA-CUR-CLI-01",
        "The stated reasons are a dependency on a credential and recurring spend. The credential dependency is dissolved by AI-02, and spend is a founder-held class that is not engaged by design, specification or a dry run.",
        "The Agent Client Protocol escape hatch can be specified and dry-qualified now. That matters disproportionately for FB-09, because ACP is the documented interface that would let a different agent runtime drive the same work if Cursor were removed, so it is the concrete form of the substitutability requirement rather than an aspiration.",
        "FB-21 is retained: no spend is committed by specification or by a dry run, and any step that would incur recurring cost returns as a founder action.",
        "DOCUMENTED",
    ),
    (
        "AI-18",
        "Independent acceptance, evaluation and red-teaming are housed in ChatGPT assurance projects.",
        "topology",
        f"{OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#13.2 (P-ASSURE-EVAL, P-ASSURE-ACCEPT, P-ASSURE-REDTEAM)",
        "Placement contradicted by reproduced evidence. Acceptance ran inside Cursor, on a distinct model family, with no founder in the loop, and refused the root controller's own evidence; L4 independently reached the same place. Meanwhile the founder's ChatGPT account is the single context most saturated with founder-visible history, which reduces context isolation rather than increasing it, and it has no qualified return route, so a verdict produced there cannot reach custody without a route that does not yet exist.",
        "Acceptance runs today, multi-lane, at zero new credential cost: isolated worktree, criteria committed as an earlier commit than the verdict, a distinct exact model configuration drawn from the two families already live in this account, container replay with no network and no inherited credentials, and a write scope fenced to the verdict path.",
        "The separation requirements L5 derived are retained and simply re-hosted: evaluation, acceptance and red-teaming remain three functions in three containers, with reciprocal acceptance ownership and no producing function inside an assurance container. ChatGPT keeps adversarial review of Cursor outputs as a contributing function under the overlap ledger, which is different from holding the acceptance decision class.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-19",
        "Cursor is bound as a single operator interface, addressed through one entry agent.",
        "agent",
        f"{CP}/state/control-plane.json#runtime_bindings[SCF-01/CUR-01] and #founder_operating_environment_assignment.delivery",
        "The founder states that Cursor is an agent platform, not one agent and not a narrow repository worker. The binding as written describes a single runtime with a single provider locator and a single delivery route, which is a description of an interface rather than of a platform.",
        "The unit of dispatch becomes an agent group rather than an agent. This lane reproduced that the platform is already operating that way: nine top-level cloud agents on this repository, four distinct exact model configurations and two model families, with subagents and isolated worktrees beneath them.",
        "FB-22 is retained: platform-scale operation does not make Cursor the permanent brain or the canonical store, and every role in the architecture names its substitution route.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-20",
        "A founder follow-up submission is required to deliver the operating-environment scope to Cursor, blocked by a cloud-browser security verification loop.",
        "touchpoint",
        f"{CP}/state/control-plane.json#current_founder_actions[FA-SCF01-CURSOR-LAUNCH]",
        "Stale, and it asks the founder to be a relay for delivering an instruction to a platform that is demonstrably already executing that instruction. The commission is running: five lanes returned, a synthesis was integrated, and this lane exists. A queued owner action whose purpose has already been achieved by another path is a standing request for a routine verb FB-05 prohibits.",
        "One item leaves the founder action queue. The queue's remaining entries are then all genuine owner acts, which is what makes the queue readable as a signal rather than as a backlog.",
        "The closure is recorded as a disposition rather than a deletion, per FB-23, and the underlying finding is retained: an authenticated provider UI is not reachable from a cloud agent, which is a structural property of the topology and belongs in the plane analysis rather than in an action queue.",
        "DIRECTLY_REPRODUCED",
    ),
    (
        "AI-21",
        "Do not make consequential account changes, read as a bar on inspecting and configuring Ahmed/Obzio-owned surfaces.",
        "scope",
        f"{CP}/commissions/CURSOR-OPERATING-ENVIRONMENT-01.md#current-boundaries",
        "The founder has granted authority to inspect, access, configure, connect, use and optimise the complete Ahmed/Obzio-controlled operating estate where it advances the existing mandate, and to inspect existing configuration and secret locations. The boundary as written was being read as covering configuration work rather than only the acts on the stop list.",
        "Configuration, connection and optimisation proceed across verified in-scope surfaces without a founder turn for each one. This is what makes AI-04, AI-05 and AI-11 actionable rather than merely reclassified.",
        "FB-25's stop list is retained verbatim and is the operative boundary. The removal narrows the constraint to what the founder actually wrote rather than widening it past what he authorised.",
        "DOCUMENTED",
    ),
    (
        "AI-22",
        "The quota function fails closed: unknown runtime headroom is treated as zero headroom for new work.",
        "pace",
        f"{OE}/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md#14",
        "Fail-closed is the right default for evidence and the wrong default here, because headroom is structurally unknown in this environment rather than temporarily unknown. Capacity non-interference was measurable only at the visible top-level run layer and cannot see compute or rate-limit contention, so a rule that reads unknown as zero halts all new work permanently. It also contradicts the founder's instruction to seek maximum effective provider capacity and to queue work above the ceiling rather than lower ambition.",
        "Work proceeds against the layer that is actually observable, which is top-level run status, with a declared stop condition instead of a permanent stop.",
        "The blind spot is not swept away: it is recorded as a dated non-assessability record with a retry route and a risk-conversion date, which is the mechanism L5 already built for exactly this case, and the fail-closed rule is retained where the unknown is genuinely temporary rather than structural.",
        "DIRECTLY_REPRODUCED",
    ),
]

# Re-inheritance probes for the removed constraints. A probe is a case-insensitive
# regular expression that matches the restriction as it would be *written into a
# routing surface*. Matching inside an evidence surface is expected and is not a
# failure: superseded files remain evidence, not launch surfaces (FB-23).
PROBES = {
    "AI-01": [r"nothing\s+beyond\s+this\s+tranche", r"gate\s+before\s+tranche\s*0?2", r"until\s+tranche\s*0?1\s+is\s+evaluated"],
    "AI-02": [r"(issue|create)\s+(a\s+)?(new\s+)?cursor\s+api\s+key", r"cursor\.com/dashboard/api"],
    "AI-03": [r"touch[\s_-]?point\s+budget", r"founder[\s_-]?touch[\s_-]?points?[\s_-]?per[\s_-]?wave"],
    "AI-04": [r"inert\s+until\s+applied", r"pending\s+an?\s+explicit\s+founder\s+act"],
    "AI-05": [r"connect\s+nothing", r"mcp[^.\n]{0,40}out\s+of\s+scope"],
    "AI-06": [r"chatgpt[^.\n]{0,30}is\s+a\s+supporting\s+function"],
    "AI-07": [r"reduce[ds]?\s+to\s+evidence\s+review", r"passive\s+founder\s+interface"],
    "AI-08": [r"single[\s_-]top[\s_-]level[\s_-]agent", r"no[\s_-]subagents?\s+rule", r"one[\s_-]agent\s+ceiling"],
    "AI-09": [r"two\s+routes?\s+before\s+(any\s+)?useful\s+work", r"qualify\s+two\s+routes\s+before"],
    "AI-10": [r"until\s+one\s+non-?founder\s+return\s+route\s+is\s+qualified", r"m10\s+is\s+the\s+real\s+gate"],
    "AI-11": [r"trigger-environment-build[^.\n]{0,40}(excluded|not\s+permitted|prohibited)"],
    "AI-12": [r"grant\s+nothing\s+new", r"widening\s+it\s+probably\s+never"],
    "AI-13": [r"which\s+chatgpt\s+plan\s+does\s+the\s+account\s+hold"],
    "AI-14": [r"eleven\s+operat(e|ing)[^.\n]{0,40}twelfth\s+is\s+frozen", r"eleven\s+operating\s+slots"],
    "AI-15": [r"retires\s+when\s+the\s+unswept\s+backlog\s+is\s+zero"],
    "AI-16": [r"before\s+the\s+second\s+plane\s+is\s+worth\s+having"],
    "AI-17": [r"fa-cur-cli-01", r"cursor\s+cli\s+in\s+ci[^.\n]{0,30}(later|deferred)"],
    "AI-18": [r"p-assure-accept", r"p-assure-redteam", r"acceptance[^.\n]{0,30}chatgpt\s+project"],
    "AI-19": [r"one\s+entry\s+agent", r"single\s+operator\s+interface"],
    "AI-20": [r"fa-scf01-cursor-launch"],
    "AI-21": [r"consequential\s+account\s+changes"],
    "AI-22": [r"unknown\s+headroom\s+is\s+treated\s+as\s+zero"],
}

# Constraints deliberately not classified, with the reason. Recorded so the
# denominator is honest rather than quietly trimmed to fit the three classes.
NOT_CLASSIFIED = [
    {
        "item": "Structured Outputs `strict` must be set explicitly or Responses may silently fall back to best-effort tool calling.",
        "source": f"{OE}/l5-chatgpt-scale/OPENAI-API-SURFACE-FINDINGS-20260822-v001.md#4",
        "why_not_classified": "This is documented provider behaviour, not a limit any actor in this estate invented. It constrains how an interface is called correctly; it does not constrain scope, roles, tooling choice, topology or pace.",
    },
    {
        "item": "Background responses must set `store` explicitly and be reconciled inside the retention window or they are deleted after roughly ten minutes.",
        "source": f"{OE}/l5-chatgpt-scale/OPENAI-API-SURFACE-FINDINGS-20260822-v001.md#2",
        "why_not_classified": "Same class: a provider retention fact, correctly recorded, and not a restriction on the operation.",
    },
    {
        "item": "The Workspace Agents API cannot return an agent's response; the Compliance API is plan-gated and its contract is not published.",
        "source": f"{OE}/l5-chatgpt-scale/OPENAI-API-SURFACE-FINDINGS-20260822-v001.md#8",
        "why_not_classified": "A capability limit of an external product, not a constraint any actor here imposed. It is load-bearing for the role architecture and is carried there as a routing fact rather than as a constraint to remove.",
    },
    {
        "item": "A cloud VM has no route to the founder's browser session or microphone.",
        "source": f"{OE}/l2-capability-research/TOPOLOGY-COMPARISON.md#2",
        "why_not_classified": "A structural property of the runtime, correctly identified as permanent rather than immature. It shapes the plane split in the architecture and cannot be removed by a classification.",
    },
    {
        "item": "Founder question set FQ-01 through FQ-09 and Q1 through Q6.",
        "source": f"{OE}/l2-capability-research/TOPOLOGY-COMPARISON.md#7 and {OE}/FOUNDER-TRANCHE-01.md#questions-that-need-your-judgment-ranked",
        "why_not_classified": "Open questions are not constraints. Where one of them was being used as a gate on unrelated work, the gate is classified separately: see AI-01, AI-09 and AI-13. Q7, the touch-point budget, is classified as AI-03 because it was written as a sizing rule rather than only as a question.",
    },
]


def build() -> dict:
    entries = []
    for cid, statement, klass, source, justification, label in FOUNDER_BOUND:
        entries.append(
            {
                "constraint_id": cid,
                "verdict": "FOUNDER_BOUND",
                "statement": statement,
                "class_of_limit": klass,
                "founder_source": source,
                "justification": justification,
                "evidence_label": label,
                "action": "RETAIN_UNCHANGED",
            }
        )
    for cid, statement, klass, source, defect, label, defect_ref in EARNED:
        entries.append(
            {
                "constraint_id": cid,
                "verdict": "EARNED_CONTROL",
                "statement": statement,
                "class_of_limit": klass,
                "introduced_in": source,
                "defect_caught": defect,
                "defect_evidence_path": defect_ref,
                "evidence_label": label,
                "action": "RETAIN_WITH_EVIDENCE_CITED",
            }
        )
    for cid, statement, klass, source, why, unlocks, replacement, label in REMOVED:
        entries.append(
            {
                "constraint_id": cid,
                "verdict": "ASSISTANT_IMPOSED",
                "statement": statement,
                "class_of_limit": klass,
                "introduced_in": source,
                "why_not_founder_bound_and_no_defect_evidence": why,
                "removal_unlocks": unlocks,
                "replacement_control_retained": replacement,
                "evidence_label": label,
                "action": "REMOVE",
                "reinheritance_probe": PROBES[cid],
            }
        )
    entries.sort(key=lambda e: e["constraint_id"])

    counts = {"FOUNDER_BOUND": 0, "EARNED_CONTROL": 0, "ASSISTANT_IMPOSED": 0}
    for e in entries:
        counts[e["verdict"]] += 1

    return {
        "register_id": REGISTER_ID,
        "lane": LANE,
        "commission_id": COMMISSION,
        "declares_commission": False,
        "governing_authority": "FOUNDER-AUTHORITY-DERESTRICTION-20260822T2225Z",
        "governing_authority_path": f"{OE}/FOUNDER-AUTHORITY-20260822T2225Z.json",
        "base_commit": BASE_SHA,
        "state": "READY_TO_COMMIT",
        "is_a_proposal_not_a_binding": True,
        "binds_company_strategy": False,
        "classification_rule": {
            "FOUNDER_BOUND": "Traceable to direct founder intent. Retained; this lane may not remove it.",
            "EARNED_CONTROL": "Invented by an agent, and demonstrably caught a real defect in this estate. Retained, with the defect cited.",
            "ASSISTANT_IMPOSED": "Invented by an assistant, constrains scope, roles, tooling, topology or pace, and has no defect evidence behind it. Removed.",
            "exactly_one": True,
            "symmetry_note": "Removing a control that caught a real defect would be as damaging as keeping an invented limit. Every EARNED_CONTROL record names the defect and the path it can be read at; every ASSISTANT_IMPOSED record names where it was introduced and what its removal unlocks.",
        },
        "counts": counts,
        "total_classified": len(entries),
        "constraints": entries,
        "not_classified_with_reason": NOT_CLASSIFIED,
        "removal_is_not_deletion": (
            "No file is deleted by this register. A removed constraint keeps its "
            "source document as evidence under FB-23; what changes is that it no "
            "longer routes, and derestrictctl.py fails closed if it reappears in an "
            "active surface."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    register = build()
    path = pathlib.Path(args.out)
    path.write_text(json.dumps(register, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    c = register["counts"]
    print(
        f"wrote {path} "
        f"total={register['total_classified']} "
        f"FOUNDER_BOUND={c['FOUNDER_BOUND']} "
        f"EARNED_CONTROL={c['EARNED_CONTROL']} "
        f"ASSISTANT_IMPOSED={c['ASSISTANT_IMPOSED']} "
        f"not_classified={len(register['not_classified_with_reason'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
