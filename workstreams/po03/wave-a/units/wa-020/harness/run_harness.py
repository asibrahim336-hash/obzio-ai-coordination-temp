"""Entry point: run the harness, evaluate the hypotheses, write the evidence.

Order matters and is enforced rather than described. The criteria are sealed
before the submission pool is built, and the seal digest recorded in
``evidence/criteria-freeze.json`` is recomputed from the criteria specification at
the end of the run, so a criteria edit anywhere in between is detectable from the
evidence alone.

Usage::

    python3 -I -B -m harness.run_harness [--offline]

``--offline`` skips external retrieval and records every external source as
NOT_SUPPORTED, which is what a runtime without egress produces anyway.
"""

from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path
from typing import Any

from . import dispatched_hypothesis, research
from .bias_experiment import identity_permutations, run_experiment
from .blinding import (
    ArrivalOrderBlinder,
    Blinder,
    LeakyBlinder,
    PerIdentityVocabularyBlinder,
    find_leaks,
    label_standing_correlation,
    pool_vocabulary,
)
from .candidates import (
    STANDING_POLICY,
    build_pool,
    harvest_identity_envelopes,
    identity_pool,
    observed_prior_producer,
)
from .canonical import digest, digest_bytes, write_json
from .claims import adversarial_representation_check, attractiveness_table
from .criteria import frozen_criteria, seal_digest
from .logical_clock import LogicalClock
from .probes import RepositoryProbes, repository_root
from .seeded_case import CANDIDATE_CLAIMS, SEEDED_CASE_DESIGN, SEEDED_FALSE_CLAIM_ID

UNIT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = UNIT_ROOT / "evidence"


