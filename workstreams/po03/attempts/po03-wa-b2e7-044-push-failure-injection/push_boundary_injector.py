#!/usr/bin/env python3
"""Inject failures on either side of the push boundary and classify the outcome.

Three real repositories are used: a bare remote, a producer clone that commits
and pushes, and a separate controller clone that ingests.  That separation is
what makes the push boundary observable at all — a single repository can never
show the difference between "committed here" and "durable where the coordinator
can read it".

Run directly to print the observation as JSON:

    python3 -I push_boundary_injector.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
HEX_OBJECT = re.compile(r"\b[0-9a-f]{40}\b")
TASK_REFERENCE = re.compile(r"po03-c6-044-[a-z-]+")
_SPEC = importlib.util.spec_from_file_location("po03_c6_044_fault_kit", HERE / "fault_kit.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load fault_kit.py")
kit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kit)

BRANCH = "po03/sandbox-result-branch"


def error_signature(errors: list[str]) -> list[str]:
    """Normalise per-run identifiers so two failure modes can be compared.

    Commit ids and task names differ between runs by construction; what matters
    is whether the mechanism reports a materially different failure for a result
    that was never pushed versus one that is durable on the remote.
    """
    normalised = []
    for error in errors:
        text = HEX_OBJECT.sub("<object-id>", error)
        text = TASK_REFERENCE.sub("<task>", text)
        normalised.append(text)
    return sorted(normalised)


def stage(root: Path, task_id: str) -> dict[str, Any]:
    """Build the three repositories and a controller-side immutable capsule."""
    root.mkdir(parents=True, exist_ok=True)
    remote = kit.build_remote(root)
    producer = kit.build_producer(root, remote, BRANCH)
    controller = kit.clone_controller(root, remote, BRANCH)
    module = kit.bind_sandbox(kit.load_factory(f"044_{task_id.replace('-', '_')}"), controller)
    kit.seed_capsule(module, task_id, hypothesis="a push-boundary failure is recoverable")
    lease = module.grant_lease(task_id, holder="worker-a", lease_seconds=60, attempt=1)
    return {
        "root": root,
        "remote": remote,
        "producer": producer,
        "controller": controller,
        "module": module,
        "fence_token": lease["fence_token"],
        "task_id": task_id,
    }


def producer_commits(context: dict[str, Any]) -> dict[str, Any]:
    """The producer writes and commits its artifact locally."""
    task_id = context["task_id"]
    slot = f"workstreams/po03/attempts/{task_id}"
    path = f"{slot}/component.json"
    body = context["module"].canonical_json({"component": task_id, "computed": True})
    target = context["producer"] / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    commit = kit.commit_all(context["producer"], "po03: sandbox worker artifact")
    return {"commit": commit, "path": path, "body": body}


def controller_ingests(context: dict[str, Any], committed: dict[str, Any]) -> dict[str, Any]:
    module = context["module"]
    document = kit.build_result_document_from_bytes(
        module,
        task_id=context["task_id"],
        commit=committed["commit"],
        bodies={committed["path"]: committed["body"]},
        fence_token=context["fence_token"],
        worker_id="worker-a",
    )
    return module.ingest_result(context["task_id"], document)


def inject_pre_push_failure(root: Path) -> dict[str, Any]:
    """The producer commits, then the push never happens."""
    context = stage(root / "pre-push", "po03-c6-044-pre-push")
    committed = producer_commits(context)
    remote_has = kit.git_attempt(
        context["remote"], "cat-file", "-e", f"{committed['commit']}^{{commit}}"
    )
    kit.git_attempt(context["controller"], "fetch", "--quiet", "origin")
    ingestion = controller_ingests(context, committed)
    state = context["module"].scan_recovery("c6-sandbox", "0" * 40)
    observed = {
        "commit_present_on_remote": remote_has["returncode"] == 0,
        "ingestion_state": ingestion["obzio_state"],
        "ingestion_errors": ingestion["errors"],
        "recovery_action": state["units"][context["task_id"]]["recovery_action"],
        "false_completion_count": state["false_completion_count"],
        "producer_local_bytes": len(
            kit.git_bytes(context["producer"], "cat-file", "blob", f"{committed['commit']}:{committed['path']}")
        ),
        "producer_local_bytes_match_committed": kit.git_bytes(
            context["producer"], "cat-file", "blob", f"{committed['commit']}:{committed['path']}"
        ) == committed["body"],
    }
    passed = (
        not observed["commit_present_on_remote"]
        and observed["ingestion_state"] == "RECOVERY_REQUIRED"
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "PRE_PUSH_FAILURE_COMMIT_LOCAL_ONLY",
        "injected_at_state_transition": "RESULT_COMMITTED -> (push never executed)",
        "observed": observed,
        "error_signature": error_signature(observed["ingestion_errors"]),
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_post_push_controller_fetched(root: Path) -> dict[str, Any]:
    """The producer pushes, the report is lost, and the controller has fetched."""
    context = stage(root / "post-push-fetched", "po03-c6-044-post-push-fetched")
    committed = producer_commits(context)
    push = kit.git_attempt(context["producer"], "push", "--quiet", "origin", BRANCH)
    kit.git_attempt(context["controller"], "fetch", "--quiet", "origin")
    ingestion = controller_ingests(context, committed)
    state = context["module"].scan_recovery("c6-sandbox", "0" * 40)
    unit = state["units"][context["task_id"]]
    observed = {
        "push_returncode": push["returncode"],
        "ingestion_state": ingestion["obzio_state"],
        "ingestion_errors": ingestion["errors"],
        "artifact_readback_match": [item["match"] for item in ingestion["artifact_readback"]],
        "recovery_action": unit["recovery_action"],
        "scanner_sees_ingested_result": unit["ingested"],
        "false_completion_count": state["false_completion_count"],
    }
    passed = (
        push["returncode"] == 0
        and observed["ingestion_state"] == "PARENT_INGESTED"
        and observed["ingestion_errors"] == []
        and all(observed["artifact_readback_match"])
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "POST_PUSH_REPORT_LOST_CONTROLLER_ALREADY_FETCHED",
        "injected_at_state_transition": "RESULT_COMMITTED -> pushed -> (report lost)",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_post_push_controller_not_fetched(root: Path) -> dict[str, Any]:
    """The producer pushes, the report is lost, and the controller never fetches."""
    context = stage(root / "post-push-unfetched", "po03-c6-044-post-push-unfetched")
    committed = producer_commits(context)
    push = kit.git_attempt(context["producer"], "push", "--quiet", "origin", BRANCH)
    remote_has = kit.git_attempt(
        context["remote"], "cat-file", "-e", f"{committed['commit']}^{{commit}}"
    )
    ingestion = controller_ingests(context, committed)
    state = context["module"].scan_recovery("c6-sandbox", "0" * 40)
    observed = {
        "push_returncode": push["returncode"],
        "commit_present_on_remote": remote_has["returncode"] == 0,
        "controller_fetched": False,
        "ingestion_state": ingestion["obzio_state"],
        "ingestion_errors": ingestion["errors"],
        "recovery_action": state["units"][context["task_id"]]["recovery_action"],
        "false_completion_count": state["false_completion_count"],
        "mechanism_attempted_a_fetch": False,
    }
    # The bar for this unit is that a pushed-but-unreported result is not lost.
    # It is durable on the remote, but the live mechanism never reaches for it.
    passed = observed["ingestion_state"] == "PARENT_INGESTED"
    return {
        "fault_class": "POST_PUSH_REPORT_LOST_CONTROLLER_NOT_FETCHED",
        "injected_at_state_transition": "RESULT_COMMITTED -> pushed -> (report lost, no fetch)",
        "observed": observed,
        "error_signature": error_signature(observed["ingestion_errors"]),
        "verdict": "PASS" if passed else "FAIL",
    }


def inject_rejected_non_fast_forward_push(root: Path) -> dict[str, Any]:
    """A competing worker advanced the branch, so the producer's push is refused."""
    context = stage(root / "non-fast-forward", "po03-c6-044-rejected-push")
    competitor = context["root"] / "competitor"
    subprocess.run(
        ("git", "clone", "--quiet", "--branch", BRANCH, str(context["remote"]), str(competitor)),
        check=True,
        capture_output=True,
    )
    kit.identify(competitor)
    (competitor / "competitor.txt").write_bytes(b"another worker advanced the branch\n")
    competitor_commit = kit.commit_all(competitor, "po03: competing worker commit")
    kit.git(competitor, "push", "--quiet", "origin", BRANCH)

    committed = producer_commits(context)
    push = kit.git_attempt(context["producer"], "push", "origin", BRANCH)
    remote_tip = kit.git(context["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    ingestion = controller_ingests(context, committed)
    state = context["module"].scan_recovery("c6-sandbox", "0" * 40)
    observed = {
        "push_returncode": push["returncode"],
        "push_rejected": "reject" in push["stderr"].lower(),
        "remote_tip_is_competitor_commit": remote_tip == competitor_commit,
        "producer_bytes_intact_locally": kit.git_bytes(
            context["producer"], "cat-file", "blob", f"{committed['commit']}:{committed['path']}"
        ) == committed["body"],
        "ingestion_state": ingestion["obzio_state"],
        "recovery_action": state["units"][context["task_id"]]["recovery_action"],
        "false_completion_count": state["false_completion_count"],
    }
    passed = (
        observed["push_returncode"] != 0
        and observed["push_rejected"]
        and observed["remote_tip_is_competitor_commit"]
        and observed["ingestion_state"] == "RECOVERY_REQUIRED"
        and observed["producer_bytes_intact_locally"]
        and observed["false_completion_count"] == 0
    )
    return {
        "fault_class": "PUSH_REJECTED_NON_FAST_FORWARD",
        "injected_at_state_transition": "RESULT_COMMITTED -> push refused",
        "observed": observed,
        "verdict": "PASS" if passed else "FAIL",
    }


INJECTIONS = (
    inject_pre_push_failure,
    inject_post_push_controller_fetched,
    inject_post_push_controller_not_fetched,
    inject_rejected_non_fast_forward_push,
)


def inject_all(root: Path) -> dict[str, Any]:
    results = [injection(root) for injection in INJECTIONS]
    by_class = {item["fault_class"]: item for item in results}
    pre_push_signature = by_class["PRE_PUSH_FAILURE_COMMIT_LOCAL_ONLY"]["error_signature"]
    unfetched_signature = by_class["POST_PUSH_REPORT_LOST_CONTROLLER_NOT_FETCHED"]["error_signature"]
    distinguishable = pre_push_signature != unfetched_signature
    false_completions = sum(
        int(item["observed"].get("false_completion_count", 0) or 0) for item in results
    )
    return {
        "unit": "po03-wa-b2e7-044-push-failure-injection",
        "fault_classes": len(results),
        "results": results,
        "pre_push_error_signature": pre_push_signature,
        "post_push_unfetched_error_signature": unfetched_signature,
        "pre_and_post_push_failures_distinguishable_by_the_mechanism": distinguishable,
        "false_completions_observed": false_completions,
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in results) and distinguishable else "FAIL",
        "verdict_basis": (
            "ingest_result reads artifacts with git cat-file in the coordinator's own repository and "
            "never fetches; a result that is durable on the remote but absent locally fails with the "
            "same error as a result that was never pushed at all"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-root", default=None)
    arguments = parser.parse_args(argv)
    if arguments.sandbox_root:
        report = inject_all(Path(arguments.sandbox_root).resolve())
    else:
        with tempfile.TemporaryDirectory() as temporary:
            report = inject_all(Path(temporary))
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
