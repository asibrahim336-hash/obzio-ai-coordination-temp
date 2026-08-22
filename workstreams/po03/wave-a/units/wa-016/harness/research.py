#!/usr/bin/env python3
"""Source claims, frozen hypotheses and mechanism changes, kept separate.

The commission requires the states
``source claim -> frozen hypothesis -> Obzio reproduction -> result -> live
mechanism change or evidence-backed rejection -> independent recurrence test``
to remain distinct.  This module holds the first, second and fifth of those as
declarative records; the reproductions module produces the third and fourth, and
the tests produce the sixth.

Every external claim carries the URL actually fetched, the HTTP status observed,
and the SHA-256 of the exact bytes retrieved.  Sources that could not be read in
this runtime are recorded as NOT_SUPPORTED and support no claim.
"""

from __future__ import annotations

from typing import Any

RETRIEVED_AT = "2026-08-22T07:30:00Z"
RETRIEVAL_METHOD = "curl --max-time 45 -sSL from the runner VM; SHA-256 taken over the exact response body bytes"

# ---------------------------------------------------------------- source claims
EXTERNAL_SOURCE_CLAIMS: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "S1",
        "url": "https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html",
        "http_status": 200,
        "bytes": 42382,
        "sha256": "74ee5c1c9253ca5ef55a9791bafb7c240170c9559a8245724222bf9fd39ed295",
        "readable_in_runtime": True,
        "claim": (
            "A fencing token is a number that increases every time a client acquires the lock; the storage "
            "server must take an active role in checking tokens and reject any write whose token has gone "
            "backwards. A lock service that cannot generate monotonic tokens cannot be made safe against a "
            "paused or delayed client."
        ),
    },
    {
        "claim_id": "S2",
        "url": "https://apple.github.io/foundationdb/testing.html",
        "http_status": 200,
        "bytes": 23618,
        "sha256": "a97c135cf5e25670b951ea73b27d77c6b06c4f54ab2882ca7d49cec10cb00303",
        "readable_in_runtime": True,
        "claim": (
            "A deterministic simulation of an entire cluster inside a single-threaded process, where "
            "determinism gives perfect repeatability of a simulated run, is central to their correctness "
            "process; simulated failures include connection failures, machine shutdowns and reboots."
        ),
    },
    {
        "claim_id": "S3",
        "url": "https://docs.tigerbeetle.com/concepts/safety/",
        "http_status": 200,
        "bytes": 38762,
        "sha256": "f472806e74058dacf88901025dd55d4ecd32539193fe5d8d8e5a7a52b1dc4f67",
        "readable_in_runtime": True,
        "claim": (
            "The state machine follows an end-to-end idempotency principle: each transfer carries a unique "
            "client-generated id and is processed at most once, even in the presence of intermediate retry "
            "loops."
        ),
    },
    {
        "claim_id": "S4",
        "url": "https://microservices.io/patterns/data/transactional-outbox.html",
        "http_status": 200,
        "bytes": 25608,
        "sha256": "4a86d3fb29ea43f67802cbe0ed94763ab0691684525e394d8e6619842b8cc3a5",
        "readable_in_runtime": True,
        "claim": (
            "Storing the message in the database as part of the transaction that updates the business entity "
            "guarantees messages are sent if and only if the transaction commits. The relay may publish a "
            "message more than once, for example by crashing after publishing but before recording that it "
            "did, so the consumer must be idempotent."
        ),
    },
    {
        "claim_id": "S5",
        "url": "https://principlesofchaos.org/",
        "http_status": 200,
        "bytes": 8281,
        "sha256": "06bb2df5d5da7442473850d74d911458dba77e0a289b4ebac73c55c4ded1229b",
        "readable_in_runtime": True,
        "claim": (
            "Define steady state as a measurable output indicating normal behaviour, hypothesise it continues, "
            "introduce variables reflecting real-world events, and then try to disprove the hypothesis rather "
            "than confirm it."
        ),
    },
    {
        "claim_id": "S6",
        "url": "https://jepsen.io/consistency",
        "http_status": 200,
        "bytes": 4371,
        "sha256": "3973e30505147b7e79d7e6f8d1bbd36c51ed0568a59aff949635e101c6234c96",
        "readable_in_runtime": True,
        "claim": (
            "A consistency model is a safety property that defines the set of histories a system can legally "
            "execute, and violations are identified as proscribed patterns over those histories."
        ),
    },
    {
        "claim_id": "S7",
        "url": "https://antithesis.com/blog/is_something_bugging_you/",
        "http_status": 200,
        "bytes": 98754,
        "sha256": "6e6ccd94a5b42525cd6af98397c2f298067bdef167fed6a830518ee0ffddef07",
        "readable_in_runtime": True,
        "claim": (
            "A fully deterministic event-based simulation driven by a single random number generator lets a "
            "failing run be replayed with the same seed so the exact same series of events happens in the "
            "same order, converting a rare non-deterministic bug into one with unlimited retries."
        ),
    },
    {
        "claim_id": "S8",
        "url": "https://docs.stripe.com/api/idempotent_requests",
        "http_status": 200,
        "bytes": 1249316,
        "sha256": "3b4ddef34ec66941cdab0b888002553e0d25ff3ac498835108a38ad2192549b8",
        "readable_in_runtime": True,
        "claim": (
            "Idempotency works by saving the resulting status code and body of the first request made for a "
            "given idempotency key; subsequent requests with the same key return the same result. The "
            "idempotency layer compares incoming parameters to those of the original request and errors if "
            "they are not the same."
        ),
    },
    {
        "claim_id": "S9",
        "url": "https://www.usenix.org/system/files/conference/osdi14/osdi14-paper-yuan.pdf",
        "http_status": 200,
        "bytes": 619692,
        "sha256": "2cd4463c773dae22259ed7c112f287b2126b669f75cc6777cc36b8cc8f964e09",
        "readable_in_runtime": False,
        "claim": "NOT_SUPPORTED",
        "limitation": (
            "The PDF was retrieved and hashed, but no PDF text extractor is available in this runtime "
            "(pdftotext absent, no third-party packages permitted), so no claim is asserted from it."
        ),
    },
    {
        "claim_id": "S10",
        "url": "https://www.usenix.org/conference/osdi14/technical-sessions/presentation/yuan",
        "http_status": 403,
        "bytes": 5460,
        "sha256": "202f3abc0c39757a5c5bb1d348ac15ecc5291a79eb07d4137f379de341853e68",
        "readable_in_runtime": False,
        "claim": "NOT_SUPPORTED",
        "limitation": "The abstract page returned an interstitial challenge rather than content.",
    },
    {
        "claim_id": "S11",
        "url": "https://people.eecs.berkeley.edu/~palvaro/molly.pdf",
        "http_status": 404,
        "bytes": 3684,
        "sha256": "6c134308ad963409b229440707aee4e8d1e6070995a544046642055df4527232",
        "readable_in_runtime": False,
        "claim": "NOT_SUPPORTED",
        "limitation": (
            "Intended as a lineage-driven fault injection source; the URL no longer resolves to the paper, so "
            "no lineage-driven claim is asserted anywhere in this unit."
        ),
    },
)

