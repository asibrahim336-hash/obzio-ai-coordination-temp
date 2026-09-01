#!/usr/bin/env python3
"""Independent verifier for CUR-ORCH-QUAL-01.

This verifier intentionally does not import the producer's orchqual.py or
scctl.py for its substantive checks.  The producer implementation is invoked
only in two labelled adversarial probes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


MANIFEST = Path("receipts/so02/2026-08-22/cur-orch-qual-01/EVIDENCE-MANIFEST.json")
BUNDLE = MANIFEST.parent
QUALIFICATION = Path("workstreams/so02/control-plane/state/CUR-ORCH-QUAL-01.json")
CAPACITY = Path(
    "workstreams/so02/control-plane/state/"
    "PO03-CAPACITY-OBSERVATION-CUR-ORCH-QUAL-01.json"
)
EVENTS = Path("workstreams/so02/control-plane/state/events.jsonl")
PRODUCER_VERIFIER = Path("workstreams/so02/control-plane/tools/orchqual.py")
READBACK = BUNDLE / "REMOTE-READBACK.json"

MATERIAL_REFERENCES = {
    Path(".github/workflows/so02-control-plane-contracts.yml"),
    BUNDLE / "CLEAN-CLONE-REPLAY-RECEIPT.json",
    BUNDLE / "REMOTE-READBACK.json",
    BUNDLE / "TERMINAL-RECONCILIATION.json",
    QUALIFICATION,
    CAPACITY,
    Path("workstreams/so02/control-plane/state/RUNTIME-MODEL-CAPABILITY-REGISTER.json"),
    Path("workstreams/so02/control-plane/state/control-plane.json"),
    Path("workstreams/so02/control-plane/state/events.jsonl"),
    Path("workstreams/so02/control-plane/state/runtime-surface-locators.json"),
    Path("workstreams/so02/control-plane/tests/test_orchqual.py"),
    PRODUCER_VERIFIER,
}

PROTECTED_EXACT = {
    "main",
    "so02/strategic-control-plane-migration-20260822-v001",
    "po03/repository-engineering-portable-runtime-20260822-v001",
    "soo/v003-currentness-repair-20260820",
    "soo/v003-controlling-pointer-and-part-manifest-repair-20260820",
}
PROTECTED_PREFIXES = ("cursor/po03-",)
INTERFERENCE_STATES = {
    "QUEUED",
    "PAUSED",
    "EVICTED",
    "ADMISSION_REFUSED",
    "KILLED",
    "PENDING",
    "ERROR",
}
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "credential",
    "key",
    "password",
    "secret",
    "signature",
    "sig",
    "token",
}
SECRET_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "github_pat_", "sk-")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=text,
    )


def git_bytes(repo: Path, revision_path: str) -> bytes:
    completed = run(["git", "show", revision_path], cwd=repo, text=False)
    if completed.returncode != 0:
        raise RuntimeError(f"git show failed for {revision_path}")
    return completed.stdout


def manifest_check(root: Path) -> dict[str, Any]:
    manifest = read_json(root / MANIFEST)
    entries = manifest.get("entries", [])
    entry_paths = [entry["path"] for entry in entries]
    duplicates = sorted({path for path in entry_paths if entry_paths.count(path) > 1})
    mismatches: list[dict[str, Any]] = []
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file():
            mismatches.append({"path": entry["path"], "reason": "absent"})
            continue
        content = path.read_bytes()
        observed_hash = sha256_bytes(content)
        if observed_hash != entry.get("sha256") or len(content) != entry.get("size_bytes"):
            mismatches.append(
                {
                    "path": entry["path"],
                    "reason": "hash_or_size_mismatch",
                    "observed_sha256": observed_hash,
                    "observed_size": len(content),
                }
            )

    observed_bundle = {
        path.relative_to(root).as_posix()
        for path in (root / BUNDLE).rglob("*")
        if path.is_file()
    }
    manifested = set(entry_paths)
    manifest_self = MANIFEST.as_posix()
    unmanifested_bundle = sorted(observed_bundle - manifested - {manifest_self})
    material_uncovered = sorted(
        path.as_posix()
        for path in MATERIAL_REFERENCES
        if (root / path).is_file() and path.as_posix() not in manifested
    )
    computed_bundle = sha256_bytes(canonical_bytes(entries))
    return {
        "entry_count_recorded": manifest.get("entry_count"),
        "entry_count_observed": len(entries),
        "duplicate_paths": duplicates,
        "file_mismatches": mismatches,
        "bundle_sha256_recorded": manifest.get("bundle_sha256"),
        "bundle_sha256_computed": computed_bundle,
        "bundle_sha256_matches": computed_bundle == manifest.get("bundle_sha256"),
        "unmanifested_bundle_files_excluding_manifest_itself": unmanifested_bundle,
        "material_references_not_manifested": material_uncovered,
        "passes_listed_entry_integrity": (
            manifest.get("entry_count") == len(entries)
            and not duplicates
            and not mismatches
            and computed_bundle == manifest.get("bundle_sha256")
        ),
        "passes_material_closure": not unmanifested_bundle and not material_uncovered,
    }


def remote_check(
    root: Path,
    remote_url: str,
    evidence_commit: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="oe-l3-independent-readback-") as temp:
        clone = Path(temp) / "clone"
        cloned = run(["git", "clone", "--quiet", "--no-checkout", remote_url, str(clone)], cwd=root)
        if cloned.returncode != 0:
            return {"passes": False, "error": "fresh clone failed"}
        fetched = run(
            ["git", "fetch", "--quiet", "--no-tags", "origin", evidence_commit],
            cwd=clone,
        )
        if fetched.returncode != 0:
            return {"passes": False, "error": "immutable commit fetch failed"}
        exists = run(["git", "cat-file", "-e", f"{evidence_commit}^{{commit}}"], cwd=clone)
        mismatches: list[dict[str, str]] = []
        bytes_compared = 0
        for entry in entries:
            path = entry["path"]
            fetched_blob = run(
                ["git", "show", f"{evidence_commit}:{path}"],
                cwd=clone,
                text=False,
            )
            if fetched_blob.returncode != 0:
                mismatches.append({"path": path, "reason": "absent_from_remote_commit"})
                continue
            content = fetched_blob.stdout
            bytes_compared += len(content)
            observed = sha256_bytes(content)
            if observed != entry["sha256"] or len(content) != entry["size_bytes"]:
                mismatches.append({"path": path, "reason": "remote_hash_or_size_mismatch"})
        return {
            "immutable_commit": evidence_commit,
            "commit_exists_after_fresh_fetch": exists.returncode == 0,
            "entry_count_compared": len(entries),
            "bytes_compared": bytes_compared,
            "mismatches": mismatches,
            "passes": exists.returncode == 0 and not mismatches,
        }


def independent_capacity_verdict(observation: dict[str, Any]) -> dict[str, Any]:
    snapshots = observation.get("snapshots", [])
    if len(snapshots) < 3:
        return {"verdict": "INCOMPLETE", "findings": ["fewer than three snapshots"]}
    baseline_agents = {
        item["bcId"]: item
        for item in snapshots[0].get("agents", [])
        if item.get("role") == "pre_existing_po03"
    }
    findings: list[str] = []
    for snapshot in snapshots[1:]:
        current = {item["bcId"]: item for item in snapshot.get("agents", [])}
        for bc_id, before in baseline_agents.items():
            after = current.get(bc_id)
            if after is None:
                findings.append(f"{snapshot.get('label')}: {bc_id} disappeared")
                continue
            if after.get("isKilled") and not before.get("isKilled"):
                findings.append(f"{snapshot.get('label')}: {bc_id} became killed")
            before_status = str(before.get("status"))
            after_status = str(after.get("status"))
            if after_status != before_status and after_status in INTERFERENCE_STATES:
                findings.append(
                    f"{snapshot.get('label')}: {bc_id} regressed "
                    f"{before_status}->{after_status}"
                )
    expected_count = observation.get("pre_existing_po03_top_level_task_count")
    if expected_count != len(baseline_agents):
        findings.append(
            f"baseline denominator mismatch: recorded={expected_count}, "
            f"observed={len(baseline_agents)}"
        )
    return {
        "verdict": (
            "CAPACITY_INTERFERENCE_FAIL"
            if findings
            else "ZERO_PO03_CAPACITY_INTERFERENCE"
        ),
        "findings": findings,
        "baseline_count": len(baseline_agents),
    }


def synthetic_capacity_checks(observation: dict[str, Any]) -> dict[str, Any]:
    target = next(
        item
        for item in observation["snapshots"][0]["agents"]
        if item.get("role") == "pre_existing_po03" and item.get("status") != "ERROR"
    )
    results: dict[str, Any] = {}
    for injected_status in ("QUEUED", "ERROR"):
        changed = copy.deepcopy(observation)
        changed_target = next(
            item
            for item in changed["snapshots"][1]["agents"]
            if item["bcId"] == target["bcId"]
        )
        changed_target["status"] = injected_status
        results[injected_status] = independent_capacity_verdict(changed)
    return results


def producer_capacity_adversarial(root: Path, observation: dict[str, Any]) -> dict[str, Any]:
    """Invoke producer code only to test its response to synthetic regressions."""
    spec = importlib.util.spec_from_file_location(
        "producer_orchqual_adversarial_only",
        root / PRODUCER_VERIFIER,
    )
    if spec is None or spec.loader is None:
        return {"error": "producer module could not be loaded"}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = next(
        item
        for item in observation["snapshots"][0]["agents"]
        if item.get("role") == "pre_existing_po03" and item.get("status") != "ERROR"
    )
    results: dict[str, Any] = {}
    for injected_status in ("QUEUED", "ERROR"):
        changed = copy.deepcopy(observation)
        changed_target = next(
            item
            for item in changed["snapshots"][1]["agents"]
            if item["bcId"] == target["bcId"]
        )
        changed_target["status"] = injected_status
        verdict, findings = module.capacity_verdict(changed)
        results[injected_status] = {"verdict": verdict, "findings": findings}
    return results


def event_chain_findings(events: list[dict[str, Any]]) -> tuple[list[str], str | None]:
    findings: list[str] = []
    previous: str | None = None
    ids: set[str] = set()
    idempotency_keys: set[str] = set()
    for expected_sequence, event in enumerate(events, 1):
        event_id = str(event.get("event_id"))
        if event_id in ids:
            findings.append(f"duplicate event_id at sequence {expected_sequence}")
        ids.add(event_id)
        key = str(event.get("idempotency_key"))
        if key in idempotency_keys:
            findings.append(f"duplicate idempotency_key at sequence {expected_sequence}")
        idempotency_keys.add(key)
        if event.get("sequence") != expected_sequence:
            findings.append(f"non-contiguous sequence at {expected_sequence}")
        if event.get("previous_event_sha256") != previous:
            findings.append(f"broken predecessor link at {expected_sequence}")
        payload = copy.deepcopy(event)
        recorded_hash = payload.pop("event_sha256", None)
        computed_hash = sha256_bytes(canonical_bytes(payload))
        if recorded_hash != computed_hash:
            findings.append(f"event hash mismatch at {expected_sequence}")
        if event.get("payload", {}).get("decision_changed") != []:
            findings.append(f"non-empty decision_changed at {expected_sequence}")
        previous = recorded_hash
    return findings, previous


def event_chain_check(root: Path) -> dict[str, Any]:
    events = [
        json.loads(line)
        for line in (root / EVENTS).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    findings, previous = event_chain_findings(events)
    return {
        "event_count": len(events),
        "head_sha256": previous,
        "findings": findings,
        "passes": not findings,
    }


def event_chain_synthetic_checks(root: Path) -> dict[str, Any]:
    events = [
        json.loads(line)
        for line in (root / EVENTS).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    variants: dict[str, list[dict[str, Any]]] = {}

    altered = copy.deepcopy(events)
    altered[4]["subject"] = "synthetic-tamper"
    variants["alter_event_without_rehash"] = altered

    deleted = copy.deepcopy(events)
    del deleted[5]
    variants["delete_event"] = deleted

    reordered = copy.deepcopy(events)
    reordered[6], reordered[7] = reordered[7], reordered[6]
    variants["reorder_events"] = reordered

    spliced = copy.deepcopy(events)
    spliced[8]["subject"] = "synthetic-rehashed-splice"
    payload = copy.deepcopy(spliced[8])
    payload.pop("event_sha256", None)
    spliced[8]["event_sha256"] = sha256_bytes(canonical_bytes(payload))
    variants["rehash_one_event_without_successor_relink"] = spliced

    results: dict[str, Any] = {}
    for name, variant in variants.items():
        findings, _ = event_chain_findings(variant)
        results[name] = {"detected": bool(findings), "findings": findings}
    return results


def nested_decision_changed(value: Any, location: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key == "decision_changed" and child != []:
                findings.append(child_location)
            findings.extend(nested_decision_changed(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(nested_decision_changed(child, f"{location}[{index}]"))
    return findings


def decision_changed_check(root: Path, start_sha: str, evidence_commit: str) -> dict[str, Any]:
    changed = run(
        ["git", "diff", "--name-only", f"{start_sha}..{evidence_commit}"],
        cwd=root,
        check=True,
    ).stdout.splitlines()
    findings: list[dict[str, str]] = []
    parsed_files = 0
    for relative in changed:
        path = root / relative
        if not path.is_file():
            continue
        values: list[Any] = []
        if path.suffix == ".json":
            try:
                values = [read_json(path)]
            except json.JSONDecodeError:
                findings.append({"path": relative, "location": "invalid_json"})
        elif path.suffix == ".jsonl":
            try:
                values = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except json.JSONDecodeError:
                findings.append({"path": relative, "location": "invalid_jsonl"})
        if values:
            parsed_files += 1
        for index, value in enumerate(values):
            for location in nested_decision_changed(value):
                findings.append(
                    {
                        "path": relative,
                        "location": f"record[{index}]{location}",
                    }
                )
    return {
        "producer_changed_machine_records_parsed": parsed_files,
        "nonempty_decision_changed_locations": findings,
        "passes": not findings,
    }


def iter_locator_values(value: Any, location: str = "$") -> list[tuple[str, str]]:
    located: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if isinstance(child, str) and (
                key in {"locator", "stable_locator", "provider_locator", "url"}
                or key.endswith("_url")
            ):
                located.append((child_location, child))
            located.extend(iter_locator_values(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            located.extend(iter_locator_values(child, f"{location}[{index}]"))
    return located


def credential_locator_check(root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    json_files = sorted((root / BUNDLE).rglob("*.json"))
    json_files.extend(
        [
            root / QUALIFICATION,
            root / "workstreams/so02/control-plane/state/runtime-surface-locators.json",
        ]
    )
    for path in json_files:
        if not path.is_file():
            continue
        value = read_json(path)
        for location, locator in iter_locator_values(value):
            split = urlsplit(locator)
            markers: list[str] = []
            if split.username or split.password:
                markers.append("url_userinfo")
            sensitive_keys = {
                key.lower()
                for key, _ in parse_qsl(split.query, keep_blank_values=True)
                if key.lower() in SENSITIVE_QUERY_KEYS
            }
            if sensitive_keys:
                markers.append("sensitive_query_key")
            lowered = locator.lower()
            if any(prefix in lowered for prefix in SECRET_PREFIXES):
                markers.append("secret_prefix")
            if markers:
                findings.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "location": location,
                        "marker": ",".join(sorted(markers)),
                    }
                )
    return {"findings_without_values": findings, "passes": not findings}


def route_operational_and_independence_check(root: Path) -> dict[str, Any]:
    qualification = read_json(root / QUALIFICATION)
    manifest = read_json(root / MANIFEST)
    r1 = read_json(root / BUNDLE / "routes/R1-github-immutable-exchange.json")
    r2 = read_json(root / BUNDLE / "routes/R2-cursor-agent-control-mcp.json")
    orchestrator_id = qualification["orchestrator"]["provider_run_id"]
    retrieved_id = r2["result_retrieval"]["retrieved_content_summary"]["bcId"]
    provider_hashes = {
        item["sha256"] for item in r2["result_retrieval"]["artifacts_returned"]
    }
    manifested_hashes = {item["sha256"] for item in manifest["entries"]}
    raw_hashes_manifested = sorted(provider_hashes & manifested_hashes)
    return {
        "distinct_declared_transports": r1.get("transport") != r2.get("transport"),
        "same_root_controller_produced_both_records": True,
        "r2_retrieved_run_is_the_producing_run": retrieved_id == orchestrator_id,
        "r2_retrieved_status": r2["result_retrieval"]["retrieved_content_summary"].get(
            "status_at_retrieval"
        ),
        "r2_retrieved_event_count": r2["result_retrieval"][
            "retrieved_content_summary"
        ].get("events_count"),
        "r2_raw_provider_artifact_hash_count": len(provider_hashes),
        "r2_raw_provider_artifact_hashes_present_as_manifested_files": (
            len(raw_hashes_manifested)
        ),
        "r2_raw_provider_artifacts_replayable_from_manifest": (
            provider_hashes <= manifested_hashes
        ),
        "r2_provider_directory_recorded_ephemeral": (
            "non-durable" in r2.get("result_retrieval", {}).get("ephemerality_note", "")
        ),
        "r2_durable_record_depends_on_r1_github_custody": (
            r2["result_retrieval"].get("ephemerality_note", "").endswith(
                "where the hash-bound bundle, not the provider path, is canonical."
            )
        ),
        "assessment": (
            "Transport diversity is real, but trust/failure-domain independence is not: "
            "one controller produced both records, R2 queried that same still-running "
            "producer, its two raw artifacts are not committed, and R2 depends on the "
            "R1 GitHub path for durable custody."
        ),
    }


def forged_readback_probe(root: Path) -> dict[str, Any]:
    """Show whether producer verify accepts a non-remote synthetic read-back."""
    with tempfile.TemporaryDirectory(prefix="oe-l3-forged-readback-") as temp:
        temp_repo = Path(temp) / "repo"
        control_src = root / "workstreams/so02/control-plane"
        bundle_src = root / BUNDLE
        shutil.copytree(control_src, temp_repo / "workstreams/so02/control-plane")
        shutil.copytree(bundle_src, temp_repo / BUNDLE)
        forged = {
            "immutable_commit": "0" * 40,
            "bundle_sha256": "f" * 64,
            "entry_count": 1,
            "transports": ["invented_transport_a", "invented_transport_b"],
            "comparisons": [
                {
                    "path": "not/a/manifested/path",
                    "local_sha256": "a" * 64,
                    "remote_git_sha256": "a" * 64,
                    "identical_git_transport": True,
                }
            ],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }
        (temp_repo / READBACK).write_text(
            json.dumps(forged, indent=2) + "\n",
            encoding="utf-8",
        )
        completed = run(
            [
                sys.executable,
                "-I",
                str(temp_repo / PRODUCER_VERIFIER),
                "verify",
            ],
            cwd=temp_repo,
        )
        return {
            "forged_record_contains_no_remote_operation": True,
            "producer_verify_exit_code": completed.returncode,
            "producer_verify_accepted_forgery": completed.returncode == 0,
            "producer_stdout_last_line": (
                completed.stdout.strip().splitlines()[-1]
                if completed.stdout.strip()
                else ""
            ),
        }


def remote_refs_and_protected_check(
    root: Path,
    remote_url: str,
    start_sha: str,
    evidence_commit: str,
    expected_base_head: str,
) -> dict[str, Any]:
    refs_result = run(["git", "ls-remote", "--heads", remote_url], cwd=root, check=True)
    refs: dict[str, str] = {}
    for line in refs_result.stdout.splitlines():
        sha, full_ref = line.split()
        refs[full_ref.removeprefix("refs/heads/")] = sha
    protected = {
        branch: sha
        for branch, sha in refs.items()
        if branch in PROTECTED_EXACT
        or any(branch.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    }
    producer_commits = run(
        ["git", "rev-list", "--reverse", f"{start_sha}..{evidence_commit}"],
        cwd=root,
        check=True,
    ).stdout.splitlines()
    reachable: list[dict[str, str]] = []
    for branch, head in protected.items():
        for commit in producer_commits:
            check = run(["git", "merge-base", "--is-ancestor", commit, head], cwd=root)
            if check.returncode == 0:
                reachable.append({"branch": branch, "producer_commit": commit})
    base_branch = "so02/strategic-control-plane-migration-20260822-v001"
    return {
        "protected_ref_count_observed": len(protected),
        "protected_refs": dict(sorted(protected.items())),
        "producer_commits_checked": producer_commits,
        "producer_commits_reachable_from_protected_heads": reachable,
        "strategic_base_head": protected.get(base_branch),
        "strategic_base_matches_expected": protected.get(base_branch) == expected_base_head,
        "current_ref_and_reachability_check_passes": (
            not reachable and protected.get(base_branch) == expected_base_head
        ),
        "proof_limit": (
            "Current refs and reachable history cannot exclude a transient protected-ref "
            "write later removed by force-push; no retained repository push/audit event "
            "was available for the qualification interval."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument(
        "--evidence-commit",
        default="11a60dcf6dbc2eac4e6d975efab5d985ebbabd62",
    )
    parser.add_argument(
        "--expected-base-head",
        default="fe0a595206e5986de7eaac6cabc619215a1eb81b",
    )
    parser.add_argument("--remote-url")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.evidence_root.resolve()
    qualification = read_json(root / QUALIFICATION)
    start_sha = qualification["orchestrator"]["immutable_start_sha"]
    manifest = read_json(root / MANIFEST)
    if args.remote_url:
        remote_url = args.remote_url
    else:
        remote_result = run(["git", "remote", "get-url", "origin"], cwd=root, check=True)
        remote_url = remote_result.stdout.strip()

    capacity = read_json(root / CAPACITY)
    result = {
        "schema_version": "1.0",
        "verifier": "OE-L3 acceptor-authored; no producer verifier imported for substantive checks",
        "evidence_commit": args.evidence_commit,
        "producer_start_sha": start_sha,
        "manifest": manifest_check(root),
        "fresh_remote_readback": remote_check(
            root,
            remote_url,
            args.evidence_commit,
            manifest["entries"],
        ),
        "capacity_independent_recomputation": independent_capacity_verdict(capacity),
        "capacity_synthetic_independent_checks": synthetic_capacity_checks(capacity),
        "capacity_producer_detector_adversarial_only": producer_capacity_adversarial(
            root,
            capacity,
        ),
        "event_chain": event_chain_check(root),
        "event_chain_synthetic_checks": event_chain_synthetic_checks(root),
        "decision_changed": decision_changed_check(
            root,
            start_sha,
            args.evidence_commit,
        ),
        "credential_locators": credential_locator_check(root),
        "route_operational_and_independence": route_operational_and_independence_check(
            root
        ),
        "phase_gate_forged_readback_probe": forged_readback_probe(root),
        "protected_refs": remote_refs_and_protected_check(
            root,
            remote_url,
            start_sha,
            args.evidence_commit,
            args.expected_base_head,
        ),
    }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
