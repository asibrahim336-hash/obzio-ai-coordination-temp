#!/usr/bin/env python3
"""Mutate the utterance ledger into known failure modes and require rejection.

Standard library only. Writes nothing outside a temporary directory.

Without this file, "the admission rule works" is an assertion. Each test names
a way an old, persuasive or mis-attributed thread could be laundered into
current founder intent, injects exactly that, and requires the rule to catch
it. A test that stops failing is a regression in the rule, not a passing build.

    python3 tools/negative_tests_intentctl.py
"""

from __future__ import annotations

import copy
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intentctl  # noqa: E402

RULE = intentctl.load_rule()
REAL = intentctl.load_utterances()
BY_ID = {r["utterance_id"]: r for r in REAL}

FOUNDER_INSTRUCTION = BY_ID["urn:obzio:w8:utterance:founder-standing-instruction-20260822"]
ADVISORY = BY_ID["urn:obzio:w8:utterance:chatgpt-advisory-proposal-20260822"]

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str, str]] = []


def record(tid: str, mode: str, ok: bool, detail: str) -> None:
    results.append((tid, mode, PASS if ok else FAIL, detail))


def base(**over) -> dict:
    """A well-formed record, so each test injects exactly one defect."""
    rec = {
        "utterance_id": "urn:obzio:w8:utterance:test-subject",
        "record_kind": "ILLUSTRATIVE",
        "locator": {
            "class": "REPOSITORY_PATH",
            "value": "does/not/matter.md",
            "commit": "0" * 40,
            "resolvable_by_third_party": True,
        },
        "speaker_class": "FOUNDER_DIRECT",
        "speech_act": "DIRECTIVE",
        "is_verbatim": True,
        "verbatim": "synthetic fixture text, not a real founder utterance",
        "scope": ["DC-TEST"],
        "capture_mode": "TEXT",
        "read_back_confirmed": True,
        "designated_standing": False,
        "supersedes": [],
        "uttered_at": "2026-01-01T00:00:00Z",
        "custody": "COMMITTED",
        "evidence_label": "HYPOTHESIS",
    }
    rec.update(over)
    return rec


def standing_of(rec: dict, others: list[dict] | None = None) -> str:
    pool = list(others or []) + [rec]
    by_id = {r["utterance_id"]: r for r in pool}
    return intentctl.effective_standing_for_scope(rec, by_id, RULE)[0]


def resolve(records: list[dict], scope: str) -> dict:
    return intentctl.resolve_scope(scope, records, RULE)


# --------------------------------------------------------------------------
# NT1 - the laundering path. Assent to an assistant proposal must not become
# founder intent. This is the failure the founder himself flagged.

def nt1_acknowledgement_laundering() -> None:
    ack = base(
        utterance_id="urn:obzio:w8:utterance:test-ack",
        speech_act="ACKNOWLEDGEMENT",
        acknowledges=ADVISORY["utterance_id"],
        verbatim="yes, do that",
        scope=["DC-CHATGPT-FUNCTIONS"],
        restates_content_verbatim=False,
    )
    got = standing_of(ack, [ADVISORY])
    record(
        "NT1",
        "founder assents to an assistant proposal; the proposal is claimed as founder intent",
        got == "S1",
        f"effective standing {got}, expected S1 (the standing of what was acknowledged, not of the assent)",
    )

    # and the honest counterpart: if he restates it himself, it is his utterance
    ack2 = copy.deepcopy(ack)
    ack2["restates_content_verbatim"] = True
    got2 = standing_of(ack2, [ADVISORY])
    record(
        "NT1b",
        "founder restates the content himself, which must NOT be suppressed",
        got2 == "S3",
        f"effective standing {got2}, expected S3 (a rule that only ever suppresses is not a rule, it is a veto)",
    )


# NT2 - a summary of a thread is an assistant utterance about a thread.

def nt2_paraphrase_cannot_bind() -> None:
    rec = base(is_verbatim=False, verbatim=None, speech_act="DIRECTIVE", designated_standing=True)
    got = standing_of(rec)
    record(
        "NT2",
        "a recovered directive stored as a paraphrase rather than verbatim, claiming standing",
        got == "S1",
        f"standing {got}, expected S1 (CAP-PARAPHRASE outranks the designation)",
    )


# NT3 - "the chat where we discussed pricing" resolves to whatever the reader
# happens to be looking at.

def nt3_alias_locator() -> None:
    rec = base(locator={"class": "ALIAS", "value": "the chat where we discussed the roadmap", "resolvable_by_third_party": False})
    got = standing_of(rec)
    record(
        "NT3",
        "a founder directive whose only locator is a display alias",
        got == "S0",
        f"standing {got}, expected S0 INADMISSIBLE",
    )


