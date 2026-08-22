#!/usr/bin/env python3
"""Rank evidence-backed repository opportunities at an immutable Git commit.

The candidate vocabulary and score are frozen in a fixture.  This executable
only measures that fixture against blobs at ``source_base``; it never treats
its own output, proposal text, or the mutable working tree as evidence.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


OWNED_PREFIX = "workstreams/po03/wave-a/units/wa-021/"
PROTOCOL = "PO03-OPPORTUNITY-SCANNER-v1"
FIXTURE_PROTOCOL = "PO03-OPPORTUNITY-SCORING-FIXTURE-v1"
SCORE_WEIGHTS = {
    "recurrence": 25,
    "missing_recurrence_test": 25,
    "leverage": 25,
    "traceability": 15,
    "actionability": 10,
}


class ScannerError(RuntimeError):
    """Raised for invalid fixtures or unavailable immutable evidence."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GitSnapshot:
    """Read-only access to one exact Git tree."""

    def __init__(self, repo: Path, commit: str) -> None:
        self.repo = repo.resolve()
        self.commit = commit
        resolved = self._git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
        if resolved != commit:
            raise ScannerError(
                f"source_base must be a full immutable commit: expected {commit}, resolved {resolved}"
            )
        raw_paths = self._git("ls-tree", "-r", "--name-only", commit)
        self.paths = tuple(raw_paths.decode("utf-8").splitlines())
        self._blob_cache: dict[str, bytes] = {}

    def _git(self, *args: str, check: bool = True) -> bytes:
        process = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and process.returncode:
            detail = process.stderr.decode("utf-8", errors="replace").strip()
            raise ScannerError(f"git {' '.join(args)} failed: {detail}")
        return process.stdout

    def matching_paths(self, pattern: str) -> list[str]:
        return sorted(path for path in self.paths if fnmatch.fnmatchcase(path, pattern))

    def blob(self, path: str) -> bytes:
        if path not in self.paths:
            raise ScannerError(f"evidence path absent at source_base: {path}")
        if path not in self._blob_cache:
            self._blob_cache[path] = self._git("show", f"{self.commit}:{path}")
        return self._blob_cache[path]

    def text(self, path: str) -> str:
        try:
            return self.blob(path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ScannerError(f"evidence path is not UTF-8: {path}") from exc

    def object_is_commit(self, object_id: str) -> bool:
        process = subprocess.run(
            ["git", "cat-file", "-e", f"{object_id}^{{commit}}"],
            cwd=self.repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return process.returncode == 0

    def source_record(self, path: str) -> dict[str, Any]:
        data = self.blob(path)
        return {"path": path, "sha256": sha256_bytes(data), "bytes": len(data)}


def nested_value(document: Any, dotted_field: str) -> Any:
    value = document
    for segment in dotted_field.split("."):
        if not isinstance(value, dict) or segment not in value:
            raise KeyError(dotted_field)
        value = value[segment]
    return value


def scaled_points(count: int, maximum: int) -> int:
    """Map an observed population to frozen 1/2/4/8/16 thresholds."""
    if count >= 16:
        return maximum
    if count >= 8:
        return maximum * 4 // 5
    if count >= 4:
        return maximum * 3 // 5
    if count >= 2:
        return maximum * 2 // 5
    if count >= 1:
        return maximum // 5
    return 0


def evaluate_rule(snapshot: GitSnapshot, rule: dict[str, Any]) -> dict[str, Any]:
    rule_type = rule["type"]
    sources: list[dict[str, Any]] = []
    observed_count = 0
    passed = False
    detail: dict[str, Any] = {}

    if rule_type == "glob_count":
        paths = snapshot.matching_paths(rule["path_glob"])
        if "content_regex" in rule:
            expression = re.compile(rule["content_regex"], re.IGNORECASE | re.MULTILINE)
            paths = [path for path in paths if expression.search(snapshot.text(path))]
        observed_count = len(paths)
        passed = observed_count >= rule["minimum"]
        sources = [snapshot.source_record(path) for path in paths]
        detail = {"minimum": rule["minimum"], "matching_paths": paths}

    elif rule_type == "file_regex":
        path = rule["path"]
        text = snapshot.text(path)
        matched = bool(re.search(rule["regex"], text, re.IGNORECASE | re.MULTILINE))
        expectation = rule["expect"]
        passed = matched if expectation == "present" else not matched
        observed_count = 1 if matched else 0
        sources = [snapshot.source_record(path)]
        detail = {"expect": expectation, "regex_matched": matched}

    elif rule_type == "glob_regex":
        expression = re.compile(rule["regex"], re.IGNORECASE | re.MULTILINE)
        candidate_paths = snapshot.matching_paths(rule["path_glob"])
        paths = [path for path in candidate_paths if expression.search(snapshot.text(path))]
        observed_count = len(paths)
        passed = observed_count >= rule["minimum_distinct_files"]
        sources = [snapshot.source_record(path) for path in paths]
        detail = {
            "minimum_distinct_files": rule["minimum_distinct_files"],
            "matching_paths": paths,
        }

    elif rule_type == "json_field_unresolvable":
        matching: list[dict[str, str]] = []
        parse_failures: list[str] = []
        for path in snapshot.matching_paths(rule["path_glob"]):
            try:
                document = json.loads(snapshot.text(path))
                object_id = nested_value(document, rule["field"])
            except (json.JSONDecodeError, KeyError):
                parse_failures.append(path)
                continue
            if isinstance(object_id, str) and not snapshot.object_is_commit(object_id):
                matching.append({"path": path, "object_id": object_id})
        observed_count = len(matching)
        passed = observed_count >= rule["minimum"]
        sources = [snapshot.source_record(item["path"]) for item in matching]
        detail = {
            "field": rule["field"],
            "minimum": rule["minimum"],
            "unresolvable": matching,
            "parse_or_field_failures": parse_failures,
        }

    elif rule_type == "no_evidence":
        detail = {"reason": rule["reason"]}
        passed = False

    else:
        raise ScannerError(f"unsupported rule type: {rule_type}")

    return {
        "evidence_id": rule["evidence_id"],
        "claim": rule["claim"],
        "type": rule_type,
        "mode": rule.get("mode", "required"),
        "roles": rule.get("roles", []),
        "passed": passed,
        "observed_count": observed_count,
        "sources": sources,
        "detail": detail,
    }


def validate_fixture(fixture: dict[str, Any]) -> None:
    if fixture.get("protocol_version") != FIXTURE_PROTOCOL:
        raise ScannerError("unsupported scoring fixture protocol")
    if fixture.get("scoring", {}).get("weights") != SCORE_WEIGHTS:
        raise ScannerError("fixture score weights differ from the scanner's frozen model")
    if fixture.get("scoring", {}).get("eligibility_threshold") != 55:
        raise ScannerError("fixture eligibility threshold must remain 55")
    if sum(SCORE_WEIGHTS.values()) != 100:
        raise ScannerError("internal scoring weights do not sum to 100")
    candidates = fixture.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ScannerError("fixture must contain candidates")
    candidate_ids = [candidate.get("candidate_id") for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ScannerError("candidate ids must be unique")


def score_candidate(
    snapshot: GitSnapshot, candidate: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    observations = [evaluate_rule(snapshot, rule) for rule in candidate["evidence_rules"]]
    required = [item for item in observations if item["mode"] == "required"]
    exclusions = [item for item in observations if item["mode"] == "reject_if_pass"]

    reasons: list[str] = []
    declared_sources = candidate.get("declared_source_paths", [])
    if any(path.startswith(OWNED_PREFIX) for path in declared_sources):
        reasons.append("CIRCULAR_EVIDENCE")
    if not required:
        reasons.append("UNSUPPORTED_NO_REQUIRED_EVIDENCE")
    if any(not item["passed"] for item in required):
        reasons.append("UNSUPPORTED_REQUIRED_EVIDENCE_FAILED")
    if any(item["passed"] for item in exclusions):
        reasons.append("ALREADY_NAMED_WORK")
    if any(
        source["path"].startswith(OWNED_PREFIX)
        for observation in observations
        for source in observation["sources"]
    ):
        reasons.append("CIRCULAR_EVIDENCE")

    recurrence_count = max(
        (
            item["observed_count"]
            for item in required
            if item["passed"] and "recurrence" in item["roles"]
        ),
        default=0,
    )
    leverage_count = max(
        (
            item["observed_count"]
            for item in required
            if item["passed"] and "leverage" in item["roles"]
        ),
        default=0,
    )
    test_gap = any(
        item["passed"] and "missing_recurrence_test" in item["roles"] for item in required
    )
    independent_paths = sorted(
        {
            source["path"]
            for item in required
            if item["passed"]
            for source in item["sources"]
        }
    )
    if required and len(independent_paths) < 2:
        reasons.append("INSUFFICIENT_INDEPENDENT_SOURCE_PATHS")

    targets = candidate.get("action_targets", [])
    actionable = bool(targets) and all(target in snapshot.paths for target in targets)
    score_components = {
        "recurrence": scaled_points(recurrence_count, SCORE_WEIGHTS["recurrence"]),
        "missing_recurrence_test": (
            SCORE_WEIGHTS["missing_recurrence_test"] if test_gap else 0
        ),
        "leverage": scaled_points(leverage_count, SCORE_WEIGHTS["leverage"]),
        "traceability": min(
            SCORE_WEIGHTS["traceability"],
            5 * sum(1 for item in required if item["passed"] and item["sources"]),
        ),
        "actionability": SCORE_WEIGHTS["actionability"] if actionable else 0,
    }
    score = sum(score_components.values())
    if score < 55:
        reasons.append("BELOW_FROZEN_THRESHOLD")

    reasons = sorted(set(reasons))
    disposition = "ELIGIBLE_UNNAMED_OPPORTUNITY" if not reasons else "REJECTED"
    record = {
        "candidate_id": candidate["candidate_id"],
        "title": candidate["title"],
        "opportunity_type": candidate["opportunity_type"],
        "hypothesis": candidate["hypothesis"],
        "disposition": disposition,
        "rejection_reasons": reasons,
        "score": score,
        "score_components": score_components,
        "measurements": {
            "recurrence_count": recurrence_count,
            "leverage_population": leverage_count,
            "missing_recurrence_test": test_gap,
            "independent_source_path_count": len(independent_paths),
            "action_targets_exist": actionable,
        },
        "action_targets": targets,
        "evidence_ids": [item["evidence_id"] for item in observations],
        "source_paths": independent_paths,
    }
    return record, observations


def scan(repo: Path, fixture_path: Path) -> dict[str, Any]:
    fixture_bytes = fixture_path.read_bytes()
    fixture = json.loads(fixture_bytes)
    if not isinstance(fixture, dict):
        raise ScannerError("fixture root must be an object")
    validate_fixture(fixture)
    snapshot = GitSnapshot(repo, fixture["source_base"])
    try:
        fixture_display_path = fixture_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        fixture_display_path = fixture_path.as_posix()

    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    source_claims: list[dict[str, Any]] = []
    for candidate in fixture["candidates"]:
        record, candidate_observations = score_candidate(snapshot, candidate)
        observations.extend(candidate_observations)
        if record["disposition"] == "ELIGIBLE_UNNAMED_OPPORTUNITY":
            eligible.append(record)
        else:
            rejected.append(record)
        for observation in candidate_observations:
            if observation["mode"] == "required" and observation["passed"]:
                source_claims.append(
                    {
                        "claim_id": f"SC-{observation['evidence_id']}",
                        "state": "SOURCE_CLAIM",
                        "statement": observation["claim"],
                        "source_commit": snapshot.commit,
                        "observed_count": observation["observed_count"],
                        "sources": observation["sources"],
                    }
                )

    eligible.sort(key=lambda item: (-item["score"], item["candidate_id"]))
    rejected.sort(key=lambda item: (-item["score"], item["candidate_id"]))
    for rank, item in enumerate(eligible, start=1):
        item["rank"] = rank

    outcome = "SUPPORTED" if eligible else "REFUTED"
    return {
        "protocol_version": PROTOCOL,
        "state": "REPRODUCTION_RESULT",
        "task_id": fixture["task_id"],
        "hypothesis_id": fixture["hypothesis_id"],
        "falsifiable_hypothesis": fixture["falsifiable_hypothesis"],
        "hypothesis_outcome": outcome,
        "outcome_rule": fixture["outcome_rule"],
        "source_base": snapshot.commit,
        "fixture": {
            "path": fixture_display_path,
            "sha256": sha256_bytes(fixture_bytes),
            "frozen_at": fixture["frozen_at"],
        },
        "scoring": fixture["scoring"],
        "summary": {
            "candidate_count": len(fixture["candidates"]),
            "eligible_count": len(eligible),
            "rejected_count": len(rejected),
            "source_claim_count": len(source_claims),
        },
        "ranked_opportunities": eligible,
        "rejected_candidates": rejected,
        "source_claims": source_claims,
        "evidence_observations": observations,
        "separation": {
            "source_claims": "sources/source-claims.json",
            "hypotheses": "hypotheses/hypotheses.json",
            "reproduction": "reproductions/reproduction.json",
            "mechanism_changes": "proposals/mechanism-changes.json",
            "strategy_proposals": "proposals/strategy-proposals.json",
        },
        "decision_changed": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-determinism", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = scan(args.repo, args.fixture)
        encoded = canonical_json_bytes(report)
        if args.check_determinism:
            second = canonical_json_bytes(scan(args.repo, args.fixture))
            if encoded != second:
                raise ScannerError("same snapshot and fixture produced different bytes")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(encoded)
        else:
            sys.stdout.buffer.write(encoded)
    except (OSError, json.JSONDecodeError, ScannerError) as exc:
        print(f"OPPORTUNITY_SCANNER_ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