# Repository sources, identified by immutable content digest rather than by URL.
REPOSITORY_SOURCE_CLAIMS: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "P1",
        "path": "workstreams/po03/control/inputs/wave-a/wa-016.json",
        "sha256": "b574ca414864bec359a8edef86f13f064a31a4304eed5c5b95fab83eae88a824",
        "claim": "The frozen task input for this unit, including its falsifiable hypothesis, owned globs and required executable output.",
    },
    {
        "claim_id": "P2",
        "path": "workstreams/po03/control/acceptance/wave-a-material-v1.json",
        "sha256": "b46620e26cec19872279f0a0ac9aefbc562436c808b1ebea8a078b58e2c8585a",
        "claim": "The frozen producer-neutral acceptance contract, twelve required assertions and required artifact list.",
    },
    {
        "claim_id": "P3",
        "path": "workstreams/po03/COMMISSION.md",
        "sha256": "b6dff810facb443c7f081b98a3b578f6ad8521a1e79f13c3b862f527504b968d",
        "claim": "The custody lifecycle, the fault-injection clause, the PO-02 Code-2 fault fixture instruction and the collision boundary.",
    },
    {
        "claim_id": "P4",
        "path": "workstreams/po03/contracts/transactional-result.schema.json",
        "sha256": "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1",
        "claim": "The wire format for a transactional result, including the result_transaction.state enumeration.",
    },
    {
        "claim_id": "P5",
        "path": "workstreams/po03/tools/validate_contracts.py",
        "sha256": "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03",
        "claim": "The dependency-free executable validator that gates result custody; read-only to this unit and composed unmodified.",
    },
    {
        "claim_id": "P6",
        "path": "workstreams/po03/tests/test_validate_contracts.py",
        "sha256": "401a684c0a2d3817d08a76044a331f0f241b16d687d2dd12d9ea0f31612dc112",
        "claim": "The seeded validator tests, which establish that verified_at is the post-commit durability verification.",
    },
    {
        "claim_id": "P7",
        "path": "workstreams/po03/control/recovery-state.json",
        "claim": "The recorded PO-02 Code-2 fixture: provider COMPLETED, Obzio PROVIDER_COMPLETED_UNCOMMITTED, UNRECOVERED_AFTER_FOUR_REPORTED_ROUTES, NOT_ACCEPTED.",
        "note": "Read live rather than pinned, because the controller updates this file during the wave; the reproduction compares against whatever it reads.",
    },
    {
        "claim_id": "P8",
        "path": "workstreams/po03/runs/bc-b1956656-b897-4889-aeab-82c4556c1a9f/units/wa-isolation-canary-001/result/canary.txt",
        "commit": "371e8da6ab306c2948e0fe1f47c884ae46b2e81f",
        "sha256": "5fdeb53d88f287e7e82006277c55ab0b3359b3b1881f408929359285be95f31b",
        "bytes": 74,
        "claim": "A previously committed PO-03 artifact with an independently recorded digest, reused as this unit's sanitized workload payload.",
    },
    {
        "claim_id": "P9",
        "path": ".github/workflows/po03-contracts.yml",
        "sha256": "427949c07d93fe69bea6485a91ca58c4297be21759e6b0b00a0e5cc9f450c7cb",
        "claim": "CI discovers tests only under workstreams/po03/tests, so tests in a unit subtree are not yet executed by the seeded workflow.",
    },
)