# NT4 - the headline case. A persuasive old thread with no verifiable
# utterance time must not beat a current founder statement on recency, and
# must not silently lose either. It must fail closed.

def nt4_old_thread_cannot_win_on_recency() -> None:
    old = base(
        utterance_id="urn:obzio:w8:utterance:test-recovered-thread",
        locator={"class": "CONVERSATION_URL", "value": "https://chatgpt.com/c/EXAMPLE-NOT-REAL", "resolvable_by_third_party": True},
        designated_standing=True,
        uttered_at=None,
        scope=["DC-TEST"],
    )
    current = base(
        utterance_id="urn:obzio:w8:utterance:test-current",
        designated_standing=True,
        uttered_at="2026-08-22T23:55:00Z",
        scope=["DC-TEST"],
    )
    out = resolve([old, current], "DC-TEST")
    ok = out["state"] == "UNRESOLVED" and out["winner"] is None
    record(
        "NT4",
        "a recovered thread of equal standing with no verifiable utterance time contests a current founder statement",
        ok,
        f"state {out['state']}, winner {out['winner']}, expected UNRESOLVED with no winner and one binary question",
    )
    ok2 = bool(out.get("founder_question")) and "Which stands?" in out.get("founder_question", "")
    record(
        "NT4b",
        "the unresolved conflict must arrive as one question, not as reading material",
        ok2,
        f"founder_question present: {bool(out.get('founder_question'))}",
    )


# NT5 - recency is a tie-break the founder authorised for his own direct
# intent. It must not reach across standings.

def nt5_recency_never_beats_standing() -> None:
    old_high = base(
        utterance_id="urn:obzio:w8:utterance:test-old-high",
        designated_standing=True,
        uttered_at="2025-01-01T00:00:00Z",
        scope=["DC-TEST"],
    )
    new_low = base(
        utterance_id="urn:obzio:w8:utterance:test-new-low",
        speaker_class="ASSISTANT",
        speech_act="DIRECTIVE",
        uttered_at="2026-08-22T23:59:00Z",
        scope=["DC-TEST"],
    )
    out = resolve([old_high, new_low], "DC-TEST")
    ok = out["state"] == "RESOLVED" and out["winner"] == old_high["utterance_id"] and out["resolved_by"] == "STANDING"
    record(
        "NT5",
        "a newer assistant utterance contests an older founder directive",
        ok,
        f"winner {out.get('winner')}, by {out.get('resolved_by')}, expected the older founder utterance by STANDING",
    )


# NT6 - supersession is named. Inferring it from date order is how an estate
# ends up with a change graph nobody wrote.

def nt6_supersession_must_be_named() -> None:
    a = base(utterance_id="urn:obzio:w8:utterance:test-a", supersedes=["urn:obzio:w8:utterance:test-does-not-exist"])
    errs = intentctl.check_cross_record([a])
    ok = any("SUPERSESSION_TARGET_UNKNOWN" in e for e in errs)
    record(
        "NT6",
        "an utterance claims to supersede a target that is not in the ledger",
        ok,
        f"errors: {errs or 'none'}",
    )


# NT7 - scope is declared, never inferred from what a thread was about.

def nt7_scope_is_declared() -> None:
    rec = base(scope=["pricing strategy"])
    errs = intentctl.check_schema(rec, RULE)
    ok = any("SCOPE_NOT_A_DECISION_CLASS" in e for e in errs)
    record(
        "NT7",
        "scope given as a topic keyword rather than a decision class",
        ok,
        f"errors: {errs or 'none'}",
    )


# NT8 - read-back is a gate, not a feature.

def nt8_unconfirmed_voice_capped() -> None:
    rec = base(capture_mode="VOICE", read_back_confirmed=False, designated_standing=True)
    got = standing_of(rec)
    record(
        "NT8",
        "a voice-captured directive whose read-back was never confirmed, claiming standing",
        got == "S2",
        f"standing {got}, expected S2 CAPTURED_UNCONFIRMED",
    )


# NT9 - custody and standing are different axes. Recovery does not admit.

def nt9_uncommitted_is_not_evidence() -> None:
    rec = base(custody="RECOVERED_UNCOMMITTED", designated_standing=True, scope=["DC-TEST"])
    st = standing_of(rec)
    out = resolve([rec], "DC-TEST")
    ok = st == "S4" and out["state"] == "NO_ADMITTED_CLAIM"
    record(
        "NT9",
        "a recovered founder directive still in the provider, claiming to settle a class",
        ok,
        f"standing {st} (correctly high), admitted candidates {out['candidate_count']} (correctly zero)",
    )


