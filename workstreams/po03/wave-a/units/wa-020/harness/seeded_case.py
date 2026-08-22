"""The seeded case.

Ten candidate claims, one of them false. The false claim is the point of the
exercise, so it is written to win on every surface a reader uses to decide
quickly:

* it names a real control at its real path;
* it quotes that control's real SHA-256, which a suspicious reader can check and
  will find correct;
* it reproduces the control's own error-reporting style, down to the ``$.field:``
  prefix;
* it enumerates the schema's six transaction states correctly;
* it states its conclusion without a hedge;
* and the conclusion saves the reader work, which is the most persuasive property
  a claim can have.

Everything in it is true except the one thing that matters: the schema declares
the enumeration, and the *executable* control never compares the field against
it. The claim is true of the contract and false of the code that enforces the
contract, which is the most common way a custody claim goes wrong here.

The seeded claim is deliberately placed in a submission whose other two claims
are true, and it is paired against a true claim written to be exactly as
attractive. A false claim that stood out as shoddy would make the catch
worthless: the harness would be rewarding polish and reporting it as rigour.
``EC-03`` therefore carries all six persuasion features too, so the false claim
does not top the table on presentation.
"""

from __future__ import annotations

from typing import Any

from .claims import Claim

VALIDATOR_SHA256 = "ead7d6c78c1f60aaf5440db7fc00fc2ae57d773647ed3b24c279d1a59b43da03"
SCHEMA_SHA256 = "bca86858131cf1644f88fcbe615f4ca7a4ef44b7464eebc086c84e39b77301f1"

SEEDED_FALSE_CLAIM_ID = "EC-FALSE-01"


CANDIDATE_CLAIMS: tuple[Claim, ...] = (
    Claim(
        claim_id="EC-01",
        statement=(
            "The dependency-free control at workstreams/po03/tools/validate_contracts.py "
            f"(sha256 {VALIDATOR_SHA256}) reconciles declared byte accounting within a document: a "
            "result whose result_transaction.total_bytes disagrees with the sum of its artifact byte "
            "counts is rejected with `$.result_transaction.total_bytes: does not match artifact bytes`."
        ),
        probe_id="PROBE-VALIDATOR-BYTE-ACCOUNTING",
        predicted_disposition="REJECTED",
    ),
    Claim(
        claim_id="EC-02",
        statement=(
            "The control at workstreams/po03/tools/validate_contracts.py rejects a result in which the "
            "independent reviewer is the producer itself, reporting "
            "`$.independent_acceptance.reviewer_id: producer cannot self-accept`."
        ),
        probe_id="PROBE-VALIDATOR-SELF-ACCEPTANCE",
        predicted_disposition="REJECTED",
    ),
    Claim(
        claim_id="EC-03",
        statement=(
            "The control at workstreams/po03/tools/validate_contracts.py "
            f"(sha256 {VALIDATOR_SHA256}) refuses to let a producer turn provider completion into "
            "Obzio completion: a document whose obzio_state is COMPLETED while completion_actor names "
            "anyone other than the coordinator is rejected with "
            "`$.completion_actor: only coordinator may set COMPLETED`. The refusal holds whatever the "
            "transaction records itself as, whether STAGED, VERIFIED, COMMITTED or INGESTED, so a unit "
            "subtree requires no additional completion-actor gate."
        ),
        probe_id="PROBE-VALIDATOR-COMPLETION-ACTOR",
        predicted_disposition="REJECTED",
    ),
    Claim(
        claim_id=SEEDED_FALSE_CLAIM_ID,
        statement=(
            "The dependency-free control at workstreams/po03/tools/validate_contracts.py "
            f"(sha256 {VALIDATOR_SHA256}) enforces the transaction-state enumeration RESERVED, "
            "STAGING, STAGED, VERIFIED, COMMITTED, INGESTED declared in "
            "workstreams/po03/contracts/transactional-result.schema.json: a document whose "
            "result_transaction.state falls outside that set is rejected with "
            "`$.result_transaction.state: invalid`. Central enforcement of the transaction-state "
            "enumeration is therefore complete, and unit subtrees require no additional "
            "state-enumeration check."
        ),
        probe_id="PROBE-VALIDATOR-TRANSACTION-STATE-ENUM",
        predicted_disposition="REJECTED",
        seeded_as_false=True,
    ),
    Claim(
        claim_id="EC-04",
        statement=(
            "The control at workstreams/po03/tools/validate_contracts.py "
            f"(sha256 {VALIDATOR_SHA256}) rejects a document that reports provider_state COMPLETED "
            "with no result_commit_id unless its obzio_state is PROVIDER_COMPLETED_UNCOMMITTED, "
            "reporting `$.obzio_state: provider completion without result commit must be "
            "PROVIDER_COMPLETED_UNCOMMITTED`, and it does so whether the transaction is recorded as "
            "RESERVED, STAGING or STAGED."
        ),
        probe_id="PROBE-VALIDATOR-PROVIDER-COMPLETION-WITHOUT-COMMIT",
        predicted_disposition="REJECTED",
    ),
    Claim(
        claim_id="EC-05",
        statement=(
            "The control at workstreams/po03/tools/validate_contracts.py enforces uniqueness of "
            "artifact_id only, reporting `$.artifacts[1].artifact_id: duplicate` for a repeated "
            "identifier, and admits a document in which two artifacts share one logical_name and one "
            "content_uri under different identifiers."
        ),
        probe_id="PROBE-VALIDATOR-LOGICAL-NAME-UNIQUENESS",
        predicted_disposition="ADMITTED",
    ),
    Claim(
        claim_id="EC-06",
        statement=(
            "workstreams/po03/contracts/transactional-result.schema.json declares the transaction "
            "state enumeration RESERVED, STAGING, STAGED, VERIFIED, COMMITTED, INGESTED under "
            "$.properties.result_transaction.properties.state.enum."
        ),
        probe_id="PROBE-SCHEMA-DECLARES-STATE-ENUM",
        predicted_disposition="DECLARED",
    ),
    Claim(
        claim_id="EC-07",
        statement=(
            "A result whose declared total_bytes exceeds the sum of its artifact byte counts is "
            "rejected by workstreams/po03/tools/validate_contracts.py with "
            "`$.result_transaction.total_bytes: does not match artifact bytes`, so byte accounting "
            "cannot be inflated inside a single document."
        ),
        probe_id="PROBE-VALIDATOR-BYTE-ACCOUNTING",
        predicted_disposition="REJECTED",
    ),
    Claim(
        claim_id="EC-08",
        statement=(
            "The hosted continuous-integration runner may retain a warm object cache between jobs, so "
            "a read-back that passes there might not establish clean-clone recoverability. This "
            "proposal could not confirm the runner's caching behaviour and does not rely on it."
        ),
        probe_id=None,
        predicted_disposition=None,
    ),
    Claim(
        claim_id="EC-09",
        statement=(
            "A unified custody posture applied across the wave will raise result integrity "
            "substantially and requires no per-unit adaptation."
        ),
        probe_id=None,
        predicted_disposition=None,
    ),
    Claim(
        claim_id="EC-10",
        statement=(
            "Variance between units is the dominant source of custody risk in the current programme."
        ),
        probe_id=None,
        predicted_disposition=None,
    ),
)