# ------------------------------------------------------------ frozen hypotheses
HYPOTHESES: tuple[dict[str, Any], ...] = (
    {
        "hypothesis_id": "CM-H1",
        "source_claim_ids": ["S1"],
        "statement": (
            "If the durable store actively checks a monotonic fence token, a worker whose lease expired cannot "
            "write after ownership transfers, so a stale attempt cannot produce a second durable result."
        ),
        "prediction": "Every STALE_LEASE cell records a FENCED_OUT refusal and still reaches exactly one durable result.",
        "reproduction_ids": ["R6-HARNESS-FALSIFICATION-POWER", "MATRIX-STALE-LEASE-CELLS"],
        "evaluator": "fence",
    },
    {
        "hypothesis_id": "CM-H2",
        "source_claim_ids": ["S2", "S7"],
        "statement": (
            "If the harness is single-threaded with a logical clock and a declared fault schedule, re-running a "
            "cell reproduces the same fault ordering and the same custody outcome exactly."
        ),
        "prediction": "Two runs of one cell produce identical arrival-trace digests and identical result rows.",
        "reproduction_ids": ["R4-DETERMINISTIC-REPLAY"],
        "evaluator": "determinism",
    },
    {
        "hypothesis_id": "CM-H3",
        "source_claim_ids": ["S3", "S8"],
        "statement": (
            "If the external effect is keyed by the frozen idempotency key and is content addressed, repeated "
            "delivery attempts after a crash produce at most one distinct durable effect."
        ),
        "prediction": "No cell or fuzz case ever records more than one distinct external effect.",
        "reproduction_ids": ["R7-IDEMPOTENT-REPLAY-CONFLICT", "R3-REAL-GIT-CUSTODY", "MATRIX-I4"],
        "evaluator": "at_most_once",
    },
    {
        "hypothesis_id": "CM-H4",
        "source_claim_ids": ["S4"],
        "statement": (
            "If the parent callback is journaled in the same durable record as the RESULT_COMMITTED transition, "
            "a lost callback is replayable from the surviving outbox and a duplicated callback is harmless."
        ),
        "prediction": (
            "A lost callback is redelivered from the surviving outbox and the parent ingests exactly once; a "
            "duplicated callback is ignored exactly once."
        ),
        "prediction_correction": (
            "The prediction first written named the recovery scanner action REPLAY_LOST_CALLBACK specifically. "
            "The matrix showed the redelivery happening through the at-least-once relay on the next step, with "
            "the scanner path exercised instead by R1 route five. Naming one of two valid replay paths was an "
            "implementation detail, not part of the claim, so the prediction was widened to the claim itself "
            "and both paths are now checked. Recorded because the correction was made after seeing the result."
        ),
        "reproduction_ids": ["R1-PO02-CODE2-LOST-RETURN", "MATRIX-CALLBACK-CELLS"],
        "evaluator": "outbox",
    },
    {
        "hypothesis_id": "CM-H5",
        "source_claim_ids": ["S8"],
        "statement": (
            "If a replay under an existing idempotency key presents different parameters, the store errors "
            "rather than overwriting, so a divergent second result is detected instead of silently published."
        ),
        "prediction": "A restage with different bytes under the same key raises IdempotencyConflict.",
        "reproduction_ids": ["R7-IDEMPOTENT-REPLAY-CONFLICT"],
        "evaluator": "conflict",
    },
    {
        "hypothesis_id": "CM-H6",
        "source_claim_ids": ["S5"],
        "statement": (
            "If the harness has real falsification power, deliberately defective custody machines produce "
            "invariant violations, including a detected false completion for a machine that trusts the provider."
        ),
        "prediction": "All four mutants are detected and the provider-trusting mutant violates the no-false-completion invariant.",
        "reproduction_ids": ["R6-HARNESS-FALSIFICATION-POWER"],
        "evaluator": "falsification",
    },
    {
        "hypothesis_id": "CM-H7",
        "source_claim_ids": ["S6"],
        "statement": (
            "If custody is checked as a history and as a set of cross-field relations rather than per-field "
            "presence, documents exist that the seeded per-field validator admits while they assert a "
            "completion whose evidence is internally impossible."
        ),
        "prediction": "At least one such document exists and the strengthened layer rejects every one of them.",
        "reproduction_ids": ["R5-SEEDED-VALIDATOR-GAPS"],
        "evaluator": "gaps",
    },
    {
        "hypothesis_id": "CM-H8",
        "source_claim_ids": ["S2"],
        "statement": (
            "At this custody model's size, seeded randomized multi-fault scheduling discovers safety-invariant "
            "violation classes that exhaustive single-fault matrix enumeration does not."
        ),
        "prediction": "The fuzz campaign reports at least one safety class absent from the exhaustive matrix.",
        "reproduction_ids": ["FUZZ-CAMPAIGN"],
        "evaluator": "fuzz_advantage",
    },
)

