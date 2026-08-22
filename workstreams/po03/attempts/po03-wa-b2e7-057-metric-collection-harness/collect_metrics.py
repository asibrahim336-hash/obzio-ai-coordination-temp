#!/usr/bin/env python3
"""Metric collection harness for the PO-03 Wave A counted units.

The harness reads the frozen metric definitions and the append-only control
ledger, then emits exactly one row per counted work unit.  Every emitted value
is traced to durable bytes: an immutable task capsule, a hash-chained event, a
committed result document, or a Git object read back by object id.

Where no durable source exposes a value the harness emits the frozen
``NOT_SUPPORTED`` sentinel and records the exact observed boundary, including
the key census that was actually executed against the ledger corpus.  The
harness never substitutes a default, a zero or a guess for a missing value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_VERSION = "PO03-METRIC-COLLECTION-v1"
UNSUPPORTED = "NOT_SUPPORTED"
COUNTED_WAVE = "A"

REASON_PROVIDER_NO_EXPOSURE = "PROVIDER_NO_EXPOSURE"
REASON_NOT_YET_OBSERVED = "NOT_YET_OBSERVED"
REASON_OBSERVED_SENTINEL = "OBSERVED_VALUE_IS_THE_SENTINEL"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

# Ledger inputs the harness is allowed to treat as durable measurement sources.
DEFINITIONS_PATH = "workstreams/po03/metrics/metric-definitions.json"
CRITERIA_PATH = "workstreams/po03/evidence/criteria-freeze.json"
REGISTRY_PATH = "workstreams/po03/control/work-unit-registry.jsonl"
TASKS_ROOT = "workstreams/po03/control/tasks"
EVENTS_ROOT = "workstreams/po03/control/events"

RECOVERY_EVENT_STATES = {"RECOVERY_REQUIRED", "RETRY_SCHEDULED"}
PROVIDER_BLOCK_STATES = {"FAILED_TERMINAL", "CANCELLED", "PROVIDER_COMPLETED_UNCOMMITTED"}
CONTROLLER_ACTORS = {"integration-controller", "coordinator"}
FOUNDER_ACTOR_RE = re.compile(r"founder|owner|principal", re.IGNORECASE)

# Operational definition and durable source for every frozen required field.
# ``kind`` is MEASURED when a durable byte source exists, PROVIDER_UNSUPPORTED
# when no source in this runtime can expose the value at all, and OBSERVED_OR_
# ABSENT when the value exists only once a subordinate has committed a result.
FIELD_SOURCES: dict[str, dict[str, str]] = {
    "task_id": {
        "kind": "MEASURED",
        "operational_definition": "The counted unit's task id as recorded by the CREATED registry line.",
        "durable_source": REGISTRY_PATH,
    },
    "parent_id": {
        "kind": "MEASURED",
        "operational_definition": "controller_run_id recorded in the immutable task capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "function": {
        "kind": "MEASURED",
        "operational_definition": "function recorded in the immutable task capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "runtime": {
        "kind": "MEASURED",
        "operational_definition": "runtime.route recorded in the immutable task capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "exact_model": {
        "kind": "MEASURED",
        "operational_definition": "runtime.exact_model recorded in the immutable task capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "reasoning": {
        "kind": "MEASURED",
        "operational_definition": "runtime.reasoning_control recorded in the immutable task capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "prompt_sha256": {
        "kind": "MEASURED",
        "operational_definition": "sha256 of the UTF-8 bytes of task_prompt in the immutable capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "source_sha256": {
        "kind": "MEASURED",
        "operational_definition": (
            "sha256 of workstreams/po03/evidence/source-lock.json read by Git object id at the "
            "capsule's controller_head_sha."
        ),
        "durable_source": "git:<controller_head_sha>:workstreams/po03/evidence/source-lock.json",
    },
    "context_sha256": {
        "kind": "MEASURED",
        "operational_definition": (
            "sha256 over the concatenated frozen context bundle: capsule input.json bytes, "
            "acceptance.json bytes, metric-definitions.json bytes, criteria-freeze.json bytes."
        ),
        "durable_source": TASKS_ROOT + "/<task_id>/{input,acceptance}.json + " + DEFINITIONS_PATH + " + " + CRITERIA_PATH,
    },
    "available_tokens": {
        "kind": "PROVIDER_UNSUPPORTED",
        "operational_definition": "Per-attempt token budget or token consumption exposed by the provider.",
        "durable_source": "NONE",
    },
    "available_cost": {
        "kind": "PROVIDER_UNSUPPORTED",
        "operational_definition": "Per-attempt monetary cost or cost budget exposed by the provider.",
        "durable_source": "NONE",
    },
    "queue_ms": {
        "kind": "PROVIDER_UNSUPPORTED",
        "operational_definition": "Milliseconds between dispatch enqueue and provider start.",
        "durable_source": "NONE",
    },
    "active_ms": {
        "kind": "PROVIDER_UNSUPPORTED",
        "operational_definition": "Provider-side active compute milliseconds for the attempt.",
        "durable_source": "NONE",
    },
    "wall_ms": {
        "kind": "OBSERVED_OR_ABSENT",
        "operational_definition": (
            "Durable-custody wall interval in milliseconds: committer timestamp of the observed "
            "artifact commit minus the capsule created_at timestamp. This is a custody interval "
            "measured from Git and capsule bytes, not provider active time."
        ),
        "durable_source": "git commit committer timestamp of the observed result_commit_id",
    },
    "review_ms": {
        "kind": "PROVIDER_UNSUPPORTED",
        "operational_definition": "Milliseconds an independent non-producer reviewer spent on the unit.",
        "durable_source": "NONE",
    },
    "checkpoint_count": {
        "kind": "OBSERVED_OR_ABSENT",
        "operational_definition": "attempt.checkpoint_seq in the observed committed result document.",
        "durable_source": "<result_slot>/result.json on an observed ref",
    },
    "retry_count": {
        "kind": "MEASURED",
        "operational_definition": "transaction.attempt_number minus one, from the immutable capsule.",
        "durable_source": TASKS_ROOT + "/<task_id>/input.json",
    },
    "result_commit_id": {
        "kind": "OBSERVED_OR_ABSENT",
        "operational_definition": "result_transaction.result_commit_id in the observed committed result document.",
        "durable_source": "<result_slot>/result.json on an observed ref",
    },
    "readback_state": {
        "kind": "MEASURED",
        "operational_definition": (
            "Outcome of this harness reading every artifact of the observed result back by Git "
            "object id and comparing sha256 and byte count: VERIFIED, MISMATCH, UNREADABLE or "
            "NO_RESULT_OBSERVED."
        ),
        "durable_source": "git cat-file blob <content_uri>",
    },
    "first_pass_outcome": {
        "kind": "OBSERVED_OR_ABSENT",
        "operational_definition": "verdict recorded in the observed artifact manifest for attempt 1.",
        "durable_source": "<result_slot>/manifest.json on an observed ref",
    },
    "independent_disposition": {
        "kind": "OBSERVED_OR_ABSENT",
        "operational_definition": "independent_acceptance.state in the observed committed result document.",
        "durable_source": "<result_slot>/result.json on an observed ref",
    },
    "defect_count": {
        "kind": "MEASURED",
        "operational_definition": (
            "Number of durable verification defects this harness observed for the unit: artifact "
            "read-back mismatches, unreadable artifact locators, result-contract violations and "
            "manifest/result disagreements."
        ),
        "durable_source": "computed by this harness from observed committed bytes",
    },
    "rework_count": {
        "kind": "MEASURED",
        "operational_definition": (
            "Distinct attempts observed for the unit minus one, counted from capsule attempt_number "
            "and any INGESTION registry lines for the unit."
        ),
        "durable_source": REGISTRY_PATH + " + " + TASKS_ROOT + "/<task_id>/input.json",
    },
    "founder_action_count": {
        "kind": "MEASURED",
        "operational_definition": "Hash-chained events for the unit whose actor is a founder or owner.",
        "durable_source": EVENTS_ROOT + "/<task_id>/*.json",
    },
    "provider_block": {
        "kind": "MEASURED",
        "operational_definition": (
            "Provider-block states present in the unit's hash-chained event log "
            "(FAILED_TERMINAL, CANCELLED, PROVIDER_COMPLETED_UNCOMMITTED), or NONE_OBSERVED."
        ),
        "durable_source": EVENTS_ROOT + "/<task_id>/*.json",
    },
    "collision_count": {
        "kind": "MEASURED",
        "operational_definition": (
            "Number of other counted units whose registered owned_paths prefix-overlap this unit's "
            "owned_paths."
        ),
        "durable_source": REGISTRY_PATH,
    },
    "recovery_events": {
        "kind": "MEASURED",
        "operational_definition": "Hash-chained events for the unit in state RECOVERY_REQUIRED or RETRY_SCHEDULED.",
        "durable_source": EVENTS_ROOT + "/<task_id>/*.json",
    },
}

# Key-name probes proving that no durable source in the corpus exposes the value.
PROBES: dict[str, list[str]] = {
    "available_tokens": [r"token"],
    "available_cost": [r"cost", r"price", r"usd", r"spend"],
    "queue_ms": [r"queue", r"dispatch(ed)?_at", r"enqueue"],
    "active_ms": [r"active", r"elapsed", r"duration"],
    "review_ms": [r"review"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_text(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments), cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout


def git_bytes(repo: Path, *arguments: str) -> bytes | None:
    completed = subprocess.run(("git", *arguments), cwd=repo, capture_output=True)
    if completed.returncode != 0:
        return None
    return completed.stdout


def read_blob(repo: Path, revision: str, path: str) -> bytes | None:
    return git_bytes(repo, "cat-file", "blob", f"{revision}:{path}")


def commit_epoch(repo: Path, commit: str) -> int | None:
    raw = git_bytes(repo, "show", "-s", "--format=%ct", commit)
    if raw is None:
        return None
    text = raw.decode("utf-8").strip()
    return int(text) if text.isdigit() else None


def capsule_epoch(created_at: str) -> int | None:
    try:
        return int(datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def load_json_path(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def all_keys(value: Any, into: set[str]) -> set[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            into.add(key)
            all_keys(item, into)
    elif isinstance(value, list):
        for item in value:
            all_keys(item, into)
    return into


def counted_units(repo: Path) -> list[dict[str, Any]]:
    """Return the CREATED registry lines for the counted wave, in ledger order."""
    lines = (repo / REGISTRY_PATH).read_text(encoding="utf-8").splitlines()
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("registry_event") != "CREATED" or entry.get("wave") != COUNTED_WAVE:
            continue
        task_id = entry["task_id"]
        if task_id in seen:
            continue
        seen.add(task_id)
        units.append(entry)
    return units


def registry_lines(repo: Path) -> list[dict[str, Any]]:
    out = []
    for line in (repo / REGISTRY_PATH).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def scan_refs(repo: Path, patterns: tuple[str, ...]) -> list[dict[str, str]]:
    """List the refs that will be searched for committed subordinate results."""
    refs: list[dict[str, str]] = []
    listing = git_text(repo, "for-each-ref", "--format=%(refname)%09%(objectname)", *patterns)
    for line in listing.splitlines():
        if not line.strip():
            continue
        name, _, sha = line.partition("\t")
        remote = name.startswith("refs/remotes/")
        refs.append(
            {
                "ref": name,
                "commit": sha.strip(),
                "ref_class": "PUSHED_REMOTE_TRACKING" if remote else "LOCAL_HEAD",
            }
        )
    # Pushed remote-tracking refs are preferred evidence: they are durable outside
    # this checkout, so a local head is only consulted when no remote ref carries
    # the unit's result.
    return sorted(refs, key=lambda item: (item["ref_class"] != "PUSHED_REMOTE_TRACKING", item["ref"]))


def event_chain(repo: Path, task_id: str) -> list[dict[str, Any]]:
    directory = repo / EVENTS_ROOT / task_id
    if not directory.is_dir():
        return []
    return [load_json_path(path) for path in sorted(directory.glob("*.json"))]


def owned_path_overlap(units: list[dict[str, Any]]) -> dict[str, int]:
    """Count registered owned-path overlaps between counted units."""
    normalised: list[tuple[str, list[str]]] = []
    for unit in units:
        paths = [path.rstrip("*").rstrip("/") for path in unit.get("owned_paths", [])]
        normalised.append((unit["task_id"], paths))
    counts = {task_id: 0 for task_id, _ in normalised}
    for index, (task_a, paths_a) in enumerate(normalised):
        for task_b, paths_b in normalised[index + 1 :]:
            overlap = any(
                a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in paths_a for b in paths_b
            )
            if overlap:
                counts[task_a] += 1
                counts[task_b] += 1
    return counts


def index_refs(repo: Path, refs: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Index every attempt-subtree path present on each scanned ref.

    One tree listing per ref replaces a per-unit probe, so the scan cost is
    linear in refs rather than refs multiplied by counted units.
    """
    index: dict[str, list[dict[str, str]]] = {}
    for ref in refs:
        listing = git_bytes(
            repo, "ls-tree", "-r", "--name-only", "-z", ref["commit"], "--", "workstreams/po03/attempts/"
        )
        if listing is None:
            continue
        for path in listing.decode("utf-8").split("\0"):
            if path:
                index.setdefault(path, []).append(ref)
    return index


