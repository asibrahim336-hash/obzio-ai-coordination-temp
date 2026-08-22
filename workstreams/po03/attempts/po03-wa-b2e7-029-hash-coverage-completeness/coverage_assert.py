#!/usr/bin/env python3
"""Refuse any PO-03 result whose manifest does not hash and count every artifact.

Unit 025 verifies a manifest against a source it generates from.  This unit
audits the manifests the live emitter actually produced, and it treats the
commit as authoritative rather than the manifest's own arithmetic.  For every
slot it enumerates the files the artifact commit really contains, re-reads each
one with `git cat-file`, and refuses the result if a file is uncovered, if a
hash or byte count is absent, malformed or wrong, or if the manifest's totals
disagree with the entries they claim to summarise.

The emitter excludes two generated documents, `manifest.json` and `result.json`,
from the artifacts it counts.  That exclusion is declared here explicitly and is
applied only at the root of a slot: the emitter excludes those names at any
depth, so a payload file at `<slot>/nested/manifest.json` would be committed and
never counted.  This auditor covers such a file and reports it, which is the
gap unit 032 demonstrates adversarially.

Exit codes: 0 coverage total, 1 coverage incomplete, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ATTEMPTS_PREFIX = "workstreams/po03/attempts"
DECLARED_EXCLUSIONS = ("manifest.json", "result.json")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_ARTIFACT_FIELDS = ("artifact_id", "logical_name", "content_uri", "sha256", "bytes")
REQUIRED_MANIFEST_FIELDS = (
    "manifest_version", "task_id", "result_slot", "artifact_commit",
    "artifact_count", "total_bytes", "artifacts",
)


class CoverageError(Exception):
    """Raised when the repository cannot be audited at all."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if not (self.root / "workstreams/po03").is_dir():
            raise CoverageError(f"not a PO-03 repository root: {self.root}")

    def git(self, *arguments: str) -> bytes:
        try:
            return subprocess.run(
                ("git", *arguments), cwd=self.root, check=True, capture_output=True
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise CoverageError(f"git {' '.join(arguments)} failed: {exc}") from exc

    def list_tree(self, commit: str, prefix: str) -> list[str]:
        listing = self.git("ls-tree", "-r", "--name-only", "-z", commit, "--", prefix)
        return sorted(item.decode("utf-8") for item in listing.split(b"\0") if item)

    def read_blob(self, commit: str, path: str) -> bytes | None:
        if path not in self.list_tree(commit, path):
            return None
        return self.git("cat-file", "blob", f"{commit}:{path}")

    def slots(self, commit: str) -> list[str]:
        found: set[str] = set()
        for path in self.list_tree(commit, ATTEMPTS_PREFIX):
            parts = path.split("/")
            if len(parts) > 4:
                found.add("/".join(parts[:4]))
        return sorted(found)


def counted_files(repository: Repository, commit: str, slot: str) -> list[str]:
    """Files the commit holds under a slot that a manifest is required to cover."""
    excluded = {f"{slot}/{name}" for name in DECLARED_EXCLUSIONS}
    return [path for path in repository.list_tree(commit, slot) if path not in excluded]


def audit_documents(
    repository: Repository,
    slot: str,
    manifest: dict,
    raw_manifest: bytes,
    result: dict | None,
) -> tuple[dict, list[str]]:
    """Measure a manifest against the commit it names.

    Documents are passed in rather than read here so that a caller can audit a
    candidate manifest without committing it first.
    """
    findings: list[str] = []
    summary = {"slot": slot, "artifact_commit": None, "covered": 0, "measured_bytes": 0}

    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            findings.append(f"MISSING_FIELD slot={slot} field={field}")
    if findings:
        return summary, findings

    artifact_commit = manifest["artifact_commit"]
    summary["artifact_commit"] = artifact_commit
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        return summary, [f"NO_ARTIFACTS slot={slot}: a counted result must leave durable bytes"]

    covered: set[str] = set()
    entry_bytes = 0
    seen_names: set[str] = set()
    for index, artifact in enumerate(artifacts):
        label = f"slot={slot} index={index}"
        if not isinstance(artifact, dict):
            findings.append(f"ARTIFACT_NOT_AN_OBJECT {label}")
            continue
        absent = [field for field in REQUIRED_ARTIFACT_FIELDS if field not in artifact]
        for field in absent:
            findings.append(f"MISSING_FIELD {label} field={field}")
        if absent:
            continue

        name = artifact["logical_name"]
        if name in seen_names:
            findings.append(f"DUPLICATE_LOGICAL_NAME {label} logical_name={name}")
        seen_names.add(name)

        digest = artifact["sha256"]
        if digest is None or digest == "":
            findings.append(f"HASH_MISSING {label} logical_name={name}")
            digest = None
        elif not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            findings.append(f"HASH_MALFORMED {label} logical_name={name} sha256={digest!r}")
            digest = None

        size = artifact["bytes"]
        if size is None:
            findings.append(f"BYTES_MISSING {label} logical_name={name}")
            size = None
        elif isinstance(size, bool) or not isinstance(size, int) or size < 1:
            findings.append(f"BYTES_NOT_POSITIVE_INT {label} logical_name={name} bytes={size!r}")
            size = None
        else:
            entry_bytes += size

        locator = artifact["content_uri"]
        expected_prefix = f"git:{artifact_commit}:"
        if not isinstance(locator, str) or not locator.startswith(expected_prefix):
            findings.append(
                f"LOCATOR_FOREIGN_COMMIT {label} content_uri={locator!r} "
                f"artifact_commit={artifact_commit}"
            )
            continue
        path = locator[len(expected_prefix):]
        if not path.startswith(f"{slot}/"):
            findings.append(f"LOCATOR_OUTSIDE_SLOT {label} path={path}")
            continue
        covered.add(path)

        body = repository.read_blob(artifact_commit, path)
        if body is None:
            findings.append(f"ARTIFACT_MISSING_FROM_COMMIT {label} path={path}")
            continue
        summary["measured_bytes"] += len(body)
        if digest is not None and sha256_bytes(body) != digest:
            findings.append(
                f"MEASURED_HASH_MISMATCH {label} path={path} manifest={digest} "
                f"measured={sha256_bytes(body)}"
            )
        if size is not None and len(body) != size:
            findings.append(
                f"MEASURED_BYTES_MISMATCH {label} path={path} manifest={size} measured={len(body)}"
            )

    summary["covered"] = len(covered)
    if manifest["artifact_count"] != len(artifacts):
        findings.append(
            f"COUNT_DISAGREEMENT slot={slot} artifact_count={manifest['artifact_count']} "
            f"entries={len(artifacts)}"
        )
    if manifest["total_bytes"] != entry_bytes:
        findings.append(
            f"TOTAL_BYTES_DISAGREEMENT slot={slot} total_bytes={manifest['total_bytes']} "
            f"entries={entry_bytes}"
        )

    present = counted_files(repository, artifact_commit, slot)
    for path in sorted(set(present) - covered):
        findings.append(f"UNCOVERED_FILE slot={slot} path={path}")
    for path in sorted(covered - set(present)):
        findings.append(f"COVERED_FILE_NOT_IN_COMMIT slot={slot} path={path}")

    if result is None:
        findings.append(f"RESULT_MISSING slot={slot}")
    else:
        try:
            transaction = result["result_transaction"]
        except (KeyError, TypeError) as exc:
            findings.append(f"RESULT_UNPARSEABLE slot={slot} error={exc}")
        else:
            if transaction.get("artifact_count") != manifest["artifact_count"]:
                findings.append(
                    f"RESULT_DISAGREES_WITH_MANIFEST slot={slot} field=artifact_count "
                    f"result={transaction.get('artifact_count')} manifest={manifest['artifact_count']}"
                )
            if transaction.get("total_bytes") != manifest["total_bytes"]:
                findings.append(
                    f"RESULT_DISAGREES_WITH_MANIFEST slot={slot} field=total_bytes "
                    f"result={transaction.get('total_bytes')} manifest={manifest['total_bytes']}"
                )
            claimed = transaction.get("manifest_sha256")
            measured = sha256_bytes(raw_manifest)
            if claimed != measured:
                findings.append(
                    f"MANIFEST_SHA256_MISMATCH slot={slot} result={claimed} measured={measured}"
                )
    return summary, findings


def audit_slot(repository: Repository, result_commit: str, slot: str) -> tuple[dict, list[str]]:
    """Read one slot's committed documents and audit them."""
    summary = {"slot": slot, "artifact_commit": None, "covered": 0, "measured_bytes": 0}
    raw_manifest = repository.read_blob(result_commit, f"{slot}/manifest.json")
    if raw_manifest is None:
        return summary, [f"MANIFEST_MISSING slot={slot}"]
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return summary, [f"MANIFEST_UNPARSEABLE slot={slot} error={exc}"]
    if not isinstance(manifest, dict):
        return summary, [f"MANIFEST_UNPARSEABLE slot={slot} error=root is not an object"]

    raw_result = repository.read_blob(result_commit, f"{slot}/result.json")
    result: dict | None = None
    if raw_result is not None:
        try:
            parsed = json.loads(raw_result.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return summary, [f"RESULT_UNPARSEABLE slot={slot} error={exc}"]
        result = parsed if isinstance(parsed, dict) else {}
    return audit_documents(repository, slot, manifest, raw_manifest, result)


def audit(repository: Repository, result_commit: str, only: str | None = None) -> tuple[list[dict], list[str]]:
    slots = repository.slots(result_commit)
    if only is not None:
        slots = [slot for slot in slots if slot.endswith(f"/{only}")]
        if not slots:
            return [], [f"NO_SUCH_SLOT task={only}"]
    if not slots:
        return [], ["NO_SLOTS_FOUND: nothing to audit, which cannot be reported as coverage"]
    summaries: list[dict] = []
    findings: list[str] = []
    for slot in slots:
        summary, slot_findings = audit_slot(repository, result_commit, slot)
        summaries.append(summary)
        findings.extend(slot_findings)
    return summaries, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--commit", default="HEAD", help="commit holding the manifests to audit")
    parser.add_argument("--task-id", help="audit only this task's slot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        repository = Repository(Path(args.repo_root))
        resolved = repository.git("rev-parse", args.commit).decode("utf-8").strip()
        summaries, findings = audit(repository, resolved, args.task_id)
    except CoverageError as exc:
        print(f"PO03_COVERAGE_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"commit": resolved, "slots": summaries, "findings": findings},
                         indent=2, sort_keys=True))
    else:
        for summary in summaries:
            print(
                f"{'COMPLETE' if not findings else 'AUDITED '} {summary['slot']} "
                f"covered={summary['covered']} measured_bytes={summary['measured_bytes']} "
                f"artifact_commit={summary['artifact_commit']}"
            )
        for finding in findings:
            print(f"PO03_COVERAGE_INCOMPLETE: {finding}", file=sys.stderr)
    if findings:
        return 1
    total = sum(summary["measured_bytes"] for summary in summaries)
    print(
        f"PO03_COVERAGE_PASS slots={len(summaries)} "
        f"artifacts={sum(summary['covered'] for summary in summaries)} measured_bytes={total} "
        f"excluded_by_declaration={','.join(DECLARED_EXCLUSIONS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
