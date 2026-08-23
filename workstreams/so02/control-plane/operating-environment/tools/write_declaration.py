#!/usr/bin/env python3
"""The write declaration: what makes a write admissible after the protected-surface category was voided.

Ahmed Sadek, founder of Obzio, standing amendment 2026-08-23:

    "It is void as a category. Every surface in the Ahmed/Obzio-controlled estate
    is writable under my authority [...] No surface is off-limits because of a
    name on a list."

    "You do not need my permission for any of it — you need a reason and a rollback."

    "the write-scope guard now checks that a write was **declared and reasoned**,
    not that its target avoided a forbidden list."

So the question this module answers is not "is the target forbidden" but "was
this write declared, and does the declaration carry a live operational reason, a
constructed reversal, and — where it asserts a result — the evidence for it."

Nothing here is a shorter denylist. There is no list of targets. A declaration
naming `main` and a declaration naming a scratch branch pass and fail by exactly
the same tests.

## Every constraint states its provenance class

The founder's rule, quoted:

    "any lane proposing a constraint states its provenance class in the same
    breath. An unclassified constraint is not in force."

    | Founder-authored | Binding until I amend it |
    | Earned — demonstrably caught a real defect | Binding as mechanism; cite the defect |
    | Assistant-authored on my behalf | Void unless I ratify it |

That table is implemented, not merely quoted. Every check below carries its
provenance class, and `ASSISTANT_AUTHORED` checks are ADVISORY — they are
recorded and reported but they never refuse a write, because a constraint an
assistant invented while speaking for the founder is void until he ratifies it.
Ratification is possible (`ratified_assistant_checks`) and is an explicit,
recorded act rather than a default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable


FOUNDER_AUTHORED = "FOUNDER_AUTHORED"
EARNED = "EARNED"
ASSISTANT_AUTHORED = "ASSISTANT_AUTHORED"

#: Only these two classes may refuse a write. The third is void until ratified.
BLOCKING_PROVENANCE = frozenset({FOUNDER_AUTHORED, EARNED})

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

DECLARATION_VERSION = "1.0"


@dataclass(frozen=True)
class Finding:
    """One check result, inseparable from the authority it claims.

    `basis` is not decoration. For FOUNDER_AUTHORED it is his words verbatim;
    for EARNED it is the specific defect the control caught. A finding that
    cannot fill it is ASSISTANT_AUTHORED by construction and cannot refuse.
    """

    code: str
    message: str
    provenance: str
    basis: str

    @property
    def blocking(self) -> bool:
        return self.provenance in BLOCKING_PROVENANCE

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["blocking"] = self.blocking
        return out


@dataclass(frozen=True)
class ReasonCode:
    """A member of the closed reason vocabulary.

    A closed vocabulary alone would not stop a vacuous reason — it would only
    shorten the list of strings that always pass. What makes a reason falsifiable
    is `required_fields`: each code carries obligations that can be checked and
    that are false when the reason is not live. `expires_when` records the
    founder's own framing that a gate dies with its reason.
    """

    code: str
    description: str
    required_fields: tuple[str, ...]
    asserts_result: bool
    expires_when: str


#: The closed vocabulary. Adding a code is a deliberate act; free text is not a
#: reason and an unknown code is refused rather than waved through.
REASON_VOCABULARY: dict[str, ReasonCode] = {
    "INTEGRATE_RETURNED_LANE": ReasonCode(
        code="INTEGRATE_RETURNED_LANE",
        description="Integrate a lane branch that has returned and been accepted.",
        required_fields=("lane_id", "lane_branch", "lane_head_sha"),
        asserts_result=True,
        expires_when="the named lane head is already an ancestor of the target",
    ),
    "PUBLISH_LANE_DELIVERABLE": ReasonCode(
        code="PUBLISH_LANE_DELIVERABLE",
        description="Publish this lane's own commissioned output onto its own branch.",
        required_fields=("lane_id", "commission_id"),
        asserts_result=False,
        expires_when="the lane's commission closes",
    ),
    "REPAIR_BROKEN_CONTRACT": ReasonCode(
        code="REPAIR_BROKEN_CONTRACT",
        description="Repair a contract the repository itself reports as broken.",
        required_fields=("failing_check_command", "observed_exit_code"),
        asserts_result=True,
        expires_when="the named check exits zero",
    ),
    "RECORD_FOUNDER_INSTRUCTION": ReasonCode(
        code="RECORD_FOUNDER_INSTRUCTION",
        description="Record founder-authored text verbatim on a durable surface.",
        required_fields=("founder_utterance_quote", "recorded_at"),
        asserts_result=False,
        expires_when="never; the record is append-only and the write is one-shot",
    ),
    "RETIRE_SUPERSEDED_SURFACE": ReasonCode(
        code="RETIRE_SUPERSEDED_SURFACE",
        description="Retire a surface that a named successor has superseded.",
        required_fields=("superseded_by", "custody_ref"),
        asserts_result=True,
        expires_when="the successor is itself superseded",
    ),
    "SNAPSHOT_CUSTODY": ReasonCode(
        code="SNAPSHOT_CUSTODY",
        description="Create the tag, archive or recorded SHA that gives a later write its rollback.",
        required_fields=("custody_ref", "custody_of_sha"),
        asserts_result=False,
        expires_when="the write it was taken for completes or is abandoned",
    ),
    "CORRECT_PUBLISHED_ERROR": ReasonCode(
        code="CORRECT_PUBLISHED_ERROR",
        description="Correct something already published that is demonstrably wrong.",
        required_fields=("defect_reference", "defect_observed_at"),
        asserts_result=True,
        expires_when="the named defect no longer reproduces",
    ),
}

#: Operations a declaration may cover. Anything else is refused as undeclared
#: rather than assumed harmless.
OPERATION_VOCABULARY = frozenset({
    "COMMIT_AND_PUSH",
    "FORCE_UPDATE_REF",
    "DELETE_REF",
    "MERGE",
    "TAG",
})

#: Reversal methods. Each names an artifact that must already exist at
#: declaration time, because a rollback invented after the write is not a rollback.
REVERSAL_METHODS: dict[str, tuple[str, ...]] = {
    "RESTORE_REF_TO_RECORDED_SHA": ("recorded_sha", "custody_ref"),
    "DELETE_CREATED_REF": ("created_ref",),
    "REVERT_COMMIT_RANGE": ("recorded_sha", "custody_ref"),
    "RESTORE_FROM_ARCHIVE": ("archive_path", "archive_sha256"),
}

#: Advisory only. A phrase list is exactly the kind of preference an assistant
#: smuggles in as a rule, so it is classified ASSISTANT_AUTHORED and never refuses.
_BOILERPLATE_HINTS = (
    "as instructed", "as required", "as needed", "per the task", "per instructions",
    "update", "cleanup", "misc", "improvements", "various changes", "because it is needed",
)

#: Advisory only. Any specific number here is assistant taste, not founder intent.
_ADVISORY_MIN_STATEMENT_CHARS = 40


def _quote(text: str) -> str:
    return f'Ahmed Sadek, standing amendment 2026-08-23: "{text}"'


def validate_declaration(
    declaration: Any,
    ratified_assistant_checks: Iterable[str] = (),
) -> list[Finding]:
    """Check a declaration's structure, reason, reversal and evidence obligations.

    Pure: no git, no network, no clock. The gates that need the world — is the
    target in flight, does the reversal actually reverse, does the evidence
    recompute — are enforced by `write_admission`, which recomputes rather than
    trusting what the declaration claims about any of them.
    """
    ratified = frozenset(ratified_assistant_checks)
    findings: list[Finding] = []

    def add(code: str, message: str, provenance: str, basis: str) -> None:
        if provenance == ASSISTANT_AUTHORED and code in ratified:
            provenance = EARNED
            basis = f"ratified by the founder as an explicit act; original basis: {basis}"
        findings.append(Finding(code=code, message=message, provenance=provenance, basis=basis))

    # ------------------------------------------------------------------
    # The write must exist as a declaration at all.
    # ------------------------------------------------------------------
    if not isinstance(declaration, dict) or not declaration:
        add(
            "NO_DECLARATION",
            "no write declaration was supplied; an undeclared write is refused regardless of its target",
            FOUNDER_AUTHORED,
            _quote("the write-scope guard now checks that a write was declared and reasoned, "
                   "not that its target avoided a forbidden list"),
        )
        return findings

    if declaration.get("declaration_version") != DECLARATION_VERSION:
        add(
            "UNKNOWN_DECLARATION_VERSION",
            f"declaration_version {declaration.get('declaration_version')!r} is not {DECLARATION_VERSION!r}",
            EARNED,
            "a schema whose version is not pinned drifts silently between runs; this estate has "
            "already lost a classification to a document that changed meaning without changing name",
        )

    for key in ("declared_by", "declared_at"):
        if not str(declaration.get(key) or "").strip():
            add(
                "DECLARATION_UNATTRIBUTED",
                f"{key} is missing; a declaration nobody signed cannot expire with its author's reason",
                FOUNDER_AUTHORED,
                _quote("A write is gated only by a live operational reason, and each gate expires "
                       "when its reason does"),
            )

    declared_at = str(declaration.get("declared_at") or "")
    if declared_at and not ISO_RE.match(declared_at):
        add(
            "DECLARED_AT_MALFORMED",
            f"declared_at {declared_at!r} is not an ISO-8601 UTC instant",
            EARNED,
            "freshness cannot be recomputed from an unparseable timestamp, and an unparseable "
            "timestamp previously let a stale observation be presented as current",
        )

    _check_target(declaration, add)
    _check_reason(declaration, add)
    _check_reversal(declaration, add)
    _check_evidence(declaration, add)
    _check_concurrency_shape(declaration, add)

    return findings


def _check_target(declaration: dict[str, Any], add) -> None:
    target = declaration.get("target")
    if not isinstance(target, dict):
        add(
            "TARGET_MISSING",
            "the declaration names no target; a write with no declared target cannot be reasoned about",
            FOUNDER_AUTHORED,
            _quote("Report instead: what you wrote, where, why, on what evidence, and how to reverse it"),
        )
        return

    if not str(target.get("ref") or "").strip():
        add(
            "TARGET_REF_MISSING",
            "target.ref is empty",
            FOUNDER_AUTHORED,
            _quote("Report instead: what you wrote, where, why, on what evidence, and how to reverse it"),
        )

    paths = target.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p.strip() for p in paths):
        add(
            "TARGET_PATHS_MISSING",
            "target.paths must be a non-empty list of path globs this write may touch",
            EARNED,
            "the live SHARED_WORKTREE_COLLISION: lanes in one shared checkout captured each other's "
            "files, which was undetectable because no write said in advance which paths were its own",
        )

    operation = target.get("operation")
    if operation not in OPERATION_VOCABULARY:
        add(
            "OPERATION_NOT_IN_VOCABULARY",
            f"target.operation {operation!r} is not one of {sorted(OPERATION_VOCABULARY)}",
            EARNED,
            "a denylist of bad states passed ERROR and FAILED silently in capacity_verdict; an "
            "open operation field repeats that failure by admitting every operation nobody enumerated",
        )
    return


def _check_reason(declaration: dict[str, Any], add) -> None:
    reason = declaration.get("reason")
    if not isinstance(reason, dict):
        add(
            "REASON_MISSING",
            "the declaration carries no reason",
            FOUNDER_AUTHORED,
            _quote("You do not need my permission for any of it — you need a reason and a rollback"),
        )
        return

    code = reason.get("code")
    spec = REASON_VOCABULARY.get(code) if isinstance(code, str) else None
    if spec is None:
        add(
            "REASON_CODE_NOT_IN_VOCABULARY",
            f"reason.code {code!r} is not in the closed vocabulary {sorted(REASON_VOCABULARY)}",
            FOUNDER_AUTHORED,
            _quote("A write is gated only by a live operational reason"),
        )
        return

    statement = str(reason.get("statement") or "")
    if not statement.strip():
        add(
            "REASON_STATEMENT_EMPTY",
            f"reason.statement is empty; the code {code} asserts an obligation that nothing states",
            FOUNDER_AUTHORED,
            _quote("You do not need my permission for any of it — you need a reason and a rollback"),
        )

    missing = [f for f in spec.required_fields if not str(reason.get(f) or "").strip()]
    if missing:
        add(
            "REASON_OBLIGATIONS_UNMET",
            f"reason.code {code} requires {list(spec.required_fields)}; missing or empty: {missing}. "
            f"This reason is live only while: {spec.expires_when}",
            FOUNDER_AUTHORED,
            _quote("A write is gated only by a live operational reason, and each gate expires when "
                   "its reason does"),
        )

    # The portable-reason test. A statement that names neither the ref nor any
    # declared path is true of every write in the estate and therefore
    # distinguishes none of them.
    if statement.strip():
        target = declaration.get("target") if isinstance(declaration.get("target"), dict) else {}
        ref = str(target.get("ref") or "").strip()
        paths = [p for p in (target.get("paths") or []) if isinstance(p, str)]
        anchors = [a for a in ([ref] + paths) if a]
        if anchors and not any(a in statement for a in anchors):
            add(
                "REASON_NOT_ANCHORED_TO_TARGET",
                "reason.statement names neither target.ref nor any declared path, so it is equally "
                "true of every write in the estate and cannot expire with anything specific to this one",
                EARNED,
                "the FB-11 mis-certification: the provenance classifier read commit authorship, a "
                "signal identical for every commit in this repository, and so certified a "
                "constraint as FOUNDER_BOUND on evidence that carried no per-item information at "
                "all. A reason statement identical for every write is that same defect",
            )

        lowered = statement.strip().lower()
        if any(hint in lowered for hint in _BOILERPLATE_HINTS):
            add(
                "REASON_READS_AS_BOILERPLATE",
                "reason.statement contains filler phrasing; advisory only",
                ASSISTANT_AUTHORED,
                "a phrase list is assistant taste, not a founder rule and not a defect this estate "
                "has recorded; it is reported and never refuses",
            )
        if len(statement.strip()) < _ADVISORY_MIN_STATEMENT_CHARS:
            add(
                "REASON_STATEMENT_TERSE",
                f"reason.statement is under {_ADVISORY_MIN_STATEMENT_CHARS} characters; advisory only",
                ASSISTANT_AUTHORED,
                "any specific minimum length is an invented threshold; it is reported and never refuses",
            )
    return


def _check_reversal(declaration: dict[str, Any], add) -> None:
    reversal = declaration.get("reversal")
    if not isinstance(reversal, dict):
        add(
            "REVERSAL_MISSING",
            "the declaration carries no reversal",
            FOUNDER_AUTHORED,
            _quote("You do not need my permission for any of it — you need a reason and a rollback"),
        )
        return

    method = reversal.get("method")
    if method not in REVERSAL_METHODS:
        add(
            "REVERSAL_METHOD_NOT_IN_VOCABULARY",
            f"reversal.method {method!r} is not one of {sorted(REVERSAL_METHODS)}",
            FOUNDER_AUTHORED,
            _quote("Snapshot before an irreversible write: tag, archive, recorded SHA. "
                   "That is custody, not protection"),
        )
        return

    missing = [f for f in REVERSAL_METHODS[method] if not str(reversal.get(f) or "").strip()]
    if missing:
        add(
            "REVERSAL_CUSTODY_MISSING",
            f"reversal.method {method} requires {list(REVERSAL_METHODS[method])}; missing: {missing}",
            FOUNDER_AUTHORED,
            _quote("Snapshot before an irreversible write: tag, archive, recorded SHA. "
                   "That is custody, not protection"),
        )

    recorded = str(reversal.get("recorded_sha") or "")
    if recorded and not SHA_RE.match(recorded):
        add(
            "REVERSAL_RECORDED_SHA_MALFORMED",
            f"reversal.recorded_sha {recorded!r} is not a full 40-hex commit SHA",
            EARNED,
            "an abbreviated or wrong SHA is indistinguishable from a correct one until the rollback "
            "is attempted, which is when a rollback is least able to fail",
        )

    command = reversal.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        add(
            "REVERSAL_COMMAND_MISSING",
            "reversal.command must be the exact argv that undoes this write, not a prose description",
            EARNED,
            "a prior lane published a documented revert procedure that did not work when it was "
            "executed; prose cannot be rehearsed and so was never tested before it was needed",
        )
    return


def _check_evidence(declaration: dict[str, Any], add) -> None:
    reason = declaration.get("reason") if isinstance(declaration.get("reason"), dict) else {}
    spec = REASON_VOCABULARY.get(reason.get("code"))
    evidence = declaration.get("evidence") if isinstance(declaration.get("evidence"), dict) else None

    declared_asserts = bool((evidence or {}).get("asserts_result"))
    code_asserts = bool(spec.asserts_result) if spec else False
    # The reason code decides, not the declarer. Letting a write self-certify
    # that it asserts nothing is the loophole that makes the evidence gate optional.
    asserts = declared_asserts or code_asserts

    if not asserts:
        return

    if evidence is None:
        add(
            "EVIDENCE_MISSING",
            f"reason.code {reason.get('code')} asserts a result, so this write must carry the "
            "evidence for that result; the declaration carries none",
            FOUNDER_AUTHORED,
            _quote("A write that asserts a result carries the evidence for that result. "
                   "The problem was never the target of a write; it was unverified writes"),
        )
        return

    kind = evidence.get("kind")
    if kind not in {"READBACK", "MANIFEST_CLOSURE"}:
        add(
            "EVIDENCE_KIND_NOT_IN_VOCABULARY",
            f"evidence.kind {kind!r} is not one of ['MANIFEST_CLOSURE', 'READBACK']",
            FOUNDER_AUTHORED,
            _quote("A write that asserts a result carries the evidence for that result"),
        )
        return

    if not isinstance(evidence.get("record"), dict) or not evidence.get("record"):
        add(
            "EVIDENCE_RECORD_MISSING",
            f"evidence.kind {kind} declared with no record to recompute",
            EARNED,
            "verify_readback validated the SHAPE of a read-back record and never its TRUTH, so a "
            "wholly fabricated record naming commit 000...0 passed verification; an absent record "
            "is that failure taken one step further",
        )
    return


def _check_concurrency_shape(declaration: dict[str, Any], add) -> None:
    """Structural only. Whether the target is actually in flight is recomputed by
    `concurrency_observer`, because an observation a declaration asserts about
    itself is exactly the self-consistency that verify_readback mistook for custody."""
    concurrency = declaration.get("concurrency")
    if not isinstance(concurrency, dict) or not concurrency:
        add(
            "CONCURRENCY_OBSERVATION_MISSING",
            "the declaration carries no concurrency observation for its target",
            FOUNDER_AUTHORED,
            _quote("Do not corrupt work in flight. PO-03 has live top-level runs; a write that "
                   "would disturb a running lane waits for that lane to finish — not forever"),
        )
        return

    observed_at = str(concurrency.get("observed_at") or "")
    if not observed_at:
        add(
            "CONCURRENCY_OBSERVATION_UNTIMED",
            "concurrency.observed_at is missing; an observation with no instant is not an "
            "observation of now and cannot show the target was idle when this write was made",
            FOUNDER_AUTHORED,
            _quote("Do not corrupt work in flight"),
        )
    elif not ISO_RE.match(observed_at):
        add(
            "CONCURRENCY_OBSERVATION_UNTIMED",
            f"concurrency.observed_at {observed_at!r} is not an ISO-8601 UTC instant",
            EARNED,
            "freshness cannot be recomputed from an unparseable timestamp",
        )

    if not isinstance(concurrency.get("agents"), list):
        add(
            "CONCURRENCY_OBSERVATION_EMPTY",
            "concurrency.agents must be the observed agent list, even when empty; a declaration "
            "that omits it is asserting idleness rather than observing it",
            FOUNDER_AUTHORED,
            _quote("Do not corrupt work in flight"),
        )
    return


def blocking_findings(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def advisory_findings(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if not f.blocking]


def is_admissible(findings: Iterable[Finding]) -> bool:
    return not blocking_findings(findings)


def report(findings: Iterable[Finding]) -> dict[str, Any]:
    items = list(findings)
    blocking = blocking_findings(items)
    return {
        "admissible": not blocking,
        "verdict": "DECLARATION_ADMISSIBLE" if not blocking else "DECLARATION_REFUSED",
        "blocking_count": len(blocking),
        "advisory_count": len(items) - len(blocking),
        "findings": [f.to_dict() for f in items],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Validate a write declaration")
    parser.add_argument("declaration", help="path to a declaration JSON file")
    parser.add_argument("--ratified", nargs="*", default=[],
                        help="assistant-authored check codes the founder has ratified")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.declaration).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read declaration: {exc}", file=sys.stderr)
        return 2

    result = report(validate_declaration(payload, args.ratified))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["verdict"])
        for item in result["findings"]:
            mark = "REFUSE " if item["blocking"] else "advise "
            print(f"  {mark}{item['code']} [{item['provenance']}]: {item['message']}")
    return 0 if result["admissible"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