def _reproductions(
    root: Path, probes: RepositoryProbes, pool, identities, experiment: dict[str, Any]
) -> list[dict[str, Any]]:
    """Observations obtained by running things, recorded separately from hypotheses."""
    permutations = identity_permutations(pool, identities)
    vocabulary = pool_vocabulary(identities)

    state_enum = probes.transaction_state_enum()
    logical_name = probes.logical_name_uniqueness()
    baseline = probes.baseline_is_admitted()

    renderings: dict[str, dict[str, str]] = {}
    for blinder in (Blinder(), PerIdentityVocabularyBlinder()):
        digests: dict[str, str] = {}
        for permutation in permutations:
            permuted = pool.with_identities(permutation["assignment"])
            blinded = blinder.blind(
                permuted.by_id("SUB-1"), 1, 0, pool_vocabulary(permuted.identities)
            )
            digests[permutation["permutation_id"]] = digest_bytes(blinded.rendered())
        renderings[blinder.name] = digests

    permuted = pool.with_identities(permutations[0]["assignment"])
    leaky = LeakyBlinder().blind(permuted.by_id("SUB-2"), 1, 1, vocabulary)
    correct = Blinder().blind(
        permuted.by_id("SUB-2"), 1, 1, pool_vocabulary(permuted.identities)
    )
    leaky_leaks = find_leaks(leaky.rendered(), permuted.by_id("SUB-2").identity)
    correct_leaks = find_leaks(correct.rendered(), permuted.by_id("SUB-2").identity)

    tiers = [submission.identity.standing_tier for submission in pool.submissions]
    arrival_labels = [
        ArrivalOrderBlinder().blind(submission, 1, index, vocabulary).pseudonym
        for index, submission in enumerate(pool.submissions)
    ]
    content_labels = [
        Blinder().blind(submission, 1, index, vocabulary).pseudonym
        for index, submission in enumerate(pool.submissions)
    ]

    replay = run_experiment(pool, probes, identities)
    first_digest = digest(experiment["summary_by_cell"])
    second_digest = digest(replay["summary_by_cell"])

    return [
        {
            "detail": {
                "baseline_disposition": baseline.disposition,
                "mutation": state_enum.detail["mutation"],
                "observed_disposition": state_enum.disposition,
                "reported_errors": state_enum.reported_errors,
                "returncode": state_enum.returncode,
            },
            "reproduction_id": "R1-SEEDED-CONTROL-ADMITS-UNDECLARED-TRANSACTION-STATE",
            "statement": (
                "The seeded executable control admits a transactional result whose "
                "result_transaction.state is absent from the enumeration its own schema declares. The "
                "baseline document without that mutation is admitted too, so the observation isolates "
                "the field."
            ),
            "verdict": "DEFECT_REPRODUCED" if state_enum.disposition == "ADMITTED" else "NOT_REPRODUCED",
        },
        {
            "detail": {
                "mutation": logical_name.detail["mutation"],
                "observed_disposition": logical_name.disposition,
                "returncode": logical_name.returncode,
            },
            "reproduction_id": "R2-SEEDED-CONTROL-ADMITS-DUPLICATE-LOGICAL-NAME",
            "statement": (
                "The seeded control admits a result in which two artifacts share one logical_name and "
                "one content_uri under different artifact identifiers, so one file can be counted twice "
                "toward a manifest."
            ),
            "verdict": "DEFECT_REPRODUCED" if logical_name.disposition == "ADMITTED" else "NOT_REPRODUCED",
        },
        {
            "detail": {
                "cited_prior_attempt": pool.by_id("SUB-1").prior_art[:160],
                "distinct_renderings": {
                    name: len(set(digests.values())) for name, digests in sorted(renderings.items())
                },
                "rendering_digests": {
                    name: dict(sorted(digests.items())) for name, digests in sorted(renderings.items())
                },
            },
            "reproduction_id": "R3-PER-IDENTITY-VOCABULARY-IS-AN-IDENTITY-CHANNEL",
            "statement": (
                "One submission's content, rendered under four identity permutations, produces more "
                "than one distinct byte string when redaction uses each submission's own identity "
                "vocabulary, and exactly one when redaction uses the pool-wide vocabulary. The channel "
                "is the collateral damage to a legitimate prior-art citation."
            ),
            "verdict": (
                "DEFECT_REPRODUCED"
                if len(set(renderings["PerIdentityVocabularyBlinder"].values())) > 1
                and len(set(renderings["Blinder"].values())) == 1
                else "NOT_REPRODUCED"
            ),
        },
        {
            "detail": {
                "arrival_order_correlation": label_standing_correlation(arrival_labels, tiers),
                "content_derived_correlation": label_standing_correlation(content_labels, tiers),
                "standing_tiers_in_arrival_order": tiers,
            },
            "reproduction_id": "R4-ARRIVAL-ORDER-LABELS-RANK-THE-PRODUCERS",
            "statement": (
                "For a pool arranged in descending standing, arrival-order pseudonyms reproduce the "
                "standing ranking exactly while content-derived pseudonyms do not, with every identity "
                "string removed from every payload in both cases."
            ),
            "verdict": (
                "DEFECT_REPRODUCED"
                if label_standing_correlation(arrival_labels, tiers) == 1.0
                else "NOT_REPRODUCED"
            ),
        },
        {
            "detail": {
                "correct_blinder_leaks": len(correct_leaks),
                "leaky_blinder_leaks": len(leaky_leaks),
                "sample_leaked_tokens": sorted({leak["token"] for leak in leaky_leaks})[:6],
            },
            "reproduction_id": "R5-LEAK-SCANNER-CATCHES-A-FIELD-LEVEL-REDACTOR",
            "statement": (
                "A blinder that drops the identity envelope and leaves the prose alone still leaks, "
                "because the producer's own writing names its branch, its attempt and its model. The "
                "scanner reads the rendered bytes and finds them."
            ),
            "verdict": "REPRODUCED" if leaky_leaks and not correct_leaks else "NOT_REPRODUCED",
        },
        {
            "detail": {
                "first_run_summary_sha256": first_digest,
                "second_run_summary_sha256": second_digest,
                "note": (
                    "The review path uses a logical clock and no wall-clock time, so the sixteen-cell "
                    "summary is byte-identical between runs in the same checkout."
                ),
            },
            "reproduction_id": "R6-DETERMINISTIC-REPLAY",
            "statement": "Running the whole sixteen-cell design twice produces an identical summary digest.",
            "verdict": "REPRODUCED" if first_digest == second_digest else "NOT_REPRODUCED",
        },
    ]


