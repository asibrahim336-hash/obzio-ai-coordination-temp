#!/usr/bin/env python3
"""Close the lane bundle: hash every artifact, then read it back and parse it.

Two separate checks, because this estate has already been bitten by treating them
as one. `verify_manifest_closure` proves the bytes are the bytes. It says nothing
about whether they mean anything — a truncated JSON file whose digest matched its
manifest exactly passed closure once, which is the defect seeded as ICH-05. So
every structured artifact here is re-read from disk after the digest is taken and
parsed: JSON through `json.loads`, JSONL line by line, Python through `compile`.
An artifact that hashes correctly and does not parse fails this manifest.

The remote head is read with `git ls-remote` rather than taken from the push exit
code, which is ICH-04.

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
CONTROL_PLANE = REPO_ROOT / "workstreams/so02/control-plane"
MANIFEST = REPO_ROOT / "receipts/so02/2026-08-27/scp-b/MANIFEST.json"

BRANCH = "cursor/scp-b-improvement-chain-696d"
BASE = "7f29043eece45f42f018d841718a257cfd18739b"
INTEGRATION_AUDITED = "f0fb3f51a25db67b33bdd558c73055f3d02ddb60"

#: Excluded from the entry list, and declared. The manifest cannot contain its
#: own digest, and this is the only exclusion.
SELF = "receipts/so02/2026-08-27/scp-b/MANIFEST.json"

#: In the diff because the integration branch was merged in mid-run. Covered by
#: hash so the bundle is closed, but attributed to the coordinator, because
#: claiming authorship of another actor's write would be a false provenance.
NOT_AUTHORED_HERE = {
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


evidence_integrity = load("evidence_integrity", OE_TOOLS / "evidence_integrity.py")
improvement_chain = load("improvement_chain", CONTROL_PLANE / "tools/improvement_chain.py")
scctl = load("scctl", CONTROL_PLANE / "tools/scctl.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(args: list[str]) -> str:
    done = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def bundle_paths() -> list[str]:
    out = git(["diff", "--name-only", BASE, "HEAD"])
    paths = [p for p in out.splitlines()
             if p and p != SELF and "__pycache__" not in p]
    return sorted(paths)


# ---------------------------------------------------------------------------
# read-back: the digest, then the parse, as two separate assertions
# ---------------------------------------------------------------------------

def parse_check(relative: str, raw: bytes) -> dict[str, Any]:
    """Re-derive meaning, not just bytes. Returns a per-artifact verdict."""
    if relative.endswith(".json"):
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return {"parser": "json.loads", "parsed": False, "error": str(exc)}
        shape = ("object" if isinstance(parsed, dict)
                 else "array" if isinstance(parsed, list) else "scalar")
        keys = len(parsed) if isinstance(parsed, (dict, list)) else None
        return {"parser": "json.loads", "parsed": True, "top_level": shape,
                "top_level_size": keys}
    if relative.endswith(".jsonl"):
        lines = raw.decode("utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                return {"parser": "json.loads per line", "parsed": False,
                        "error": f"line {number}: {exc.msg}"}
        return {"parser": "json.loads per line", "parsed": True,
                "records": len([line for line in lines if line.strip()])}
    if relative.endswith(".py"):
        try:
            compile(raw.decode("utf-8"), relative, "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            return {"parser": "compile", "parsed": False, "error": str(exc)}
        return {"parser": "compile", "parsed": True}
    if relative.endswith((".yaml", ".yml")):
        # No stdlib YAML parser. Saying so is the honest answer; claiming a parse
        # that did not happen is the forged read-back this lane seeded as ICH-01.
        return {"parser": None, "parsed": None,
                "note": "no stdlib YAML parser; digest bound, parse not asserted"}
    return {"parser": None, "parsed": None,
            "note": "unstructured or plain text; digest bound, parse not applicable"}


def build_entries(paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    failures: list[str] = []
    for relative in paths:
        target = REPO_ROOT / relative
        if not target.is_file():
            failures.append(f"{relative} is in the bundle set but not on disk")
            continue
        raw = target.read_bytes()
        digest = sha256_bytes(raw)
        # Read a second time, independently, and confirm the digest is stable
        # before parsing. A single read cannot distinguish a digest of what was
        # written from a digest of what is there.
        reread = target.read_bytes()
        if sha256_bytes(reread) != digest:
            failures.append(f"{relative} changed between two reads; not stable evidence")
            continue
        verdict = parse_check(relative, reread)
        if verdict.get("parsed") is False:
            failures.append(f"{relative} is hash-bound but does not parse: {verdict.get('error')}")
        entries.append({
            "path": relative,
            "size_bytes": len(raw),
            "sha256": digest,
            "authored_by": ("SCP-SI-01 coordinator, arrived by mid-run merge"
                            if relative in NOT_AUTHORED_HERE else "lane B"),
            "readback": verdict,
        })
    entries.sort(key=lambda entry: entry["path"])
    return entries, failures


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    paths = bundle_paths()
    entries, failures = build_entries(paths)

    closure_entries = [{"path": e["path"], "size_bytes": e["size_bytes"], "sha256": e["sha256"]}
                       for e in entries]
    bundle = sha256_bytes(
        json.dumps(closure_entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )

    # Re-verify with the estate's own checker rather than only our arithmetic.
    closure_record = {"entries": closure_entries, "bundle_sha256": bundle}
    closure_errors = evidence_integrity.verify_manifest_closure(closure_record, paths)
    validity_errors = evidence_integrity.verify_artifact_validity(paths, REPO_ROOT)

    events = scctl.read_jsonl(CONTROL_PLANE / "state/events.jsonl")
    chains, findings = improvement_chain.check_all(events, REPO_ROOT)
    summary = improvement_chain.summarise(chains, findings)
    hash_chain_errors: list[str] = []
    scctl.validate_events(events, hash_chain_errors)

    local_head = git(["rev-parse", "HEAD"])
    remote_line = git(["ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}"])
    remote_head = remote_line.split()[0] if remote_line.strip() else None

    manifest = {
        "record_id": "SCP-B-MANIFEST-20260827-v001",
        "lane": "SCP-SI-01/lane-B",
        "produced_at": now,
        "decision_changed": [],
        "branch": BRANCH,
        "base_commit": BASE,
        "integration_commit_audited_against": INTEGRATION_AUDITED,
        "bundle_head": local_head,
        "remote_head_via_ls_remote": remote_head,
        "bundle_is_published": remote_head == local_head,
        "manifest_commit_follows": (
            "This manifest is sealed against the head that is already on the remote, then "
            "committed and pushed as one further commit. So the branch tip after delivery "
            "is one commit ahead of bundle_head, and that commit adds only this file — "
            "which is the single declared exclusion. Saying the remote equals the tip "
            "after pushing the manifest would require the manifest to contain its own "
            "digest."
        ),
        "remote_read_method": (
            "git ls-remote origin refs/heads/<branch>. Not the push exit code and not "
            "the push transcript: ICH-04 is a push that printed success and published "
            "nothing."
        ),
        "closure": {
            "entries": entries,
            "entry_count": len(entries),
            "bundle_sha256": bundle,
            "bundle_binds": "sha256 of the canonicalised [{path,size_bytes,sha256}] list",
            "excluded_paths": [SELF],
            "exclusion_declared_because": (
                "A manifest cannot contain its own digest. This is the only exclusion; "
                "every other path this branch changed is covered, including the two "
                "written by the coordinator and attributed to them."
            ),
            "closure_verified_by": "evidence_integrity.verify_manifest_closure",
            "closure_errors": closure_errors,
            "validity_verified_by": "evidence_integrity.verify_artifact_validity",
            "validity_errors": validity_errors,
        },
        "readback_discipline": {
            "every_artifact_read_twice": True,
            "digest_stability_asserted": True,
            "structured_artifacts_parsed_after_readback": True,
            "parsers_used": ["json.loads", "json.loads per line", "compile"],
            "not_asserted": (
                "YAML files carry a digest and no parse verdict, because there is no "
                "stdlib YAML parser and a claimed parse would be a forged read-back."
            ),
            "why_two_checks": (
                "Closure proves the bytes are the bytes. ICH-05 is a truncated JSON "
                "artifact that passed closure with a correct digest. Byte integrity and "
                "meaning are separate properties and are asserted separately here."
            ),
        },
        "improvement_chain_state": {
            "chain_count": summary["chain_count"],
            "node_count": summary["node_count"],
            "refused": summary["refused"],
            "chains": summary.get("chains"),
            "hash_chain_errors": hash_chain_errors,
            "event_count": len(events),
            "event_head": events[-1]["event_sha256"] if events else None,
        },
        "no_new_store_created": True,
        "no_new_store_evidence": (
            "The links are ordinary events in workstreams/so02/control-plane/state/"
            "events.jsonl carrying one new optional payload key. The registry view is "
            "scctl.py project; the currentness and recovery views are currentctl.py "
            "compile. All three are pure functions of the same event list. Deleting "
            "improvement_chain.py loses no evidence, only the ability to read it."
        ),
        "verdict": "READY_TO_COMMIT" if not (
            failures or closure_errors or validity_errors or hash_chain_errors
            or summary["refused"] or remote_head != local_head
        
        ) else "NOT_READY",
        "failures": failures,
        "provenance_class": "EARNED",
        "provenance_basis": (
            "Every check in this manifest exists because of a named defect this lane "
            "seeded: ICH-01 for recomputing rather than trusting a read-back, ICH-04 for "
            "reading the remote instead of the push exit code, ICH-05 for parsing and "
            "not only hashing."
        ),
        "evidence_label": "DIRECTLY_REPRODUCED",
    }

    text = json.dumps(manifest, indent=2) + "\n"
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(text, encoding="utf-8")

    # Read the manifest back and parse it, holding it to its own rule.
    written = MANIFEST.read_bytes()
    json.loads(written.decode("utf-8"))

    print(json.dumps({
        "verdict": manifest["verdict"],
        "entry_count": len(entries),
        "bundle_sha256": bundle,
        "manifest_sha256": sha256_bytes(written),
        "local_head": local_head,
        "remote_head": remote_head,
        "bundle_is_published": manifest["bundle_is_published"],
        "chains": summary["chain_count"],
        "chain_refused": summary["refused"],
        "closure_errors": closure_errors,
        "validity_errors": validity_errors,
        "hash_chain_errors": hash_chain_errors,
        "failures": failures,
    }, indent=2))
    return 0 if manifest["verdict"] == "READY_TO_COMMIT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
