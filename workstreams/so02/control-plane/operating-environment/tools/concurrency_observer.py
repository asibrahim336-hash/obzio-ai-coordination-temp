#!/usr/bin/env python3
"""The concurrency gate: observed, never asserted, and honest about what it cannot see.

Ahmed Sadek, standing amendment 2026-08-23:

    "Concurrency. Do not corrupt work in flight. PO-03 has live top-level runs; a
    write that would disturb a running lane waits for that lane to finish — not
    forever. When it completes, the gate is gone."

Concurrency is a property of a target **at a moment**, not of its name. The same
branch is closed at 03:00 and open at 03:20 with nothing about it having changed
but the world. So this module takes an observation with an instant attached and
returns what was true then; it holds no list of branches and would not know what
to do with one.

## Two signals, because one of them has a hole in it

**Signal 1 — the top-level agent layer.** `cursor-cloud list-cloud-agents` is
read-only and reports each accessible run's `status` and `branchName`.

**The hole, DIRECTLY_REPRODUCED on 2026-08-23T03:40Z.** Lane OE-W9 called that
tool while itself running against `cursor/oe-w9-reason-gated-writes-696d`, and
its own branch was absent from all 13 returned agents. Sibling lanes running as
subagents were likewise absent; only top-level runs carried a `branchName`. A
writer can therefore be fully live and completely invisible to signal 1, so
"no agent named this branch" is NOT evidence that nobody is writing it. Treating
absence as idleness would be exactly the "assumed success" this estate has
already been burned by.

**Signal 2 — remote ref movement.** An invisible writer still has to move the
remote ref to do any damage. Comparing the ref now against the SHA recorded when
the declaration was made catches a writer that signal 1 cannot see. It is not
complete either — a writer that has not pushed yet is invisible to both — but it
closes the common case and it is cheap.

The composed verdict names its own limit rather than rounding up to "clear".

## Why an allowlist and not a denylist of busy states

EARNED, and the defect is recorded: `capacity_verdict` in `evidence_integrity.py`
used a DENYLIST of interference statuses, so every status nobody enumerated —
including `ERROR` and `FAILED` — passed silently. This module inverts it. Only
statuses affirmatively known to mean "this run is not writing" are settled;
every other status, including ones this code has never heard of, counts as
possibly in flight.

Note the deliberate difference from `evidence_integrity.BENIGN_STATUSES`, which
includes `RUNNING`. That set answers "did my work disturb a pre-existing task",
where a task still running is a task unharmed. This set answers "is someone
writing my target right now", where a task still running is the whole problem.
Same word, opposite polarity, so they are separate constants on purpose.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z$")

#: Statuses affirmatively known to mean the run is not writing. Anything else,
#: known or not yet invented, is treated as possibly in flight and must be
#: adjudicated rather than passing silently.
SETTLED_STATUSES = frozenset({
    "IDLE",
    "ERROR",
    "ARCHIVED",
    "EXPIRED",
    "COMPLETED",
    "FINISHED",
})

#: Recorded for the reader's benefit: statuses observed in this estate that are
#: NOT settled. This is documentation of what has been seen, not the check —
#: the check is the allowlist above, which fails closed on the unseen.
OBSERVED_LIVE_STATUSES = ("RUNNING", "NOT_YET_STARTED", "WAITING_FOR_BACKGROUND_WORK", "UNSPECIFIED")

IN_FLIGHT = "IN_FLIGHT_LIVE_AGENT_HOLDS_TARGET"
IN_FLIGHT_REF_MOVED = "IN_FLIGHT_REF_MOVED_SINCE_DECLARATION"
SETTLED = "SETTLED_SUBJECT_TO_TOP_LAYER_LIMIT"
UNOBSERVABLE = "CONCURRENCY_UNOBSERVABLE"

#: The honest caveat that travels with every non-refusing verdict.
TOP_LAYER_LIMIT = (
    "This observation sees only the top-level agent layer. Subagent lanes do not appear in "
    "list-cloud-agents and carry no branchName; lane OE-W9 reproduced its own absence while "
    "running. A settled verdict means no live agent was VISIBLE holding this ref and the ref had "
    "not moved — it is not proof that nobody is writing."
)


def _parse_instant(value: str) -> datetime | None:
    match = ISO_RE.match(str(value or ""))
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout, done.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def is_settled(status: Any) -> bool:
    """Fail closed: an unrecognised status is not settled."""
    return isinstance(status, str) and status.upper() in SETTLED_STATUSES


def live_agents_holding(ref: str, agents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs that name this ref and are not in an affirmatively settled state."""
    holders: list[dict[str, Any]] = []
    for agent in agents or []:
        if not isinstance(agent, dict):
            # A malformed entry is not evidence of idleness. Surface it as a
            # holder so it is adjudicated rather than skipped.
            holders.append({"bcId": None, "branchName": None, "status": "UNPARSEABLE_AGENT_RECORD"})
            continue
        branch = agent.get("branchName")
        if not branch or branch != ref:
            continue
        if is_settled(agent.get("status")):
            continue
        holders.append({
            "bcId": agent.get("bcId"),
            "branchName": branch,
            "status": agent.get("status"),
            "name": agent.get("name"),
            "isKilled": agent.get("isKilled"),
        })
    return holders