# NT10 - an unattributed utterance is not a founder utterance.

def nt10_unattributed_is_inadmissible() -> None:
    rec = base(speaker_class="UNATTRIBUTED", designated_standing=True)
    got = standing_of(rec)
    record(
        "NT10",
        "an utterance recovered without an established speaker, claiming founder standing",
        got == "S0",
        f"standing {got}, expected S0",
    )


# NT11 - an exploration is not a decision, however well argued.

def nt11_exploration_cannot_decide() -> None:
    rec = base(speech_act="EXPLORATION", designated_standing=True, scope=["DC-TEST"])
    st = standing_of(rec)
    out = resolve([rec], "DC-TEST")
    ok = st == "S1" and out["state"] == "NO_ADMITTED_CLAIM"
    record(
        "NT11",
        "a founder thinking aloud, admitted as a founder decision",
        ok,
        f"standing {st}, admitted candidates {out['candidate_count']}",
    )


# NT12 - a repository locator that names no commit points at a moving target.

def nt12_unpinned_repository_locator() -> None:
    rec = base(locator={"class": "REPOSITORY_PATH", "value": "some/file.md", "resolvable_by_third_party": True})
    errs = intentctl.check_schema(rec, RULE)
    ok = any("LOCATOR_UNPINNED" in e for e in errs)
    record("NT12", "a repository locator with no commit", ok, f"errors: {errs or 'none'}")


# NT13 - two direct founder utterances at equal standing with trusted times
# must resolve, not fail closed. A rule that refuses everything is useless.

def nt13_the_rule_still_decides() -> None:
    earlier = base(utterance_id="urn:obzio:w8:utterance:test-earlier", uttered_at="2026-01-01T00:00:00Z", scope=["DC-TEST"])
    later = base(utterance_id="urn:obzio:w8:utterance:test-later", uttered_at="2026-08-01T00:00:00Z", scope=["DC-TEST"])
    out = resolve([earlier, later], "DC-TEST")
    ok = out["state"] == "RESOLVED" and out["winner"] == later["utterance_id"] and out["resolved_by"] == "FOUNDER_PRECEDENCE_RECENCY"
    record(
        "NT13",
        "the founder's own precedence clause must still decide where he authorised it",
        ok,
        f"state {out['state']}, winner {out.get('winner')}, by {out.get('resolved_by')}",
    )


# NT14 - a named supersession beats date order, in both directions.

def nt14_named_supersession_beats_date() -> None:
    newer = base(utterance_id="urn:obzio:w8:utterance:test-newer", uttered_at="2026-08-01T00:00:00Z", scope=["DC-TEST"])
    older_superseding = base(
        utterance_id="urn:obzio:w8:utterance:test-older-superseding",
        uttered_at="2026-01-01T00:00:00Z",
        scope=["DC-TEST"],
        supersedes=[newer["utterance_id"]],
    )
    out = resolve([newer, older_superseding], "DC-TEST")
    ok = out["winner"] == older_superseding["utterance_id"] and out["resolved_by"] == "NAMED_SUPERSESSION"
    record(
        "NT14",
        "an older utterance that names the newer one as superseded",
        ok,
        f"winner {out.get('winner')}, by {out.get('resolved_by')} (named supersession precedes recency)",
    )


def main() -> int:
    for fn in (
        nt1_acknowledgement_laundering,
        nt2_paraphrase_cannot_bind,
        nt3_alias_locator,
        nt4_old_thread_cannot_win_on_recency,
        nt5_recency_never_beats_standing,
        nt6_supersession_must_be_named,
        nt7_scope_is_declared,
        nt8_unconfirmed_voice_capped,
        nt9_uncommitted_is_not_evidence,
        nt10_unattributed_is_inadmissible,
        nt11_exploration_cannot_decide,
        nt12_unpinned_repository_locator,
        nt13_the_rule_still_decides,
        nt14_named_supersession_beats_date,
    ):
        fn()

    width = max(len(m) for _, m, _, _ in results)
    for tid, mode, verdict, detail in results:
        print(f"{verdict:<4} {tid:<6} {mode:<{width}}  {detail}")

    failed = [r for r in results if r[2] == FAIL]
    print()
    if failed:
        print(f"FAIL: {len(failed)} of {len(results)} failure modes were NOT caught")
        return 1
    print(f"PASS: all {len(results)} failure modes rejected by the rule")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
