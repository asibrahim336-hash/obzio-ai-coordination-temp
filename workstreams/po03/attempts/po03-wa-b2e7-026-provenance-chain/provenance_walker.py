#!/usr/bin/env python3
"""Walk PO-03 results back to the immutable capsule that authorised them.

A counted result claims two provenance hashes: the SHA-256 of its task capsule
`input.json` and the SHA-256 of its `acceptance.json`.  Those are claims.  This
walker measures the capsule bytes itself and refuses any result whose claim does
not reproduce, any result with no capsule at all, and any artifact-bearing slot
with no result to root it.

The measurement matters because the emitter copies
`acceptance_contract_sha256` out of the capsule's own `source_hashes` block
rather than hashing `acceptance.json`.  A result can therefore carry an
acceptance hash that nothing ever checked against the acceptance bytes.  The
walker closes that gap by hashing the acceptance contract directly and by
cross-checking the capsule's self-declared hash against the same bytes.

Exit codes: 0 every result rooted, 1 at least one unrooted, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ATTEMPTS_PREFIX = "workstreams/po03/attempts"
TASKS_PREFIX = "workstreams/po03/control/tasks"
EVENTS_PREFIX = "workstreams/po03/control/events"
GENERATED_NAMES = frozenset({"manifest.json", "result.json"})


class ProvenanceError(Exception):
    """Raised when the repository cannot be read as a provenance source."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Reader:
    """Read repository-relative bytes from the working tree or from a commit."""

    def __init__(self, repo: Path, commit: str | None = None) -> None:
        self.repo = Path(repo)
        self.commit = commit
        if not (self.repo / "workstreams/po03").is_dir():
            raise ProvenanceError(f"not a PO-03 repository root: {self.repo}")

    @property
    def source(self) -> str:
        return f"git:{self.commit}" if self.commit else f"worktree:{self.repo.as_posix()}"

    def _git(self, *arguments: str) -> bytes:
        try:
            return subprocess.run(
                ("git", *arguments), cwd=self.repo, check=True, capture_output=True
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ProvenanceError(f"git {' '.join(arguments)} failed: {exc}") from exc

    def read(self, path: str) -> bytes | None:
        if self.commit is None:
            target = self.repo / path
            if target.is_symlink() or not target.is_file():
                return None
            return target.read_bytes()
        listed = self._git("ls-tree", "-r", "--name-only", "-z", self.commit, "--", path)
        if path.encode("utf-8") not in listed.split(b"\0"):
            return None
        return self._git("cat-file", "blob", f"{self.commit}:{path}")

    def list_under(self, prefix: str) -> list[str]:
        if self.commit is None:
            root = self.repo / prefix
            if not root.is_dir():
                return []
            return sorted(
                item.relative_to(self.repo).as_posix()
                for item in root.rglob("*")
                if item.is_file() and not item.is_symlink() and "__pycache__" not in item.parts
            )
        listing = self._git("ls-tree", "-r", "--name-only", "-z", self.commit, "--", prefix)
        return sorted(item.decode("utf-8") for item in listing.split(b"\0") if item)

    def read_json(self, path: str) -> dict | None:
        payload = self.read(path)
        if payload is None:
            return None
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProvenanceError(f"{path}: not readable JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise ProvenanceError(f"{path}: root must be an object")
        return document


def discover_slots(reader: Reader) -> list[str]:
    slots: set[str] = set()
    for path in reader.list_under(ATTEMPTS_PREFIX):
        parts = path.split("/")
        if len(parts) > 4:
            slots.add("/".join(parts[:4]))
    return sorted(slots)


def walk_slot(reader: Reader, slot: str) -> tuple[dict, list[str]]:
    """Root one result slot, returning its provenance record and any findings."""
    findings: list[str] = []
    record: dict = {"slot": slot, "task_id": None, "rooted": False}
    files = [path for path in reader.list_under(slot)]
    payload_files = [path for path in files if Path(path).name not in GENERATED_NAMES]

    result = reader.read_json(f"{slot}/result.json")
    if result is None:
        if payload_files:
            findings.append(f"ORPHAN_SLOT slot={slot} artifacts={len(payload_files)} result=absent")
        else:
            findings.append(f"EMPTY_SLOT slot={slot}")
        return record, findings

    task_id = result.get("task_id")
    record["task_id"] = task_id
    if not isinstance(task_id, str) or not task_id:
        findings.append(f"NO_TASK_ID slot={slot}")
        return record, findings
    if slot != f"{ATTEMPTS_PREFIX}/{task_id}":
        findings.append(f"SLOT_MISMATCH slot={slot} task_id={task_id}")

    capsule_path = f"{TASKS_PREFIX}/{task_id}/input.json"
    acceptance_path = f"{TASKS_PREFIX}/{task_id}/acceptance.json"
    capsule_bytes = reader.read(capsule_path)
    acceptance_bytes = reader.read(acceptance_path)
    if capsule_bytes is None:
        findings.append(f"CAPSULE_MISSING task={task_id} path={capsule_path}")
        return record, findings
    if acceptance_bytes is None:
        findings.append(f"ACCEPTANCE_MISSING task={task_id} path={acceptance_path}")
        return record, findings

    measured_input = sha256_bytes(capsule_bytes)
    measured_acceptance = sha256_bytes(acceptance_bytes)
    record["measured_input_sha256"] = measured_input
    record["measured_acceptance_sha256"] = measured_acceptance

    claimed_input = result.get("immutable_input_manifest_sha256")
    if claimed_input != measured_input:
        findings.append(
            f"INPUT_HASH_MISMATCH task={task_id} claimed={claimed_input} measured={measured_input}"
        )
    claimed_acceptance = result.get("acceptance_contract_sha256")
    if claimed_acceptance != measured_acceptance:
        findings.append(
            f"ACCEPTANCE_HASH_MISMATCH task={task_id} claimed={claimed_acceptance} "
            f"measured={measured_acceptance}"
        )

    capsule = reader.read_json(capsule_path) or {}
    declared = (capsule.get("source_hashes") or {}).get("acceptance_contract_sha256")
    if declared != measured_acceptance:
        findings.append(
            f"CAPSULE_SELF_INCONSISTENT task={task_id} declared={declared} measured={measured_acceptance}"
        )
    if capsule.get("task_id") != task_id:
        findings.append(f"CAPSULE_TASK_ID_MISMATCH task={task_id} capsule={capsule.get('task_id')}")
    if capsule.get("commission_id") != result.get("commission_id"):
        findings.append(
            f"COMMISSION_MISMATCH task={task_id} capsule={capsule.get('commission_id')} "
            f"result={result.get('commission_id')}"
        )
    declared_slot = (capsule.get("ownership") or {}).get("result_slot")
    if declared_slot != slot:
        findings.append(f"OWNERSHIP_SLOT_MISMATCH task={task_id} capsule={declared_slot} walked={slot}")

    transaction = capsule.get("transaction") or {}
    attempt = result.get("attempt") or {}
    for field in ("idempotency_key", "lease_id", "fence_token"):
        if transaction.get(field) != attempt.get(field):
            findings.append(
                f"ATTEMPT_BINDING_MISMATCH task={task_id} field={field} "
                f"capsule={transaction.get(field)} result={attempt.get(field)}"
            )

    if not reader.list_under(f"{EVENTS_PREFIX}/{task_id}"):
        findings.append(f"EVENT_CHAIN_MISSING task={task_id}")

    manifest = reader.read_json(f"{slot}/manifest.json")
    if manifest is None:
        findings.append(f"MANIFEST_MISSING task={task_id}")
    else:
        if manifest.get("task_id") != task_id:
            findings.append(f"MANIFEST_TASK_ID_MISMATCH task={task_id} manifest={manifest.get('task_id')}")
        commit = manifest.get("artifact_commit")
        record["artifact_commit"] = commit
        covered = set()
        for artifact in manifest.get("artifacts") or []:
            locator = artifact.get("content_uri", "")
            expected = f"git:{commit}:"
            if not locator.startswith(expected):
                findings.append(f"ARTIFACT_UNROOTED task={task_id} locator={locator} commit={commit}")
                continue
            covered.add(locator[len(expected):])
        uncovered = sorted(set(payload_files) - covered)
        for path in uncovered:
            findings.append(f"ARTIFACT_UNCOVERED task={task_id} path={path}")

    if result.get("obzio_state") == "COMPLETED" or result.get("completion_actor") is not None:
        findings.append(f"PRODUCER_CLAIMED_COMPLETION task={task_id} state={result.get('obzio_state')}")
    acceptance_block = result.get("independent_acceptance") or {}
    if acceptance_block.get("state") in {"ACCEPTED", "REJECTED"}:
        if acceptance_block.get("reviewer_id") == attempt.get("worker_id"):
            findings.append(f"SELF_ACCEPTANCE task={task_id} reviewer={acceptance_block.get('reviewer_id')}")

    record["rooted"] = not findings
    return record, findings


def walk(reader: Reader, only: str | None = None) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    findings: list[str] = []
    slots = discover_slots(reader)
    if only is not None:
        slots = [slot for slot in slots if slot.endswith(f"/{only}")]
        if not slots:
            findings.append(f"NO_SUCH_SLOT task={only}")
    for slot in slots:
        record, slot_findings = walk_slot(reader, slot)
        records.append(record)
        findings.extend(slot_findings)
    if not slots and only is None:
        findings.append("NO_SLOTS_FOUND")
    return records, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--commit", help="walk committed bytes at this immutable commit")
    parser.add_argument("--task-id", help="walk only this task's slot")
    parser.add_argument("--json", action="store_true", help="print the provenance records as JSON")
    args = parser.parse_args(argv)
    try:
        reader = Reader(Path(args.repo_root), args.commit)
        records, findings = walk(reader, args.task_id)
    except ProvenanceError as exc:
        print(f"PO03_PROVENANCE_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"source": reader.source, "records": records, "findings": findings},
                         indent=2, sort_keys=True))
    else:
        for record in records:
            status = "ROOTED  " if record["rooted"] else "UNROOTED"
            print(
                f"{status} task={record['task_id'] or record['slot']} "
                f"input={record.get('measured_input_sha256')} "
                f"acceptance={record.get('measured_acceptance_sha256')}"
            )
        for finding in findings:
            print(f"PO03_PROVENANCE_UNROOTED: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"PO03_PROVENANCE_PASS rooted={len(records)} source={reader.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