def find_observed_result(
    repo: Path, index: dict[str, list[dict[str, str]]], slot: str
) -> dict[str, Any] | None:
    """Locate the first committed result document for a slot across scanned refs."""
    for ref in index.get(f"{slot}/result.json", []):
        result_raw = read_blob(repo, ref["commit"], f"{slot}/result.json")
        if result_raw is None:
            continue
        manifest_raw = read_blob(repo, ref["commit"], f"{slot}/manifest.json")
        try:
            result = json.loads(result_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "ref": ref["ref"],
                "ref_commit": ref["commit"],
                "result": None,
                "manifest": None,
                "parse_error": str(exc),
            }
        manifest = None
        if manifest_raw is not None:
            try:
                manifest = json.loads(manifest_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                manifest = None
        return {
            "ref": ref["ref"],
            "ref_commit": ref["commit"],
            "ref_class": ref["ref_class"],
            "result": result,
            "manifest": manifest,
            "parse_error": None,
        }
    return None


def verify_readback(repo: Path, result: dict[str, Any]) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Read every artifact back by Git object id and report the measured outcome."""
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return "MISMATCH", ["result carries no artifacts"], []
    defects: list[str] = []
    records: list[dict[str, Any]] = []
    unreadable = False
    mismatched = False
    for artifact in artifacts:
        locator = artifact.get("content_uri", "")
        if not isinstance(locator, str) or not locator.startswith("git:"):
            defects.append(f"{artifact.get('artifact_id')}: non-durable locator {locator!r}")
            unreadable = True
            continue
        revision_path = locator[len("git:") :]
        observed = git_bytes(repo, "cat-file", "blob", revision_path)
        if observed is None:
            defects.append(f"{artifact.get('artifact_id')}: locator unreadable in this clone")
            unreadable = True
            continue
        observed_sha = sha256_bytes(observed)
        matched = observed_sha == artifact.get("sha256") and len(observed) == artifact.get("bytes")
        if not matched:
            mismatched = True
            defects.append(
                f"{artifact.get('artifact_id')}: read-back mismatch sha256={observed_sha} bytes={len(observed)}"
            )
        records.append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "locator": locator,
                "expected_sha256": artifact.get("sha256"),
                "observed_sha256": observed_sha,
                "expected_bytes": artifact.get("bytes"),
                "observed_bytes": len(observed),
                "match": matched,
            }
        )
    if mismatched:
        return "MISMATCH", defects, records
    if unreadable:
        return "UNREADABLE", defects, records
    return "VERIFIED", defects, records


def key_census(repo: Path, units: list[dict[str, Any]], observed: dict[str, Any]) -> dict[str, Any]:
    """Measure whether any key in the durable corpus could carry an unsupported field."""
    keys: set[str] = set()
    capsule_count = 0
    event_count = 0
    result_count = 0
    for unit in units:
        task_id = unit["task_id"]
        for name in ("input.json", "acceptance.json", "transaction-created.json"):
            path = repo / TASKS_ROOT / task_id / name
            if path.is_file():
                all_keys(load_json_path(path), keys)
                capsule_count += 1
        for event in event_chain(repo, task_id):
            all_keys(event, keys)
            event_count += 1
        record = observed.get(task_id)
        if record and record.get("result") is not None:
            all_keys(record["result"], keys)
            result_count += 1
            if record.get("manifest") is not None:
                all_keys(record["manifest"], keys)
    census = {
        "documents_scanned": {
            "capsule_documents": capsule_count,
            "event_documents": event_count,
            "observed_result_documents": result_count,
        },
        "distinct_key_names": len(keys),
        "matches": {},
    }
    for field, patterns in PROBES.items():
        hits = sorted(
            key for key in keys if any(re.search(pattern, key, re.IGNORECASE) for pattern in patterns)
        )
        census["matches"][field] = {"patterns": patterns, "matching_keys": hits, "hit_count": len(hits)}
    return census


def provider_boundary(field: str, census: dict[str, Any], refs: list[dict[str, str]], observed_at: str) -> str:
    probe = census["matches"][field]
    scanned = census["documents_scanned"]
    return (
        f"No durable source in this runtime exposes {field}. Executed key census over "
        f"{scanned['capsule_documents']} immutable capsule documents, {scanned['event_documents']} "
        f"hash-chained event documents and {scanned['observed_result_documents']} observed committed "
        f"result documents across {len(refs)} scanned refs at {observed_at}: patterns "
        f"{probe['patterns']} matched {probe['hit_count']} of {census['distinct_key_names']} distinct key "
        f"names (matching keys: {probe['matching_keys']}). The Cursor provider exposes no usage or "
        f"timing API to a repository-side harness in this runtime, and the harness refuses to "
        f"substitute a default."
    )


def build_rows(repo: Path, required_fields: list[str]) -> dict[str, Any]:
    observed_at = utc_now()
    units = counted_units(repo)
    ledger = registry_lines(repo)
    refs = scan_refs(repo, ("refs/heads", "refs/remotes/origin"))
    collisions = owned_path_overlap(units)

    definitions_bytes = (repo / DEFINITIONS_PATH).read_bytes()
    criteria_bytes = (repo / CRITERIA_PATH).read_bytes()

    index = index_refs(repo, refs)
    observed: dict[str, Any] = {}
    for unit in units:
        observed[unit["task_id"]] = find_observed_result(repo, index, unit["result_slot"])

    census = key_census(repo, units, observed)

    rows: list[dict[str, Any]] = []
    row_boundaries: list[dict[str, Any]] = []
    readback_records: dict[str, Any] = {}

    for unit in units:
        task_id = unit["task_id"]
        capsule_path = repo / TASKS_ROOT / task_id / "input.json"
        acceptance_path = repo / TASKS_ROOT / task_id / "acceptance.json"
        capsule_bytes = capsule_path.read_bytes()
        capsule = json.loads(capsule_bytes.decode("utf-8"))
        acceptance_bytes = acceptance_path.read_bytes()
        events = event_chain(repo, task_id)
        record = observed.get(task_id)

        source_lock = read_blob(
            repo, capsule["controller_head_sha"], "workstreams/po03/evidence/source-lock.json"
        )
        context_sha = sha256_bytes(capsule_bytes + acceptance_bytes + definitions_bytes + criteria_bytes)

        defects: list[str] = []
        if record is None:
            readback_state = "NO_RESULT_OBSERVED"
            result = None
            manifest = None
        elif record.get("result") is None:
            readback_state = "UNREADABLE"
            defects.append(f"result document unparseable: {record.get('parse_error')}")
            result = None
            manifest = None
        else:
            result = record["result"]
            manifest = record["manifest"]
            readback_state, readback_defects, records = verify_readback(repo, result)
            defects.extend(readback_defects)
            readback_records[task_id] = {
                "ref": record["ref"],
                "ref_commit": record["ref_commit"],
                "ref_class": record.get("ref_class"),
                "artifacts": records,
            }
            if manifest is None:
                defects.append("manifest.json absent or unparseable beside a committed result")
            else:
                if manifest.get("task_id") != result.get("task_id"):
                    defects.append("manifest/result task_id disagreement")
                if manifest.get("artifact_count") != result.get("result_transaction", {}).get("artifact_count"):
                    defects.append("manifest/result artifact_count disagreement")
            if result.get("obzio_state") == "COMPLETED":
                defects.append("subordinate result asserts COMPLETED, which only the coordinator may set")

        ingestion_lines = [
            entry
            for entry in ledger
            if entry.get("task_id") == task_id and entry.get("registry_event") == "INGESTION"
        ]
        attempt_number = int(capsule["transaction"]["attempt_number"])
        attempts_observed = max([attempt_number] + [1 for _ in ingestion_lines])
        founder_actions = sum(
            1
            for event in events
            if FOUNDER_ACTOR_RE.search(str(event.get("actor", "")))
            and str(event.get("actor")) not in CONTROLLER_ACTORS
        )
        recovery_events = sum(1 for event in events if event.get("state") in RECOVERY_EVENT_STATES)
        blocks = sorted({event["state"] for event in events if event.get("state") in PROVIDER_BLOCK_STATES})

        wall_ms: Any = UNSUPPORTED
        result_commit_id: Any = UNSUPPORTED
        checkpoint_count: Any = UNSUPPORTED
        first_pass_outcome: Any = UNSUPPORTED
        independent_disposition: Any = UNSUPPORTED

        if result is not None:
            commit_id = result.get("result_transaction", {}).get("result_commit_id")
            if isinstance(commit_id, str) and GIT_OBJECT_RE.fullmatch(commit_id):
                result_commit_id = commit_id
                committed_epoch = commit_epoch(repo, commit_id)
                created_epoch = capsule_epoch(capsule["created_at"])
                if committed_epoch is not None and created_epoch is not None:
                    wall_ms = (committed_epoch - created_epoch) * 1000
                else:
                    row_boundaries.append(
                        {
                            "task_id": task_id,
                            "field": "wall_ms",
                            "reason_class": REASON_NOT_YET_OBSERVED,
                            "boundary": (
                                f"result_commit_id {commit_id} is not resolvable to a committer timestamp "
                                f"in this clone at {observed_at}; no interval was invented."
                            ),
                        }
                    )
            else:
                defects.append(f"result_commit_id is not a Git object id: {commit_id!r}")
                row_boundaries.append(
                    {
                        "task_id": task_id,
                        "field": "result_commit_id",
                        "reason_class": REASON_NOT_YET_OBSERVED,
                        "boundary": (
                            f"observed result document on {record['ref']} carries "
                            f"result_commit_id={commit_id!r}, which is not a Git object id."
                        ),
                    }
                )
                row_boundaries.append(
                    {
                        "task_id": task_id,
                        "field": "wall_ms",
                        "reason_class": REASON_NOT_YET_OBSERVED,
                        "boundary": "no resolvable artifact commit, so no custody interval was measured.",
                    }
                )
            sequence = result.get("attempt", {}).get("checkpoint_seq")
            if isinstance(sequence, int):
                checkpoint_count = sequence
            disposition = result.get("independent_acceptance", {}).get("state")
            if isinstance(disposition, str) and disposition.strip():
                independent_disposition = disposition
            if manifest is not None and isinstance(manifest.get("verdict"), str) and attempt_number == 1:
                first_pass_outcome = manifest["verdict"]
                if first_pass_outcome == UNSUPPORTED:
                    # The producer's own recorded verdict is the sentinel string.  The
                    # cell is reported as observed rather than as a collection gap.
                    row_boundaries.append(
                        {
                            "task_id": task_id,
                            "field": "first_pass_outcome",
                            "reason_class": REASON_OBSERVED_SENTINEL,
                            "boundary": (
                                f"the observed artifact manifest at {record['ref']}:"
                                f"{unit['result_slot']}/manifest.json records verdict "
                                f"\"{UNSUPPORTED}\" as the producer's own first-pass verdict; the "
                                f"harness reports the recorded verdict verbatim and invents nothing."
                            ),
                        }
                    )
            elif manifest is None:
                row_boundaries.append(
                    {
                        "task_id": task_id,
                        "field": "first_pass_outcome",
                        "reason_class": REASON_NOT_YET_OBSERVED,
                        "boundary": (
                            f"a result document exists on {record['ref']} but no parseable manifest.json "
                            f"records a first-pass verdict."
                        ),
                    }
                )
        else:
            absent_boundary = (
                f"no result document existed under {unit['result_slot']} on any of the "
                f"{len(refs)} refs scanned at {observed_at}; the unit had not committed a result when "
                f"this harness ran."
            )
            for field in (
                "wall_ms",
                "checkpoint_count",
                "result_commit_id",
                "first_pass_outcome",
                "independent_disposition",
            ):
                row_boundaries.append(
                    {
                        "task_id": task_id,
                        "field": field,
                        "reason_class": REASON_NOT_YET_OBSERVED,
                        "boundary": absent_boundary,
                    }
                )

        row = {
            "task_id": task_id,
            "parent_id": capsule["controller_run_id"],
            "function": capsule["function"],
            "runtime": capsule["runtime"]["route"],
            "exact_model": capsule["runtime"]["exact_model"],
            "reasoning": capsule["runtime"]["reasoning_control"],
            "prompt_sha256": sha256_bytes(capsule["task_prompt"].encode("utf-8")),
            "source_sha256": sha256_bytes(source_lock) if source_lock is not None else UNSUPPORTED,
            "context_sha256": context_sha,
            "available_tokens": UNSUPPORTED,
            "available_cost": UNSUPPORTED,
            "queue_ms": UNSUPPORTED,
            "active_ms": UNSUPPORTED,
            "wall_ms": wall_ms,
            "review_ms": UNSUPPORTED,
            "checkpoint_count": checkpoint_count,
            "retry_count": attempt_number - 1,
            "result_commit_id": result_commit_id,
            "readback_state": readback_state,
            "first_pass_outcome": first_pass_outcome,
            "independent_disposition": independent_disposition,
            "defect_count": len(defects),
            "rework_count": attempts_observed - 1,
            "founder_action_count": founder_actions,
            "provider_block": "NONE_OBSERVED" if not blocks else ",".join(blocks),
            "collision_count": collisions[task_id],
            "recovery_events": recovery_events,
        }
        if source_lock is None:
            row_boundaries.append(
                {
                    "task_id": task_id,
                    "field": "source_sha256",
                    "reason_class": REASON_NOT_YET_OBSERVED,
                    "boundary": (
                        f"workstreams/po03/evidence/source-lock.json is not readable at capsule "
                        f"controller_head_sha {capsule['controller_head_sha']} in this clone."
                    ),
                }
            )
        missing = [field for field in required_fields if field not in row]
        extra = [field for field in row if field not in required_fields]
        if missing or extra:
            raise ValueError(f"{task_id}: row field mismatch missing={missing} extra={extra}")
        rows.append({field: row[field] for field in required_fields})

    field_boundaries = [
        {
            "field": field,
            "reason_class": REASON_PROVIDER_NO_EXPOSURE,
            "boundary": provider_boundary(field, census, refs, observed_at),
        }
        for field, spec in FIELD_SOURCES.items()
        if spec["kind"] == "PROVIDER_UNSUPPORTED"
    ]

    return {
        "observed_at": observed_at,
        "rows": rows,
        "boundaries": {
            "boundaries_version": "PO03-METRIC-BOUNDARIES-v1",
            "unsupported_value": UNSUPPORTED,
            "observed_at": observed_at,
            "scanned_refs": refs,
            "key_census": census,
            "field_level": field_boundaries,
            "row_level": row_boundaries,
        },
        "field_source_registry": {
            "registry_version": "PO03-METRIC-FIELD-SOURCES-v1",
            "harness_version": HARNESS_VERSION,
            "metrics_version": json.loads(definitions_bytes.decode("utf-8"))["metrics_version"],
            "metric_definitions_sha256": sha256_bytes(definitions_bytes),
            "criteria_freeze_sha256": sha256_bytes(criteria_bytes),
            "fields": FIELD_SOURCES,
            "decision_changed": [],
        },
        "readback": {
            "readback_version": "PO03-METRIC-READBACK-v1",
            "observed_at": observed_at,
            "units": readback_records,
        },
    }


def render_report(payload: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    rows = payload["rows"]
    per_field = {}
    for field in required_fields:
        unsupported = sum(1 for row in rows if row[field] == UNSUPPORTED)
        per_field[field] = {
            "rows": len(rows),
            "not_supported": unsupported,
            "measured": len(rows) - unsupported,
        }
    return {
        "report_version": "PO03-METRIC-COLLECTION-REPORT-v1",
        "harness_version": HARNESS_VERSION,
        "observed_at": payload["observed_at"],
        "row_count": len(rows),
        "field_count": len(required_fields),
        "not_supported_cells": sum(1 for row in rows for field in required_fields if row[field] == UNSUPPORTED),
        "total_cells": len(rows) * len(required_fields),
        "per_field": per_field,
        "readback_states": {
            state: sum(1 for row in rows if row["readback_state"] == state)
            for state in sorted({row["readback_state"] for row in rows})
        },
        "scanned_ref_count": len(payload["boundaries"]["scanned_refs"]),
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    definitions = load_json_path(repo / DEFINITIONS_PATH)
    required_fields = list(definitions["required_fields"])

    payload = build_rows(repo, required_fields)
    report = render_report(payload, required_fields)

    (out / "work-unit-runs.jsonl").write_bytes(b"".join(canonical(row) for row in payload["rows"]))
    (out / "not-supported-boundaries.json").write_bytes(canonical(payload["boundaries"]))
    (out / "field-source-registry.json").write_bytes(canonical(payload["field_source_registry"]))
    (out / "artifact-readback.json").write_bytes(canonical(payload["readback"]))
    (out / "collection-report.json").write_bytes(canonical(report))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