def observe_ref_movement(ref: str, recorded_sha: str | None, repo: Path | None = None,
                         remote: str = "origin") -> dict[str, Any]:
    """Compare the remote ref now against the SHA the declaration recorded.

    This is the only signal that can catch a writer the agent layer cannot see.
    """
    code, out, err = run(["git", "ls-remote", "--heads", remote, f"refs/heads/{ref}"], cwd=repo)
    if code != 0:
        return {"observable": False, "detail": f"ls-remote failed: {err.strip()}",
                "remote_sha": None, "moved": None}
    observed = out.split()[0] if out.strip() else None
    if recorded_sha is None:
        return {"observable": True, "remote_sha": observed, "moved": None,
                "detail": "no recorded_sha to compare against; movement not determinable"}
    return {
        "observable": True,
        "remote_sha": observed,
        "recorded_sha": recorded_sha,
        "moved": observed != recorded_sha,
        "detail": (
            "the remote ref differs from the SHA recorded at declaration time"
            if observed != recorded_sha else "the remote ref is where the declaration recorded it"
        ),
    }


def concurrency_verdict(
    ref: str,
    observation: dict[str, Any],
    repo: Path | None = None,
    recorded_sha: str | None = None,
    check_ref_movement: bool = True,
    now: datetime | None = None,
    max_observation_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Decide whether `ref` may be written, from evidence rather than assertion.

    `max_observation_age_seconds` is ASSISTANT_AUTHORED: any specific threshold
    is invented, so it is None by default and reported as an advisory age rather
    than enforced. What is not invented, and does block, is an observation with
    no instant at all or an instant in the future — neither is an observation of
    now, and the founder's gate is about now.
    """
    now = now or datetime.now(timezone.utc)
    findings: list[str] = []

    if not isinstance(observation, dict):
        return {
            "ref": ref, "verdict": UNOBSERVABLE, "writable": False,
            "findings": ["no observation supplied; idleness was asserted rather than observed"],
            "limit": TOP_LAYER_LIMIT,
        }

    observed_at_raw = observation.get("observed_at")
    observed_at = _parse_instant(observed_at_raw)
    if observed_at is None:
        findings.append(
            f"observed_at {observed_at_raw!r} is missing or unparseable; an observation with no "
            "instant cannot show the target was idle when this write was made"
        )
    elif observed_at > now:
        findings.append(f"observed_at {observed_at_raw} is in the future relative to {now.isoformat()}")

    agents = observation.get("agents")
    if not isinstance(agents, list):
        findings.append("observation carries no agent list; absence of data is not evidence of idleness")
        agents = []

    if findings:
        return {
            "ref": ref, "verdict": UNOBSERVABLE, "writable": False,
            "findings": findings, "limit": TOP_LAYER_LIMIT,
        }

    age_seconds = int((now - observed_at).total_seconds())
    advisories: list[str] = []
    if max_observation_age_seconds is not None and age_seconds > max_observation_age_seconds:
        return {
            "ref": ref, "verdict": UNOBSERVABLE, "writable": False,
            "observed_at": observed_at_raw, "observation_age_seconds": age_seconds,
            "findings": [
                f"observation is {age_seconds}s old, over the operator-set limit of "
                f"{max_observation_age_seconds}s; it describes a moment that has passed"
            ],
            "limit": TOP_LAYER_LIMIT,
        }
    if age_seconds > 900:
        advisories.append(
            f"observation is {age_seconds}s old; no threshold is enforced because any specific "
            "number is assistant-invented, but concurrency is a property of a moment"
        )

    holders = live_agents_holding(ref, agents)
    movement = (
        observe_ref_movement(ref, recorded_sha, repo)
        if check_ref_movement else
        {"observable": False, "detail": "ref-movement check disabled by caller", "moved": None}
    )

    if holders:
        verdict, writable = IN_FLIGHT, False
        for holder in holders:
            findings.append(
                f"run {holder.get('bcId')} is {holder.get('status')} on this ref; the gate is this "
                "run finishing, not permission"
            )
    elif movement.get("moved") is True:
        verdict, writable = IN_FLIGHT_REF_MOVED, False
        findings.append(
            f"the remote ref is at {movement.get('remote_sha')} but the declaration recorded "
            f"{recorded_sha}; something moved it after this write was declared"
        )
    elif check_ref_movement and not movement.get("observable"):
        verdict, writable = UNOBSERVABLE, False
        findings.append(f"ref movement could not be observed: {movement.get('detail')}")
    else:
        verdict, writable = SETTLED, True

    return {
        "ref": ref,
        "verdict": verdict,
        "writable": writable,
        "observed_at": observed_at_raw,
        "observation_age_seconds": age_seconds,
        "agents_considered": len(agents),
        "live_holders": holders,
        "ref_movement": movement,
        "findings": findings,
        "advisories": advisories,
        "limit": TOP_LAYER_LIMIT,
        "settled_statuses_allowlisted": sorted(SETTLED_STATUSES),
        "gate_expires_when": (
            "the runs named in live_holders reach a settled status; the founder: 'a write that "
            "would disturb a running lane waits for that lane to finish — not forever'"
        ) if holders else "not gated at this observation",
    }


def normalise_observation(payload: Any) -> dict[str, Any]:
    """Accept either a bare {observed_at, agents} or a stored capture receipt.

    A capture keeps the tool payload untouched under `payload` and its own
    metadata under `_capture`, so that the retained evidence is the bytes the
    tool returned rather than a reshaped copy of them.
    """
    if not isinstance(payload, dict):
        return {}
    agents = payload.get("agents")
    if agents is None and isinstance(payload.get("payload"), dict):
        agents = payload["payload"].get("agents")
    observed_at = payload.get("observed_at")
    if observed_at is None and isinstance(payload.get("_capture"), dict):
        observed_at = payload["_capture"].get("observed_at")
    return {"observed_at": observed_at, "agents": agents}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide whether a ref is safe to write from an observed agent list")
    parser.add_argument("ref", help="the ref the write targets")
    parser.add_argument("--observation", required=True,
                        help="path to JSON with {observed_at, agents:[...]} from list-cloud-agents")
    parser.add_argument("--recorded-sha", default=None,
                        help="the SHA the declaration recorded for this ref")
    parser.add_argument("--repo", default=".", help="repository to run ls-remote from")
    parser.add_argument("--no-ref-movement", action="store_true")
    parser.add_argument("--max-observation-age-seconds", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        observation = normalise_observation(json.loads(Path(args.observation).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read observation: {exc}", file=sys.stderr)
        return 2

    result = concurrency_verdict(
        args.ref, observation, repo=Path(args.repo), recorded_sha=args.recorded_sha,
        check_ref_movement=not args.no_ref_movement,
        max_observation_age_seconds=args.max_observation_age_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["writable"] else 1


if __name__ == "__main__":
    sys.exit(main())
