#!/usr/bin/env python3
"""Corrected evidence controls, derived from an independent acceptance refusal.

Two defects in the CUR-ORCH-QUAL-01 verifier were found by an independent
acceptor on a different model family and then reproduced directly:

1. `verify_readback` validated the SHAPE of a read-back record, never its
   TRUTH. A wholly fabricated record naming commit 000...0 with invented
   transports passed verification. Self-consistency is not custody.

2. `capacity_verdict` used a DENYLIST of interference statuses. Any status not
   enumerated — including ERROR and FAILED — passed silently. A denylist of
   bad states fails open on every state nobody thought of.

Both corrections below invert the failing pattern: recompute instead of trust,
and allowlist benign states instead of denylisting harmful ones.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


GIT_SHA_RE_LEN = 40

# Inverted control. Only these are asserted benign for a pre-existing task.
# Anything else — known or not yet invented — is treated as possible
# interference and must be adjudicated explicitly rather than passing silently.
BENIGN_STATUSES = frozenset({"RUNNING", "IDLE", "COMPLETED", "FINISHED"})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(args: list[str], cwd: Path | None = None) -> tuple[int, bytes, str]:
    done = subprocess.run(args, cwd=cwd, capture_output=True)
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Correction 1: read-back truth, not read-back shape
# ---------------------------------------------------------------------------

def verify_readback_truth(record: dict[str, Any], remote_url: str, repo: Path) -> list[str]:
    """Recompute a read-back claim against the remote instead of trusting it.

    Every assertion in the record is re-derived. A record that cannot be
    re-derived is rejected even if it is internally perfectly consistent.
    """
    errors: list[str] = []

    commit = str(record.get("immutable_commit", ""))
    if len(commit) != GIT_SHA_RE_LEN or not all(c in "0123456789abcdef" for c in commit):
        return [f"readback: {commit!r} is not a full immutable commit SHA"]

    transports = record.get("transports", [])
    if len(transports) < 2:
        errors.append("readback: fewer than two independent transports claimed")

    with tempfile.TemporaryDirectory(prefix="evidence-truth-") as workdir:
        clone = Path(workdir) / "clone"
        code, _, err = run(["git", "clone", "--quiet", "--no-checkout", remote_url, str(clone)])
        if code != 0:
            return [f"readback: clean clone failed, claim unverifiable: {err.strip()}"]

        code, _, _ = run(["git", "fetch", "--quiet", "--no-tags", "origin", commit], cwd=clone)
        if code != 0:
            return [f"readback: commit {commit} is not retrievable from the remote; the claim is unfounded"]

        code, _, _ = run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=clone)
        if code != 0:
            return [f"readback: {commit} does not resolve to a commit on the remote"]

        comparisons = record.get("comparisons", [])
        if not comparisons:
            errors.append("readback: no entry compared")

        for item in comparisons:
            path = str(item.get("path", ""))
            code, blob, _ = run(["git", "cat-file", "-p", f"{commit}:{path}"], cwd=clone)
            if code != 0:
                errors.append(f"readback {path}: claimed compared but absent from the remote commit")
                continue
            actual = sha256_bytes(blob)
            claimed = item.get("remote_git_sha256")
            if claimed != actual:
                errors.append(
                    f"readback {path}: record claims remote digest {claimed} but the remote actually serves {actual}"
                )
            if item.get("identical_git_transport") is not True:
                errors.append(f"readback {path}: not asserted identical over the git transport")

        if record.get("mismatches"):
            errors.append("readback: record carries unresolved mismatches")
        if record.get("result") != "REMOTE_BYTE_FOR_BYTE_IDENTICAL":
            errors.append("readback: result is not a byte-for-byte identical claim")

    return errors


# ---------------------------------------------------------------------------
# Correction 2: allowlist benign states rather than denylist harmful ones
# ---------------------------------------------------------------------------

def capacity_verdict(observation: dict[str, Any], benign: Iterable[str] = BENIGN_STATUSES) -> tuple[str, list[str]]:
    """Recompute interference, failing closed on any unrecognised state."""
    benign_set = frozenset(benign)
    findings: list[str] = []

    if observation.get("capacity_observation_state") == "CAPACITY_OBSERVATION_UNAVAILABLE":
        return "CAPACITY_OBSERVATION_UNAVAILABLE", findings

    snapshots = observation.get("snapshots", [])
    if len(snapshots) < 3:
        return "INCOMPLETE", ["fewer than three snapshots"]

    baseline = {item["bcId"]: item for item in snapshots[0].get("agents", [])}
    self_id = observation.get("orchestrator_bc_id")

    for snapshot in snapshots[1:]:
        label = snapshot.get("label", "unlabelled")
        current = {item["bcId"]: item for item in snapshot.get("agents", [])}
        for bc_id, before in baseline.items():
            if bc_id == self_id:
                continue
            after = current.get(bc_id)
            if after is None:
                findings.append(f"{label}: pre-existing task {bc_id} disappeared from the visible set")
                continue
            before_status, after_status = before.get("status"), after.get("status")
            if after_status == before_status:
                continue
            if after_status not in benign_set:
                findings.append(
                    f"{label}: task {bc_id} moved {before_status} -> {after_status}, "
                    "which is not an asserted-benign state"
                )
            if after.get("isKilled") and not before.get("isKilled"):
                findings.append(f"{label}: task {bc_id} was killed after the baseline")

    return ("CAPACITY_INTERFERENCE_FAIL" if findings else "ZERO_PO03_CAPACITY_INTERFERENCE"), findings


# ---------------------------------------------------------------------------
# Correction 3: manifest closure
# ---------------------------------------------------------------------------

def verify_manifest_truth(manifest: dict[str, Any], repo: Path) -> list[str]:
    """Open every manifested file and compare its real digest to the recorded one.

    Closure and bundle-binding are SHAPE checks: they ask whether the record is
    internally consistent, and a forged record is internally consistent by
    construction. Neither opens a file.

    Found live by Lane C and reproduced by the coordinator against its own
    declaration: an entry whose recorded sha256 was sixty-four zeroes, with
    bundle_sha256 recomputed over the corrupted list, passed the evidence gate
    as EVIDENCE_RECOMPUTED. This is the verify_readback_truth defect — shape
    checked, truth never — in the other evidence kind, inside the very gate
    built as that defect's remedy.
    """
    return _manifest_truth(manifest, repo, anchor_commit=None)[0]


def audit_manifest_truth(manifest: dict[str, Any], repo: Path,
                         anchor_commit: str) -> tuple[list[str], list[str]]:
    """Retrospective audit that separates a tampered record from a superseded one.

    At admission time the working tree IS the thing being declared, so
    verify_manifest_truth is correct. Re-auditing an old declaration later is a
    different question, and answering it with the same check manufactures an
    alarm every time an authorised change lands.

    DEF-SCP-01: supersession and tampering demand opposite responses. A hash
    that was correct at its own commit and has since changed is routine. A hash
    that was wrong even at its own commit is an incident. Returns
    (mismatches, superseded).
    """
    return _manifest_truth(manifest, repo, anchor_commit=anchor_commit)


def _manifest_truth(manifest: dict[str, Any], repo: Path,
                    anchor_commit: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    superseded: list[str] = []
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        return (["manifest truth: no entries to verify; an empty record cannot evidence anything"], [])

    if anchor_commit is not None:
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append("manifest truth: entry is not an object")
                continue
            relative = str(entry.get("path", ""))
            done = subprocess.run(["git", "cat-file", "-p", f"{anchor_commit}:{relative}"],
                                  cwd=repo, capture_output=True)
            if done.returncode != 0:
                errors.append(f"manifest truth: {relative} is absent from anchor commit {anchor_commit}")
                continue
            at_anchor = sha256_bytes(done.stdout)
            if at_anchor != entry.get("sha256"):
                errors.append(
                    f"manifest truth: {relative} records {entry.get('sha256')} but hashed "
                    f"{at_anchor} at its own commit {anchor_commit} — wrong when written"
                )
                continue
            target = repo / relative
            if target.is_file() and sha256_bytes(target.read_bytes()) != at_anchor:
                superseded.append(
                    f"evidence superseded: {relative} was correct at {anchor_commit} and has changed since"
                )
        return (errors, superseded)

    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest truth: entry is not an object")
            continue
        relative = str(entry.get("path", ""))
        if not relative:
            errors.append("manifest truth: entry carries no path")
            continue
        target = repo / relative
        if not target.is_file():
            errors.append(f"manifest truth: {relative} is recorded but absent from disk")
            continue
        actual = sha256_bytes(target.read_bytes())
        claimed = entry.get("sha256")
        if claimed != actual:
            errors.append(
                f"manifest truth: {relative} records {claimed} but the file actually hashes to {actual}"
            )
        size = entry.get("size_bytes")
        if size is not None and size != target.stat().st_size:
            errors.append(
                f"manifest truth: {relative} records {size} bytes but the file is {target.stat().st_size}"
            )
    return (errors, superseded)


def verify_artifact_validity(paths: Iterable[str], repo: Path) -> list[str]:
    """A hash-bound artifact can still be unparseable.

    Found live: a lane published a truncated JSON file whose digest matched its
    manifest exactly and whose closure check passed. Byte integrity says the
    bytes are the ones that were committed; it says nothing about whether they
    mean anything. A structured artifact nobody can load is not evidence.
    """
    errors: list[str] = []
    for relative in sorted(set(paths)):
        if not relative.endswith(".json"):
            continue
        target = repo / relative
        if not target.is_file():
            continue
        try:
            json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"validity: {relative} is hash-bound but does not parse as JSON ({exc.msg} at line {exc.lineno})")
        except UnicodeDecodeError as exc:
            errors.append(f"validity: {relative} is not decodable as UTF-8 ({exc})")
    return errors


def verify_manifest_closure(manifest: dict[str, Any], present_paths: Iterable[str]) -> list[str]:
    """Every material file must be covered. An excluded file is an unbound file."""
    errors: list[str] = []
    covered = {entry.get("path") for entry in manifest.get("entries", [])}
    for path in sorted(set(present_paths)):
        if path not in covered:
            errors.append(f"manifest: {path} is present but not covered by any hash")
    recomputed = sha256_bytes(
        json.dumps(manifest.get("entries", []), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if manifest.get("bundle_sha256") != recomputed:
        errors.append("manifest: bundle_sha256 does not bind the entry list")
    return errors
