#!/usr/bin/env python3
"""Build lane B's write declaration with its closure computed, not typed.

The declaration asserts a result — a manifest closure over the set this lane
changed — so every digest in it has to come from the bytes on disk at the moment
the declaration is written. A hand-maintained digest list is the forged read-back
this lane seeded as ICH-01, in a different costume.

The reversal command is likewise re-derived from `reversal_rehearsal.build_reversal`
rather than written out, because `command_matches_constructor` refuses a drifted
command and the honest way to satisfy that gate is to not hand-write the command
in the first place.

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
DECLARATION = (REPO_ROOT / "workstreams/so02/control-plane/operating-environment"
               / "write-declarations/WRITE-DECLARATION-SCP-B.json")
OBSERVATION = (REPO_ROOT / "workstreams/so02/control-plane/operating-environment/scp-si-01"
               / "lane-b/chains/CONCURRENCY-OBSERVATION-SCP-B.json")

BRANCH = "cursor/scp-b-improvement-chain-696d"
BASE = "7f29043eece45f42f018d841718a257cfd18739b"
INTEGRATION_AUDITED = "f0fb3f51a25db67b33bdd558c73055f3d02ddb60"
LANE_ID = "SCP-SI-01/lane-B"
COMMISSION_ID = "COM-CUR-ENV-01-20260822-v001"

#: Paths this lane did not author. They are in the diff because the integration
#: branch was merged in mid-run, and declaring them as this lane's write would be
#: a false claim of authorship.
NOT_OURS = {
    "workstreams/so02/control-plane/operating-environment/scp-si-01/"
    "DEFECT-SCP-01-SUPERSESSION-READS-AS-TAMPERING.json",
    "workstreams/so02/control-plane/operating-environment/write-declarations/"
    "WRITE-DECLARATION-SCP-DEF01.json",
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reversal_rehearsal = load("reversal_rehearsal", OE_TOOLS / "reversal_rehearsal.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(args: list[str]) -> str:
    done = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def changed_paths() -> list[str]:
    out = git(["diff", "--name-only", BASE, "HEAD"])
    paths = [p for p in out.splitlines() if p]
    # The declaration names itself nowhere: it is the authorisation for the write,
    # not part of the result the write asserts.
    ours = [p for p in paths
            if p not in NOT_OURS
            and not p.endswith("WRITE-DECLARATION-SCP-B.json")
            and "__pycache__" not in p]
    return sorted(ours)


def closure(paths: list[str]) -> dict[str, Any]:
    entries = []
    for rel in paths:
        target = REPO_ROOT / rel
        if not target.exists():
            raise SystemExit(f"declared path is not on disk: {rel}")
        raw = target.read_bytes()
        entries.append({"path": rel, "size_bytes": len(raw), "sha256": sha256_bytes(raw)})
    entries.sort(key=lambda e: e["path"])
    bundle = sha256_bytes(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return {
        "entries": entries,
        "entry_count": len(entries),
        "bundle_sha256": bundle,
        "closure_note": (
            "Closure over every path this lane authored between "
            f"{BASE[:8]} and this branch head. Two paths present in the diff are "
            "excluded and named in the declaration: they arrived by merging the "
            "integration branch mid-run and were written by the coordinator."
        ),
    }


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    paths = changed_paths()
    record = closure(paths)
    reversal = reversal_rehearsal.build_reversal("DELETE_CREATED_REF", BRANCH, remote="origin")
    observation = json.loads(OBSERVATION.read_text(encoding="utf-8"))

    declaration = {
        "declaration_version": "1.0",
        "declared_by": f"lane B, run bc-1c0486c5-f59f-5aed-9490-4bcb33d6b0e3 ({LANE_ID})",
        "declared_at": now,
        "target": {
            "ref": BRANCH,
            "paths": paths,
            "operation": "COMMIT_AND_PUSH",
        },
        "reason": {
            "code": "PUBLISH_LANE_DELIVERABLE",
            "statement": (
                "Publish lane B's commissioned deliverable — a typed improvement link "
                "chain projected from the existing hash-chained event log — onto lane "
                "B's own branch. No other lane's namespace and no shared ref is written."
            ),
            "lane_id": LANE_ID,
            "commission_id": COMMISSION_ID,
            "expires_when": "the lane's commission closes",
        },
        "reversal": {
            "method": reversal["method"],
            "remote": "origin",
            "command": reversal["command"],
            "restores": reversal["restores"],
            "custody_required": reversal["custody_required"],
            "custody_note": (
                "The ref is created by this lane and did not exist on the remote before "
                "this write, so the pre-write state is its absence and deleting it is "
                "the whole rollback. No custody tag of a prior SHA is owed because there "
                "is no prior SHA to restore."
            ),
        },
        "evidence": {
            "asserts_result": True,
            "kind": "MANIFEST_CLOSURE",
            "record": record,
        },
        "concurrency": observation,
        "scope_attestation": {
            "integration_commit_audited_against": INTEGRATION_AUDITED,
            "base_commit": BASE,
            "canonical_files_extended": [
                "workstreams/so02/control-plane/state/events.jsonl",
                "workstreams/so02/control-plane/state/control-plane.json",
                "workstreams/so02/control-plane/tools/scctl.py",
                "workstreams/so02/control-plane/tools/improvement_chain.py",
                "workstreams/so02/control-plane/tools/../tests/test_scctl.py",
                "workstreams/so02/control-plane/.gitignore",
                "workstreams/so02/control-plane/operating-environment/"
                "l4-currentness-recovery/tools/currentctl.py",
                "workstreams/so02/control-plane/operating-environment/"
                "l4-currentness-recovery/ledger/admission-ladder.json",
                "workstreams/so02/control-plane/operating-environment/"
                "l4-currentness-recovery/ledger/workstream-ledger.json",
            ],
            "canonical_extension_is_permitted_because": (
                "The dispatch permits extending canonical files under "
                "workstreams/so02/control-plane/** where the schema evolution belongs "
                "there, and it does: the deliverable is an extension of the existing "
                "ledger and its projections, not a new store. Putting the links "
                "anywhere else would have created the competing ledger the dispatch "
                "forbids."
            ),
            "paths_in_diff_not_authored_by_this_lane": sorted(NOT_OURS),
            "other_lane_namespaces_written": [],
            "no_new_store_created": True,
        },
    }

    text = json.dumps(declaration, indent=2) + "\n"
    DECLARATION.write_text(text, encoding="utf-8")
    print(json.dumps({
        "declaration": str(DECLARATION.relative_to(REPO_ROOT)),
        "declared_paths": len(paths),
        "bundle_sha256": record["bundle_sha256"],
        "declaration_sha256": sha256_bytes(text.encode("utf-8")),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
