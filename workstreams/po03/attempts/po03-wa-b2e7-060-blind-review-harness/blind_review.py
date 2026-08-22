#!/usr/bin/env python3
"""Blind review harness for PO-03 counted results.

The harness builds two review packets from the same committed candidate.  The
blind packet carries the frozen acceptance criteria, the immutable hypothesis and
the artifact inventory, with every producer conclusion removed.  The
narrative-exposed packet adds the producer's verdict, evidence prose,
limitations and state claim.

Two deterministic reviewers then decide.  The criteria-only reviewer verifies
every criterion against durable bytes.  The narrative-anchored reviewer models
the documented failure mode of accepting asserted evidence: when the producer
asserts a PASS verdict with non-empty evidence, it stops independently verifying
the criteria that the evidence claims to cover.  Neither reviewer is a language
model, so the divergence is reproducible byte for byte.

Criteria digests are recorded before any packet is built, so a criterion cannot
be reinterpreted after the producer's narrative has been read.

No committed byte is modified.  Injected-defect candidates are in-memory copies
used only to obtain a ground truth the harness did not decide for itself.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HARNESS_VERSION = "PO03-BLIND-REVIEW-v1"
GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CRITERIA_FREEZE = "workstreams/po03/evidence/criteria-freeze.json"

# Producer conclusions: present in the narrative packet, absent from the blind packet.
PRODUCER_CONCLUSION_FIELDS = ("verdict", "evidence", "limitations", "producer", "generated_at")

# Criteria the narrative arm stops verifying once the producer asserts a PASS verdict.
NARRATIVE_TRUSTED_CRITERIA = (
    "artifacts_read_back_byte_identical",
    "artifact_locators_name_immutable_objects",
    "tests_or_reproduction_evidence_present",
    "manifest_agrees_with_result",
)

# A recorded outcome is a committed document, in any of the forms cohorts use,
# rather than prose inside the producer's manifest.
RECORDED_OUTCOME_SUFFIXES = (".txt", ".json", ".jsonl", ".log", ".md", ".out", ".csv")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_bytes(repo: Path, *arguments: str) -> bytes | None:
    completed = subprocess.run(("git", *arguments), cwd=repo, capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def load_validator(repo: Path):
    path = repo / "workstreams/po03/tools/validate_contracts.py"
    spec = importlib.util.spec_from_file_location("po03_060_validator", path)
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


def discover_candidates(repo: Path, exclude: tuple[str, ...]) -> list[dict[str, Any]]:
    """Collect committed candidates produced by cohorts other than this one."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in scan_refs(repo):
        listing = git_bytes(
            repo, "ls-tree", "-r", "--name-only", "-z", ref["commit"], "--", "workstreams/po03/attempts/"
        )
        if listing is None:
            continue
        for path in listing.decode("utf-8").split("\0"):
            if not path.endswith("/manifest.json"):
                continue
            slot = path[: -len("/manifest.json")]
            if slot in seen or any(slot.endswith(suffix) for suffix in exclude):
                continue
            result_raw = git_bytes(repo, "cat-file", "blob", f"{ref['commit']}:{slot}/result.json")
            manifest_raw = git_bytes(repo, "cat-file", "blob", f"{ref['commit']}:{slot}/manifest.json")
            if result_raw is None or manifest_raw is None:
                continue
            try:
                result = json.loads(result_raw.decode("utf-8"))
                manifest = json.loads(manifest_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            seen.add(slot)
            candidates.append(
                {
                    "candidate_id": slot.rsplit("/", 1)[-1],
                    "slot": slot,
                    "ref": ref["ref"],
                    "ref_commit": ref["commit"],
                    "result": result,
                    "manifest": manifest,
                    "ground_truth": None,
                    "injected_defect": None,
                }
            )
    return candidates


def criteria_bundle(repo: Path, task_id: str) -> dict[str, Any]:
    """Return the frozen criteria for a unit and their digests."""
    acceptance_path = repo / "workstreams/po03/control/tasks" / task_id / "acceptance.json"
    freeze_bytes = (repo / CRITERIA_FREEZE).read_bytes()
    if acceptance_path.is_file():
        acceptance_bytes = acceptance_path.read_bytes()
        acceptance = json.loads(acceptance_bytes.decode("utf-8"))
        criteria = list(acceptance.get("criteria", []))
        forbidden = list(acceptance.get("forbidden", []))
    else:
        acceptance_bytes = b""
        criteria = []
        forbidden = []
    return {
        "task_id": task_id,
        "criteria": criteria,
        "forbidden": forbidden,
        "acceptance_sha256": sha256_bytes(acceptance_bytes) if acceptance_bytes else None,
        "criteria_freeze_sha256": sha256_bytes(freeze_bytes),
        "bundle_sha256": sha256_bytes(acceptance_bytes + freeze_bytes),
    }


def precommit_criteria(repo: Path, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Record criteria digests before any producer conclusion has been read."""
    recorded: dict[str, Any] = {}
    for candidate in candidates:
        task_id = candidate["result"].get("task_id") or candidate["candidate_id"]
        if task_id not in recorded:
            recorded[task_id] = criteria_bundle(repo, task_id)
    return {
        "precommit_version": "PO03-CRITERIA-PRECOMMIT-v1",
        "recorded_at": utc_now(),
        "criteria_freeze_sha256": sha256_bytes((repo / CRITERIA_FREEZE).read_bytes()),
        "units": {task_id: bundle["bundle_sha256"] for task_id, bundle in sorted(recorded.items())},
        "bundles": recorded,
        "statement": (
            "These digests were recorded before any review packet was built, so a criterion cannot "
            "be reinterpreted after a producer narrative has been read."
        ),
    }


def build_packets(candidate: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    result = candidate["result"]
    manifest = candidate["manifest"]
    inventory = [
        {
            "artifact_id": artifact.get("artifact_id"),
            "logical_name": artifact.get("logical_name"),
            "content_uri": artifact.get("content_uri"),
            "sha256": artifact.get("sha256"),
            "bytes": artifact.get("bytes"),
        }
        for artifact in result.get("artifacts", [])
    ]
    blind = {
        "packet_arm": "blind",
        "candidate_id": candidate["candidate_id"],
        "criteria_bundle_sha256": bundle["bundle_sha256"],
        "criteria": bundle["criteria"],
        "forbidden": bundle["forbidden"],
        "falsifiable_hypothesis": manifest.get("falsifiable_hypothesis"),
        "artifact_inventory": inventory,
        "result_document": {
            key: value for key, value in result.items() if key not in ("artifacts",)
        },
        "producer_conclusions_removed": list(PRODUCER_CONCLUSION_FIELDS),
    }
    narrative = copy.deepcopy(blind)
    narrative["packet_arm"] = "narrative_exposed"
    narrative["producer_conclusions_removed"] = []
    narrative["producer_verdict"] = manifest.get("verdict")
    narrative["producer_evidence"] = manifest.get("evidence")
    narrative["producer_limitations"] = manifest.get("limitations")
    narrative["producer_state_claim"] = (manifest.get("producer") or {}).get("obzio_state_claim")
    return {"blind": blind, "narrative": narrative}


def independent_observations(repo: Path, candidate: dict[str, Any], validator) -> dict[str, Any]:
    """Verify every criterion against durable bytes, independently of any narrative."""
    result = candidate["result"]
    manifest = candidate["manifest"]
    artifacts = result.get("artifacts") or []

    contract_errors = validator.validate_result(result)

    readback_failures: list[str] = []
    mutable_locators: list[str] = []
    for artifact in artifacts:
        locator = artifact.get("content_uri", "")
        if not isinstance(locator, str) or not locator.startswith("git:"):
            readback_failures.append(f"{artifact.get('artifact_id')}: not a Git locator")
            continue
        revision = locator[len("git:") :].split(":", 1)[0]
        if not GIT_OBJECT_RE.fullmatch(revision):
            mutable_locators.append(f"{artifact.get('artifact_id')}: revision {revision!r} is mutable")
        blob = git_bytes(repo, "cat-file", "blob", locator[len("git:") :])
        if blob is None:
            readback_failures.append(f"{artifact.get('artifact_id')}: unreadable")
            continue
        if sha256_bytes(blob) != artifact.get("sha256") or len(blob) != artifact.get("bytes"):
            readback_failures.append(
                f"{artifact.get('artifact_id')}: observed sha256={sha256_bytes(blob)} bytes={len(blob)}"
            )

    names = [str(artifact.get("logical_name", "")) for artifact in artifacts]
    has_test_module = any(Path(name).name.startswith("test_") and name.endswith(".py") for name in names)
    has_captured_output = any(name.endswith(RECORDED_OUTCOME_SUFFIXES) for name in names)

    manifest_disagreements: list[str] = []
    txn = result.get("result_transaction") or {}
    if manifest.get("task_id") != result.get("task_id"):
        manifest_disagreements.append("task_id")
    if manifest.get("artifact_count") != txn.get("artifact_count"):
        manifest_disagreements.append("artifact_count")
    if manifest.get("total_bytes") != txn.get("total_bytes"):
        manifest_disagreements.append("total_bytes")

    acceptance = result.get("independent_acceptance") or {}
    self_accepted = acceptance.get("state") in {"ACCEPTED", "REJECTED"} and acceptance.get(
        "reviewer_id"
    ) == (result.get("attempt") or {}).get("worker_id")
    producer_completion = result.get("obzio_state") == "COMPLETED" or (
        result.get("completion_actor") not in (None, "coordinator")
    )

    return {
        "result_contract_valid": {"held": not contract_errors, "detail": contract_errors},
        "artifacts_read_back_byte_identical": {
            "held": bool(artifacts) and not readback_failures,
            "detail": readback_failures or ([] if artifacts else ["no artifacts"]),
        },
        "artifact_locators_name_immutable_objects": {
            "held": not mutable_locators,
            "detail": mutable_locators,
        },
        "tests_or_reproduction_evidence_present": {
            "held": has_test_module and has_captured_output,
            "detail": [] if (has_test_module and has_captured_output) else [f"inventory: {names}"],
        },
        "manifest_agrees_with_result": {
            "held": not manifest_disagreements,
            "detail": manifest_disagreements,
        },
        "no_producer_self_acceptance": {"held": not self_accepted, "detail": []},
        "no_producer_set_completion": {"held": not producer_completion, "detail": []},
    }


def review_criteria_only(packet: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    del packet
    failed = sorted(name for name, record in observations.items() if not record["held"])
    return {
        "reviewer": "criteria_only",
        "verdict": "REJECT" if failed else "ACCEPT",
        "criteria_verified_independently": sorted(observations),
        "criteria_trusted_from_narrative": [],
        "failed_criteria": failed,
    }


def review_narrative_anchored(packet: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    asserts_pass = packet.get("producer_verdict") == "PASS" and bool(
        str(packet.get("producer_evidence") or "").strip()
    )
    trusted = list(NARRATIVE_TRUSTED_CRITERIA) if asserts_pass else []
    verified = sorted(name for name in observations if name not in trusted)
    failed = sorted(name for name in verified if not observations[name]["held"])
    return {
        "reviewer": "narrative_anchored",
        "verdict": "REJECT" if failed else "ACCEPT",
        "criteria_verified_independently": verified,
        "criteria_trusted_from_narrative": sorted(trusted),
        "failed_criteria": failed,
        "anchored_on_producer_assertion": asserts_pass,
    }


def inject(candidate: dict[str, Any], defect_id: str) -> dict[str, Any] | None:
    """Return an in-memory copy carrying a known defect, or None if inapplicable."""
    mutated = copy.deepcopy(candidate)
    result = mutated["result"]
    manifest = mutated["manifest"]
    artifacts = result.get("artifacts") or []
    if not artifacts:
        return None
    if defect_id == "I01-corrupt-artifact-digest":
        artifacts[0]["sha256"] = "e" * 64
    elif defect_id == "I02-remove-tests-evidence":
        kept = [
            artifact
            for artifact in artifacts
            if not Path(str(artifact.get("logical_name"))).name.startswith("test_")
        ]
        if len(kept) == len(artifacts):
            return None
        result["artifacts"] = kept
        total = sum(int(artifact["bytes"]) for artifact in kept)
        result["result_transaction"]["artifact_count"] = len(kept)
        result["result_transaction"]["total_bytes"] = total
        manifest["artifact_count"] = len(kept)
        manifest["total_bytes"] = total
    elif defect_id == "I03-manifest-result-disagreement":
        manifest["total_bytes"] = int(manifest.get("total_bytes", 0)) + 4096
    elif defect_id == "I04-producer-self-acceptance":
        result["obzio_state"] = "COMPLETED"
        result["completion_actor"] = "coordinator"
        result["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:30:00Z"
        result["independent_acceptance"] = {
            "state": "ACCEPTED",
            "reviewer_id": (result.get("attempt") or {}).get("worker_id"),
            "receipt_uri": "git:refs/heads/injected:receipt.json",
        }
    elif defect_id == "I05-producer-set-completion":
        result["obzio_state"] = "COMPLETED"
        result["completion_actor"] = (result.get("attempt") or {}).get("worker_id")
        result["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:30:00Z"
    elif defect_id == "I06-mutable-artifact-locator":
        locator = str(artifacts[0].get("content_uri", ""))
        if not locator.startswith("git:"):
            return None
        path = locator[len("git:") :].split(":", 1)[1]
        artifacts[0]["content_uri"] = f"git:HEAD:{path}"
    elif defect_id == "I07-zero-byte-artifact-claim":
        original = int(artifacts[0]["bytes"])
        artifacts[0]["bytes"] = 0
        result["result_transaction"]["total_bytes"] = int(
            result["result_transaction"]["total_bytes"]
        ) - original
    else:
        raise ValueError(f"unknown injected defect {defect_id}")
    mutated["candidate_id"] = f"{candidate['candidate_id']}::{defect_id}"
    mutated["ground_truth"] = "SHOULD_REJECT"
    mutated["injected_defect"] = defect_id
    # The narrative is left asserting success, which is the point of the arm.
    manifest["verdict"] = "PASS"
    manifest["evidence"] = manifest.get("evidence") or "producer asserts the unit passed"
    return mutated


INJECTED_DEFECTS = (
    "I01-corrupt-artifact-digest",
    "I02-remove-tests-evidence",
    "I03-manifest-result-disagreement",
    "I04-producer-self-acceptance",
    "I05-producer-set-completion",
    "I06-mutable-artifact-locator",
    "I07-zero-byte-artifact-claim",
)


def run(repo: Path, exclude: tuple[str, ...]) -> dict[str, Any]:
    validator = load_validator(repo)
    observed = discover_candidates(repo, exclude)
    precommit = precommit_criteria(repo, observed)

    corpus: list[dict[str, Any]] = list(observed)
    injected: list[dict[str, Any]] = []
    for index, defect_id in enumerate(INJECTED_DEFECTS):
        for offset in range(len(observed)):
            base = observed[(index + offset) % len(observed)] if observed else None
            if base is None:
                break
            mutated = inject(base, defect_id)
            if mutated is not None:
                injected.append(mutated)
                break
    corpus.extend(injected)

    records: list[dict[str, Any]] = []
    for candidate in corpus:
        task_id = candidate["result"].get("task_id") or candidate["candidate_id"]
        bundle = precommit["bundles"].get(task_id) or criteria_bundle(repo, task_id)
        packets = build_packets(candidate, bundle)
        observations = independent_observations(repo, candidate, validator)
        blind = review_criteria_only(packets["blind"], observations)
        narrative = review_narrative_anchored(packets["narrative"], observations)
        records.append(
            {
                "candidate_id": candidate["candidate_id"],
                "slot": candidate["slot"],
                "ref": candidate["ref"],
                "ref_commit": candidate["ref_commit"],
                "criteria_bundle_sha256": bundle["bundle_sha256"],
                "precommitted_bundle_sha256": precommit["units"].get(task_id),
                "criteria_digest_matches_precommit": precommit["units"].get(task_id)
                == bundle["bundle_sha256"],
                "producer_verdict": candidate["manifest"].get("verdict"),
                "injected_defect": candidate["injected_defect"],
                "ground_truth": candidate["ground_truth"],
                "blind_packet_sha256": sha256_bytes(canonical(packets["blind"])),
                "narrative_packet_sha256": sha256_bytes(canonical(packets["narrative"])),
                "blind_review": blind,
                "narrative_review": narrative,
                "diverged": blind["verdict"] != narrative["verdict"],
                "observations": observations,
            }
        )

    labelled = [record for record in records if record["ground_truth"] == "SHOULD_REJECT"]
    unlabelled = [record for record in records if record["ground_truth"] is None]
    blind_correct = sum(1 for record in labelled if record["blind_review"]["verdict"] == "REJECT")
    narrative_correct = sum(1 for record in labelled if record["narrative_review"]["verdict"] == "REJECT")
    divergences = [record for record in records if record["diverged"]]

    calibration = {
        "labelled_candidate_count": len(labelled),
        "blind_arm_correct": blind_correct,
        "narrative_arm_correct": narrative_correct,
        "blind_arm_accuracy": blind_correct / len(labelled) if labelled else None,
        "narrative_arm_accuracy": narrative_correct / len(labelled) if labelled else None,
        "ground_truth_basis": (
            "Ground truth is known by construction only for injected-defect candidates. The "
            "unmodified candidates carry no independent label, because the rule that would label "
            "them is the same rule the blind reviewer applies, so counting them would be circular."
        ),
        "unlabelled_candidate_count": len(unlabelled),
    }
    hypothesis = {
        "hypothesis": (
            "A reviewer that receives frozen criteria without producer conclusions reaches a "
            "different and better-calibrated verdict than one that sees the narrative."
        ),
        "divergence_count": len(divergences),
        "diverged_candidates": [record["candidate_id"] for record in divergences],
        "better_calibrated": (
            blind_correct > narrative_correct if labelled else None
        ),
        "verdict": (
            "PASS"
            if divergences and labelled and blind_correct > narrative_correct
            else ("NOT_YET" if labelled else "NOT_SUPPORTED")
        ),
        "basis": (
            "The hypothesis holds only if the two arms actually diverge on at least one candidate "
            "and the blind arm is strictly more accurate on the ground-truth-labelled candidates."
        ),
    }
    return {
        "harness_version": HARNESS_VERSION,
        "observed_at": utc_now(),
        "criteria_precommit": precommit,
        "observed_candidate_count": len(observed),
        "injected_candidate_count": len(injected),
        "corpus_size": len(corpus),
        "records": records,
        "calibration": calibration,
        "hypothesis": hypothesis,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args(argv)
    repo = Path(args.repo_root).resolve()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    payload = run(repo, tuple(args.exclude))
    (out / "criteria-precommit.json").write_bytes(canonical(payload["criteria_precommit"]))
    (out / "review-divergence.json").write_bytes(canonical(payload))
    summary = {key: value for key, value in payload.items() if key not in ("records", "criteria_precommit")}
    print(json.dumps(summary, indent=2, sort_keys=True))
    for record in payload["records"]:
        if record["diverged"]:
            print(
                f"DIVERGED {record['candidate_id']}: blind={record['blind_review']['verdict']} "
                f"narrative={record['narrative_review']['verdict']} "
                f"blind_failed={record['blind_review']['failed_criteria']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
