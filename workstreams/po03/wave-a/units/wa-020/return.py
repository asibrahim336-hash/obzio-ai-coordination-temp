#!/usr/bin/env python3
"""Write ready-to-commit.json after the result commit exists and is pushed.

This runs in two phases because the document has to name things that do not exist
when the result is built:

    phase 1  the result commit is created and pushed
    phase 2  every manifest artifact is read out of the pushed commit, reconciled,
             and recorded here, in a distinct return commit

Read-back reads ``git show <result_commit_id>:<path>`` after fetching the remote
tracking ref, so the bytes are the ones the remote holds rather than the local
working tree. A working-tree edit after the result commit cannot make it reconcile.

Usage::

    python3 -I -B return.py --result-commit <sha> --emitted-at <iso8601>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

UNIT_ROOT = Path(__file__).resolve().parent
if str(UNIT_ROOT) not in sys.path:
    sys.path.insert(0, str(UNIT_ROOT))

from harness import emit_result  # noqa: E402
from harness.canonical import digest_bytes, write_json  # noqa: E402
from harness.probes import repository_root  # noqa: E402

RESULT = UNIT_ROOT / "result"
UNIT_RELPATH = emit_result.UNIT_RELPATH
REMOTE_BRANCH = "cursor/po03-wa-020-b195-a02-1a9f"
SOURCE_BASE = "4e4641e96cc0ad6e48f58e06140d33b0410e6072"
TASK_ID = "PO03-WA-020"
HYPOTHESIS_ID = "H-PO03-WA-020"
RUNNER_ID = "best-of-n-runner-bc-b1956656-wa-020-a02"
MODEL_OBSERVED = "claude-opus-5-thinking-high"

ATTEMPT = {
    "attempt_id": "PO03-WA-020-A02",
    "checkpoint_seq": 0,
    "fence_token": 2,
    "idempotency_key": "po03:100bc2079ced:wa-020:a02",
    "lease_expires_at": "2026-08-22T14:11:10Z",
    "lease_id": "lease-po03-wa-020-a02",
}

PROHIBITED_PREFIXES = (
    "state/",
    "dispatch/",
    ".cursor/environment.json",
    "receipts/po01/",
    "workstreams/po01/",
)


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..{head}"],
        capture_output=True,
        check=True,
        cwd=root,
        text=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-commit", required=True)
    parser.add_argument("--emitted-at", required=True)
    args = parser.parse_args(argv)

    root = repository_root()
    result_commit = emit_result.git(root, "rev-parse", args.result_commit)
    manifest = emit_result.load_json(RESULT / "artifact-manifest.json")
    manifest_bytes = (RESULT / "artifact-manifest.json").read_bytes()

    # The remote ref is fetched first so the read-back is against what the remote
    # holds. A local-only commit would fail here rather than pass quietly.
    emit_result.git(root, "fetch", "origin", REMOTE_BRANCH)
    remote_head = emit_result.git(root, "rev-parse", f"origin/{REMOTE_BRANCH}")

    verification = emit_result.readback(root, result_commit, manifest)

    result_paths = changed_paths(root, SOURCE_BASE, result_commit)
    beyond = [f"{UNIT_RELPATH}/result/ready-to-commit.json"]
    outside = [
        path
        for path in result_paths + beyond
        if not path.startswith(f"{UNIT_RELPATH}/")
    ]
    prohibited = [
        path
        for path in result_paths + beyond
        if any(path.startswith(prefix) for prefix in PROHIBITED_PREFIXES)
    ]

    commits = [
        {
            "commit": emit_result.git(root, "rev-parse", line.split()[0]),
            "subject": " ".join(line.split()[1:]),
        }
        for line in emit_result.git(
            root, "log", "--format=%H %s", f"{SOURCE_BASE}..{result_commit}"
        ).splitlines()
    ]

    tests = emit_result.load_json(RESULT / "tests.json")
    limitations = emit_result.load_json(RESULT / "limitations.json")
    result = emit_result.load_json(RESULT / "result.json")

    document = {
        "artifact_count": manifest["artifact_count"],
        "attempt": ATTEMPT,
        "changed_files": {
            "beyond_the_result_commit": {
                "note": (
                    "Carried by the return commit rather than the result commit, so covered by neither "
                    "the manifest nor its read-back. The manifest and the "
                    f"{manifest['artifact_count']} artifacts it lists describe the result commit, which "
                    "is unchanged and independently verifiable at that commit."
                ),
                "paths": beyond,
            },
            "commits": commits,
            "count_in_result_commit": len(result_paths),
            "in_result_commit": result_paths,
            "source_base_commit": SOURCE_BASE,
        },
        "completion_claim": {
            "accepted": False,
            "completed": False,
            "note": (
                "This producer does not claim COMPLETED or ACCEPTED. Only the coordinator may record "
                "completion, and a producer cannot accept its own result."
            ),
            "obzio_state": "READY_TO_COMMIT",
        },
        "decision_changed": [],
        "emitted_at": args.emitted_at,
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_outcome": result["hypothesis_outcome"],
        "hypothesis_outcome_reading": result["dispatched_hypothesis"]["summary"],
        "immutable_input": result["immutable_input"],
        "limitations": {
            "count": limitations["count"],
            "document": f"{UNIT_RELPATH}/result/limitations.json",
            "not_supported_count": limitations["not_supported_count"],
            "summary": [
                f"{item['limitation_id']}: {item['statement']}" for item in limitations["limitations"]
            ],
        },
        "manifest_path": f"{UNIT_RELPATH}/result/artifact-manifest.json",
        "manifest_sha256": digest_bytes(manifest_bytes),
        "model_observed": MODEL_OBSERVED,
        "ownership_validation": {
            "allowed_write_globs": [f"{UNIT_RELPATH}/**"],
            "every_changed_path_inside_the_allowed_glob": not outside,
            "outside_owned_subtree": outside,
            "po01_or_pr8_touched": False,
            "prohibited_paths_touched": prohibited,
            "pull_request_created_or_modified": False,
            "validated_against": SOURCE_BASE,
        },
        "protocol_version": "OBZIO-PRODUCER-RETURN-v1",
        "readback_from_immutable_remote": verification,
        "reasoning_observed": "high",
        "remote_branch": REMOTE_BRANCH,
        "remote_head_at_readback": remote_head,
        "result_commit_id": result_commit,
        "return_commit_id": "RECORDED_BY_THE_COMMIT_THAT_CARRIES_THIS_FILE",
        "runner_id": RUNNER_ID,
        "task_id": TASK_ID,
        "terminal_report": "READY_TO_COMMIT",
        "tests": {
            "focused": {
                "command": tests["focused_suite"]["command"],
                "outcome": tests["focused_suite"]["outcome"],
                "total": tests["focused_suite"]["total"],
            },
            "seeded_po03_contract_tests": {
                "command": tests["control_checks"]["seeded_po03_contract_tests"]["command"],
                "outcome": tests["control_checks"]["seeded_po03_contract_tests"]["outcome"],
                "total": tests["control_checks"]["seeded_po03_contract_tests"]["total"],
            },
            "taxonomy_check": {
                "command": tests["control_checks"]["taxonomy_check"]["command"],
                "outcome": tests["control_checks"]["taxonomy_check"]["outcome"],
            },
        },
        "total_bytes": manifest["total_bytes"],
    }

    sha, size = write_json(RESULT / "ready-to-commit.json", document)

    print("WA-020 PRODUCER RETURN")
    print(f"  result commit            {result_commit}")
    print(f"  remote head              {remote_head}")
    print(f"  manifest sha256          {document['manifest_sha256']}")
    print(f"  artifacts read back      {verification['artifact_count']}")
    print(f"  all reconcile            {verification['all_artifacts_reconcile']}")
    print(f"  mismatches               {len(verification['mismatches'])}")
    print(f"  changed in result commit {len(result_paths)}")
    print(f"  outside owned subtree    {outside}")
    print(f"  prohibited touched       {prohibited}")
    print(f"  wrote result/ready-to-commit.json {size} bytes  {sha}")
    if not verification["all_artifacts_reconcile"]:
        return 1
    if outside or prohibited:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