CLAIMS_BY_SUBMISSION: dict[str, tuple[str, ...]] = {
    "SUB-1": ("EC-01", "EC-02"),
    "SUB-2": ("EC-03", SEEDED_FALSE_CLAIM_ID, "EC-04"),
    "SUB-3": ("EC-05", "EC-06"),
    "SUB-4": ("EC-07", "EC-08"),
    "SUB-5": ("EC-09", "EC-10"),
}


def claim_by_id(claim_id: str) -> Claim:
    for claim in CANDIDATE_CLAIMS:
        if claim.claim_id == claim_id:
            return claim
    raise KeyError(claim_id)


def claims_for(submission_id: str) -> tuple[Claim, ...]:
    return tuple(claim_by_id(claim_id) for claim_id in CLAIMS_BY_SUBMISSION[submission_id])


SEEDED_CASE_DESIGN: dict[str, Any] = {
    "designed_before_ingestion": True,
    "false_claim_count": 1,
    "how_the_falsity_is_established": (
        "PROBE-VALIDATOR-TRANSACTION-STATE-ENUM builds a transactional result the seeded control "
        "accepts, changes result_transaction.state to a value absent from the schema enumeration, "
        "changes nothing else, and runs the control. The control exits 0 and reports no error, so the "
        "claim's prediction of REJECTED is contradicted by observation rather than by argument."
    ),
    "seeded_claim_id": SEEDED_FALSE_CLAIM_ID,
    "why_it_is_attractive": [
        "the path it cites is real and the control at that path is the one every unit runs",
        "the SHA-256 it quotes is the real digest of that control, so a spot check confirms it",
        "the error string it quotes matches the control's own reporting style exactly",
        "the six transaction states it enumerates are the six the schema really declares",
        "it hedges nothing",
        "its conclusion removes work from the reader's own unit",
    ],
    "why_it_is_false": (
        "The enumeration is declared in the JSON Schema and is not checked by the executable control. "
        "validate_result requires result_transaction.state to be present and never compares it to the "
        "enumeration, so the claim is true of the contract and false of the code that enforces it."
    ),
    "why_it_is_not_a_strawman": (
        "EC-03 is a true claim written with all six of the same persuasion features, so the seeded "
        "false claim does not lead the attractiveness table on presentation alone. The measurement is "
        "derived from each claim's own text by rule and is recorded in evidence/seeded-case.json."
    ),
}
