#!/usr/bin/env python3
"""Recompute source drift lineage from git, then compare independent evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


class ReconciliationError(ValueError):
    """Raised when immutable git lineage cannot be reconstructed."""


def _git(repo: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise ReconciliationError(
            f"git {' '.join(args)} failed: {detail or exc}"
        ) from exc


def _full_commit(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def _assert_ancestor(repo: Path, ancestor: str, descendant: str) -> None:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ReconciliationError(
            f"frozen ref {ancestor} is not an ancestor of current ref {descendant}"
        )


def _tree_blob(repo: Path, commit_sha: str, path: str) -> str | None:
    output = _git(repo, "ls-tree", "-z", commit_sha, "--", path)
    rows = [row for row in output.split(b"\x00") if row]
    if not rows:
        return None
    if len(rows) != 1:
        raise ReconciliationError(
            f"{path}: expected at most one tree entry, found {len(rows)}"
        )
    try:
        metadata, observed_path = rows[0].split(b"\t", 1)
        _mode, object_type, object_id = metadata.decode("ascii").split(" ")
        decoded_path = observed_path.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReconciliationError(f"{path}: malformed git ls-tree output") from exc
    if decoded_path != path or object_type != "blob":
        raise ReconciliationError(f"{path}: tree entry is not the expected blob")
    return object_id


def _blob_sha256(repo: Path, blob_sha: str) -> str:
    return hashlib.sha256(_git(repo, "cat-file", "blob", blob_sha)).hexdigest()


def _source_paths_from_git(
    repo: Path, frozen_commit: str, source_spec_path: str
) -> tuple[list[str], dict[str, str]]:
    raw = _git(repo, "cat-file", "blob", f"{frozen_commit}:{source_spec_path}")
    try:
        spec = json.loads(raw)
        source_hashes = spec["source_hashes"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReconciliationError(
            f"{source_spec_path}: source_hashes cannot be read from frozen git object"
        ) from exc
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ReconciliationError(f"{source_spec_path}: source_hashes must be non-empty")
    if not all(isinstance(path, str) and isinstance(digest, str) for path, digest in source_hashes.items()):
        raise ReconciliationError(f"{source_spec_path}: source_hashes entries are invalid")
    return sorted(source_hashes), source_hashes


def _causal_commits(
    repo: Path, frozen_commit: str, current_commit: str, path: str
) -> list[dict[str, str]]:
    revision_range = f"{frozen_commit}..{current_commit}"
    output = _git(repo, "rev-list", "--reverse", revision_range, "--", path)
    commits = output.decode("ascii").splitlines()
    return [
        {
            "sha": commit,
            "subject": _git(repo, "show", "-s", "--format=%s", commit)
            .decode("utf-8")
            .strip(),
        }
        for commit in commits
    ]


def recompute_lineage(
    repo: Path,
    *,
    frozen_ref: str,
    current_ref: str,
    source_spec_path: str,
) -> dict[str, Any]:
    """Compute every byte and causal commit before any evidence is consulted."""
    frozen_commit = _full_commit(repo, frozen_ref)
    current_commit = _full_commit(repo, current_ref)
    _assert_ancestor(repo, frozen_commit, current_commit)
    paths, declared_hashes = _source_paths_from_git(
        repo, frozen_commit, source_spec_path
    )
    drifted: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    frozen_spec_discrepancies: list[dict[str, str]] = []
    for path in paths:
        frozen_blob = _tree_blob(repo, frozen_commit, path)
        current_blob = _tree_blob(repo, current_commit, path)
        if frozen_blob is None or current_blob is None:
            missing.append(
                {
                    "path": path,
                    "frozen_blob_sha": frozen_blob,
                    "current_blob_sha": current_blob,
                }
            )
            continue
        frozen_sha256 = _blob_sha256(repo, frozen_blob)
        current_sha256 = _blob_sha256(repo, current_blob)
        if frozen_sha256 != declared_hashes[path]:
            frozen_spec_discrepancies.append(
                {
                    "path": path,
                    "declared_sha256": declared_hashes[path],
                    "computed_sha256": frozen_sha256,
                }
            )
        if frozen_blob != current_blob:
            drifted.append(
                {
                    "path": path,
                    "state": "DRIFTED",
                    "frozen_commit_sha": frozen_commit,
                    "frozen_blob_sha": frozen_blob,
                    "frozen_sha256": frozen_sha256,
                    "current_commit_sha": current_commit,
                    "current_blob_sha": current_blob,
                    "current_sha256": current_sha256,
                    "causal_commits": _causal_commits(
                        repo, frozen_commit, current_commit, path
                    ),
                }
            )
    return {
        "protocol_version": "OBZIO-SOURCE-CAPSULE-LINEAGE-v1",
        "method": "git-history-only",
        "source_spec_git_locator": f"{frozen_commit}:{source_spec_path}",
        "frozen_commit_sha": frozen_commit,
        "current_commit_sha": current_commit,
        "source_count": len(paths),
        "drift_count": len(drifted),
        "missing_count": len(missing),
        "frozen_spec_discrepancies": frozen_spec_discrepancies,
        "missing_sources": missing,
        "drifted_sources": drifted,
    }


def _add_discrepancy(
    discrepancies: list[dict[str, Any]],
    *,
    path: str,
    field: str,
    computed: Any,
    evidence: Any,
) -> None:
    discrepancies.append(
        {
            "path": path,
            "field": field,
            "computed": computed,
            "evidence": evidence,
        }
    )


def compare_with_evidence(
    computed: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Compare immutable values; never rewrite either side to make them agree."""
    computed_rows = {
        row["path"]: row for row in computed.get("drifted_sources", [])
    }
    evidence_rows = {
        row["path"]: row for row in evidence.get("drifted_sources", [])
    }
    discrepancies: list[dict[str, Any]] = []
    for path in sorted(set(computed_rows) | set(evidence_rows)):
        computed_row = computed_rows.get(path)
        evidence_row = evidence_rows.get(path)
        if computed_row is None or evidence_row is None:
            _add_discrepancy(
                discrepancies,
                path=path,
                field="drift_presence",
                computed=computed_row is not None,
                evidence=evidence_row is not None,
            )
            continue
        for field in ("state", "frozen_sha256", "current_sha256"):
            if computed_row.get(field) != evidence_row.get(field):
                _add_discrepancy(
                    discrepancies,
                    path=path,
                    field=field,
                    computed=computed_row.get(field),
                    evidence=evidence_row.get(field),
                )
        computed_commits = computed_row.get("causal_commits", [])
        evidence_commits = evidence_row.get("causal_commits", [])
        if len(computed_commits) != len(evidence_commits):
            _add_discrepancy(
                discrepancies,
                path=path,
                field="causal_commits.length",
                computed=len(computed_commits),
                evidence=len(evidence_commits),
            )
        for index, (computed_commit, evidence_commit) in enumerate(
            zip(computed_commits, evidence_commits)
        ):
            evidence_sha = evidence_commit.get("sha")
            computed_sha = computed_commit.get("sha")
            if (
                not isinstance(evidence_sha, str)
                or not isinstance(computed_sha, str)
                or not computed_sha.startswith(evidence_sha)
            ):
                _add_discrepancy(
                    discrepancies,
                    path=path,
                    field=f"causal_commits[{index}].sha",
                    computed=computed_sha,
                    evidence=evidence_sha,
                )
            if computed_commit.get("subject") != evidence_commit.get("subject"):
                _add_discrepancy(
                    discrepancies,
                    path=path,
                    field=f"causal_commits[{index}].subject",
                    computed=computed_commit.get("subject"),
                    evidence=evidence_commit.get("subject"),
                )
    return {
        "protocol_version": "OBZIO-SOURCE-CAPSULE-RECONCILIATION-v1",
        "computed_frozen_commit_sha": computed.get("frozen_commit_sha"),
        "computed_current_commit_sha": computed.get("current_commit_sha"),
        "compared_drift_count": len(set(computed_rows) | set(evidence_rows)),
        "compared_fields": [
            "drift presence",
            "state",
            "frozen_sha256",
            "current_sha256",
            "ordered causal commit SHA and subject",
        ],
        "evidence_only_fields_not_inferred_from_git": ["legitimate", "note"],
        "agrees": not discrepancies,
        "discrepancies": discrepancies,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"{path}: root must be an object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    recompute = subparsers.add_parser("recompute")
    recompute.add_argument("--repo", type=Path, required=True)
    recompute.add_argument("--frozen-ref", required=True)
    recompute.add_argument("--current-ref", required=True)
    recompute.add_argument("--source-spec", required=True)
    recompute.add_argument("--output", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--computed", type=Path, required=True)
    compare.add_argument("--evidence", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "recompute":
            value = recompute_lineage(
                args.repo,
                frozen_ref=args.frozen_ref,
                current_ref=args.current_ref,
                source_spec_path=args.source_spec,
            )
            _write(args.output, value)
            print(
                f"WROTE {args.output} drift={value['drift_count']} "
                f"missing={value['missing_count']} method=git-history-only"
            )
            return 0 if not value["missing_sources"] else 4

        computed = _load_json(args.computed)
        evidence = _load_json(args.evidence)
        value = compare_with_evidence(computed, evidence)
        _write(args.output, value)
        print(
            f"WROTE {args.output} agrees={str(value['agrees']).lower()} "
            f"discrepancies={len(value['discrepancies'])}"
        )
        return 0 if value["agrees"] else 5
    except ReconciliationError as exc:
        print(f"INVALID: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
