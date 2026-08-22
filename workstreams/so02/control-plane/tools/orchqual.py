#!/usr/bin/env python3
"""Executable route qualifier for CUR-ORCH-QUAL-01.

Dependency-free. `verify` runs offline from a clean clone so an independent
actor can replay every claim; `readback` performs the live remote comparison.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]

QUALIFICATION_PATH = ROOT / "state/CUR-ORCH-QUAL-01.json"
CAPACITY_PATH = ROOT / "state/PO03-CAPACITY-OBSERVATION-CUR-ORCH-QUAL-01.json"
BUNDLE_DIR = REPO / "receipts/so02/2026-08-22/cur-orch-qual-01"
MANIFEST_PATH = BUNDLE_DIR / "EVIDENCE-MANIFEST.json"
READBACK_PATH = BUNDLE_DIR / "REMOTE-READBACK.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

QUALIFICATION_BRANCH = "cursor/so02-cur-orch-qual-01"

# The SO-02 commission allowlist. Everything else is out of scope for this branch.
ALLOWED_PATH_PREFIXES = ("workstreams/so02/control-plane/", "receipts/so02/")
ALLOWED_WORKFLOW_RE = re.compile(r"^\.github/workflows/so02-control-plane-[A-Za-z0-9._-]+\.yml$")

# Branches this commission may never write, resolved to exact refs rather than PR numbers.
PROTECTED_BRANCHES = {
    "main": "repository default branch",
    "so02/strategic-control-plane-migration-20260822-v001": "selected SO-02 source branch, PR #10 head",
    "po03/repository-engineering-portable-runtime-20260822-v001": "active PO-03 branch, PR #9 head",
    "soo/v003-currentness-repair-20260820": "PR #6 head",
    "soo/v003-controlling-pointer-and-part-manifest-repair-20260820": "PR #7 head",
    "cursor/setup-dev-environment-b5ce": "PR #9 base",
}
PROTECTED_BRANCH_PREFIXES = ("cursor/po03-", "po03/", "packs/", "soo/")

# Any pre-existing PO-03 task moving into one of these is capacity interference.
INTERFERENCE_STATUSES = {"QUEUED", "PAUSED", "EVICTED", "ADMISSION_REFUSED", "KILLED", "PENDING"}

ROUTE_EVIDENCE_KEYS = (
    "bounded_launch_observed",
    "addressable_result_retrieval_observed",
    "stable_locator_recorded",
    "reconciled_into_immutable_repository_custody",
    "remote_byte_for_byte_readback",
    "failure_or_unavailable_fallback_exercised",
    "zero_po03_capacity_interference",
)

CREDENTIAL_MARKERS = (
    "token=", "api_key=", "apikey=", "bearer ", "x-ops-gate", "password",
    "client_secret", "ghp_", "gho_", "ghu_", "ghs_", "sk-", "private_key",
)

# A subordinate result may only be READY_TO_COMMIT until an immutable remote
# read-back exists; COMPLETED is reserved for the reconciled phase.
PHASE_READY = "EVIDENCE_BUNDLE_READY_TO_COMMIT"
PHASE_COMPLETED = "RECONCILED_COMPLETED"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def require_keys(errors: list[str], value: dict[str, Any], keys: Iterable[str], prefix: str) -> None:
    for key in keys:
        add(errors, key in value, f"{prefix}: missing {key}")


def run(args: list[str], cwd: Path = REPO) -> tuple[int, str, str]:
    completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr


# --------------------------------------------------------------------------
# write-scope guard
# --------------------------------------------------------------------------

def guard_paths(paths: Iterable[str], branch: str) -> list[str]:
    """Fail-closed write-scope guard. Returns one refusal per rejected write."""
    errors: list[str] = []
    if branch in PROTECTED_BRANCHES:
        errors.append(f"branch {branch}: protected target ({PROTECTED_BRANCHES[branch]})")
    for prefix in PROTECTED_BRANCH_PREFIXES:
        if branch.startswith(prefix) and branch != QUALIFICATION_BRANCH:
            errors.append(f"branch {branch}: protected namespace {prefix}*")
    for path in paths:
        normalised = path.strip()
        if not normalised:
            continue
        if ".." in Path(normalised).parts or normalised.startswith("/"):
            errors.append(f"path {normalised}: non-portable or escaping path")
            continue
        if normalised.startswith(ALLOWED_PATH_PREFIXES):
            continue
        if ALLOWED_WORKFLOW_RE.fullmatch(normalised):
            continue
        errors.append(f"path {normalised}: outside the SO-02 write allowlist")
    return errors


def changed_paths(base: str, head: str) -> list[str]:
    code, out, err = run(["git", "diff", "--name-only", f"{base}..{head}"])
    if code != 0:
        raise RuntimeError(f"git diff failed: {err.strip()}")
    return [line for line in out.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# evidence manifest
# --------------------------------------------------------------------------

STATE_BINDINGS = (
    "workstreams/so02/control-plane/state/CUR-ORCH-QUAL-01.json",
    "workstreams/so02/control-plane/state/PO03-CAPACITY-OBSERVATION-CUR-ORCH-QUAL-01.json",
    "workstreams/so02/control-plane/state/RUNTIME-MODEL-CAPABILITY-REGISTER.json",
    "workstreams/so02/control-plane/tools/orchqual.py",
    "workstreams/so02/control-plane/tests/test_orchqual.py",
)


def bundle_files() -> list[Path]:
    """The receipts bundle plus the control-plane state it binds.

    REMOTE-READBACK.json is excluded because it is derived from this manifest.
    """
    files = {
        path for path in BUNDLE_DIR.rglob("*")
        if path.is_file() and path != MANIFEST_PATH and path != READBACK_PATH
    }
    files.update((REPO / relative) for relative in STATE_BINDINGS if (REPO / relative).is_file())
    return sorted(files)


def build_manifest() -> dict[str, Any]:
    entries = []
    for path in bundle_files():
        entries.append({
            "path": path.relative_to(REPO).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return {
        "manifest_id": "CUR-ORCH-QUAL-01-EVIDENCE-MANIFEST",
        "decision_changed": [],
        "bundle_root": BUNDLE_DIR.relative_to(REPO).as_posix(),
        "entry_count": len(entries),
        "entries": entries,
        "bundle_sha256": sha256_bytes(canonical_bytes(entries)),
    }


def verify_manifest(errors: list[str]) -> None:
    if not MANIFEST_PATH.is_file():
        errors.append("manifest: EVIDENCE-MANIFEST.json missing")
        return
    manifest = read_json(MANIFEST_PATH)
    require_keys(errors, manifest, ["manifest_id", "bundle_root", "entry_count", "entries", "bundle_sha256"], "manifest")
    entries = {item["path"]: item for item in manifest.get("entries", []) if isinstance(item, dict)}
    add(errors, manifest.get("entry_count") == len(entries), "manifest: entry denominator mismatch")
    observed = {path.relative_to(REPO).as_posix() for path in bundle_files()}
    for missing in sorted(observed - set(entries)):
        errors.append(f"manifest: bundle file not covered by a hash: {missing}")
    for absent in sorted(set(entries) - observed):
        errors.append(f"manifest: manifested file absent from the bundle: {absent}")
    for path_text, entry in sorted(entries.items()):
        target = REPO / path_text
        if not target.is_file():
            continue
        add(errors, SHA256_RE.fullmatch(str(entry.get("sha256", ""))) is not None, f"manifest {path_text}: invalid SHA-256")
        add(errors, entry.get("sha256") == sha256_file(target), f"manifest {path_text}: content hash mismatch")
        add(errors, entry.get("size_bytes") == target.stat().st_size, f"manifest {path_text}: size mismatch")
    recomputed = sha256_bytes(canonical_bytes(manifest.get("entries", [])))
    add(errors, manifest.get("bundle_sha256") == recomputed, "manifest: bundle_sha256 does not bind the entry list")


# --------------------------------------------------------------------------
# capacity non-interference
# --------------------------------------------------------------------------

def capacity_verdict(observation: dict[str, Any]) -> tuple[str, list[str]]:
    """Recompute the PO-03 interference verdict from raw snapshots only."""
    findings: list[str] = []
    snapshots = observation.get("snapshots", [])
    if observation.get("capacity_observation_state") == "CAPACITY_OBSERVATION_UNAVAILABLE":
        return "CAPACITY_OBSERVATION_UNAVAILABLE", findings
    if len(snapshots) < 3:
        return "INCOMPLETE", ["fewer than three snapshots (T0, T+60, completion)"]

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
                findings.append(f"{label}: pre-existing PO-03 task {bc_id} disappeared from the visible set")
                continue
            if after.get("status") != before.get("status") and after.get("status") in INTERFERENCE_STATUSES:
                findings.append(
                    f"{label}: PO-03 task {bc_id} moved {before.get('status')} -> {after.get('status')}"
                )
            if after.get("isKilled") and not before.get("isKilled"):
                findings.append(f"{label}: PO-03 task {bc_id} was killed after T0")
    return ("CAPACITY_INTERFERENCE_FAIL" if findings else "ZERO_PO03_CAPACITY_INTERFERENCE"), findings


def verify_capacity(errors: list[str]) -> None:
    if not CAPACITY_PATH.is_file():
        errors.append("capacity: observation file missing")
        return
    observation = read_json(CAPACITY_PATH)
    require_keys(
        errors,
        observation,
        ["observation_id", "instrument", "orchestrator_bc_id", "capacity_observation_state", "snapshots", "verdict"],
        "capacity",
    )
    for index, snapshot in enumerate(observation.get("snapshots", [])):
        prefix = f"capacity snapshot[{index}]"
        require_keys(errors, snapshot, ["label", "observed_at", "agents"], prefix)
        for agent in snapshot.get("agents", []):
            require_keys(errors, agent, ["bcId", "status", "isKilled", "updatedAtMs"], f"{prefix} agent")
    verdict, findings = capacity_verdict(observation)
    add(errors, observation.get("verdict") == verdict, f"capacity: recorded verdict does not match recomputed {verdict}")
    for finding in findings:
        errors.append(f"capacity: {finding}")


# --------------------------------------------------------------------------
# route register
# --------------------------------------------------------------------------

def route_is_qualified(route: dict[str, Any]) -> bool:
    evidence = route.get("evidence", {})
    return all(evidence.get(key) is True for key in ROUTE_EVIDENCE_KEYS)


def verify_qualification(errors: list[str]) -> None:
    if not QUALIFICATION_PATH.is_file():
        errors.append("qualification: CUR-ORCH-QUAL-01.json missing")
        return
    data = read_json(QUALIFICATION_PATH)
    require_keys(
        errors,
        data,
        [
            "qualification_id", "decision_changed", "phase", "state", "orchestrator", "routes",
            "aggregate_classification", "qualified_route_count", "fallback_exercises",
            "capacity_verdict", "admits", "does_not_admit", "independent_acceptance",
        ],
        "qualification",
    )
    add(errors, data.get("qualification_id") == "CUR-ORCH-QUAL-01", "qualification: wrong identity")
    add(errors, data.get("decision_changed") == [], "qualification: unbound strategy change")
    phase = data.get("phase")
    add(errors, phase in {PHASE_READY, PHASE_COMPLETED}, "qualification: invalid transactional phase")

    orchestrator = data.get("orchestrator", {})
    require_keys(
        errors,
        orchestrator,
        [
            "provider", "stable_agent_url", "provider_run_id", "exact_model_configuration",
            "immutable_start_sha", "isolated_branch", "top_level_agent_count",
            "cursor_subagents_started", "multiple_agents_groups_started", "tool_census",
        ],
        "orchestrator",
    )
    add(errors, orchestrator.get("top_level_agent_count") == 1, "orchestrator: more than one top-level agent used")
    add(errors, orchestrator.get("cursor_subagents_started") == 0, "orchestrator: a Cursor subagent was started during qualification")
    add(errors, orchestrator.get("multiple_agents_groups_started") == 0, "orchestrator: a Multiple Agents group was started during qualification")
    add(errors, orchestrator.get("isolated_branch") == QUALIFICATION_BRANCH, "orchestrator: work left the isolated branch")
    add(errors, GIT_SHA_RE.fullmatch(str(orchestrator.get("immutable_start_sha", ""))) is not None, "orchestrator: immutable start SHA not recorded")
    add(errors, bool(orchestrator.get("exact_model_configuration")), "orchestrator: exact model configuration not recorded")
    add(errors, "auto" not in str(orchestrator.get("exact_model_configuration", "")).lower(), "orchestrator: model alias must not be Auto")

    routes = data.get("routes", [])
    ids = [route.get("route_id") for route in routes]
    add(errors, len(ids) == len(set(ids)), "qualification: duplicate route id")
    add(errors, len(routes) >= 6, "qualification: practical control surface not fully inventoried")

    allowed_availability = {
        "QUALIFIED", "AVAILABLE_NOT_QUALIFIED", "OWNER_REQUIRED",
        "NOT_SUPPORTED", "NOT_YET_CREATED", "OPTIONAL_PROBE_NOT_REQUIRED",
    }
    qualified = 0
    for route in routes:
        prefix = f"route {route.get('route_id')}"
        require_keys(
            errors,
            route,
            ["route_id", "name", "transport", "independent_of", "availability", "evidence", "stable_locators", "instrument"],
            prefix,
        )
        availability = route.get("availability")
        add(errors, availability in allowed_availability, f"{prefix}: invalid availability state")
        evidence = route.get("evidence", {})
        for key in ROUTE_EVIDENCE_KEYS:
            add(errors, isinstance(evidence.get(key), bool), f"{prefix}: evidence {key} must be an explicit boolean")
        if availability == "QUALIFIED":
            qualified += 1
            add(errors, phase == PHASE_COMPLETED, f"{prefix}: qualified before the reconciled phase")
            add(errors, route_is_qualified(route), f"{prefix}: claimed QUALIFIED without complete end-to-end evidence")
            add(errors, bool(route.get("stable_locators")), f"{prefix}: qualified without a stable locator")
        else:
            add(errors, not route_is_qualified(route), f"{prefix}: complete evidence recorded but not marked QUALIFIED")
        if availability in {"OWNER_REQUIRED", "NOT_SUPPORTED", "NOT_YET_CREATED"}:
            add(errors, bool(route.get("owner_required_action")), f"{prefix}: blocked route without an exact owner action")
        for locator in route.get("stable_locators", []):
            lowered = str(locator.get("locator", "")).lower()
            add(
                errors,
                not any(marker in lowered for marker in CREDENTIAL_MARKERS),
                f"{prefix}: locator contains credential material",
            )

    add(errors, data.get("qualified_route_count") == qualified, "qualification: qualified route denominator mismatch")

    classification = data.get("aggregate_classification")
    if phase == PHASE_READY:
        expected = "READY_TO_COMMIT_REMOTE_READBACK_PENDING"
    elif qualified >= 2:
        expected = "PASS_TWO_OR_MORE_ROUTES"
    elif qualified == 1:
        expected = "PASS_ONE_ROUTE_PARTIAL"
    else:
        expected = "FAIL"
    if data.get("capacity_verdict") == "CAPACITY_INTERFERENCE_FAIL":
        expected = "CAPACITY_INTERFERENCE_FAIL"
    add(errors, classification == expected, f"qualification: aggregate classification must be {expected}")

    add(errors, len(data.get("fallback_exercises", [])) >= 1, "qualification: no failure or unavailable-route fallback exercised")
    for exercise in data.get("fallback_exercises", []):
        require_keys(
            errors,
            exercise,
            ["exercise_id", "kind", "route_id", "injected", "observed", "fail_closed", "programme_continued"],
            f"fallback {exercise.get('exercise_id')}",
        )
        add(errors, exercise.get("fail_closed") is True, f"fallback {exercise.get('exercise_id')}: did not fail closed")

    admits = data.get("admits", {})
    add(errors, admits.get("persistent_single_agent_orchestrators") == 1, "qualification: a pass admits exactly one persistent orchestrator")
    add(errors, admits.get("additional_cursor_multiple_agents_group") is False, "qualification: a pass must not admit another Cursor group")
    add(errors, admits.get("exclusive_dependence_on_cursor_or_sw") is False, "qualification: a pass must not create exclusive provider dependence")
    add(errors, admits.get("merge_promotion_or_cutover") is False, "qualification: a pass must not admit merge, promotion or cutover")
    add(errors, admits.get("strategy_binding") is False, "qualification: a pass must not bind strategy")
    add(errors, admits.get("chatgpt_projects_ui_required") is False, "qualification: Projects UI must not become a promotion gate")

    acceptance = data.get("independent_acceptance", {})
    add(errors, acceptance.get("self_accepted") is False, "qualification: producer self-acceptance is prohibited")
    add(errors, acceptance.get("state") in {"REQUESTED_NOT_GRANTED", "GRANTED"}, "qualification: independent acceptance state missing")
    add(
        errors,
        acceptance.get("acceptor") != data.get("orchestrator", {}).get("provider_run_id"),
        "qualification: acceptor must not be the producing run",
    )

    capacity = read_json(CAPACITY_PATH) if CAPACITY_PATH.is_file() else {}
    add(errors, data.get("capacity_verdict") == capacity.get("verdict"), "qualification: capacity verdict diverges from the observation record")


# --------------------------------------------------------------------------
# remote read-back
# --------------------------------------------------------------------------

def remote_readback(commit: str, use_api: bool = True) -> dict[str, Any]:
    """Fetch the immutable commit from the remote and compare every bundle byte."""
    code, _, err = run(["git", "fetch", "--no-tags", "origin", commit])
    if code != 0:
        code, _, err = run(["git", "fetch", "--no-tags", "origin", QUALIFICATION_BRANCH])
        if code != 0:
            raise RuntimeError(f"remote fetch failed: {err.strip()}")

    manifest = read_json(MANIFEST_PATH)
    comparisons = []
    mismatches = []
    for entry in manifest["entries"]:
        path_text = entry["path"]
        local = (REPO / path_text).read_bytes()
        code, out, err = run(["git", "cat-file", "-p", f"{commit}:{path_text}"])
        if code != 0:
            mismatches.append(f"{path_text}: absent from remote commit {commit}")
            continue
        remote_git = subprocess.run(
            ["git", "cat-file", "-p", f"{commit}:{path_text}"], cwd=REPO, capture_output=True
        ).stdout
        record = {
            "path": path_text,
            "manifest_sha256": entry["sha256"],
            "local_sha256": sha256_bytes(local),
            "remote_git_sha256": sha256_bytes(remote_git),
            "byte_length_local": len(local),
            "byte_length_remote_git": len(remote_git),
            "identical_git_transport": remote_git == local,
        }
        if use_api:
            blob_sha = run(["git", "rev-parse", f"{commit}:{path_text}"])[1].strip()
            code, out, _ = run([
                "gh", "api",
                f"/repos/asibrahim336-hash/obzio-ai-coordination-temp/git/blobs/{blob_sha}",
                "--jq", ".content",
            ])
            if code == 0 and out.strip():
                remote_api = base64.b64decode(out.strip())
                record["blob_sha1"] = blob_sha
                record["remote_api_sha256"] = sha256_bytes(remote_api)
                record["byte_length_remote_api"] = len(remote_api)
                record["identical_api_transport"] = remote_api == local
            else:
                record["identical_api_transport"] = None
                record["api_note"] = "REST blob transport unavailable for this entry"
        if record["manifest_sha256"] != record["local_sha256"]:
            mismatches.append(f"{path_text}: manifest hash does not match working tree")
        if not record["identical_git_transport"]:
            mismatches.append(f"{path_text}: remote git bytes differ from local bytes")
        if record.get("identical_api_transport") is False:
            mismatches.append(f"{path_text}: remote REST blob bytes differ from local bytes")
        comparisons.append(record)

    api_confirmed = sum(1 for item in comparisons if item.get("identical_api_transport") is True)
    return {
        "readback_id": "CUR-ORCH-QUAL-01-REMOTE-READBACK",
        "decision_changed": [],
        "immutable_commit": commit,
        "bundle_sha256": manifest["bundle_sha256"],
        "entry_count": len(comparisons),
        "transports": ["git_protocol_fetch_by_immutable_sha", "github_rest_git_blobs_api"],
        "api_confirmed_entry_count": api_confirmed,
        "comparisons": comparisons,
        "mismatches": mismatches,
        "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL" if not mismatches else "REMOTE_READBACK_MISMATCH",
    }


def ingest_return_branch(branch: str, source_sha: str) -> dict[str, Any]:
    """Fail-closed ingestion of a parallel specialist return branch.

    Refuses on absence, on a branch that does not descend from the recorded
    SO-02 source SHA, on a missing manifest and on any byte divergence. It
    never merges and never asks the founder to retrieve or compare anything.
    """
    code, out, err = run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"])
    if code != 0:
        return {"branch": branch, "state": "PROVIDER_UNREACHABLE", "detail": err.strip(), "ingested": False}
    if not out.strip():
        return {
            "branch": branch,
            "state": "NOT_YET_CREATED",
            "detail": "git ls-remote returned zero refs for the return branch",
            "ingested": False,
            "owner_required_action": (
                "The parallel specialist must create the isolated return branch from the recorded SO-02 "
                f"source SHA {source_sha} and push a hash-bound manifest before any ingestion can occur."
            ),
        }

    head = out.split()[0]
    code, _, err = run(["git", "fetch", "--no-tags", "origin", branch])
    if code != 0:
        return {"branch": branch, "state": "FETCH_FAILED", "detail": err.strip(), "ingested": False}

    code, _, _ = run(["git", "merge-base", "--is-ancestor", source_sha, head])
    if code != 0:
        return {
            "branch": branch,
            "state": "REJECTED_UNRELATED_LINEAGE",
            "detail": f"{head} does not descend from the recorded SO-02 source SHA {source_sha}",
            "ingested": False,
        }

    code, listing, _ = run(["git", "ls-tree", "-r", "--name-only", head])
    manifests = [line for line in listing.splitlines() if line.endswith("MANIFEST.json")]
    if not manifests:
        return {
            "branch": branch,
            "state": "REJECTED_NO_HASH_BOUND_MANIFEST",
            "detail": "a return branch without a content-hash manifest cannot be independently verified",
            "immutable_head": head,
            "ingested": False,
        }

    divergences: list[str] = []
    for manifest_path in manifests:
        _, blob, _ = run(["git", "cat-file", "-p", f"{head}:{manifest_path}"])
        try:
            manifest = json.loads(blob)
        except json.JSONDecodeError as exc:
            divergences.append(f"{manifest_path}: unreadable manifest ({exc})")
            continue
        for entry in manifest.get("entries", []):
            path_text = entry.get("path", "")
            content = subprocess.run(
                ["git", "cat-file", "-p", f"{head}:{path_text}"], cwd=REPO, capture_output=True
            )
            if content.returncode != 0:
                divergences.append(f"{path_text}: manifested file absent from the return branch")
                continue
            if sha256_bytes(content.stdout) != entry.get("sha256"):
                divergences.append(f"{path_text}: remote bytes do not match the manifested hash")
    return {
        "branch": branch,
        "state": "READY_TO_INGEST" if not divergences else "REJECTED_BYTE_DIVERGENCE",
        "immutable_head": head,
        "manifests": manifests,
        "divergences": divergences,
        "ingested": False,
        "note": "Verification only. Integration requires independent criteria and never an automatic merge.",
    }


def verify_readback(errors: list[str]) -> None:
    phase = read_json(QUALIFICATION_PATH).get("phase") if QUALIFICATION_PATH.is_file() else None
    if not READBACK_PATH.is_file():
        add(errors, phase != PHASE_COMPLETED, "readback: reconciled phase declared without a remote read-back record")
        return
    record = read_json(READBACK_PATH)
    require_keys(
        errors,
        record,
        ["immutable_commit", "bundle_sha256", "entry_count", "transports", "comparisons", "mismatches", "result"],
        "readback",
    )
    add(errors, GIT_SHA_RE.fullmatch(str(record.get("immutable_commit", ""))) is not None, "readback: immutable commit not recorded")
    add(errors, len(record.get("transports", [])) >= 2, "readback: fewer than two independent transports")
    add(errors, record.get("mismatches") == [], "readback: unresolved byte mismatch")
    add(errors, record.get("result") == "REMOTE_BYTE_FOR_BYTE_IDENTICAL", "readback: not byte-for-byte identical")
    add(errors, record.get("entry_count", 0) > 0, "readback: no entry compared")
    for comparison in record.get("comparisons", []):
        prefix = f"readback {comparison.get('path')}"
        add(errors, comparison.get("identical_git_transport") is True, f"{prefix}: git transport bytes differ")
        add(errors, comparison.get("local_sha256") == comparison.get("remote_git_sha256"), f"{prefix}: digest divergence")


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------

def verify(offline: bool = True) -> list[str]:
    errors: list[str] = []
    verify_manifest(errors)
    verify_capacity(errors)
    verify_qualification(errors)
    verify_readback(errors)
    if not offline:
        code, out, _ = run(["git", "rev-parse", "HEAD"])
        if code == 0:
            head = out.strip()
            base = read_json(QUALIFICATION_PATH)["orchestrator"]["immutable_start_sha"]
            for refusal in guard_paths(changed_paths(base, head), QUALIFICATION_BRANCH):
                errors.append(f"guard: {refusal}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CUR-ORCH-QUAL-01 route qualifier")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("manifest")
    online = sub.add_parser("verify-online")
    online.set_defaults(online=True)
    readback = sub.add_parser("readback")
    readback.add_argument("--commit", required=True)
    guard = sub.add_parser("guard")
    guard.add_argument("--base", required=True)
    guard.add_argument("--head", default="HEAD")
    guard.add_argument("--branch", default=QUALIFICATION_BRANCH)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--branch", default="capability-factory/return-20260822-v001")
    ingest.add_argument("--source-sha", default="a5adfdff6921b34b05c1ea6eed0c1752bb4ebbbb")
    args = parser.parse_args(argv)

    if args.command == "ingest":
        record = ingest_return_branch(args.branch, args.source_sha)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if record["state"] == "READY_TO_INGEST" else 2

    if args.command == "manifest":
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"WROTE: {MANIFEST_PATH.relative_to(REPO)}")
        return 0

    if args.command == "readback":
        record = remote_readback(args.commit)
        READBACK_PATH.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in record.items() if k != "comparisons"}, indent=2, sort_keys=True))
        return 0 if record["result"] == "REMOTE_BYTE_FOR_BYTE_IDENTICAL" else 1

    if args.command == "guard":
        refusals = guard_paths(changed_paths(args.base, args.head), args.branch)
        for refusal in refusals:
            print(f"REFUSED: {refusal}")
        if refusals:
            return 1
        print("PASS: every write stayed inside the SO-02 allowlist on the isolated branch")
        return 0

    errors = verify(offline=args.command == "verify")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: CUR-ORCH-QUAL-01 route qualification evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
