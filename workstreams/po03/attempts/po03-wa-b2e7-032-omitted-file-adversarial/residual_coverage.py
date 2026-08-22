#!/usr/bin/env python3
"""Find files a slot really holds now that no manifest in it ever covered.

This closes a gap the adversarial omission fixture found rather than assumed.
The unit 029 auditor measures a manifest against the commit that manifest names,
which is the correct question to ask of a manifest: it declares "at commit X the
artifacts are these", and that claim stays true forever. But a slot accumulates
commits. A file added after the artifact commit is real, durable and present at
the branch tip, and every manifest in the slot can still be perfectly faithful to
its own commit, so per-manifest auditing cannot see it.

This tool asks the other question. It enumerates what the slot holds at a chosen
commit, usually the branch tip, and subtracts everything any manifest in that
slot ever claimed to cover, at any artifact commit, matching by content hash as
well as by path so that a file moved after being manifested is still recognised
as covered. What remains is residual: committed bytes no manifest accounts for.

The two generated documents the emitter declines to count, `manifest.json` and
`result.json`, are excluded at the slot root only, matching the unit 029
declaration. A payload at `<slot>/nested/manifest.json` is deliberately not
excluded, because that is exactly the omission the emitter's basename matching
lets through.

Exit codes: 0 no residual bytes, 1 residual bytes found, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DECLARED_EXCLUSIONS = ("manifest.json", "result.json")
ATTEMPTS_PREFIX = "workstreams/po03/attempts"


class ResidualError(Exception):
    """Raised when the repository cannot be read at all."""


def git(repo: Path, *arguments: str) -> bytes:
    completed = subprocess.run(("git", *arguments), cwd=repo, capture_output=True)
    if completed.returncode != 0:
        raise ResidualError(
            f"git {' '.join(arguments)} failed: {completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    return completed.stdout


def list_tree(repo: Path, commit: str, prefix: str) -> list[str]:
    listing = git(repo, "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix)
    return sorted(
        item.decode("utf-8", "surrogateescape") for item in listing.split(b"\0") if item
    )


def read_blob(repo: Path, commit: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"), cwd=repo, capture_output=True
    )
    return completed.stdout if completed.returncode == 0 else None


def slots(repo: Path, commit: str) -> list[str]:
    found: set[str] = set()
    for path in list_tree(repo, commit, ATTEMPTS_PREFIX):
        parts = path.split("/")
        if len(parts) > 4:
            found.add("/".join(parts[:4]))
    return sorted(found)


def covered_by_any_manifest(repo: Path, commit: str, slot: str) -> tuple[set[str], set[str], int]:
    """Everything any manifest in this slot ever claimed, by path and by hash.

    Only the manifest present at `commit` is readable as a document, but it names
    an artifact commit that may differ, and a slot may have carried earlier
    manifests. History is walked so that a file covered by a superseded manifest
    is not reported as residual.
    """
    paths: set[str] = set()
    hashes: set[str] = set()
    manifests = 0
    revisions = git(
        repo, "rev-list", commit, "--", f"{slot}/manifest.json"
    ).decode("utf-8").split()
    for revision in revisions:
        raw = read_blob(repo, revision, f"{slot}/manifest.json")
        if raw is None:
            continue
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entries = manifest.get("artifacts")
        if not isinstance(entries, list):
            continue
        manifests += 1
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("logical_name")
            if isinstance(name, str):
                paths.add(f"{slot}/{name}")
            locator = entry.get("content_uri")
            if isinstance(locator, str) and locator.startswith("git:"):
                remainder = locator[4:]
                if ":" in remainder:
                    paths.add(remainder.split(":", 1)[1])
            digest = entry.get("sha256")
            if isinstance(digest, str):
                hashes.add(digest)
    return paths, hashes, manifests


def audit_slot(repo: Path, commit: str, slot: str) -> tuple[dict, list[str]]:
    excluded = {f"{slot}/{name}" for name in DECLARED_EXCLUSIONS}
    present = [path for path in list_tree(repo, commit, slot) if path not in excluded]
    claimed_paths, claimed_hashes, manifests = covered_by_any_manifest(repo, commit, slot)

    findings: list[str] = []
    residual_bytes = 0
    if not manifests and present:
        findings.append(
            f"NO_MANIFEST slot={slot} present={len(present)}: "
            "the slot holds committed bytes and never declared a manifest"
        )
    for path in present:
        if path in claimed_paths:
            continue
        body = read_blob(repo, commit, path)
        if body is None:
            findings.append(f"UNREADABLE slot={slot} path={path}")
            continue
        digest = hashlib.sha256(body).hexdigest()
        if digest in claimed_hashes:
            # Same bytes under a different name: covered, though relocated.
            continue
        residual_bytes += len(body)
        findings.append(
            f"RESIDUAL_FILE slot={slot} path={path} bytes={len(body)} sha256={digest}"
        )
    summary = {
        "slot": slot,
        "present": len(present),
        "manifests_seen": manifests,
        "residual_files": sum(1 for f in findings if f.startswith("RESIDUAL_FILE")),
        "residual_bytes": residual_bytes,
    }
    return summary, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--commit", default="HEAD", help="commit whose slot contents are judged")
    parser.add_argument("--slot", help="audit only this slot path")
    parser.add_argument("--task-id", help="audit only this task's slot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    try:
        resolved = git(repo, "rev-parse", args.commit).decode("utf-8").strip()
        explicit = args.slot or (f"{ATTEMPTS_PREFIX}/{args.task_id}" if args.task_id else None)
        if explicit is not None:
            # An explicitly named target that holds nothing must not report a
            # clean pass: a mistyped task id in a CI loop would otherwise turn
            # the gate green having audited no bytes at all.
            if not list_tree(repo, resolved, explicit):
                raise ResidualError(f"{explicit} holds no files at {resolved}; nothing was audited")
            targets = [explicit]
        else:
            targets = slots(repo, resolved)
        if not targets:
            raise ResidualError(f"no slot found under {ATTEMPTS_PREFIX} at {resolved}")
        summaries = []
        findings: list[str] = []
        for slot in targets:
            summary, slot_findings = audit_slot(repo, resolved, slot)
            summaries.append(summary)
            findings.extend(slot_findings)
    except (ResidualError, OSError) as exc:
        print(f"PO03_RESIDUAL_ERROR: {exc}", file=sys.stderr)
        return 2

    stream = sys.stderr if args.json else sys.stdout
    if args.json:
        print(json.dumps({"commit": resolved, "slots": summaries, "findings": findings}, indent=2))
    else:
        for summary in summaries:
            print(
                f"{'RESIDUAL' if summary['residual_files'] else 'CLEAN   '} {summary['slot']} "
                f"present={summary['present']} manifests={summary['manifests_seen']} "
                f"residual_files={summary['residual_files']} "
                f"residual_bytes={summary['residual_bytes']}"
            )
    if findings:
        for finding in findings:
            print(f"PO03_RESIDUAL_UNCOVERED: {finding}", file=sys.stderr)
        return 1
    total = sum(summary["present"] for summary in summaries)
    print(
        f"PO03_RESIDUAL_PASS slots={len(summaries)} files_accounted_for={total} "
        f"commit={resolved}",
        file=stream,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
