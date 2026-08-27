#!/usr/bin/env python3
"""Reproduce a fail-open in the concurrency gate, found by tripping it.

Lane B declared `ref_sha_at_observation: null` for its own branch, on the stated
belief that the ref did not exist on the remote yet. The belief was wrong — the
ref was at a1592234, published earlier in this same run — and the gate returned
SETTLED anyway. The declaration was false and the gate did not notice, which is
the interesting half.

The mechanism: `observe_ref_movement` is honest and returns
`{"observable": True, "moved": None, "detail": "no recorded_sha to compare
against; movement not determinable"}`. `concurrency_verdict` then tests only
`moved is True` and `not observable`, so `moved is None` falls through to the
terminal `else`, which is SETTLED and writable. Movement is the one signal the
comment in that function calls "the only signal that can catch a writer the agent
layer cannot see", and it is skipped by omitting a field.

This is ICH-02's shape exactly — the denylist capacity detector where IDLE→ERROR
passed because the check enumerated the bad states instead of the good ones.
Here the branch enumerates the bad movement outcomes (True, unobservable) and
lets everything else, including "I could not tell", reach the permissive default.
Same fix shape too: decide on an allowlist of outcomes that mean safe.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[7]
OE_TOOLS = REPO_ROOT / "workstreams/so02/control-plane/operating-environment/tools"
BRANCH = "cursor/scp-b-improvement-chain-696d"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


observer = load("concurrency_observer", OE_TOOLS / "concurrency_observer.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_sha(ref: str) -> str | None:
    done = subprocess.run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{ref}"],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    out = done.stdout.strip()
    return out.split()[0] if out else None


IDLE_AGENTS = [{"bcId": "bc-probe-idle", "name": "probe", "branchName": None, "status": "IDLE"}]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verdict_for(recorded: str | None) -> dict[str, Any]:
    return observer.concurrency_verdict(
        BRANCH,
        {"observed_at": now_iso(), "agents": IDLE_AGENTS},
        repo=REPO_ROOT,
        recorded_sha=recorded,
        check_ref_movement=True,
    )


def main() -> int:
    live = remote_sha(BRANCH)

    # Case A: no recorded SHA at all. This is what lane B's own admitted
    # declaration carried, and what any declaration using DELETE_CREATED_REF
    # carries by default, since that reversal method has no recorded_sha field.
    omitted = verdict_for(None)

    # Case B: a recorded SHA that is deliberately wrong. The same gate, given one
    # more field, correctly refuses. So the gate is not weak — it is skippable.
    wrong = verdict_for("0" * 40)

    # Case C: the truthful recorded SHA. Passes, as it should.
    truthful = verdict_for(live) if live else None

    fail_open = bool(omitted.get("writable")) and omitted["ref_movement"].get("moved") is None
    catches_when_told = wrong.get("writable") is False

    report = {
        "record_id": "SCP-B-MOVEMENT-GATE-FAILOPEN-REPRO-20260827-v001",
        "decision_changed": [
            "Lane B's own concurrency observation was corrected: it claimed the ref did "
            "not exist on the remote, and the ref existed at a1592234. The declaration "
            "was rebuilt with the observed remote SHA and re-admitted."
        ],
        "produced_at": now_iso(),
        "instrument": "workstreams/so02/control-plane/operating-environment/scp-si-01/"
                      "lane-b/tools/reproduce_movement_gate_failopen.py",
        "interpreter": f"python3 -I {sys.version.split()[0]}",
        "module_under_test": "workstreams/so02/control-plane/operating-environment/"
                             "tools/concurrency_observer.py",
        "ref": BRANCH,
        "live_remote_sha": live,
        "how_it_was_found": (
            "Not by auditing the module. Lane B pushed, and `git push` reported "
            "a1592234..a24b0b6d — a range, meaning the ref already existed. The lane's "
            "own admitted declaration had asserted it did not. Checking why the gate "
            "had not caught the false assertion produced the defect."
        ),
        "cases": {
            "A_recorded_sha_omitted": {
                "recorded_sha": None,
                "verdict": omitted.get("verdict"),
                "writable": omitted.get("writable"),
                "ref_movement": omitted.get("ref_movement"),
                "expected_if_failing_closed": "UNOBSERVABLE / writable false",
                "fails_open": fail_open,
            },
            "B_recorded_sha_wrong": {
                "recorded_sha": "0" * 40,
                "verdict": wrong.get("verdict"),
                "writable": wrong.get("writable"),
                "gate_catches_it": catches_when_told,
            },
            "C_recorded_sha_truthful": {
                "recorded_sha": live,
                "verdict": truthful.get("verdict") if truthful else None,
                "writable": truthful.get("writable") if truthful else None,
            },
        },
        "finding": (
            "concurrency_verdict tests `moved is True` and `not observable`, so the third "
            "outcome — observable, movement not determinable — reaches the terminal else "
            "and is reported SETTLED and writable. Omitting one optional field disables "
            "the check the module's own docstring calls the only signal that can catch a "
            "writer the agent layer cannot see."
        ),
        "reproduced": fail_open and catches_when_told,
        "evidence_label": "DIRECTLY_REPRODUCED",
        "same_class_as": "ICH-02-DENYLIST-CAPACITY",
        "why_same_class": (
            "Both enumerate the outcomes that are bad and let the remainder reach a "
            "permissive default. There IDLE→ERROR was not in the harmful list; here "
            "moved=None is not in the refusing list. The fix shape is the same "
            "inversion: name the outcomes that mean safe and refuse the rest."
        ),
        "provenance_class": "EARNED",
        "provenance_basis": (
            "Found by this lane tripping the gate with a false declaration and then "
            "noticing the gate had admitted it. Not an invented rule and not traceable "
            "to a founder utterance, so it binds as mechanism."
        ),
        "mechanism_change_state": "PENDING",
        "mechanism_change_owner": "owner of the write-admission subsystem "
                                  "(lane D or the SCP-SI-01 coordinator)",
        "why_this_lane_does_not_ship_it": (
            "concurrency_observer.py is the write-admission subsystem, not the ledger "
            "schema this lane was commissioned to extend, and every lane in this cohort "
            "is pushing through that gate right now. Changing the gate's verdict "
            "mid-cohort from a lane that is itself being gated by it would be a producer "
            "editing its own admission criteria. Recorded PENDING and routed."
        ),
        "what_this_lane_did_instead": [
            "Corrected its own concurrency observation to carry the observed remote SHA, "
            "so the movement check actually runs against a real value.",
            "Re-ran write_admission and recorded the second verdict.",
            "Seeded the finding as ICH-08 with the mechanism change declared pending.",
        ],
        "honest_limits": [
            "One module, one branch in the verdict function. Whether other gates in "
            "write_admission share the pattern was not audited and is not claimed.",
            "The fail-open is shown for a ref that exists. It was not tested against a "
            "ref genuinely absent from the remote, where moved=None is the honest answer "
            "and refusing may be the wrong behaviour — which is precisely why the fix is "
            "an allowlist of outcomes and not a blanket refusal on None.",
        ],
    }

    out = REPO_ROOT / "receipts/so02/2026-08-27/scp-b/reproductions"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2) + "\n"
    (out / "MOVEMENT-GATE-FAILOPEN-REPRO.json").write_text(text, encoding="utf-8")
    print(json.dumps({
        "reproduced": report["reproduced"],
        "case_A_verdict": omitted.get("verdict"),
        "case_A_writable": omitted.get("writable"),
        "case_A_moved": omitted["ref_movement"].get("moved"),
        "case_B_verdict": wrong.get("verdict"),
        "case_B_writable": wrong.get("writable"),
        "live_remote_sha": live,
        "sha256": sha256_bytes(text.encode("utf-8")),
    }, indent=2))
    return 0 if report["reproduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