# --------------------------------------------------------- mechanism dispositions
MECHANISM_CHANGES: tuple[dict[str, Any], ...] = (
    {
        "mechanism_id": "M1",
        "hypothesis_ids": ["CM-H7"],
        "scope": "PROPOSAL_TO_COORDINATOR",
        "change": (
            "custody_invariants.validate_result_strict composes the read-only seeded validator and appends six "
            "invariants: declared transaction state, lifecycle/transaction coherence, custody timestamp order, "
            "unique logical name and content URI, artifacts located at the claimed result commit, and a manifest "
            "digest whenever a manifest URI is claimed."
        ),
        "target": "workstreams/po03/tools/validate_contracts.py (not modified by this unit; strengthening lives in this unit's subtree)",
        "recurrence_test": "tests/test_custody_invariants.py::GapTests::test_every_declared_gap_is_admitted_upstream_and_rejected_here",
        "disposition": "PROPOSED_TO_COORDINATOR",
        "rationale": (
            "The seeded validator is an active control and read-only to this unit, so the change is delivered as "
            "a composing layer plus paired evidence rather than an edit."
        ),
    },
    {
        "mechanism_id": "M2",
        "hypothesis_ids": ["CM-H2"],
        "scope": "PROPOSAL_TO_COORDINATOR",
        "change": (
            "input_resolvability.gate refuses dispatch unless every pointer in a frozen input resolves in the "
            "target repository, closing the gap where automatic resume from immutable input is impossible "
            "because the input's own source base cannot be located."
        ),
        "target": "workstreams/po03/tools/prepare_wave_a.py and the dispatch precondition (not modified by this unit)",
        "recurrence_test": "tests/test_input_resolvability.py::DefectTests::test_the_gate_refuses_dispatch_while_the_defect_stands",
        "disposition": "PROPOSED_TO_COORDINATOR",
        "rationale": "prepare_wave_a.py is read-only to this unit; the defect it produced is reproduced and gated instead.",
    },
    {
        "mechanism_id": "M3",
        "hypothesis_ids": ["CM-H3", "CM-H5"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "commit_result re-reconciles staged bytes against the recorded manifest immediately before "
            "publishing. Found by this unit's own matrix: damage landing between verification and commit was "
            "published under the earlier manifest, and the spent idempotency key then blocked the repair."
        ),
        "target": "harness/custody_machine.py:commit_result",
        "recurrence_test": "tests/test_custody_machine.py::StagingVerificationTests::test_damage_between_verify_and_commit_is_refused",
        "disposition": "RETAIN",
        "rationale": "Measured defect with a recurrence test; the matrix cell that found it now passes.",
    },
    {
        "mechanism_id": "M4",
        "hypothesis_ids": ["CM-H1"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "The recovery scanner classifies repeated read-back failure against an immutable commit as "
            "FAILED_TERMINAL instead of retrying without bound, so unrecoverable remote damage terminates "
            "without ever approaching completion."
        ),
        "target": "harness/recovery.py:CLASSIFY_UNRECOVERABLE_REMOTE_DAMAGE",
        "recurrence_test": "tests/test_transition_matrix.py::RemoteDamageTests::test_remote_damage_terminates_without_completion",
        "additional_recurrence_test": "tests/test_recovery.py::BoundedTerminationTests::test_repeated_remote_damage_is_classified_terminally",
        "disposition": "RETAIN",
        "rationale": "Found by this unit's matrix as an unbounded retry loop; bounded and tested.",
    },
    {
        "mechanism_id": "M5",
        "hypothesis_ids": ["CM-H7"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "Re-entering RESULT_COMMITTED after a lost acknowledgement preserves the original committed_at "
            "instead of restamping it, so custody timestamps cannot claim a commit later than its own ingestion."
        ),
        "target": "harness/custody_machine.py:_record_commit_transition",
        "recurrence_test": "tests/test_transition_matrix.py::RemoteDamageTests::test_commit_reentry_preserves_commit_time",
        "disposition": "RETAIN",
        "rationale": "Found by the strengthened timestamp-order invariant applied to the matrix's own output.",
    },
    {
        "mechanism_id": "M7",
        "hypothesis_ids": ["CM-H2"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "The checkpoint sequence number travels inside the CHECKPOINTED transition record instead of a "
            "second journal record. Found by this unit's own focused tests: a crash between the two records "
            "left a task claiming CHECKPOINTED at a sequence it had never reached."
        ),
        "target": "harness/custody_machine.py:checkpoint",
        "recurrence_test": "tests/test_custody_machine.py::JournalIsTruthTests::test_checkpoint_sequence_lands_atomically_with_the_transition",
        "disposition": "RETAIN",
        "rationale": (
            "The machine already required a transition and its payload to land in one record for staging and "
            "for the outbox; checkpoints were the one place that rule was not applied."
        ),
    },
    {
        "mechanism_id": "M8",
        "hypothesis_ids": ["CM-H8"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "The fuzz driver applies an environment fault inside the same recovery path as the custody step. "
            "Found only at campaign scale: an environment action is itself a durable write, so a point fault "
            "scheduled on the same step crashed it and the exception escaped the driver rather than being "
            "recovered."
        ),
        "target": "harness/fuzz.py:run_case",
        "recurrence_test": "tests/test_fuzz.py::CaseTests::test_a_fault_during_an_environment_action_does_not_escape_the_driver",
        "disposition": "RETAIN",
        "rationale": (
            "A defect in the measuring instrument, not the machine under test, but it silently truncated the "
            "campaign the M6 rejection rests on, so it is recorded with the same standing."
        ),
    },
    {
        "mechanism_id": "M9",
        "hypothesis_ids": ["CM-H7"],
        "scope": "LIVE_IN_THIS_UNIT",
        "change": (
            "The return documents record where each undigestable digest is deferred to instead of reading "
            "their own path off disk. A document cannot contain its own digest, and an implementation that "
            "tries reports whatever an earlier run left behind: a digest that is plausible, current-looking "
            "and wrong. The manifest and result now defer explicitly and name the link that closes the chain."
        ),
        "target": "harness/emit_result.py:build_manifest, harness/emit_result.py:artifact_accounting",
        "recurrence_test": (
            "tests/test_emit_result.py::ArtifactAccountingTests::"
            "test_a_stale_digest_left_by_an_earlier_run_is_not_reported_as_current"
        ),
        "additional_recurrence_test": (
            "tests/test_emit_result.py::ArtifactAccountingTests::"
            "test_the_chain_accounts_for_every_owned_file_exactly_once"
        ),
        "disposition": "RETAIN",
        "rationale": (
            "The same class of defect as a false completion, in the reporting layer rather than the machine: "
            "a self-digest reads as verified while attesting to bytes that are no longer there. Caught here "
            "only because the digest was recomputed rather than trusted."
        ),
    },
    {
        "mechanism_id": "M6",
        "hypothesis_ids": ["CM-H8"],
        "scope": "REJECTION",
        "change": (
            "Randomized multi-fault fuzzing is retained as a cheap regression sweep but rejected as a "
            "substitute for exhaustive single-fault enumeration at this model's size."
        ),
        "target": "harness/fuzz.py",
        "recurrence_test": "tests/test_fuzz.py::CampaignTests::test_fuzz_finds_no_class_the_matrix_missed",
        "disposition": "EVIDENCE_BACKED_REJECTION",
        "rationale": "Filled in from the campaign result at run time; see mechanism_evidence in result.json.",
    },
)


