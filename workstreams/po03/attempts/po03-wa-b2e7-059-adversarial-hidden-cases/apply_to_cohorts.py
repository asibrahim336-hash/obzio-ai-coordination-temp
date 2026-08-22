#!/usr/bin/env python3
"""Apply the evaluator-held invariants to other cohorts' committed results.

The producer of this unit produced none of the results examined here.  Every
finding is read from committed bytes on another cohort's branch by Git object id,
so a finding is reproducible from the recorded ref and commit alone.

The invariants are the hidden arm's, not the producing cohort's: an artifact
locator must name an immutable object rather than a mutable ref, a manifest must
agree with its result, artifact bytes must read back byte-identical, and a
producer must not have claimed completion or acceptance for itself.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APPLICATION_VERSION = "PO03-HIDDEN-CROSS-COHORT-v1"
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def git_bytes(repo: Path, *arguments: str) -> bytes | None:
    completed = subprocess.run(("git", *arguments), cwd=repo, capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def load_validator(repo: Path):
    path = repo / "workstreams/po03/tools/validate_contracts.py"
    spec = importlib.util.spec_from_file_location("po03_059_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scan_refs(repo: Path) -> list[dict[str, str]]:
    raw = git_bytes(repo, "for-each-ref", "--format=%(refname)%09%(objectname)", "refs/heads", "refs/remotes/origin")
    refs = []
    for line in (raw or b"").decode("utf-8").splitlines():
        if not line.strip():
            continue
        name, _, sha = line.partition("\t")
        refs.append({"ref": name, "commit": sha.strip()})
    return sorted(refs, key=lambda item: (not item["ref"].startswith("refs/remotes/"), item["ref"]))


def discover_results(repo: Path, exclude_prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    """Find every committed result document that this cohort did not produce."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in scan_refs(repo):
        listing = git_bytes(
            repo, "ls-tree", "-r", "--name-only", "-z", ref["commit"], "--", "workstreams/po03/attempts/"
        )
        if listing is None:
            continue
        for path in (listing.decode("utf-8").split("\0")):
            if not path.endswith("/result.json"):
                continue
            slot = path[: -len("/result.json")]
            if any(slot.endswith(prefix) for prefix in exclude_prefixes):
                continue
            if slot in seen:
                continue
            seen.add(slot)
            found.append({"slot": slot, "ref": ref["ref"], "commit": ref["commit"]})
    return found


def check(repo: Path, validator, record: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    result_raw = git_bytes(repo, "cat-file", "blob", f"{record['commit']}:{record['slot']}/result.json")
    manifest_raw = git_bytes(repo, "cat-file", "blob", f"{record['commit']}:{record['slot']}/manifest.json")
    if result_raw is None:
        return {**record, "readable": False, "findings": ["result.json unreadable at the recorded commit"]}
    try:
        result = json.loads(result_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {**record, "readable": False, "findings": [f"result.json unparseable: {exc}"]}
    manifest = None
    if manifest_raw is not None:
        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(f"manifest.json unparseable: {exc}")

    contract_errors = validator.validate_result(result)
    findings.extend(f"contract: {error}" for error in contract_errors)

    artifacts = result.get("artifacts") or []
    seen_ids: set[str] = set()
    verified = 0
    for artifact in artifacts:
        locator = artifact.get("content_uri", "")
        artifact_id = artifact.get("artifact_id")
        if artifact_id in seen_ids:
            findings.append(f"duplicate artifact_id {artifact_id}")
        seen_ids.add(artifact_id)
        if not isinstance(locator, str) or not locator.startswith("git:"):
            findings.append(f"{artifact_id}: locator is not a Git locator ({locator!r})")
            continue
        revision = locator[len("git:") :].split(":", 1)[0]
        if not GIT_OBJECT_RE.fullmatch(revision):
            findings.append(
                f"{artifact_id}: locator names the mutable revision {revision!r} rather than an immutable object id"
            )
        blob = git_bytes(repo, "cat-file", "blob", locator[len("git:") :])
        if blob is None:
            findings.append(f"{artifact_id}: locator unreadable in this clone")
            continue
        if not blob:
            findings.append(f"{artifact_id}: artifact is zero bytes")
        if hashlib.sha256(blob).hexdigest() != artifact.get("sha256") or len(blob) != artifact.get("bytes"):
            findings.append(
                f"{artifact_id}: read-back disagrees with the recorded digest or byte count "
                f"(observed sha256={hashlib.sha256(blob).hexdigest()} bytes={len(blob)})"
            )
        else:
            verified += 1

    if result.get("obzio_state") == "COMPLETED":
        findings.append("producer result asserts COMPLETED, which only the coordinator may set")
    if result.get("completion_actor") not in (None, "coordinator"):
        findings.append(f"completion_actor is {result.get('completion_actor')!r}")
    acceptance = result.get("independent_acceptance") or {}
    if acceptance.get("state") in {"ACCEPTED", "REJECTED"}:
        if acceptance.get("reviewer_id") == result.get("attempt", {}).get("worker_id"):
            findings.append("producer recorded itself as the independent reviewer")
    if manifest is not None:
        claim = (manifest.get("producer") or {}).get("obzio_state_claim")
        if claim not in (None, "READY_TO_COMMIT"):
            findings.append(f"manifest producer claim is {claim!r} rather than READY_TO_COMMIT")
        if manifest.get("task_id") != result.get("task_id"):
            findings.append("manifest and result disagree on task_id")
        if manifest.get("artifact_count") != result.get("result_transaction", {}).get("artifact_count"):
            findings.append("manifest and result disagree on artifact_count")
        if manifest.get("total_bytes") != result.get("result_transaction", {}).get("total_bytes"):
            findings.append("manifest and result disagree on total_bytes")
    else:
        findings.append("no manifest.json beside the committed result")

    return {
        **record,
        "readable": True,
        "task_id": result.get("task_id"),
        "artifact_count": len(artifacts),
        "artifacts_verified": verified,
        "manifest_present": manifest is not None,
        "recorded_verdict": (manifest or {}).get("verdict"),
        "findings": findings,
        "clean": not findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="result-slot suffix to exclude because this cohort produced it; repeatable",
    )
    args = parser.parse_args(argv)
    repo = Path(args.repo_root).resolve()
    validator = load_validator(repo)
    records = [check(repo, validator, item) for item in discover_results(repo, tuple(args.exclude))]
    payload = {
        "application_version": APPLICATION_VERSION,
        "observed_at": utc_now(),
        "excluded_own_units": args.exclude,
        "results_examined": len(records),
        "results_clean": sum(1 for record in records if record.get("clean")),
        "results_with_findings": sum(1 for record in records if record.get("findings")),
        "finding_count": sum(len(record.get("findings", [])) for record in records),
        "records": records,
        "decision_changed": [],
    }
    Path(args.out).write_bytes(canonical(payload))
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "records"}, indent=2, sort_keys=True
        )
    )
    for record in records:
        if record.get("findings"):
            print(f"FINDING {record.get('task_id') or record['slot']} @ {record['ref']}")
            for finding in record["findings"]:
                print(f"  - {finding}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
