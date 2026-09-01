#!/usr/bin/env python3
"""subagentStart / subagentStop ledger.

Reproduced constraint this exists to answer: a subagent is not addressable at
the provider layer. cursor-cloud run-info, list-cloud-agents and
/v1/meta-data/agent/id all resolve to the TOP-LEVEL run, and a subagent never
appears as its own run. So when a group fans out into lanes, the provider
cannot say which lane did what, how many lanes actually started, or whether a
lane that was dispatched ever returned.

That is exactly the "declared denominator versus actual" problem. These hooks
record it locally, from inside the runtime, at the only moment the information
exists.

The ledger is append-only JSONL under .cursor/.run/, which is per-pod and not
committed. Promote an entry into a receipt if it needs to be durable — this is
an observation instrument, not custody.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(".cursor/.run/subagent-ledger.jsonl")
SOCK_META = "/v1/meta-data"


def meta(path: str) -> str:
    """Read one metadata leaf, or "" when it is absent.

    The service answers a missing path with a JSON error body on a 404 rather
    than with empty output, and the `turn/` subtree is transient: it was
    observed present and then absent within the same run. Treat any JSON error
    body as absence so a vanished leaf never gets recorded as a value.
    """
    import os
    sock = os.environ.get("CURSOR_AGENT_SOCKET", "/run/cursor/api.sock")
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "5", "--unix-socket", sock,
             f"http://localhost{SOCK_META}/{path}"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    value = r.stdout.strip()
    if value.startswith("{") and '"error"' in value:
        return ""
    return value


def boot_binding() -> dict:
    """Fall back to the binding start.sh captured at boot."""
    try:
        return json.loads(Path(".cursor/.run/runtime-binding.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> None:
    phase = "stop" if "--stop" in sys.argv else "start"
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    boot = boot_binding()
    entry = {
        "phase": phase,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Provider-side identity: constant across every subagent of one run.
        "top_level_agent_id": meta("agent/id") or boot.get("agent_id", ""),
        # turn/* is transient. Prefer the live value, fall back to the boot
        # snapshot, and record which source was used rather than silently
        # presenting a stale value as current.
        "turn_id": meta("turn/id") or boot.get("turn_id", ""),
        "turn_model": meta("turn/model") or boot.get("turn_model", ""),
        "turn_source": "live" if meta("turn/id") else ("boot_snapshot" if boot.get("turn_id") else "unavailable"),
        # Subagent-side identity: the only place this is visible at all.
        "subagent_type": payload.get("subagent_type") or payload.get("type"),
        "subagent_id": payload.get("subagent_id") or payload.get("id"),
        "conversation_id": payload.get("conversation_id"),
        "generation_id": payload.get("generation_id"),
        "status": payload.get("status"),
        "checked_out_branch": _branch(),
    }
    entry["raw_keys"] = sorted(payload.keys())

    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass

    sys.exit(0)


def _branch() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        sys.exit(0)