def evaluate(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach an outcome to each frozen hypothesis from observed evidence."""
    matrix = evidence["matrix"]
    reproductions = {r["reproduction_id"]: r for r in evidence["reproductions"]}
    campaign = evidence["fuzz_campaign"]
    comparison = evidence["fuzz_comparison"]
    rows = matrix["rows"]

    def outcome(ok: bool | None, detail: str) -> dict[str, Any]:
        if ok is None:
            return {"state": "REPRODUCED", "outcome": "NOT_SUPPORTED", "evidence": detail}
        return {"state": "REPRODUCED", "outcome": "SUPPORTED" if ok else "REFUTED", "evidence": detail}

    stale_rows = [r for r in rows if r["fault_kind"] == "STALE_LEASE"]
    callback_rows = [r for r in rows if r["fault_kind"] in {"CALLBACK_LOSS", "DUPLICATE_CALLBACK"}]
    results: list[dict[str, Any]] = []
    for hypothesis in HYPOTHESES:
        name = hypothesis["evaluator"]
        if name == "fence":
            ok = bool(stale_rows) and all(
                "FENCED_OUT" in r["refusals_recorded"] and r["distinct_external_effects"] <= 1 and not r["violations"]
                for r in stale_rows
            )
            detail = f"{len(stale_rows)} stale-lease cells, all recording FENCED_OUT with at most one durable effect"
        elif name == "determinism":
            repro = reproductions["R4-DETERMINISTIC-REPLAY"]
            ok = repro["verdict"] == "REPRODUCED"
            detail = f"trace digests equal={repro['trace_digests_equal']} rows equal={repro['rows_equal']}"
        elif name == "at_most_once":
            ok = (
                all(r["distinct_external_effects"] <= 1 for r in rows)
                and campaign["max_distinct_external_effects"] <= 1
                and reproductions["R7-IDEMPOTENT-REPLAY-CONFLICT"]["verdict"] == "REPRODUCED"
            )
            detail = (
                f"max distinct effects across {len(rows)} cells and {campaign['case_count']} fuzz cases = "
                f"{max([r['distinct_external_effects'] for r in rows] + [campaign['max_distinct_external_effects']])}"
            )
        elif name == "outbox":
            lost_rows = [r for r in callback_rows if r["fault_kind"] == "CALLBACK_LOSS"]
            duplicate_rows = [r for r in callback_rows if r["fault_kind"] == "DUPLICATE_CALLBACK"]
            route_five = reproductions["R1-PO02-CODE2-LOST-RETURN"]
            relay_path = bool(lost_rows) and all(
                not r["violations"] and r["history"].count("PARENT_INGESTED") == 1 and r["final_obzio_state"] == "COMPLETED"
                for r in lost_rows
            )
            duplicates_harmless = bool(duplicate_rows) and all(
                not r["violations"] and r["history"].count("PARENT_INGESTED") == 1 and r["duplicate_ingests_ignored"] >= 1
                for r in duplicate_rows
            )
            scanner_path = "REPLAY_LOST_CALLBACK" in route_five.get("route_five_recovery_actions", [])
            ok = relay_path and duplicates_harmless and scanner_path
            detail = (
                f"{len(lost_rows)} lost-callback cells redelivered with exactly one ingestion, "
                f"{len(duplicate_rows)} duplicate-callback cells ignored the duplicate, "
                f"scanner replay path evidenced by R1 route five={scanner_path}"
            )
        elif name == "conflict":
            repro = reproductions["R7-IDEMPOTENT-REPLAY-CONFLICT"]
            ok = repro.get("divergent_replay_outcome") == "IdempotencyConflict"
            detail = f"divergent replay outcome={repro.get('divergent_replay_outcome')}"
        elif name == "falsification":
            repro = reproductions["R6-HARNESS-FALSIFICATION-POWER"]
            ok = repro["all_mutants_detected"] and repro["false_completion_detected_in_provider_trusting_mutant"]
            detail = "; ".join(
                f"{m['mutant']}={m['cells_with_violations']} cells" for m in repro["mutants"]
            )
        elif name == "gaps":
            repro = reproductions["R5-SEEDED-VALIDATOR-GAPS"]
            ok = repro["admitted_by_seeded_validator"] > 0 and repro["closed_by_strengthened_layer"] == repro["gap_count"]
            detail = (
                f"{repro['admitted_by_seeded_validator']} of {repro['gap_count']} documents admitted by the seeded "
                f"validator, {repro['closed_by_strengthened_layer']} rejected by the strengthened layer"
            )
        elif name == "fuzz_advantage":
            ok = comparison["fuzz_found_new_class"]
            detail = (
                f"{campaign['case_count']} seeded cases with up to {campaign['max_faults_per_case']} overlapping "
                f"faults found safety classes {sorted(campaign['safety_violation_classes'])}; classes unique to "
                f"fuzz={comparison['classes_found_only_by_fuzz']}"
            )
        else:
            ok, detail = None, "no evaluator"
        record = dict(hypothesis)
        record.update(outcome(ok, detail))
        results.append(record)
    return results


def resolve_mechanisms(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Fill the rejection's evidence from the observed campaign."""
    comparison = evidence["fuzz_comparison"]
    campaign = evidence["fuzz_campaign"]
    resolved: list[dict[str, Any]] = []
    for mechanism in MECHANISM_CHANGES:
        record = dict(mechanism)
        if mechanism["mechanism_id"] == "M6":
            record["mechanism_evidence"] = (
                f"{campaign['case_count']} seeded fuzz cases with up to {campaign['max_faults_per_case']} "
                f"overlapping faults produced {campaign['cases_with_safety_violations']} safety violations and "
                f"{len(comparison['classes_found_only_by_fuzz'])} classes not already covered by the "
                f"{comparison['exhaustive_cells']}-cell exhaustive matrix."
            )
            record["rejected_claim"] = "CM-H8"
        resolved.append(record)
    return resolved
