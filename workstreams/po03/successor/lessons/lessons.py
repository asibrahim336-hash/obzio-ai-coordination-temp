#!/usr/bin/env python3
"""The lesson register: what was learned, what changed, and how it is held open.

A lesson only counts here if it did three things: it came from somewhere other
than this cohort's own opinion, it changed a live mechanism, and the change is
pinned by a test that fails if the mechanism reverts.  A lesson that changed
nothing is a note, and a change nothing tests is a change that will quietly
revert, so both are excluded by construction rather than by good intentions.

Independence is defined narrowly.  ``po03-worker-a8`` authors the generations,
so support from ``po03-worker-a8`` is not independent support no matter how well
evidenced it is.  Every claim of independence below names an owner, a branch, a
commit, a git blob id and a content digest, so the claim can be checked rather
than believed - run ``build_lessons.py --verify-support``.

Dispositions carry their ordinary meaning and are load-bearing:

RETAIN     the mechanism change stands and the recurrence test guards it
SUPERSEDE  an earlier formulation was replaced; the earlier one is kept as record
RETEST     the change landed but a named residual keeps the question open
REJECT     the candidate lesson was examined and refused on evidence
DELETE     a belief this cohort held was withdrawn on the evaluator's own correction

A truthful REJECT or DELETE is worth as much as a RETAIN; what would be worth
nothing is a register in which every lesson happens to be a success.
"""

from __future__ import annotations

from typing import Any

OWNER = "po03-worker-a8"

# Immutable evidence anchors.  Recorded rather than recomputed so the register is
# readable in a clean clone that fetched only this cohort's branch; --verify-support
# re-derives them from git whenever the evaluator refs are present.
A6 = {
    "owner": "po03-worker-a6",
    "role": "independent evaluator (a6-u01..a6-u06)",
    "branch": "cursor/po03-a6-independent-review-ed20",
    "commit": "da01535a4f1969a2ccbefb799a7d298b69b325c4",
}
A10 = {
    "owner": "po03-worker-a10",
    "role": "cross-family evaluator (a10-u01..a10-u04)",
    "branch": "cursor/po03-a10-crossfamily-review-ed20",
    "commit": "af2e2c08a6ca158d527b88e12f4075f03528a225",
}

EVIDENCE: dict[str, dict[str, Any]] = {
    "a6-readback-audit": {
        **A6,
        "path": "workstreams/po03/review/luna/readback-audit.json",
        "blob": "1f9bef9a9824145d937ef9a14c7ef1c8cee7029d",
        "sha256": "78f9bca9dfbd75dc10855d588d30e96a5de5c21b98435b0e1f12e0e6e8ba5f3f",
        "finding": "result_record_not_at_declared_commit",
        "observed": "9 result records audited, 5 whose record was absent at the declared result_commit_id",
    },
    "a6-dispositions": {
        **A6,
        "path": "workstreams/po03/review/luna/dispositions.json",
        "blob": "97a695ac004b83311df47e5869d52daf1408f101",
        "sha256": "d5a4ccdaf69bd62fc02827b6c5d2c22d0d8bf229cf9d230c502c2bf1c8219577",
        "finding": "material_defects",
        "observed": "a3-u01/a7-u01/a7-u02 rejected for the result-locator discrepancy; tracked __pycache__ bytecode recorded as a defect class",
    },
    "a6-correction": {
        **A6,
        "path": "workstreams/po03/review/luna/rejection-assessment-correction.json",
        "blob": "f52db4176e2188fb01878df93ef795a65e2d43a4",
        "sha256": "a8cebf4417e05830104d1275247068d18ec9794e5d1f74389cd752ee068ce6c6",
        "finding": "availability_reclassification",
        "observed": "27 of 30 rejections reclassified as evidence-availability boundaries; bytecode escape reattributed to coordinator commits 04827c3 and 6f5e386",
    },
    "a6-hidden-cases": {
        **A6,
        "path": "workstreams/po03/review/luna/hidden-cases/cases.json",
        "blob": "37dde197e5fd9dc53e1c235109ea64d65d0249b7",
        "sha256": "52ac6507f66086ff339c3659b681986f1337cea08411d099493b14b65c3d90ef",
        "finding": "evaluator-held novel cases",
        "observed": "10 custody cases authored without sight of any generation in this test; bound as the holdout suite",
    },
    "a10-control-plane-audit": {
        **A10,
        "path": "workstreams/po03/review/sonnet/coordinator-audit/findings.json",
        "blob": "2b001207e018f1b6187f4be569fd79344eca516d",
        "sha256": "8510b731fd9be42a8d0506df8c65374ea9e2551ec96b058438cd41898c6ce94c",
        "finding": "9 invariants attacked, 5 broken, 1 boundary",
        "observed": "adversarial audit of the same control_plane.py G1 ports, at the same file digest this cohort ported from",
    },
}

