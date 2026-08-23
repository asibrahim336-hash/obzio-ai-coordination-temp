#!/usr/bin/env python3
"""intentctl - derive standing for recovered founder utterances and rank conflicts.

Standard library only. No network. No provider access. Reads the rule tables and
the utterance ledger, derives a standing for every utterance from its speaker
class and speech act rather than from anyone's reading of it, and resolves each
contested decision class by the declared order: standing, then named
supersession, then the founder's own recency clause where he authorised it, and
otherwise fail closed.

    intentctl.py validate                  schema and locator discipline; exit 1 on any ERROR
    intentctl.py standing --id URN         the derived standing for one utterance, with reasons
    intentctl.py resolve --scope DC-X      who wins the class, or UNRESOLVED with the question
    intentctl.py conflicts                 every contested class; exit 1 if any is UNRESOLVED
    intentctl.py report                    the full projection on stdout

Exit codes: 0 clean, 1 a check failed (which for `conflicts` is often the
correct result, not a broken build), 2 the ledger itself could not be read.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
LEDGER = HERE.parent / "ledger"
RULE_PATH = LEDGER / "admission-rule.json"
UTTERANCE_DIR = LEDGER / "utterances"

STANDING_ORDER = ["S0", "S1", "S2", "S3", "S4"]

LOCATOR_CLASSES = {"REPOSITORY_PATH", "CONVERSATION_URL", "EXPORT_RECORD", "ALIAS"}
CUSTODY_STATES = {"COMMITTED", "RECOVERED_UNCOMMITTED"}
CAPTURE_MODES = {"VOICE", "TEXT", "UNKNOWN"}
EVIDENCE_LABELS = {"DIRECTLY_REPRODUCED", "DOCUMENTED", "HYPOTHESIS"}

REQUIRED_FIELDS = [
    "utterance_id",
    "locator",
    "speaker_class",
    "speech_act",
    "is_verbatim",
    "scope",
    "custody",
    "capture_mode",
    "evidence_label",
]


class LedgerError(Exception):
    pass


# --------------------------------------------------------------------------
# loading


def load_rule(rule_path: pathlib.Path = RULE_PATH) -> dict:
    try:
        return json.loads(rule_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LedgerError(f"cannot read rule tables at {rule_path}: {exc}") from exc


def load_utterances(directory: pathlib.Path = UTTERANCE_DIR) -> list[dict]:
    if not directory.is_dir():
        raise LedgerError(f"no utterance directory at {directory}")
    out: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise LedgerError(f"{path.name}: not readable JSON: {exc}") from exc
        rec["_source_file"] = path.name
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# schema


def check_schema(rec: dict, rule: dict) -> list[str]:
    """Structural errors. An absent field is an error, never a default."""
    errs: list[str] = []
    where = rec.get("_source_file", rec.get("utterance_id", "<unknown>"))

    for field in REQUIRED_FIELDS:
        if field not in rec:
            errs.append(f"{where}: MISSING_FIELD {field}")

    uid = rec.get("utterance_id", "")
    if uid and not uid.startswith("urn:obzio:w8:utterance:"):
        errs.append(f"{where}: BAD_URN {uid!r} must start with urn:obzio:w8:utterance:")

    loc = rec.get("locator")
    if isinstance(loc, dict):
        lclass = loc.get("class")
        if lclass not in LOCATOR_CLASSES:
            errs.append(f"{where}: LOCATOR_CLASS_UNKNOWN {lclass!r}")
        if not loc.get("value"):
            errs.append(f"{where}: LOCATOR_VALUE_MISSING")
        if lclass == "REPOSITORY_PATH" and not loc.get("commit"):
            errs.append(f"{where}: LOCATOR_UNPINNED a repository locator must name a commit")
    elif "locator" in rec:
        errs.append(f"{where}: LOCATOR_NOT_AN_OBJECT")

    table = rule["standing_table"]
    sc = rec.get("speaker_class")
    sa = rec.get("speech_act")
    if sc is not None and sc not in table:
        errs.append(f"{where}: SPEAKER_CLASS_UNKNOWN {sc!r}")
    elif sc is not None and sa is not None and sa not in table[sc]:
        errs.append(f"{where}: SPEECH_ACT_UNKNOWN {sa!r} for {sc}")

    if rec.get("custody") not in CUSTODY_STATES and "custody" in rec:
        errs.append(f"{where}: CUSTODY_UNKNOWN {rec.get('custody')!r}")
    if rec.get("capture_mode") not in CAPTURE_MODES and "capture_mode" in rec:
        errs.append(f"{where}: CAPTURE_MODE_UNKNOWN {rec.get('capture_mode')!r}")
    if rec.get("evidence_label") not in EVIDENCE_LABELS and "evidence_label" in rec:
        errs.append(f"{where}: EVIDENCE_LABEL_UNKNOWN {rec.get('evidence_label')!r}")

    if rec.get("is_verbatim") and not rec.get("verbatim"):
        errs.append(f"{where}: VERBATIM_CLAIMED_BUT_ABSENT")

    if rec.get("speech_act") == "ACKNOWLEDGEMENT" and not rec.get("acknowledges"):
        errs.append(f"{where}: ACKNOWLEDGEMENT_WITHOUT_TARGET must name what it acknowledges")

    for target in rec.get("supersedes", []) or []:
        if not isinstance(target, str) or not target.startswith("urn:obzio:w8:utterance:"):
            errs.append(f"{where}: SUPERSESSION_TARGET_NOT_A_URN {target!r}")

    scope = rec.get("scope")
    if scope is not None and not isinstance(scope, list):
        errs.append(f"{where}: SCOPE_NOT_A_LIST")
    elif isinstance(scope, list):
        for cls in scope:
            if not isinstance(cls, str) or not cls.startswith("DC-"):
                errs.append(f"{where}: SCOPE_NOT_A_DECISION_CLASS {cls!r} — scope is declared, never inferred from keywords")

    return errs


def check_cross_record(records: list[dict]) -> list[str]:
    errs: list[str] = []
    seen: dict[str, str] = {}
    for rec in records:
        uid = rec.get("utterance_id")
        if not uid:
            continue
        if uid in seen:
            errs.append(f"DUPLICATE_URN {uid} in {seen[uid]} and {rec.get('_source_file')}")
        seen[uid] = rec.get("_source_file", "?")
    known = set(seen)
    for rec in records:
        where = rec.get("_source_file", "?")
        for target in rec.get("supersedes", []) or []:
            if target not in known:
                errs.append(f"{where}: SUPERSESSION_TARGET_UNKNOWN {target} — supersession is named, never inferred")
        ack = rec.get("acknowledges")
        if ack and ack not in known:
            errs.append(f"{where}: ACKNOWLEDGEMENT_TARGET_UNKNOWN {ack}")
    return errs


# --------------------------------------------------------------------------
# standing


def timestamp_trust(rec: dict) -> str:
    """A URL identifies a conversation, not when a message inside it was made."""
    if not rec.get("uttered_at"):
        return "UNTRUSTED"
    lclass = (rec.get("locator") or {}).get("class")
    if lclass == "REPOSITORY_PATH" and (rec.get("locator") or {}).get("commit"):
        return "TRUSTED"
    if lclass == "EXPORT_RECORD" and (rec.get("locator") or {}).get("message_timestamp"):
        return "TRUSTED"
    return "UNTRUSTED"


def derive_standing(rec: dict, rule: dict) -> tuple[str, list[str]]:
    """Standing from the table, then the caps, then the promotion. Never from tone."""
    reasons: list[str] = []
    table = rule["standing_table"]
    sc = rec.get("speaker_class")
    sa = rec.get("speech_act")

    if sc not in table or sa not in table.get(sc, {}):
        return "S0", ["SPEAKER_OR_ACT_UNKNOWN -> S0, never a default"]

    standing = table[sc][sa]
    reasons.append(f"table[{sc}][{sa}] = {standing}")

    lclass = (rec.get("locator") or {}).get("class")
    if lclass == "ALIAS":
        reasons.append("CAP-ALIAS-LOCATOR: a display alias resolves to whatever the reader is looking at -> S0")
        return "S0", reasons

    if not rec.get("is_verbatim") and _gt(standing, "S1"):
        reasons.append("CAP-PARAPHRASE: not recorded verbatim -> capped at S1")
        standing = "S1"

    if (
        rec.get("capture_mode") == "VOICE"
        and not rec.get("read_back_confirmed")
        and _gt(standing, "S2")
    ):
        reasons.append("CAP-UNCONFIRMED-VOICE: voice capture without a confirmed read-back -> capped at S2 (CAPTURED_UNCONFIRMED)")
        standing = "S2"

    if standing == "S3" and rec.get("designated_standing"):
        reasons.append("PROMOTE-DESIGNATED: the founder designated it as standing over future operations -> S4")
        standing = "S4"

    return standing, reasons


def effective_standing_for_scope(rec: dict, by_id: dict[str, dict], rule: dict) -> tuple[str, list[str]]:
    """Own standing, except that an acknowledgement cannot lift what it acknowledges.

    This is the laundering path: 'yes, do that' against an assistant proposal
    must not convert the proposal into founder intent.
    """
    standing, reasons = derive_standing(rec, rule)
    if rec.get("speech_act") != "ACKNOWLEDGEMENT":
        return standing, reasons
    if rec.get("restates_content_verbatim"):
        reasons.append("the founder restated the content himself, so the restatement is his utterance")
        return standing, reasons
    target = by_id.get(rec.get("acknowledges", ""))
    if target is None:
        reasons.append("CAP-ACKNOWLEDGEMENT: target unresolvable -> S0")
        return "S0", reasons
    tstanding, _ = derive_standing(target, rule)
    if _gt(standing, tstanding):
        reasons.append(
            f"CAP-ACKNOWLEDGEMENT: assent to {target.get('utterance_id')} "
            f"({tstanding}); what was authored is the assent, so effective standing is {tstanding}"
        )
        standing = tstanding
    return standing, reasons


def is_admitted(rec: dict, standing: str) -> bool:
    return rec.get("custody") == "COMMITTED" and _ge(standing, "S2")


def _idx(s: str) -> int:
    return STANDING_ORDER.index(s) if s in STANDING_ORDER else -1


def _gt(a: str, b: str) -> bool:
    return _idx(a) > _idx(b)


def _ge(a: str, b: str) -> bool:
    return _idx(a) >= _idx(b)


# --------------------------------------------------------------------------
# resolution


def _parse_time(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_scope(scope: str, records: list[dict], rule: dict) -> dict:
    by_id = {r["utterance_id"]: r for r in records if r.get("utterance_id")}

    candidates = []
    for rec in records:
        if scope not in (rec.get("scope") or []):
            continue
        standing, reasons = effective_standing_for_scope(rec, by_id, rule)
        if not is_admitted(rec, standing):
            continue
        candidates.append({"rec": rec, "standing": standing, "reasons": reasons})

    result: dict[str, Any] = {
        "scope": scope,
        "candidate_count": len(candidates),
        "candidates": [
            {
                "utterance_id": c["rec"]["utterance_id"],
                "standing": c["standing"],
                "speaker_class": c["rec"].get("speaker_class"),
                "speech_act": c["rec"].get("speech_act"),
                "uttered_at": c["rec"].get("uttered_at"),
                "timestamp_trust": timestamp_trust(c["rec"]),
                "locator": c["rec"].get("locator"),
            }
            for c in candidates
        ],
    }

    if not candidates:
        result.update(state="NO_ADMITTED_CLAIM", winner=None, resolved_by=None)
        return result

    # step 2 - standing
    top = max(_idx(c["standing"]) for c in candidates)
    at_top = [c for c in candidates if _idx(c["standing"]) == top]
    if len(at_top) == 1:
        result.update(
            state="RESOLVED",
            winner=at_top[0]["rec"]["utterance_id"],
            resolved_by="STANDING",
            winning_standing=at_top[0]["standing"],
        )
        return result

    # step 3 - named supersession
    ids_at_top = {c["rec"]["utterance_id"] for c in at_top}
    superseders = [
        c
        for c in at_top
        if ids_at_top - {c["rec"]["utterance_id"]}
        <= set(c["rec"].get("supersedes", []) or [])
    ]
    if len(superseders) == 1:
        result.update(
            state="RESOLVED",
            winner=superseders[0]["rec"]["utterance_id"],
            resolved_by="NAMED_SUPERSESSION",
            winning_standing=superseders[0]["standing"],
        )
        return result

    # step 4 - the founder's own recency clause, only where he stated it
    all_founder = all(c["rec"].get("speaker_class") == "FOUNDER_DIRECT" for c in at_top)
    trusts = [timestamp_trust(c["rec"]) for c in at_top]
    times = [_parse_time(c["rec"].get("uttered_at")) for c in at_top]
    orderable = (
        all_founder
        and all(t == "TRUSTED" for t in trusts)
        and all(t is not None for t in times)
        and len({t.isoformat() for t in times if t}) == len(times)
    )
    if orderable:
        newest = max(at_top, key=lambda c: _parse_time(c["rec"]["uttered_at"]))
        result.update(
            state="RESOLVED",
            winner=newest["rec"]["utterance_id"],
            resolved_by="FOUNDER_PRECEDENCE_RECENCY",
            winning_standing=newest["standing"],
            note="the founder's precedence clause authorises recency for direct founder intent; it is applied here and nowhere else",
        )
        return result

    # step 5 - fail closed
    blockers = []
    if not all_founder:
        blockers.append("not every tied candidate is a direct founder utterance")
    if any(t != "TRUSTED" for t in trusts):
        blockers.append("at least one timestamp is untrusted: a conversation URL identifies a conversation, not when a message inside it was made")
    if any(t is None for t in times):
        blockers.append("at least one candidate has no parseable utterance time")
    if len({t.isoformat() for t in times if t}) != len([t for t in times if t]):
        blockers.append("two candidates share an utterance time and cannot be ordered")

    result.update(
        state="UNRESOLVED",
        winner=None,
        resolved_by=None,
        why_recency_does_not_apply=blockers,
        effect="the class retains its previously admitted value; work is not blocked",
        founder_question=(
            f"Two claims of equal standing contest {scope} and neither supersedes the other. "
            "Which stands? "
            + " | ".join(
                f"{c['rec']['utterance_id']} ({(c['rec'].get('locator') or {}).get('value')})"
                for c in at_top
            )
        ),
    )
    return result


def all_scopes(records: list[dict]) -> list[str]:
    out: set[str] = set()
    for rec in records:
        for cls in rec.get("scope") or []:
            out.add(cls)
    return sorted(out)


# --------------------------------------------------------------------------
# commands


def cmd_validate(rule: dict, records: list[dict]) -> int:
    errs: list[str] = []
    for rec in records:
        errs.extend(check_schema(rec, rule))
    errs.extend(check_cross_record(records))
    for e in errs:
        print(f"ERROR {e}")
    if errs:
        print(f"\nFAIL: {len(errs)} error(s) over {len(records)} utterance(s)")
        return 1
    print(f"PASS: {len(records)} utterance(s), schema and locator discipline hold")
    return 0


def cmd_standing(rule: dict, records: list[dict], uid: str) -> int:
    by_id = {r["utterance_id"]: r for r in records if r.get("utterance_id")}
    rec = by_id.get(uid)
    if rec is None:
        print(f"ERROR unknown utterance {uid}")
        return 1
    standing, reasons = effective_standing_for_scope(rec, by_id, rule)
    print(json.dumps(
        {
            "utterance_id": uid,
            "standing": standing,
            "standing_name": rule["standing_lattice"][standing]["name"],
            "custody": rec.get("custody"),
            "admitted": is_admitted(rec, standing),
            "timestamp_trust": timestamp_trust(rec),
            "derivation": reasons,
        },
        indent=2,
    ))
    return 0


def cmd_resolve(rule: dict, records: list[dict], scope: str) -> int:
    result = resolve_scope(scope, records, rule)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["state"] == "UNRESOLVED" else 0


def cmd_conflicts(rule: dict, records: list[dict]) -> int:
    unresolved = []
    for scope in all_scopes(records):
        result = resolve_scope(scope, records, rule)
        marker = {"RESOLVED": "ok", "UNRESOLVED": "UNRESOLVED", "NO_ADMITTED_CLAIM": "--"}[result["state"]]
        print(f"{marker:>10}  {scope:<34} candidates={result['candidate_count']} by={result.get('resolved_by')}")
        if result["state"] == "UNRESOLVED":
            unresolved.append(result)
    if unresolved:
        print(f"\n{len(unresolved)} contested class(es) fail closed. One question each:\n")
        for r in unresolved:
            print(f"  - {r['founder_question']}")
        print("\nNo lane is blocked by these. Each class retains its previously admitted value.")
        return 1
    print("\nPASS: no contested class is unresolved")
    return 0


def cmd_report(rule: dict, records: list[dict]) -> int:
    by_id = {r["utterance_id"]: r for r in records if r.get("utterance_id")}
    out = {
        "rule": rule["artifact_id"],
        "utterance_count": len(records),
        "utterances": [],
        "scopes": [],
    }
    for rec in records:
        standing, reasons = effective_standing_for_scope(rec, by_id, rule)
        out["utterances"].append({
            "utterance_id": rec.get("utterance_id"),
            "standing": standing,
            "standing_name": rule["standing_lattice"][standing]["name"],
            "admitted": is_admitted(rec, standing),
            "custody": rec.get("custody"),
            "speaker_class": rec.get("speaker_class"),
            "speech_act": rec.get("speech_act"),
            "timestamp_trust": timestamp_trust(rec),
            "scope": rec.get("scope"),
            "derivation": reasons,
        })
    for scope in all_scopes(records):
        out["scopes"].append(resolve_scope(scope, records, rule))
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["validate", "standing", "resolve", "conflicts", "report"])
    ap.add_argument("--id", help="utterance urn, for `standing`")
    ap.add_argument("--scope", help="decision class, for `resolve`")
    ap.add_argument("--ledger", help="override the utterance directory")
    ap.add_argument("--rule", help="override the rule tables")
    args = ap.parse_args(argv)

    try:
        rule = load_rule(pathlib.Path(args.rule) if args.rule else RULE_PATH)
        records = load_utterances(pathlib.Path(args.ledger) if args.ledger else UTTERANCE_DIR)
    except LedgerError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        return cmd_validate(rule, records)
    if args.command == "standing":
        if not args.id:
            print("ERROR --id is required", file=sys.stderr)
            return 2
        return cmd_standing(rule, records, args.id)
    if args.command == "resolve":
        if not args.scope:
            print("ERROR --scope is required", file=sys.stderr)
            return 2
        return cmd_resolve(rule, records, args.scope)
    if args.command == "conflicts":
        return cmd_conflicts(rule, records)
    return cmd_report(rule, records)


if __name__ == "__main__":
    raise SystemExit(main())