def _evaluate_hypotheses(experiment: dict[str, Any], reproductions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill each preregistered hypothesis with its outcome and the evidence for it."""
    cells = {cell["cell_id"]: cell for cell in experiment["cells"]}
    blinding = experiment["blinding_effect"]
    gate = experiment["gate_effect"]
    freeze = experiment["freeze_effect_under_blinding"]
    by_id = {item["reproduction_id"]: item for item in reproductions}

    unblinded_biased = cells.get("unblinded|gated|standing-sensitive|probing", {})
    probing_blind_cells = [
        cell for cell_id, cell in cells.items() if cell["blind"] and cell_id.endswith("probing")
    ]
    credulous_cells = [cell for cell_id, cell in cells.items() if cell_id.endswith("credulous")]

    outcomes: dict[str, dict[str, Any]] = {
        "CM-H1": {
            "evidence": (
                f"{blinding['blind_cells']} blind cells, maximum identity swing "
                f"{blinding['max_identity_swing_in_blind_cells']}, rank inversions "
                f"{blinding['rank_inversions_in_blind_cells']}"
            ),
            "outcome": "SUPPORTED"
            if blinding["max_identity_swing_in_blind_cells"] == 0
            and blinding["rank_inversions_in_blind_cells"] == 0
            else "REFUTED",
            "reproduction_ids": ["R5-LEAK-SCANNER-CATCHES-A-FIELD-LEVEL-REDACTOR", "R6-DETERMINISTIC-REPLAY"],
        },
        "CM-H2": {
            "evidence": (
                f"maximum identity swing across unblinded cells is "
                f"{blinding['max_identity_swing_in_unblinded_cells']} weighted points, with "
                f"{blinding['rank_inversions_in_unblinded_cells']} rank inversions; the neutral "
                "unblinded cells swing 0, so the effect is the interaction of visibility and bias "
                "rather than visibility alone"
            ),
            "outcome": "SUPPORTED" if blinding["max_identity_swing_in_unblinded_cells"] > 0 else "REFUTED",
            "reproduction_ids": [],
        },
        "CM-H3": {
            "evidence": (
                f"{len(probing_blind_cells)} blind probing cells catch the claim in every permutation; "
                f"{len(credulous_cells)} credulous cells catch it in none"
            ),
            "outcome": "SUPPORTED"
            if all(cell["catch_rate"].startswith("4/") for cell in probing_blind_cells)
            and all(cell["catch_rate"].startswith("0/") for cell in credulous_cells)
            else "REFUTED",
            "reproduction_ids": ["R1-SEEDED-CONTROL-ADMITS-UNDECLARED-TRANSACTION-STATE"],
        },
        "CM-H4": {
            "evidence": (
                f"unblinded standing-sensitive probing cell catch rate {unblinded_biased.get('catch_rate')}; "
                "the missed permutation is the one attributing the claim to the highest standing tier"
            ),
            "outcome": "SUPPORTED" if unblinded_biased.get("catch_rate") == "3/4" else "REFUTED",
            "reproduction_ids": [],
        },
        "CM-H5": {
            "evidence": (
                f"gated session refused a post-ingestion seal ({gate['gated_session_refused_post_hoc_seal']}); "
                f"with the gate removed the favoured submission gains {gate['shopping_gain_for_target']} "
                f"weighted points under the {gate['shopped_weighting']} weighting"
            ),
            "outcome": "SUPPORTED"
            if gate["gated_session_refused_post_hoc_seal"] and gate["shopping_gain_for_target"] > 0
            else "REFUTED",
            "reproduction_ids": [],
        },
        "CM-H6": {
            "evidence": str(by_id["R3-PER-IDENTITY-VOCABULARY-IS-AN-IDENTITY-CHANNEL"]["detail"]["distinct_renderings"]),
            "outcome": "SUPPORTED"
            if by_id["R3-PER-IDENTITY-VOCABULARY-IS-AN-IDENTITY-CHANNEL"]["verdict"] == "DEFECT_REPRODUCED"
            else "REFUTED",
            "reproduction_ids": ["R3-PER-IDENTITY-VOCABULARY-IS-AN-IDENTITY-CHANNEL"],
        },
        "CM-H7": {
            "evidence": (
                f"arrival-order correlation "
                f"{by_id['R4-ARRIVAL-ORDER-LABELS-RANK-THE-PRODUCERS']['detail']['arrival_order_correlation']}, "
                f"content-derived correlation "
                f"{by_id['R4-ARRIVAL-ORDER-LABELS-RANK-THE-PRODUCERS']['detail']['content_derived_correlation']}"
            ),
            "outcome": "SUPPORTED"
            if by_id["R4-ARRIVAL-ORDER-LABELS-RANK-THE-PRODUCERS"]["verdict"] == "DEFECT_REPRODUCED"
            else "REFUTED",
            "reproduction_ids": ["R4-ARRIVAL-ORDER-LABELS-RANK-THE-PRODUCERS"],
        },
        "CM-H8": {
            "evidence": (
                f"under blinding, removing the gate changed a ranking: "
                f"{freeze['any_ranking_changed_under_blinding']}. Secondary and not preregistered: the "
                f"post-ingestion weighting produced a gain spread of "
                f"{freeze['differential_gain']['max_gain_spread']} weighted points across candidates, so "
                "it favoured some over others rather than shifting the scale. The preregistered metric "
                "is the ranking, and it is reported as measured."
            ),
            "outcome": "SUPPORTED" if freeze["any_ranking_changed_under_blinding"] else "REFUTED",
            "reproduction_ids": [],
        },
        "CM-H9": {
            "evidence": (
                "No human reviewer and no language-model reviewer was measured anywhere in this unit. "
                "The unblinded arm is a declared model of a standing-sensitive reviewer written by this "
                "unit, so it fixes the magnitude by construction and cannot estimate the magnitude for "
                "any real reviewer. The blind-arm result is a property of real code and stands on its "
                "own; the transfer claim does not follow from it."
            ),
            "outcome": "NOT_SUPPORTED",
            "reproduction_ids": [],
        },
    }

    evaluated: list[dict[str, Any]] = []
    for hypothesis in research.HYPOTHESES:
        record = dict(hypothesis)
        record.update(outcomes[hypothesis["hypothesis_id"]])
        record["state"] = "REPRODUCED" if record["outcome"] in ("SUPPORTED", "REFUTED") else "UNRESOLVED"
        evaluated.append(record)
    return evaluated


def _mechanism_changes(
    reproductions: list[dict[str, Any]], dispatched: dict[str, Any]
) -> list[dict[str, Any]]:
    """What this unit did about each outcome, kept separate from the outcomes."""
    by_id = {item["reproduction_id"]: item for item in reproductions}
    conjunct_b = next(item for item in dispatched["conjuncts"] if item["conjunct_id"] == "B")
    return [
        {
            "change": (
                "Redaction runs against the union of every identity token in the submission pool rather "
                "than against each submission's own identity, so the collateral damage to prose is "
                "identical whoever wrote the submission."
            ),
            "disposition": "RETAIN",
            "found_by": "this unit's metamorphic comparison of one submission rendered under four identities",
            "hypothesis_ids": ["CM-H1", "CM-H6"],
            "mechanism_id": "M1",
            "rationale": (
                "The naive version removes every identity string and still leaks. A submission that "
                "cites a committed prior attempt loses the citation under one reviewer and keeps it "
                "under the others, so the surviving bytes differ by identity. The defect is invisible to "
                "a leak scan of any single payload and only appears when the same content is rendered "
                "twice."
            ),
            "recurrence_test": "tests/test_blinding.py::PoolVocabularyTests::test_pool_vocabulary_renders_identically_under_every_identity",
            "scope": "LIVE_IN_THIS_UNIT",
            "target": "harness/blinding.py:pool_vocabulary, harness/blinding.py:Blinder.vocabulary_for",
            "verdict_evidence": by_id["R3-PER-IDENTITY-VOCABULARY-IS-AN-IDENTITY-CHANNEL"]["detail"][
                "distinct_renderings"
            ],
        },
        {
            "change": (
                "Hedging is measured on the author's own prose, with quoted spans removed, so a claim is "
                "not penalised for accurately reproducing a control's error message."
            ),
            "disposition": "RETAIN",
            "found_by": "this unit's own attractiveness table, which scored the paired true claim one feature low",
            "hypothesis_ids": ["CM-H3"],
            "mechanism_id": "M2",
            "rationale": (
                "The seeded false claim outscored its paired true claim by one feature solely because the "
                "true claim quoted the string 'only coordinator may set COMPLETED', and the hedge "
                "detector read the modal verb inside the quotation as the author's own hedging. Left "
                "uncorrected, the adversarial-representation check would have reported the seeded claim "
                "as strictly most attractive on the strength of a measurement artefact."
            ),
            "recurrence_test": "tests/test_claims.py::AttractivenessTests::test_quoted_control_output_is_not_read_as_hedging",
            "scope": "LIVE_IN_THIS_UNIT",
            "target": "harness/claims.py:author_prose",
        },
        {
            "change": (
                "Pseudonyms are derived from the digest of the blinded content instead of from arrival "
                "order."
            ),
            "disposition": "RETAIN",
            "found_by": "designed as a control, then measured",
            "hypothesis_ids": ["CM-H7"],
            "mechanism_id": "M3",
            "rationale": (
                "Arrival order is an identity channel whenever submissions arrive in standing order, and "
                "it survives complete redaction of every payload."
            ),
            "recurrence_test": "tests/test_blinding.py::LabelChannelTests::test_arrival_order_labels_rank_the_withheld_standing",
            "scope": "LIVE_IN_THIS_UNIT",
            "target": "harness/blinding.py:Blinder.label",
        },
        {
            "change": (
                "A catch requires both a refutation and the frozen gate criterion scoring zero for the "
                "candidate that carried the claim, rather than a refutation alone."
            ),
            "disposition": "RETAIN",
            "found_by": "specifying the metric before running the design",
            "hypothesis_ids": ["CM-H3", "CM-H4"],
            "mechanism_id": "M4",
            "rationale": (
                "A review that records a refutation and still scores the candidate as though nothing were "
                "wrong has not caught anything. Under the weaker definition the unblinded standing-"
                "sensitive cell would have reported a catch in the permutation where the reviewer "
                "discounted the refutation, which is precisely the failure the experiment exists to see."
            ),
            "recurrence_test": "tests/test_review.py::CatchDefinitionTests::test_a_refutation_the_reviewer_discounts_is_not_a_catch",
            "scope": "LIVE_IN_THIS_UNIT",
            "target": "harness/review.py:ReviewRecord.caught",
        },
        {
            "change": (
                "The seeded executable control should compare result_transaction.state against the "
                "enumeration its own schema declares."
            ),
            "disposition": "PROPOSED_TO_COORDINATOR",
            "found_by": "R1, by executing the control on a document the control itself accepts",
            "hypothesis_ids": ["CM-H3"],
            "mechanism_id": "M5",
            "rationale": (
                "The control is read-only to this unit, so the gap is reproduced and proposed rather than "
                "edited. Independently reached here by execution; WA-016 recorded the same gap as GAP-1 "
                "from a different direction, which is corroboration rather than this unit's evidence."
            ),
            "recurrence_test": "tests/test_probes.py::GroundTruthTests::test_the_control_admits_an_undeclared_transaction_state",
            "scope": "PROPOSAL_TO_COORDINATOR",
            "target": "workstreams/po03/tools/validate_contracts.py (not modified by this unit)",
        },
        {
            "change": (
                "The seeded control should enforce uniqueness of artifact logical_name and content_uri, "
                "not only of artifact_id."
            ),
            "disposition": "PROPOSED_TO_COORDINATOR",
            "found_by": "R2, by executing the control",
            "hypothesis_ids": ["CM-H3"],
            "mechanism_id": "M6",
            "rationale": (
                "Two entries describing one path under two identifiers inflate both artifact_count and "
                "total_bytes while every per-field check passes."
            ),
            "recurrence_test": "tests/test_probes.py::GroundTruthTests::test_the_control_admits_a_duplicate_logical_name",
            "scope": "PROPOSAL_TO_COORDINATOR",
            "target": "workstreams/po03/tools/validate_contracts.py (not modified by this unit)",
        },
        {
            "change": (
                "This unit's own preregistered claim CM-H8, that removing the ordering gate changes a "
                "review ranking once identity is withheld, is rejected on the evidence. The gate is "
                "retained on the separate grounds established by CM-H5, and its marginal value under "
                "blinding is recorded as not demonstrated on this pool rather than assumed."
            ),
            "disposition": "EVIDENCE_BACKED_REJECTION",
            "found_by": "the blind gated versus blind ungated comparison, which failed the metric this unit set for it",
            "hypothesis_ids": ["CM-H8"],
            "mechanism_id": "M7",
            "prediction_as_written": (
                "Under blinding, removing the ordering gate still changes at least one ranking, so "
                "blinding does not make the freeze redundant."
            ),
            "rationale": (
                "The observation is that the weighting chosen after ingestion moved the margins a long "
                "way and reordered nobody. The extra gain landed on the candidate resting on a refuted "
                "claim and on the candidate whose only strength is its own confidence, which is the "
                "direction the freeze exists to prevent, but a margin is not the metric this unit "
                "preregistered. Restating the metric after seeing the result would be the exact failure "
                "the criteria seal is built to prevent, so the claim is recorded as refuted and the "
                "margin observation is reported separately as an unpreregistered secondary reading. The "
                "gate is retained because CM-H5 establishes its effect directly and without reference to "
                "blinding: it refuses a post-ingestion seal, and with it removed the favoured submission "
                "gains 40 weighted points in the unblinded arm."
            ),
            "recurrence_test": "tests/test_bias_experiment.py::FreezeEffectTests::test_the_preregistered_ranking_metric_is_reported_as_measured",
            "rejected_claim": "CM-H8, as this unit preregistered it",
            "scope": "REJECTION",
            "secondary_reading_not_preregistered": (
                "Under blinding the post-ingestion weighting produced a gain spread across candidates "
                "rather than a uniform shift, favouring the candidate with a refuted claim. Recorded as an "
                "observation, not as support for the rejected claim."
            ),
            "target": "the design of the review session; no code change follows from the rejection",
        },
        {
            "change": (
                "A blind review gate must carry an execution step. Freezing a criterion that demands "
                "verification does not produce verification, so a review procedure built from an "
                "ordering gate and anonymization alone should not be credited with catching false "
                "claims."
            ),
            "disposition": "EVIDENCE_BACKED_REJECTION",
            "found_by": (
                "holding both factors of the dispatched mechanism on and varying only the adjudicator, "
                "which is the comparison the factorial design was built to make"
            ),
            "hypothesis_ids": ["H-PO03-WA-020", "CM-H3", "CM-H4"],
            "mechanism_id": "M8",
            "prediction_as_written": (
                "Criteria frozen before anonymized candidate ingestion catch one seeded attractive "
                "false claim."
            ),
            "rationale": (
                "With the ordering gate enforced and every identity withheld, a credulous adjudicator "
                f"catches the seeded claim in {conjunct_b['measurement']['mechanism_with_a_credulous_adjudicator']} "
                "permutations, while the same mechanism with a probing adjudicator catches it in "
                f"{conjunct_b['measurement']['mechanism_with_a_probing_adjudicator']}. The mechanism is "
                "fully present in both arms, so it is not what separates them. The claim was built to be "
                "true of the contract and false only of the code that enforces it, which is precisely "
                "the kind of falsity that reading cannot reach and execution can. Anonymization keeps "
                "the narrower credit the evidence supports: it prevents a biased reviewer discounting a "
                "refutation the probe already obtained, worth one permutation in the single cell where "
                "standing is visible and the control is run."
            ),
            "recurrence_test": (
                "tests/test_dispatched_hypothesis.py::ConjunctBTests::"
                "test_the_mechanism_alone_catches_nothing_without_execution"
            ),
            "rejected_claim": "the second conjunct of the dispatched hypothesis H-PO03-WA-020, as dispatched",
            "scope": "REJECTION",
            "target": (
                "the dispatched hypothesis itself; this unit's harness already executes controls, so the "
                "rejection is a correction to the claimed causal mechanism rather than a code change"
            ),
            "verdict_evidence": {
                "marginal_effect_of_executing_the_control": conjunct_b[
                    "marginal_effect_of_executing_the_control"
                ],
                "marginal_effect_of_the_freeze": conjunct_b["marginal_effect_of_the_freeze"],
                "mechanism_with_a_credulous_adjudicator": conjunct_b["measurement"][
                    "mechanism_with_a_credulous_adjudicator"
                ],
            },
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="skip external retrieval")
    args = parser.parse_args(argv)

    started = time.time()
    root = repository_root()

    # 1. Seal the criteria. Nothing about any candidate has been read yet.
    clock = LogicalClock()
    criteria = frozen_criteria(clock)
    if criteria.sealed_at_tick != 1:
        raise AssertionError("criteria must be sealed at the first tick of the run")

    # 2. Only now build the pool.
    probes = RepositoryProbes(root)
    prior = observed_prior_producer(root)
    identities = identity_pool(root)
    pool = build_pool(identities, prior)

    control_digests = list(probes.control_digests().detail["observed_sha256"].values())
    enum_values = probes.schema_declares_state_enum().detail["enum"] or []
    table = attractiveness_table(CANDIDATE_CLAIMS, control_digests, enum_values)
    adversarial = adversarial_representation_check(CANDIDATE_CLAIMS, table)

    experiment = run_experiment(pool, probes, identities)
    reproductions = _reproductions(root, probes, pool, identities, experiment)
    hypotheses = _evaluate_hypotheses(experiment, reproductions)
    dispatched = dispatched_hypothesis.evaluate(experiment)
    mechanisms = _mechanism_changes(reproductions, dispatched)

    external = [] if args.offline else research.fetch_external_claims()
    if args.offline:
        external = [
            {
                "claim": research.NOT_SUPPORTED,
                "claim_id": source["claim_id"],
                "limitation": "run with --offline; no external retrieval was attempted",
                "readable_in_runtime": False,
                "url": source["url"],
            }
            for source in research.EXTERNAL_SOURCES
        ]
    repository = research.repository_claims(root)
    unsupported = research.unsupported_source_ids(external, repository)
    separation = research.state_separation(
        source_claim_ids=[record["claim_id"] for record in external + repository],
        hypothesis_ids=[item["hypothesis_id"] for item in hypotheses],
        reproduction_ids=[item["reproduction_id"] for item in reproductions],
        mechanism_ids=[item["mechanism_id"] for item in mechanisms],
        candidate_claim_ids=[claim.claim_id for claim in CANDIDATE_CLAIMS],
    )

    # 3. Recompute the seal over the criteria as they stand at the end of the run.
    criteria.verify()
    recomputed = seal_digest(criteria.criteria)

    written: dict[str, tuple[str, int]] = {}
    written["criteria-freeze.json"] = write_json(
        EVIDENCE / "criteria-freeze.json",
        {
            "criteria": criteria.as_record(),
            "note": (
                "Sealed at the first tick of the run, before the submission pool was constructed and "
                "before any probe was executed. The digest below is recomputed from the criteria "
                "specification at the end of the run and compared with the value taken at seal time."
            ),
            "recomputed_at_end_of_run_sha256": recomputed,
            "seal_intact": recomputed == criteria.seal_sha256,
            "sealed_before_pool_construction": True,
        },
    )
    written["seeded-case.json"] = write_json(
        EVIDENCE / "seeded-case.json",
        {
            "adversarial_representation": adversarial,
            "candidate_claims": [claim.as_record() for claim in CANDIDATE_CLAIMS],
            "design": SEEDED_CASE_DESIGN,
            "seeded_claim_id": SEEDED_FALSE_CLAIM_ID,
        },
    )
    written["candidate-pool.json"] = write_json(
        EVIDENCE / "candidate-pool.json",
        {
            "identity_envelopes": [envelope.as_record() for envelope in identities],
            "observed_identity_shapes": harvest_identity_envelopes(root),
            "observed_prior_producer": prior,
            "sanitisation": (
                "No credential, owner identity or third-party content. Every identity string is either "
                "read from a committed result document in this repository or built from the shapes those "
                "documents use."
            ),
            "standing_policy": [
                {"family": family, "role": role, "tier": tier} for family, tier, role in STANDING_POLICY
            ],
            "submissions": [
                {
                    "claim_ids": list(submission.claim_ids),
                    "identity_envelope_id": submission.identity.envelope_id,
                    "reviewable_content_sha256": digest(submission.reviewable_content()),
                    "submission_id": submission.submission_id,
                    "title": submission.title,
                }
                for submission in pool.submissions
            ],
        },
    )
    written["bias-experiment.json"] = write_json(EVIDENCE / "bias-experiment.json", experiment)
    written["reproduction-ledger.json"] = write_json(
        EVIDENCE / "reproduction-ledger.json",
        {"reproduction_count": len(reproductions), "reproductions": reproductions},
    )
    written["hypotheses.json"] = write_json(
        EVIDENCE / "hypotheses.json",
        {
            "dispatched_hypothesis": dispatched,
            "hypotheses": hypotheses,
            "hypothesis_count": len(hypotheses),
            "note": (
                "The dispatched hypothesis is the one this unit was sent to test. The CM-H series are "
                "this unit's own preregistered current-method hypotheses, recorded separately because "
                "they are its claims and not its assignment."
            ),
            "outcome_histogram": _histogram([item["outcome"] for item in hypotheses]),
        },
    )
    written["mechanism-changes.json"] = write_json(
        EVIDENCE / "mechanism-changes.json",
        {
            "disposition_histogram": _histogram([item["disposition"] for item in mechanisms]),
            "mechanism_changes": mechanisms,
            "mechanism_count": len(mechanisms),
        },
    )
    written["source-claims.json"] = write_json(
        EVIDENCE / "source-claims.json",
        {
            "external": external,
            "hypotheses_resting_only_on_unsupported_sources": research.hypotheses_resting_on_unsupported_sources(
                unsupported
            ),
            "not_supported_count": len(unsupported),
            "not_supported_ids": unsupported,
            "repository": repository,
            "retrieval_method": (
                "curl -sS -L --max-time 30 from the runner VM; SHA-256 taken over the exact response "
                "body bytes. A claim is asserted only when the transport returned 200 and the body "
                "contains the keyword declared for that claim before retrieval."
            ),
            "separation_note": (
                "Source claims are recorded here and nowhere else. Hypotheses, reproductions, mechanism "
                "dispositions and the candidate claims under review are separate records with disjoint "
                "identifier spaces."
            ),
            "state_separation": separation,
        },
    )
    written["runtime.json"] = write_json(
        EVIDENCE / "runtime.json",
        {
            "determinism": (
                "The review path uses a logical clock and no wall-clock time. Wall time below measures "
                "this run's compute only."
            ),
            "git_head": research._git_head(root),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "third_party_packages": "none; the standard library only",
            "wall_time_seconds": round(time.time() - started, 3),
        },
    )

    print("WA-020 BLIND REVIEW HARNESS")
    print(f"  criteria seal            {criteria.seal_sha256}")
    print(f"  seal intact at end       {recomputed == criteria.seal_sha256}")
    print(f"  cells                    {experiment['cell_count']}")
    print(f"  blind max identity swing {experiment['blinding_effect']['max_identity_swing_in_blind_cells']}")
    print(
        f"  unblinded max swing      {experiment['blinding_effect']['max_identity_swing_in_unblinded_cells']}"
    )
    print(f"  H-PO03-WA-020            {dispatched['outcome']} (failed conjuncts: {dispatched['failed_conjunct_ids'] or 'none'})")
    for conjunct in dispatched["conjuncts"]:
        print(
            f"    conjunct {conjunct['conjunct_id']}            {conjunct['outcome']:9s} "
            f"carried by {conjunct['load_bearing_factor']}"
        )
    print(f"  seeded claim             {SEEDED_FALSE_CLAIM_ID}")
    print(f"  adversarially represented {adversarial['adversarially_represented']}")
    print(f"  reproductions            {len(reproductions)}")
    print(f"  hypotheses               {_histogram([item['outcome'] for item in hypotheses])}")
    print(f"  mechanisms               {_histogram([item['disposition'] for item in mechanisms])}")
    print(f"  source claims            {len(external)} external, {len(repository)} repository, {len(unsupported)} NOT_SUPPORTED")
    print(f"  identifier spaces disjoint {separation['disjoint']}")
    for name, (sha, size) in sorted(written.items()):
        print(f"  wrote evidence/{name:28s} {size:>8d} bytes  {sha}")
    print(f"  wall time                {round(time.time() - started, 3)}s")
    return 0


def _histogram(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    sys.exit(main())
