#!/usr/bin/env python3
"""Tamper with committed PO-03 custody and record what the mechanisms notice.

Two mechanisms are exercised, both the live ones rather than models of them:

- the artifact manifests `workstreams/po03/tools/emit_result.py` writes, whose
  entries carry a SHA-256, a byte count and a `git:<commit>:<path>` locator;
- `verify_chain` from `workstreams/po03/tools/transactional_factory.py`, applied
  to hash-chained event files.

Nothing in the repository under test is modified.  Artifacts are materialised
into a scratch directory before being corrupted, and event chains are copied
into a scratch tree where the factory module's roots are repointed, so the real
verifier runs over scratch bytes.

Exit codes: 0 every tamper case behaved as expected, 1 at least one did not,
2 harness error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = UNIT_ROOT.parents[3]
FACTORY_PATH = REPO_ROOT / "workstreams/po03/tools/transactional_factory.py"
ATTEMPTS_PREFIX = "workstreams/po03/attempts"
EVENTS_PREFIX = "workstreams/po03/control/events"

DETECTED = "detected"
UNDETECTED = "UNDETECTED"


class HarnessError(Exception):
    """Raised when the harness cannot run at all."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git(repo: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ("git", *arguments), cwd=repo, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HarnessError(f"git {' '.join(arguments)} failed: {exc}") from exc


class Case:
    """One tamper attempt and what the mechanism was expected to notice."""

    def __init__(self, name: str, mechanism: str, expectation: str, detail: str, detected: bool) -> None:
        self.name = name
        self.mechanism = mechanism
        self.expectation = expectation
        self.detail = detail
        self.detected = detected

    @property
    def satisfied(self) -> bool:
        return self.detected == (self.expectation == DETECTED)

    @property
    def observed(self) -> str:
        if self.detected:
            return DETECTED
        return "clean" if self.expectation == "clean" else UNDETECTED

    def as_dict(self) -> dict:
        return {
            "case": self.name,
            "mechanism": self.mechanism,
            "expectation": self.expectation,
            "observed": self.observed,
            "satisfied": self.satisfied,
            "detail": self.detail,
        }