# Every lesson: statement, support, mechanism, recurrence test, disposition.
LESSONS: tuple[dict[str, Any], ...] = (
    {
        "lesson_id": "L-01",
        "statement": "Authority over a state transition has to be an authorisation decision at the moment of the transition. Writing the authorised actor's name onto the event records who was supposed to act, not who did.",
        "support": [
            {"evidence": "a6-hidden-cases", "detail": "case H02 requires that a producer driving completion be refused, not relabelled"},
            {"evidence": "a10-control-plane-audit", "detail": "finding D6 (INV-7b): identity is an unauthenticated caller-supplied string throughout, and cmd_complete hardcodes actor='coordinator' regardless of the invoking process"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-03"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c03_worker_cannot_complete",
        "disposition": "RETAIN",
        "disposition_basis": "The change closed both the frozen case P08 and a6's independently authored H02, and the recurrence test asserts G1's behaviour as well as G2's. The residual - that principal identity is still asserted by the caller rather than bound to a credential - was declared in G2's own docstring before a10 published, and a10's D6 independently confirms it as a boundary rather than contradicting the change.",
        "residual_boundary": "Binding a principal to a credential needs a transport this in-process, dependency-free controller does not have. Not claimable as closed.",
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-02",
        "statement": "Verifying artifact bytes once, at admission, proves only that the bytes were right once. Custody is a continuing claim, so it needs continuing verification.",
        "support": [
            {"evidence": "a6-hidden-cases", "detail": "case H09 requires that remote artifact bytes differing from the recorded hash be detected after the fact"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-05"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c05_post_admission_drift_detected",
        "disposition": "RETAIN",
        "disposition_basis": "G1 hashed artifacts at ingestion and never again; a6's H09 and the frozen case P21 both measured that, and both pass under G2's custody manifest with re-verification on every sweep.",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-03",
        "statement": "A result that was committed but never ingested is the failure mode that costs the most work, because nothing is wrong with the result. The commit and the intent to deliver it must be recorded together so recovery can replay the delivery instead of re-running the work.",
        "support": [
            {"evidence": "a6-hidden-cases", "detail": "case H10 requires that a parent restarting after a child commit but before ingestion still reach PARENT_INGESTED exactly once"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-08"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c08_lost_callback_is_replayed_once",
        "disposition": "RETAIN",
        "disposition_basis": "G1 treated RESULT_COMMITTED as terminal for the recovery scanner and had no outbox, so such a result was stranded rather than replayed or re-run. This is the shape of the lost PO-02 Code-2 return that the commission was written around, and it is the only lesson here whose absence is measured by both a frozen case (P30) and an independently authored one (H10).",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-04",
        "statement": "A fence token has to be checked against the grants that were actually issued. Comparing it to a high-water mark tests that the holder is not behind, which is a different question from whether the holder ever held the lease.",
        "support": [
            {"evidence": "a10-control-plane-audit", "detail": "finding D3 (INV-2b): the only fence check is `incoming < current`, so an actor that never held the lease can commit by choosing any token above the readable high-water mark"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-01", "also": ["C-02"]},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c01_forged_fence_is_refused",
        "disposition": "SUPERSEDE",
        "disposition_basis": "The earlier formulation - 'fence tokens must increase monotonically' - is retained as a record and superseded by 'a fence must correspond to a grant issued to this worker, and that grant must still be live'. Monotonicity was not wrong, it was insufficient: it is one of the two conditions, and G1 implemented only that one. C-02 completes the pair by evaluating the lease deadline at the moment of commit rather than only in the recovery scanner.",
        "residual_boundary": None,
        "lineage": {
            "derived_from": [],
            "supersedes": ["L-04-v001: fence tokens must increase monotonically (as implemented in control_plane.ingest_result at 9c3d3c9)"],
            "superseded_by": [],
        },
    },
    {
        "lesson_id": "L-05",
        "statement": "A pinned input is only pinned if something recomputes the pin. G1 carried the dispatch manifest digest and never re-derived it, and in doing so lost a check the pre-amendment controller had.",
        "support": [],
        "mechanism": {"kind": "g2_change", "change_id": "C-04"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c04_dispatch_tamper_and_input_drift_detected",
        "disposition": "RETAIN",
        "disposition_basis": "Supported by this cohort's own cross-generation measurement, not by an independent evaluator: G0 detected pinned-input drift (P05) and G1 did not, which is a regression in the direction of travel and is reported rather than suppressed. Recorded here with independent support absent, because a lesson this cohort found itself must not be presented as externally confirmed.",
        "residual_boundary": "No evaluator cohort has examined this claim. It is a measured regression, not an independently supported lesson.",
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-06",
        "statement": "Deduplicating a callback on the digest of its whole payload answers 'have I seen these exact bytes', when the question that matters is 'have I already admitted a result for this task'. Only the second question distinguishes a harmless retry from a conflicting one.",
        "support": [
            {"evidence": "a10-control-plane-audit", "detail": "finding D4 (INV-3b) root cause (a): dedup keys on the full-document hash instead of a stable content-independent identity"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-06"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c06_conflicting_replay_refused",
        "disposition": "RETAIN",
        "disposition_basis": "G2 adjudicates on the idempotency key: identical content is a harmless duplicate, different content under the same key is a refused conflict, and neither produces a second ingestion. Frozen case P26 measured this and a10 independently reached the same root cause from an adversarial direction.",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-07",
        "statement": "Hash-chaining proves that the rows present are consistent with each other. It says nothing about rows that are gone, so a log needs its length and head anchored as well as its links.",
        "support": [
            {"evidence": "a10-control-plane-audit", "detail": "finding D5 (INV-8b): verify_chain checks only internal self-consistency, so a cascade-rehashed rewrite passes end to end"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-07"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c07_tail_truncation_detected",
        "disposition": "RETEST",
        "disposition_basis": "The anchor closes the truncation case (P29) and is guarded by a recurrence test, and a companion test shows why a row-count-only anchor would not have. But a10's D5 is broader than truncation: an actor with write access to the whole store can rewrite the ledger and the anchor together, and G2's anchor lives in the same store as the ledger it protects. That residual is demonstrated by an executable test rather than described, and the lesson stays open until an anchor outside the store - a signed remote ref - exists to retest against.",
        "residual_boundary": "test_a8_g2_changes.DispositionEvidenceTests.test_retest_the_anchor_shares_the_store_it_protects asserts the exposure, so the claim cannot quietly widen.",
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-08",
        "statement": "'Committed' is a claim about an immutable store, so it has to be checked against that store. A result record that cannot be read back at the locator it declares has not been committed, whatever its own contents assert.",
        "support": [
            {"evidence": "a6-readback-audit", "detail": "5 of 9 audited result records were absent at their declared result_commit_id, across three different producer cohorts"},
            {"evidence": "a6-dispositions", "detail": "a3-u01, a7-u01 and a7-u02 rejected on exactly this ground under a6's frozen decision rule"},
            {"evidence": "a10-control-plane-audit", "detail": "finding D2 (INV-9): a fabricated 40-hex result_commit_id over a working-tree-only artifact reaches COMPLETED in a directory with no .git at all"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-09"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c09_unresolvable_locator_refused",
        "disposition": "RETAIN",
        "disposition_basis": "The most heavily supported lesson in the register: two evaluator cohorts of different owners, working from different directions, reached it independently, and a6 reached it by auditing real committed records rather than by attacking a fixture. G2 refuses admission unless the record resolves at its declared locator and the bytes there match the result being admitted.",
        "residual_boundary": "G2 resolves against a modelled immutable store. The live equivalent is `git cat-file blob <commit>:<path>`, which is what the integration proposal recommends; this cohort has not changed the live control plane.",
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-09",
        "statement": "A single weighted headline score should replace the primary metric and its separate guards, because one number is easier to compare across generations.",
        "support": [],
        "mechanism": {"kind": "none", "reason": "the candidate was refused, so no mechanism changed"},
        "recurrence_test": "test_a8_g2_changes.DispositionEvidenceTests.test_reject_a_weighted_single_score_would_have_passed_a_safety_regression",
        "disposition": "REJECT",
        "disposition_basis": "Refused on executed evidence rather than on taste. Applied to a real pair of score sets, the weighted candidate reports progress for a change that reintroduces a false completion - the precise outcome the preregistered guard exists to refuse. A metric that can be improved by regressing on safety is not a measure of progress. The guarded rule is retained.",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-10",
        "statement": "A row-count anchor is sufficient to detect a log that lost its tail.",
        "support": [],
        "mechanism": {"kind": "none", "reason": "the candidate was refused in favour of a head digest, which is C-07"},
        "recurrence_test": "test_a8_g2_changes.DispositionEvidenceTests.test_supersede_row_count_alone_cannot_detect_truncation",
        "disposition": "SUPERSEDE",
        "disposition_basis": "Built and shown insufficient rather than argued against: under truncate-then-forge, where the last row is dropped and a correctly chained replacement appended, the row count is unchanged and reports a healthy log. The head digest catches it. Superseded by the anchor in C-07, whose own residual is held open under L-07.",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": ["L-07"]},
    },
    {
        "lesson_id": "L-11",
        "statement": "A path-scope guard has to normalise the declared path exactly as the code that opens the file will. A validator that reasons about a different string than the filesystem receives is not a weaker guard, it is a guard that can be walked around.",
        "support": [
            {"evidence": "a10-control-plane-audit", "detail": "finding D1 (INV-6), the audit's highest-severity result: `str.lstrip('./')` strips a character set rather than a prefix, so a declared path whose leading run is only dots and slashes is judged in-allowlist and owned while the raw string is joined to the artifact root and the filesystem walks out of it"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-10"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c10_path_escape_refused",
        "disposition": "RETAIN",
        "disposition_basis": "This lesson also falsifies something this cohort wrote down. G2's original lineage recorded that an independent traversal check was declined because 'the allowlist already refuses traversal before ownership is consulted, so no case measured a failure and no lesson supported it'. The premise was false, and the reason no case measured it is that the frozen public case P24 happens to use a mid-string traversal, which the character-strip does catch. An evaluator of a different owner found the shape this cohort's own suite was blind to. The declined entry is kept in lineage.json with an explicit SUPERSEDED_BY_C-10 disposition rather than deleted.",
        "residual_boundary": "The escape was reproduced against the packaged G1 and against G2 before the fix; both admitted an artifact living outside the store they verify against. The live control plane still carries the defect, which is a coordinator-owned file this cohort must not modify.",
        "lineage": {
            "derived_from": [],
            "supersedes": ["lineage.json not_changed_and_why: independent rejection of path traversal inside the ownership check"],
            "superseded_by": [],
        },
    },
    {
        "lesson_id": "L-12",
        "statement": "A state machine needs to distinguish 'this unit holds a durable result' from 'this unit is closed'. Collapsing the two lets replayed work walk a projection backwards out of a terminal state.",
        "support": [
            {"evidence": "a10-control-plane-audit", "detail": "finding D4 (INV-3b) root cause (b): the projection has no rule that COMPLETED is terminal, so a resubmission after completion resets the state and a second COMPLETED row can be recorded for one unit under a different result_commit_id"},
        ],
        "mechanism": {"kind": "g2_change", "change_id": "C-11"},
        "recurrence_test": "test_a8_g2_changes.RecurrenceTests.test_c11_terminal_state_cannot_be_re_entered",
        "disposition": "RETAIN",
        "disposition_basis": "Reproduced against both the packaged G1 and G2 before the fix: after a unit reached COMPLETED, a resubmission was admitted, the projection fell back to RESULT_COMMITTED, and a second completion was recorded. Fixing it required naming the closed states separately from the merely committed ones, because refusing every unit that already holds a result would have made C-06's replay adjudication unreachable. G1's single TERMINAL_STATES set, which mixes the two, is the defect underneath a10's finding.",
        "residual_boundary": None,
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-13",
        "statement": "A custody engine that admits artifacts by digest cannot tell evidence from build residue. Derived files have stable hashes and real byte counts, so they satisfy every integrity check while being regenerated on the next import.",
        "support": [
            {"evidence": "a6-dispositions", "detail": "tracked __pycache__ bytecode recorded as one of four material defect classes found while reviewing producer branches"},
            {"evidence": "a6-correction", "detail": "the escape reattributed to coordinator commits 04827c3 and 6f5e386 staging with a broad `git add -A`; the reviewed cohort had inherited it"},
        ],
        "mechanism": {
            "kind": "repository_mechanism",
            "path": "workstreams/po03/successor/check_custody_hygiene.py",
            "detail": "refuses tracked derived files under this cohort's owned prefixes and reports, without failing, those remaining outside its ownership",
        },
        "recurrence_test": "test_a8_lessons.HygieneMechanismTests.test_no_derived_bytecode_is_tracked_under_owned_paths",
        "disposition": "RETEST",
        "disposition_basis": "The mechanism belongs where files enter the repository, not in the custody engine, because a6's corrected attribution shows the escape came from how work was staged. This cohort's owned prefixes are clean and the check enforces that. Two tracked bytecode files remain under coordinator-owned paths, which this cohort is forbidden to modify, so the lesson cannot be closed: it is retested by the same mechanism once those paths are cleaned by their owner. Recording this as RETAIN would claim a boundary this cohort does not control.",
        "residual_boundary": "workstreams/po03/tests/__pycache__/test_validate_contracts.cpython-312.pyc and workstreams/po03/tools/__pycache__/validate_contracts.cpython-312.pyc are still tracked. Both are outside this cohort's ownership. Running `unittest discover` also regenerates caches under coordinator-owned paths, which is why the check reports rather than fails on them.",
        "lineage": {"derived_from": [], "supersedes": [], "superseded_by": []},
    },
    {
        "lesson_id": "L-14",
        "statement": "Cohort a8's units are quality-deficient, since an independent evaluator rejected all six of them.",
        "support": [],
        "mechanism": {"kind": "none", "reason": "the belief was withdrawn, so nothing was changed on its basis"},
        "recurrence_test": "test_a8_lessons.WithdrawnBeliefTests.test_the_rejection_of_this_cohort_was_an_availability_boundary",
        "disposition": "DELETE",
        "disposition_basis": "Withdrawn on the evaluator's own correction. a6 initially disposed a8-u01..a8-u06 as REJECTED, and then recorded that those labels 'conflated unavailable evidence with a quality judgment': the branch was absent from a6's fetch at its scoring snapshot, so there was nothing to test. a6 reclassified 27 of its 30 rejections, including all six a8 rows, as availability boundaries and named only three units as quality-relevant, none of them a8's. Deleted rather than rejected because the claim was never evidenced in the first place - there is no finding to keep on file, only a misreading to withdraw. The correction is preserved by reference, not restated as vindication: a6's basis remains that no a8 result was available to test.",
        "residual_boundary": "No a8 unit has yet been independently accepted. Absence of an adverse finding is not acceptance, and this cohort cannot accept its own work.",
        "lineage": {"derived_from": ["a6-dispositions"], "supersedes": [], "superseded_by": ["a6-correction"]},
    },
)


def independently_supported(lesson: dict[str, Any]) -> bool:
    """True only if some support comes from an owner other than this cohort."""
    return any(EVIDENCE[item["evidence"]]["owner"] != OWNER for item in lesson["support"])


DISPOSITIONS = ("RETAIN", "DELETE", "SUPERSEDE", "RETEST", "REJECT")
