#!/usr/bin/env python3
"""Compile G2 from G1 by applying one patch per measured G1 failure.

G2 is not a rewrite.  It is G1 plus exactly six changes, and every change names
the holdout case that failed, the sentence the failing run printed, and the route
it supersedes.  Building it as a patch set rather than a hand-edited copy is what
makes the lineage checkable: the diff cannot contain a change that no measured
failure motivated, because a patch that is not in this file is not applied, and a
patch whose anchor text is missing is a hard error rather than a silent skip.

The measured G1 failures are read from unit 062's committed measurement document.
A patch whose case_id is not in that document's failure list is refused, so the
successor cannot quietly acquire improvements that were never measured as broken.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LINEAGE_VERSION = "PO03-G2-LINEAGE-v1"
STAGED_FOR = "successor/g2/"

# ----------------------------------------------------------------------------
# H01 — completion was bound to "some ingestion happened", not to this result.
#
# The naive repair is to require the completed document to be byte-identical to
# the ingested one.  That is wrong, and measurement is what shows it: the
# coordinator must stamp parent_ingested_at before the COMPLETED contract will
# validate, so a byte-identity gate makes every legitimate completion impossible.
# The binding is therefore over result identity with the coordinator-stamped
# fields normalised away.

BINDING_HELPER = '''
COORDINATOR_STAMPED_FIELDS = (
    "obzio_state",
    "completion_actor",
    "independent_acceptance",
    "result_transaction.parent_ingested_at",
)


def result_binding_digest(document: dict[str, Any]) -> str:
    """Digest the identity of a result, ignoring the fields custody stamps on it.

    Completion has to be bound to the result that was actually ingested, but the
    completed document is not the ingested document byte-for-byte: the
    coordinator sets parent_ingested_at, obzio_state, completion_actor and the
    acceptance block on the way through.  Normalising exactly those fields
    leaves the artifacts, the attempt and the result transaction identity, which
    is what "the same result" has to mean.
    """
    normalised = json.loads(json.dumps(document))
    normalised["obzio_state"] = "RESULT_COMMITTED"
    normalised["completion_actor"] = None
    normalised["independent_acceptance"] = {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None}
    transaction = normalised.get("result_transaction")
    if isinstance(transaction, dict):
        transaction["parent_ingested_at"] = None
    return sha256_bytes(canonical_json(normalised))


def ingested_binding_digests(task_id: str) -> list[str]:
    """Every result identity that reached PARENT_INGESTED for this task."""
    digests: list[str] = []
    for path in sorted((CONTROL_ROOT / "tasks" / task_id).glob("ingestion-*.json")):
        record = read_json(path)
        if record.get("obzio_state") != "PARENT_INGESTED":
            continue
        digest = record.get("result_binding_sha256")
        if isinstance(digest, str):
            digests.append(digest)
    return digests


'''

PATCHES: tuple[dict[str, Any], ...] = (
    {
        "change_id": "G2-CHANGE-001",
        "case_id": "H01-completion-bound-to-ingested-result",
        "hazard": "false completion against a result the coordinator never ingested",
        "route": "complete_unit + ingest_result",
        "disposition": "SUPERSEDE",
        "rationale": (
            "the completion gate is bound to the identity of the ingested result rather than to the "
            "existence of any PARENT_INGESTED event for the task"
        ),
        "edits": (
            {
                "anchor": "def ingest_result(task_id: str, document: dict[str, Any]) -> dict[str, Any]:",
                "replacement": BINDING_HELPER.lstrip("\n")
                + "def ingest_result(task_id: str, document: dict[str, Any]) -> dict[str, Any]:",
            },
            {
                "anchor": '        "result_sha256": result_sha,\n        "idempotency_key": attempt.get("idempotency_key"),',
                "replacement": '        "result_sha256": result_sha,\n'
                '        "result_binding_sha256": result_binding_digest(document),\n'
                '        "idempotency_key": attempt.get("idempotency_key"),',
            },
            {
                "anchor": '    events = sorted((CONTROL_ROOT / "events" / task_id).glob("*.json"))\n'
                '    ingested = any(read_json(path).get("state") == "PARENT_INGESTED" for path in events)\n'
                "    if not ingested:\n"
                '        raise ValueError(f"{task_id}: cannot complete before PARENT_INGESTED")',
                "replacement": "    binding = result_binding_digest(document)\n"
                "    ingested = ingested_binding_digests(task_id)\n"
                "    if not ingested:\n"
                '        raise ValueError(f"{task_id}: cannot complete before PARENT_INGESTED")\n'
                "    if binding not in ingested:\n"
                "        raise ValueError(\n"
                '            f"{task_id}: cannot complete a result that was never ingested; "\n'
                '            f"binding digest {binding} is not among the ingested results {ingested}"\n'
                "        )",
            },
        ),
    },
    {
        "change_id": "G2-CHANGE-002",
        "case_id": "H02-fence-monotonic-under-concurrency",
        "hazard": "duplicate fence tokens issued to concurrent workers",
        "route": "allocate_fence",
        "disposition": "SUPERSEDE",
        "rationale": (
            "the read-modify-write of the counter is serialised by an exclusive lock file, so the "
            "atomic replace of the counter can no longer lose a concurrent increment"
        ),
        "edits": (
            {
                "anchor": "import subprocess\nimport tempfile",
                "replacement": "import subprocess\nimport tempfile\nimport time",
            },
            {
                "anchor": '''def allocate_fence() -> int:
    """Allocate a strictly monotonic fence token.

    The previous value survives a crash mid-allocation because the counter is
    replaced atomically rather than rewritten in place.
    """
    counter = CONTROL_ROOT / "fence-counter.json"
    current = read_json(counter)["fence_token"] if counter.is_file() else 0
    nxt = int(current) + 1
    replace_atomic(counter, canonical_json({"fence_token": nxt, "allocated_at": utc_now()}))
    return nxt''',
                "replacement": '''FENCE_LOCK_TIMEOUT_SECONDS = 30.0


def allocate_fence() -> int:
    """Allocate a strictly monotonic fence token.

    Atomically replacing the counter file keeps a crash mid-allocation from
    leaving a torn value, but it does nothing about two allocators reading the
    same value before either writes: both then issue the same token, which is
    exactly the guarantee a fence exists to provide.  The read, the increment
    and the write are therefore held under an exclusive lock created with
    O_CREAT|O_EXCL, which is atomic on a local filesystem.
    """
    counter = CONTROL_ROOT / "fence-counter.json"
    lock = counter.with_name(counter.name + ".lock")
    counter.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + FENCE_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"fence counter lock {repo_relative(lock)} still held after "
                    f"{FENCE_LOCK_TIMEOUT_SECONDS}s; refusing to issue a token that may duplicate"
                )
            time.sleep(0.001)
            continue
        try:
            current = read_json(counter)["fence_token"] if counter.is_file() else 0
            nxt = int(current) + 1
            replace_atomic(counter, canonical_json({"fence_token": nxt, "allocated_at": utc_now()}))
            return nxt
        finally:
            os.close(handle)
            os.unlink(lock)''',
            },
        ),
    },
    {
        "change_id": "G2-CHANGE-003",
        "case_id": "H03-ingestion-rejects-foreign-task-result",
        "hazard": "one unit's result recorded as another unit's result",
        "route": "ingest_result",
        "disposition": "SUPERSEDE",
        "rationale": "the document's own task_id is compared with the custody task before anything is recorded",
        "edits": (
            {
                "anchor": "    validator = load_result_validator()\n"
                "    errors = list(validator.validate_result(document))\n"
                '    attempt = document.get("attempt", {}) if isinstance(document.get("attempt"), dict) else {}',
                "replacement": "    validator = load_result_validator()\n"
                "    errors = list(validator.validate_result(document))\n"
                '    attempt = document.get("attempt", {}) if isinstance(document.get("attempt"), dict) else {}\n'
                "\n"
                "    # A result is only this unit's result if it says so.  Without this the\n"
                "    # coordinator will happily file a sibling's work under this task's custody.\n"
                '    if document.get("task_id") != task_id:\n'
                "        errors.append(\n"
                '            f"result document task_id {document.get(\'task_id\')!r} does not match "\n'
                '            f"custody task {task_id!r}"\n'
                "        )",
            },
        ),
    },
    {
        "change_id": "G2-CHANGE-004",
        "case_id": "H04-recovery-reports-real-collision-count",
        "hazard": "recovery state asserts zero collisions while subtrees overlap",
        "route": "scan_recovery",
        "disposition": "SUPERSEDE",
        "rationale": "collision_count is computed by detect_path_collisions and the overlaps themselves are recorded",
        "edits": (
            {
                "anchor": '    state = {\n        "recovery_version": "PO03-RECOVERY-STATE-v1",',
                "replacement": "    # The count used to be the literal 0, so a scan could report a clean\n"
                "    # topology while two subordinates claimed the same subtree.\n"
                "    try:\n"
                "        collisions = detect_path_collisions()\n"
                "    except (FileNotFoundError, ValueError) as exc:\n"
                '        collisions = [f"path ownership unreadable: {exc}"]\n'
                "    state = {\n"
                '        "recovery_version": "PO03-RECOVERY-STATE-v1",',
            },
            {
                # The same two lines appear in the activation seed, where no unit
                # exists yet and zero is the true count; only the scan is wrong.
                "anchor": '        "orphan_count": orphans,\n'
                '        "duplicate_callback_count": 0,\n        "collision_count": 0,',
                "replacement": '        "orphan_count": orphans,\n'
                '        "duplicate_callback_count": 0,\n'
                '        "collision_count": len(collisions),\n'
                '        "collisions": collisions,',
            },
        ),
    },
    {
        "change_id": "G2-CHANGE-005",
        "case_id": "H05-chain-detects-truncation",
        "hazard": "deleting the newest event leaves a chain that verifies clean",
        "route": "hash_chain_event + verify_chain",
        "disposition": "SUPERSEDE",
        "rationale": (
            "every event advances a durable chain-head pointer outside the event directory, so "
            "verification compares the chain it can see against the length it is supposed to have"
        ),
        "edits": (
            {
                "anchor": "    destination = event_directory / f\"{sequence:06d}-{state.lower()}.json\"\n"
                "    write_once(destination, canonical_json(body))\n"
                "    return destination",
                "replacement": "    destination = event_directory / f\"{sequence:06d}-{state.lower()}.json\"\n"
                "    write_once(destination, canonical_json(body))\n"
                "    # The pointer lives outside the event directory so that deleting events cannot\n"
                "    # also delete the record of how many there were, and so that nothing which\n"
                "    # globs the event directory mistakes it for an event.\n"
                "    replace_atomic(\n"
                '        CONTROL_ROOT / "chain-heads" / f"{task_id}.json",\n'
                "        canonical_json(\n"
                "            {\n"
                '                "chain_head_version": "PO03-CHAIN-HEAD-v1",\n'
                '                "task_id": task_id,\n'
                '                "sequence": sequence,\n'
                '                "event_sha256": sha256_file(destination),\n'
                '                "updated_at": body["observed_at"],\n'
                "            }\n"
                "        ),\n"
                "    )\n"
                "    return destination",
            },
            {
                "anchor": "        previous_hash = sha256_file(path)\n"
                '    if not events:\n        errors.append(f"task {task_id}: no events")\n'
                "    return errors",
                "replacement": "        previous_hash = sha256_file(path)\n"
                '    if not events:\n        errors.append(f"task {task_id}: no events")\n'
                "    errors.extend(verify_chain_head(task_id, events))\n"
                "    return errors\n"
                "\n"
                "\n"
                "def verify_chain_head(task_id: str, events: list[Path]) -> list[str]:\n"
                '    """Detect a chain that has been shortened rather than altered.\n'
                "\n"
                "    Walking the files that remain can only find tampering inside them.  Removing\n"
                "    the newest event leaves a shorter but internally consistent chain, so the\n"
                "    length and tip have to be checked against a pointer that the deletion did\n"
                "    not touch.\n"
                '    """\n'
                "    errors: list[str] = []\n"
                '    head_path = CONTROL_ROOT / "chain-heads" / f"{task_id}.json"\n'
                "    if not head_path.is_file():\n"
                "        return errors\n"
                "    head = read_json(head_path)\n"
                '    recorded_sequence = int(head.get("sequence", 0))\n'
                "    if recorded_sequence != len(events):\n"
                "        errors.append(\n"
                '            f"task {task_id}: chain truncated; the recorded head is sequence "\n'
                '            f"{recorded_sequence} but {len(events)} events remain"\n'
                "        )\n"
                '    elif events and head.get("event_sha256") != sha256_file(events[-1]):\n'
                "        errors.append(\n"
                '            f"task {task_id}: the latest event does not match the recorded chain head"\n'
                "        )\n"
                "    return errors",
            },
        ),
    },
    {
        "change_id": "G2-CHANGE-006",
        "case_id": "H06-locator-must-be-immutable",
        "hazard": "a receipt points at a mutable reference whose bytes can change after ingestion",
        "route": "read_object_bytes",
        "disposition": "SUPERSEDE",
        "rationale": (
            "the locator's revision must be a full Git object id, so git:HEAD and other movable "
            "references are refused instead of read"
        ),
        "edits": (
            {
                "anchor": '''    if not locator.startswith("git:"):
        raise ValueError(f"non-durable artifact locator: {locator}")
    revision_path = locator[len("git:") :]''',
                "replacement": '''    if not locator.startswith("git:"):
        raise ValueError(f"non-durable artifact locator: {locator}")
    revision_path = locator[len("git:") :]
    # "git:" alone is not durability.  HEAD, a branch or a tag all name bytes
    # that a later commit can change, which makes the read-back verification
    # recorded at ingestion time worthless.
    revision, separator, object_path = revision_path.partition(":")
    if not separator or not object_path:
        raise ValueError(f"artifact locator must be git:<object-id>:<path>: {locator}")
    require_git_object_id(revision, f"artifact locator revision in {locator}")''',
            },
        ),
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def measured_failures(measurement: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(measurement.read_text(encoding="utf-8"))
    return {
        record["case_id"]: record
        for record in payload["records"]
        if record["outcome"] != "PASS"
    }


def apply_patches(source: str, failures: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    applied: list[dict[str, Any]] = []
    text = source
    for patch in PATCHES:
        case_id = patch["case_id"]
        if case_id not in failures:
            raise ValueError(
                f"{patch['change_id']} claims to fix {case_id}, which is not a measured G1 failure; "
                "a successor change must trace to a failure that was actually observed"
            )
        edits: list[dict[str, Any]] = []
        for edit in patch["edits"]:
            anchor = edit["anchor"]
            occurrences = text.count(anchor)
            if occurrences != 1:
                raise ValueError(
                    f"{patch['change_id']}: anchor matched {occurrences} times, expected exactly one:\n"
                    f"{anchor[:200]}"
                )
            text = text.replace(anchor, edit["replacement"], 1)
            edits.append(
                {
                    "anchor_sha256": sha256_bytes(anchor.encode("utf-8")),
                    "anchor_bytes": len(anchor.encode("utf-8")),
                    "replacement_sha256": sha256_bytes(edit["replacement"].encode("utf-8")),
                    "replacement_bytes": len(edit["replacement"].encode("utf-8")),
                    "anchor_excerpt": anchor.splitlines()[0][:120],
                }
            )
        failure = failures[case_id]
        applied.append(
            {
                "change_id": patch["change_id"],
                "disposition": patch["disposition"],
                "route": patch["route"],
                "rationale": patch["rationale"],
                "motivating_failure": {
                    "case_id": case_id,
                    "suite": failure["suite"],
                    "hazard": patch["hazard"],
                    "g1_outcome": failure["outcome"],
                    "g1_reported_success": failure["reports_success"],
                    "g1_observed_detail": failure["detail"],
                },
                "edits": edits,
                "edit_count": len(edits),
            }
        )
    return text, applied


def build(repo: Path, g1_source: Path, measurement: Path, destination: Path, *, write: bool) -> dict[str, Any]:
    failures = measured_failures(measurement)
    g1_bytes = g1_source.read_bytes()
    g2_text, applied = apply_patches(g1_bytes.decode("utf-8"), failures)
    g2_bytes = g2_text.encode("utf-8")
    compile(g2_text, destination.name, "exec")

    if write:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(g2_bytes)

    on_disk = destination.read_bytes() if destination.is_file() else b""
    covered = {entry["motivating_failure"]["case_id"] for entry in applied}
    return {
        "lineage_version": LINEAGE_VERSION,
        "built_at": utc_now(),
        "generation": "G2",
        "definition": "G1 plus one patch per measured G1 failure, with no other change",
        "staged_for_controller_path": STAGED_FOR,
        "staged_note": "this unit stages the package in its own subtree; the controller owns successor/g2/",
        "parent": {
            "generation": "G1",
            "source": g1_source.as_posix(),
            "sha256": sha256_bytes(g1_bytes),
            "bytes": len(g1_bytes),
        },
        "measured_failures_read_from": {
            "path": measurement.as_posix(),
            "sha256": sha256_bytes(measurement.read_bytes()),
            "failure_case_ids": sorted(failures),
            "failure_count": len(failures),
        },
        "changes": applied,
        "change_count": len(applied),
        "coverage": {
            "failures_addressed": sorted(covered),
            "failures_not_addressed": sorted(set(failures) - covered),
            "every_measured_failure_has_a_change": not (set(failures) - covered),
        },
        "successor": {
            "path": destination.as_posix(),
            "present": destination.is_file(),
            "sha256": sha256_bytes(on_disk) if on_disk else None,
            "bytes": len(on_disk),
            "matches_build": on_disk == g2_bytes,
            "compiles": True,
            "bytes_added_over_parent": len(g2_bytes) - len(g1_bytes),
        },
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--g1-source", required=True)
    parser.add_argument("--g1-measurement", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    record = build(
        Path(args.repo_root).resolve(),
        Path(args.g1_source).resolve(),
        Path(args.g1_measurement).resolve(),
        Path(args.destination).resolve(),
        write=args.write,
    )
    Path(args.out).write_bytes(canonical(record))
    print(json.dumps(record, indent=2, sort_keys=True))
    if not record["successor"]["matches_build"]:
        print("BUILD FAILED: the committed successor is not the build output", file=sys.stderr)
        return 1
    if not record["coverage"]["every_measured_failure_has_a_change"]:
        print(
            "BUILD INCOMPLETE: measured failures without a change: "
            + ", ".join(record["coverage"]["failures_not_addressed"]),
            file=sys.stderr,
        )
        return 1
    print(
        f"G2 BUILT: {record['change_count']} changes over G1 "
        f"({record['successor']['bytes_added_over_parent']:+d} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