def load_factory(scratch_root: Path):
    """Load the live factory module with its roots repointed at a scratch tree."""
    specification = importlib.util.spec_from_file_location("po03_factory_scratch", FACTORY_PATH)
    if specification is None or specification.loader is None:
        raise HarnessError(f"cannot load {FACTORY_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    module.REPO_ROOT = scratch_root
    module.PO03_ROOT = scratch_root / "workstreams/po03"
    module.CONTROL_ROOT = scratch_root / "workstreams/po03/control"
    module.RECEIPT_ROOT = scratch_root / "receipts/po03/2026-08-22"
    return module


def build_chain(factory, task_id: str, length: int = 4) -> list[Path]:
    states = ("CREATED", "LEASED", "RUNNING", "CHECKPOINTED", "RESULT_STAGED", "RESULT_COMMITTED")
    if length > len(states):
        raise HarnessError(f"cannot build a chain of {length} events")
    written = []
    for index in range(length):
        written.append(
            factory.hash_chain_event(
                task_id,
                states[index],
                actor="po03-wa-b2e7-030-tamper-evidence-harness",
                details={"sequence_hint": index + 1},
                observed_at=f"2026-08-22T08:0{index}:00Z",
            )
        )
    return written


def chain_cases(scratch_root: Path) -> list[Case]:
    """Tamper with hash-chained events and report what verify_chain notices."""
    cases: list[Case] = []
    task = "tamper-scratch-chain"

    def fresh() -> tuple[object, list[Path]]:
        root = Path(tempfile.mkdtemp(prefix="chain-", dir=scratch_root))
        factory = load_factory(root)
        return factory, build_chain(factory, task)

    factory, events = fresh()
    pristine = factory.verify_chain(task)
    cases.append(Case(
        "pristine-chain-verifies", "verify_chain", "clean",
        f"errors={pristine}", detected=bool(pristine),
    ))

    factory, events = fresh()
    document = json.loads(events[1].read_text(encoding="utf-8"))
    document["details"] = {"sequence_hint": 999}
    events[1].write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    errors = factory.verify_chain(task)
    cases.append(Case(
        "event-body-mutated", "verify_chain", DETECTED,
        f"errors={errors}", detected=bool(errors),
    ))

    factory, events = fresh()
    original = events[1].read_bytes()
    flipped = bytearray(original)
    for index, byte in enumerate(flipped):
        if chr(byte).isdigit() and chr(byte) != "9":
            flipped[index] = byte + 1
            break
    events[1].write_bytes(bytes(flipped))
    cases.append(Case(
        "single-byte-flip-preserving-length", "verify_chain", DETECTED,
        f"errors={factory.verify_chain(task)} original_bytes={len(original)} "
        f"tampered_bytes={len(flipped)}",
        detected=bool(factory.verify_chain(task)),
    ))

    factory, events = fresh()
    events[1].unlink()
    errors = factory.verify_chain(task)
    cases.append(Case(
        "middle-event-deleted", "verify_chain", DETECTED,
        f"errors={errors}", detected=bool(errors),
    ))

    factory, events = fresh()
    events[-1].unlink()
    errors = factory.verify_chain(task)
    cases.append(Case(
        "tail-event-deleted", "verify_chain", UNDETECTED,
        f"errors={errors}; a truncated chain is internally consistent because nothing "
        f"records the expected head",
        detected=bool(errors),
    ))

    factory, events = fresh()
    factory.hash_chain_event(
        task, "FAILED_TERMINAL", actor="an-actor-who-can-write-to-control",
        details={"forged": True}, observed_at="2026-08-22T09:00:00Z",
    )
    errors = factory.verify_chain(task)
    cases.append(Case(
        "forged-event-appended-with-correct-links", "verify_chain", UNDETECTED,
        f"errors={errors}; a hash chain constrains order, not authorship, so anyone able "
        f"to write to control/events can extend it",
        detected=bool(errors),
    ))

    factory, events = fresh()
    document = json.loads(events[2].read_text(encoding="utf-8"))
    document["event_sha256"] = "0" * 64
    events[2].write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    errors = factory.verify_chain(task)
    cases.append(Case(
        "self-hash-overwritten", "verify_chain", DETECTED,
        f"errors={errors}", detected=bool(errors),
    ))

    factory, events = fresh()
    document = json.loads(events[2].read_text(encoding="utf-8"))
    document["previous_event_sha256"] = "1" * 64
    body = dict(document)
    claimed = body.pop("event_sha256")
    document["event_sha256"] = factory.sha256_bytes(factory.canonical_json(body))
    events[2].write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    errors = factory.verify_chain(task)
    cases.append(Case(
        "previous-link-rewritten-and-self-hash-recomputed", "verify_chain", DETECTED,
        f"errors={errors}; recomputing the event's own hash cannot repair the link to its "
        f"predecessor's file hash (former self hash {claimed[:12]})",
        detected=bool(errors),
    ))
    return cases


def real_chain_case(scratch_root: Path, task_id: str) -> Case:
    """Verify a chain copied from the live repository, then tamper with the copy."""
    source = REPO_ROOT / EVENTS_PREFIX / task_id
    if not source.is_dir() or not any(source.glob("*.json")):
        raise HarnessError(f"no live event chain at {source}")
    root = Path(tempfile.mkdtemp(prefix="real-chain-", dir=scratch_root))
    destination = root / EVENTS_PREFIX / task_id
    destination.parent.mkdir(parents=True)
    shutil.copytree(source, destination)
    factory = load_factory(root)
    pristine = factory.verify_chain(task_id)
    events = sorted(destination.glob("*.json"))
    document = json.loads(events[0].read_text(encoding="utf-8"))
    document["actor"] = "an-actor-that-was-never-recorded"
    events[0].write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    tampered = factory.verify_chain(task_id)
    return Case(
        f"live-chain-copy-tampered:{task_id}", "verify_chain", DETECTED,
        f"pristine_errors={pristine} events={len(events)} tampered_errors={tampered}",
        detected=bool(tampered) and not pristine,
    )


def manifest_cases(scratch_root: Path, commit: str, slot: str) -> list[Case]:
    """Corrupt a materialised copy of a committed artifact and check the manifest."""
    raw = git(REPO_ROOT, "cat-file", "blob", f"{commit}:{slot}/manifest.json")
    manifest = json.loads(raw.decode("utf-8"))
    artifact = manifest["artifacts"][0]
    locator_prefix = f"git:{manifest['artifact_commit']}:"
    path = artifact["content_uri"][len(locator_prefix):]
    original = git(REPO_ROOT, "cat-file", "blob", f"{manifest['artifact_commit']}:{path}")
    cases: list[Case] = []

    cases.append(Case(
        "committed-artifact-matches-its-manifest-entry", "manifest", "clean",
        f"path={path} sha256={sha256_bytes(original)} bytes={len(original)}",
        detected=not (sha256_bytes(original) == artifact["sha256"] and len(original) == artifact["bytes"]),
    ))

    working = Path(tempfile.mkdtemp(prefix="artifact-", dir=scratch_root)) / Path(path).name
    corrupted = bytearray(original)
    corrupted[0] = (corrupted[0] + 1) % 256
    working.write_bytes(bytes(corrupted))
    measured = sha256_bytes(working.read_bytes())
    cases.append(Case(
        "materialised-artifact-single-byte-flipped", "manifest", DETECTED,
        f"path={path} manifest={artifact['sha256'][:16]} measured={measured[:16]} "
        f"bytes={len(corrupted)}",
        detected=measured != artifact["sha256"],
    ))

    truncated = bytes(original[: len(original) // 2])
    cases.append(Case(
        "materialised-artifact-truncated", "manifest", DETECTED,
        f"path={path} manifest_bytes={artifact['bytes']} measured_bytes={len(truncated)}",
        detected=(len(truncated) != artifact["bytes"] or sha256_bytes(truncated) != artifact["sha256"]),
    ))

    reread = git(REPO_ROOT, "cat-file", "blob", f"{manifest['artifact_commit']}:{path}")
    cases.append(Case(
        "committed-bytes-unchanged-by-working-copy-tampering", "git object store", "clean",
        f"path={path} sha256_after_tamper={sha256_bytes(reread)} identical={reread == original}",
        detected=reread != original,
    ))

    result_raw = git(REPO_ROOT, "cat-file", "blob", f"{commit}:{slot}/result.json")
    result = json.loads(result_raw.decode("utf-8"))
    claimed = result["result_transaction"]["manifest_sha256"]
    cases.append(Case(
        "result-cites-the-committed-manifest-bytes", "result document", "clean",
        f"claimed={claimed[:16]} measured={sha256_bytes(raw)[:16]}",
        detected=claimed != sha256_bytes(raw),
    ))

    tampered_manifest = json.loads(raw.decode("utf-8"))
    tampered_manifest["artifacts"][0]["sha256"] = "0" * 64
    tampered_bytes = (
        json.dumps(tampered_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")
    cases.append(Case(
        "manifest-entry-rewritten-breaks-the-result-hash", "result document", DETECTED,
        f"result_claims={claimed[:16]} tampered_manifest={sha256_bytes(tampered_bytes)[:16]}",
        detected=sha256_bytes(tampered_bytes) != claimed,
    ))
    return cases


def choose_slot(commit: str) -> str:
    listing = git(REPO_ROOT, "ls-tree", "-r", "--name-only", "-z", commit, "--", ATTEMPTS_PREFIX)
    slots = sorted({
        "/".join(item.decode("utf-8").split("/")[:4])
        for item in listing.split(b"\0")
        if item and item.decode("utf-8").endswith("/manifest.json")
    })
    if not slots:
        raise HarnessError(f"no slot with a manifest at {commit}")
    return slots[0]


def run_all(commit: str, slot: str, chain_task: str, scratch_root: Path) -> list[Case]:
    cases = manifest_cases(scratch_root, commit, slot)
    cases.extend(chain_cases(scratch_root))
    cases.append(real_chain_case(scratch_root, chain_task))
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--slot", help="slot to tamper with; defaults to the first with a manifest")
    parser.add_argument("--chain-task", default="po03-canary-001")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    holder = Path(tempfile.mkdtemp(prefix="po03-tamper-"))
    try:
        commit = git(REPO_ROOT, "rev-parse", args.commit).decode("utf-8").strip()
        slot = args.slot or choose_slot(commit)
        cases = run_all(commit, slot, args.chain_task, holder)
    except (HarnessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"PO03_TAMPER_ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(holder, ignore_errors=True)

    table = [case.as_dict() for case in cases]
    if args.json:
        print(json.dumps({"commit": commit, "slot": slot, "cases": table}, indent=2, sort_keys=True))
    else:
        print(f"# commit={commit}")
        print(f"# slot={slot}")
        for entry in table:
            print(
                f"{'OK      ' if entry['satisfied'] else 'SURPRISE'} "
                f"{entry['case']} mechanism={entry['mechanism']} "
                f"expected={entry['expectation']} observed={entry['observed']}"
            )
            print(f"         {entry['detail']}")
    unsatisfied = [entry for entry in table if not entry["satisfied"]]
    undetected = [entry for entry in table if entry["expectation"] == UNDETECTED]
    if unsatisfied:
        for entry in unsatisfied:
            print(
                f"PO03_TAMPER_SURPRISE: {entry['case']} expected {entry['expectation']} "
                f"but observed {entry['observed']}: {entry['detail']}",
                file=sys.stderr,
            )
        return 1
    # In JSON mode stdout must stay a single parseable document.
    stream = sys.stderr if args.json else sys.stdout
    print(
        f"PO03_TAMPER_PASS cases={len(table)} "
        f"detected={sum(1 for e in table if e['expectation'] == DETECTED)} "
        f"clean={sum(1 for e in table if e['expectation'] == 'clean')} "
        f"known_undetected={len(undetected)}",
        file=stream,
    )
    for entry in undetected:
        print(f"KNOWN_GAP: {entry['case']}: {entry['detail']}", file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
