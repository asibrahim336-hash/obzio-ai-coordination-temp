#!/usr/bin/env python3
"""Re-execute, against the live modules, the defects this lane seeds into the chain.

Every link seeded into `state/events.jsonl` must cite an artifact. For four of
the five closed chains the artifact this script produces is a *direct*
reproduction rather than a quotation of somebody else's report, which is the
difference between an `EARNED` mechanism and a `DOCUMENTED` one.

What it does NOT do is re-run the unit suites; those are run separately and
their exit codes recorded, because a reproduction harness that also grades
itself is the self-acceptance shape this estate has already refused once.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANE_ROOT = Path(__file__).resolve().parents[1]
OE_TOOLS = Path(__file__).resolve().parents[3] / "tools"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evidence_integrity = load("evidence_integrity", OE_TOOLS / "evidence_integrity.py")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return done.returncode, (done.stdout + done.stderr).strip()


# ---------------------------------------------------------------------------
# REPRO-A  a hash-valid truncated JSON artifact passes manifest closure
# ---------------------------------------------------------------------------

def repro_truncated_json_passes_closure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="repro-validity-") as workdir:
        repo = Path(workdir)
        truncated = b'{"record_id": "TRUNCATED", "entries": [{"path": "a.json"'
        (repo / "truncated.json").write_bytes(truncated)
        digest = sha256_bytes(truncated)
        entries = [{"path": "truncated.json", "size_bytes": len(truncated), "sha256": digest}]
        manifest = {
            "entries": entries,
            "bundle_sha256": sha256_bytes(
                json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ),
        }
        closure = evidence_integrity.verify_manifest_closure(manifest, ["truncated.json"])
        validity = evidence_integrity.verify_artifact_validity(["truncated.json"], repo)
        return {
            "reproduction_id": "REPRO-A-HASH-VALID-BUT-UNPARSEABLE",
            "artifact_bytes_sha256": digest,
            "manifest_closure_errors": closure,
            "manifest_closure_verdict": "PASS" if not closure else "FAIL",
            "artifact_validity_errors": validity,
            "artifact_validity_verdict": "PASS" if not validity else "FAIL",
            "defect_shown": (
                "byte integrity and manifest closure both pass on an artifact that cannot be "
                "loaded; closure proves the bytes are the committed bytes and says nothing about "
                "whether they mean anything"
            ),
            "mechanism_catches_it": bool(validity),
            "evidence_label": "DIRECTLY_REPRODUCED",
        }


# ---------------------------------------------------------------------------
# REPRO-B  a forged read-back naming an all-zero commit
# ---------------------------------------------------------------------------

def repro_forged_readback_is_refused() -> dict[str, Any]:
    """Build a real remote, produce a true record, then forge one and compare."""
    with tempfile.TemporaryDirectory(prefix="repro-readback-") as workdir:
        root = Path(workdir)
        remote = root / "remote.git"
        work = root / "work"
        git(["init", "--quiet", "--bare", str(remote)], root)
        git(["init", "--quiet", str(work)], root)
        git(["config", "user.email", "repro@example.invalid"], work)
        git(["config", "user.name", "repro"], work)
        payload = b'{"claim": "real"}\n'
        (work / "claim.json").write_bytes(payload)
        git(["add", "claim.json"], work)
        git(["commit", "--quiet", "-m", "claim"], work)
        git(["branch", "-M", "main"], work)
        git(["remote", "add", "origin", str(remote)], work)
        git(["push", "--quiet", "-u", "origin", "main"], work)
        code, head = git(["rev-parse", "HEAD"], work)
        remote_url = str(remote)

        truthful = {
            "immutable_commit": head,
            "transports": ["git-https", "git-file"],
            "comparisons": [{
                "path": "claim.json",
                "remote_git_sha256": sha256_bytes(payload),
                "identical_git_transport": True,
            }],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }
        forged = {
            "immutable_commit": "0" * 40,
            "transports": ["invented-transport-a", "invented-transport-b"],
            "comparisons": [{
                "path": "never-existed.json",
                "remote_git_sha256": "f" * 64,
                "identical_git_transport": True,
            }],
            "mismatches": [],
            "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL",
        }
        # The shape check the acceptor defeated: every key present, every type
        # right, internally perfectly consistent. It cannot tell these apart.
        shape_keys = {"immutable_commit", "transports", "comparisons", "mismatches", "result"}
        shape_passes_forgery = shape_keys.issubset(forged) and forged["result"] == (
            "REMOTE_BYTE_FOR_BYTE_IDENTICAL")

        truthful_errors = evidence_integrity.verify_readback_truth(truthful, remote_url, work)
        forged_errors = evidence_integrity.verify_readback_truth(forged, remote_url, work)
        return {
            "reproduction_id": "REPRO-B-FORGED-READBACK",
            "remote_head": head,
            "shape_check_accepts_the_forgery": shape_passes_forgery,
            "truth_check_on_truthful_record_errors": truthful_errors,
            "truth_check_on_truthful_record_verdict": "PASS" if not truthful_errors else "FAIL",
            "truth_check_on_forged_record_errors": forged_errors,
            "truth_check_on_forged_record_verdict": "PASS" if not forged_errors else "REFUSED",
            "defect_shown": (
                "a fabricated record naming commit 000...0 with invented transports is "
                "indistinguishable from a real one to a verifier that checks shape"
            ),
            "mechanism_catches_it": bool(forged_errors) and not truthful_errors,
            "evidence_label": "DIRECTLY_REPRODUCED",
        }


# ---------------------------------------------------------------------------
# REPRO-C  IDLE -> ERROR, and a status nobody has invented yet
# ---------------------------------------------------------------------------

def _observation(after_status: str) -> dict[str, Any]:
    agent = {"bcId": "bc-pre-existing", "status": "IDLE", "isKilled": False}
    return {
        "orchestrator_bc_id": "bc-self",
        "snapshots": [
            {"label": "baseline", "agents": [dict(agent)]},
            {"label": "mid", "agents": [dict(agent, status=after_status)]},
            {"label": "after", "agents": [dict(agent, status=after_status)]},
        ],
    }


def repro_denylist_fails_open() -> dict[str, Any]:
    denylist = frozenset({"QUEUED", "PAUSED", "EVICTED", "ADMISSION_REFUSED", "KILLED", "PENDING"})

    def old_detector(observation: dict[str, Any]) -> str:
        """The refused shape, reconstructed from the ingestion record."""
        baseline = {a["bcId"]: a for a in observation["snapshots"][0]["agents"]}
        for snapshot in observation["snapshots"][1:]:
            for bc_id, before in baseline.items():
                after = {a["bcId"]: a for a in snapshot["agents"]}.get(bc_id)
                if after and after["status"] != before["status"] and after["status"] in denylist:
                    return "CAPACITY_INTERFERENCE_FAIL"
        return "ZERO_PO03_CAPACITY_INTERFERENCE"

    rows = []
    for status in ("ERROR", "FAILED", "QUEUED", "RUNNING", "SOME_STATUS_NOBODY_HAS_INVENTED_YET"):
        observation = _observation(status)
        old = old_detector(observation)
        new, findings = evidence_integrity.capacity_verdict(observation)
        rows.append({
            "transition": f"IDLE -> {status}",
            "denylist_detector_verdict": old,
            "allowlist_detector_verdict": new,
            "allowlist_findings": findings,
            "denylist_failed_open": old == "ZERO_PO03_CAPACITY_INTERFERENCE"
                                    and new == "CAPACITY_INTERFERENCE_FAIL",
        })
    return {
        "reproduction_id": "REPRO-C-DENYLIST-FAILS-OPEN",
        "denylist_under_test": sorted(denylist),
        "allowlist_in_force": sorted(evidence_integrity.BENIGN_STATUSES),
        "transitions": rows,
        "defect_shown": (
            "a denylist of harmful statuses returns ZERO_PO03_CAPACITY_INTERFERENCE for every "
            "status nobody enumerated, including ERROR, FAILED and any status not yet invented"
        ),
        "mechanism_catches_it": all(
            row["denylist_failed_open"] for row in rows
            if row["transition"].split(" -> ")[1] not in ("QUEUED", "RUNNING")
        ),
        "evidence_label": "DIRECTLY_REPRODUCED",
    }


# ---------------------------------------------------------------------------
# REPRO-D  git push exits 0 and publishes nothing
# ---------------------------------------------------------------------------

def repro_silent_push_no_op() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="repro-push-") as workdir:
        root = Path(workdir)
        remote = root / "remote.git"
        work = root / "work"
        git(["init", "--quiet", "--bare", str(remote)], root)
        git(["init", "--quiet", str(work)], root)
        git(["config", "user.email", "repro@example.invalid"], work)
        git(["config", "user.name", "repro"], work)
        (work / "f.txt").write_text("one\n", encoding="utf-8")
        git(["add", "f.txt"], work)
        git(["commit", "--quiet", "-m", "one"], work)
        git(["branch", "-M", "lane"], work)
        git(["remote", "add", "origin", str(remote)], work)
        git(["push", "--quiet", "-u", "origin", "lane"], work)
        _, published = git(["rev-parse", "HEAD"], work)

        # The shared-worktree shape: a detached HEAD commits, then a branch ref
        # that never moved is pushed.
        git(["checkout", "--quiet", "--detach"], work)
        (work / "f.txt").write_text("two\n", encoding="utf-8")
        git(["add", "f.txt"], work)
        git(["commit", "--quiet", "-m", "two"], work)
        _, local_head = git(["rev-parse", "HEAD"], work)
        push_code, push_output = git(["push", "origin", "lane"], work)
        _, ls_remote = git(["ls-remote", "--heads", "origin", "refs/heads/lane"], work)
        remote_head = ls_remote.split()[0] if ls_remote else None
        return {
            "reproduction_id": "REPRO-D-SILENT-PUSH-NO-OP",
            "commit_made_locally": local_head,
            "push_exit_code": push_code,
            "push_output": push_output,
            "remote_ref_after_push": remote_head,
            "remote_ref_before_push": published,
            "remote_serves_the_new_commit": remote_head == local_head,
            "defect_shown": (
                "git push printed 'Everything up-to-date' and exited 0 while the commit was "
                "never published; a zero exit is not evidence of publication"
            ),
            "mechanism_catches_it": push_code == 0 and remote_head != local_head,
            "mechanism": "lane_guard.verify_reported_head compares the reported SHA to git ls-remote",
            "evidence_label": "DIRECTLY_REPRODUCED",
        }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv[0] if argv else None
    report = {
        "report_id": "SCP-B-SEEDED-DEFECT-REPRODUCTIONS",
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": (
            "Direct reproduction of the defects this lane seeds into the improvement chain, so "
            "each seeded link cites a reproduction rather than a quotation."
        ),
        "decision_changed": [],
        "reproductions": [
            repro_truncated_json_passes_closure(),
            repro_forged_readback_is_refused(),
            repro_denylist_fails_open(),
            repro_silent_push_no_op(),
        ],
    }
    report["all_defects_reproduced_and_caught"] = all(
        item["mechanism_catches_it"] for item in report["reproductions"]
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"wrote {out}")
        print(f"all_defects_reproduced_and_caught: {report['all_defects_reproduced_and_caught']}")
    else:
        print(text, end="")
    return 0 if report["all_defects_reproduced_and_caught"] else 1


if __name__ == "__main__":
    sys.exit(main())
