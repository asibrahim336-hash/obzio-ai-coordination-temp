#!/usr/bin/env python3
"""Uncommitted-file gate (unit a3-u07).

Refuses to let a result claim rest on bytes that were never pushed.  This is the
exact failure mode that lost the PO-02 Code-2 packaging return: the work existed
in a working tree, the provider reported completion, and nothing durable was
ever committed, so four reported recovery routes found nothing.

Two independent checks, because either one alone can be satisfied by a lie:

``tree``
    The working tree must be clean.  A dirty tree means the artifact bytes on
    disk are not the bytes anyone else can read.

``manifest``
    Every path a result manifest references must be tracked, must exist, and its
    recorded sha256 and byte count must match the committed blob -- not the
    working file.  Comparing against the blob is what makes the check
    meaningful: a tracked-but-modified file has committed bytes that differ from
    what the producer hashed, and reading the working file would hide that.

Bytecode caches are classified separately from real content.  They are build
output, and conflating them with a genuine uncommitted artifact would train
reviewers to pass a dirty tree.  They are counted and reported, never silently
dropped.

Dependency-free: standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]

REPORT_SCHEMA = "po03-committed-only-report-v1"
BYTECODE_MARKERS = ("__pycache__", ".pyc", ".pyo")


class GateError(RuntimeError):
    """Raised when the gate cannot reach a verdict, which is itself a failure."""


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def is_bytecode(path: str) -> bool:
    return any(marker in path for marker in BYTECODE_MARKERS)


def parse_porcelain(output: str) -> list[dict[str, str]]:
    """Parse ``git status --porcelain`` into status/path records.

    Renames are reported as ``R  old -> new``; the new path is the one that
    matters for a claim about content.
    """
    entries: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        entries.append({"status": status.strip() or "??", "path": path})
    return entries


def check_tree(root: Path) -> dict[str, Any]:
    """Any entry git reports fails the gate, bytecode included.

    This once forgave bytecode as build output, because two ``.pyc`` files were
    committed and every run therefore reported dirty. That defect was fixed
    upstream and ``workstreams/po03/.gitignore`` now declares bytecode, so git
    no longer reports it and the forgiveness became unreachable code that would
    have silently swallowed a committed ``.pyc`` if one ever came back. The
    strength now rests on the repository's own declaration rather than on a
    tolerance in this file: if the ignore rule were removed, git would start
    reporting bytecode and this gate would fail, which is correct.

    --untracked-files=all matters: the default collapses a wholly untracked
    directory to a single "pkg/" entry, and a path-level gate must see paths.
    """
    entries = parse_porcelain(git(root, "status", "--porcelain", "--untracked-files=all"))
    return {
        "check": "tree",
        "dirty_entries": entries,
        "dirty_count": len(entries),
        "bytecode_entries": [entry for entry in entries if is_bytecode(entry["path"])],
        "bytecode_forgiven": False,
        "verdict": "FAIL" if entries else "PASS",
    }


def tracked_paths(root: Path) -> set[str]:
    return {line for line in git(root, "ls-files").splitlines() if line}


def committed_blob(root: Path, path: str, rev: str) -> bytes | None:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{path}"],
        cwd=root,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def manifest_paths(document: Any) -> list[dict[str, Any]]:
    """Pull referenced paths out of a transactional result document.

    ``content_uri`` is ``git:<branch>@<commit>:<path>``, so the path is the
    segment after the last colon.
    """
    references: list[dict[str, Any]] = []
    for artifact in document.get("artifacts", []):
        uri = artifact.get("content_uri", "")
        path = uri.split(":", 2)[-1] if uri else ""
        references.append(
            {
                "logical_name": artifact.get("logical_name"),
                "path": path,
                "sha256": artifact.get("sha256"),
                "bytes": artifact.get("bytes"),
            }
        )
    return references


RESULT_PROTOCOL = "OBZIO-TRANSACTIONAL-RESULT-v1"
COMMITTED_STATES = {"RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"}


def check_manifest(root: Path, manifest_path: Path, rev: str) -> dict[str, Any]:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))

    # A document that is not a result manifest would otherwise produce a
    # vacuous "0 of 0 verified" pass, which is the shape of a green check that
    # checked nothing.
    if document.get("protocol_version") != RESULT_PROTOCOL:
        return {
            "check": "manifest",
            "manifest": str(manifest_path),
            "revision": rev,
            "referenced_count": 0,
            "verified_count": 0,
            "findings": [],
            "verdict": "SKIP",
            "skip_reason": f"not a {RESULT_PROTOCOL} document",
        }

    tracked = tracked_paths(root)
    findings: list[dict[str, str]] = []
    verified = 0

    references = manifest_paths(document)
    if not references and document.get("obzio_state") in COMMITTED_STATES:
        findings.append(
            {
                "path": "<none>",
                "reason": f"{document.get('obzio_state')} manifest references no artifacts",
            }
        )

    for reference in references:
        path = reference["path"]
        if not path:
            findings.append({"path": "<missing>", "reason": "manifest entry has no content_uri path"})
            continue
        if path not in tracked:
            findings.append({"path": path, "reason": "referenced path is not tracked by git"})
            continue
        blob = committed_blob(root, path, rev)
        if blob is None:
            findings.append({"path": path, "reason": f"referenced path is not present in {rev}"})
            continue
        digest = hashlib.sha256(blob).hexdigest()
        if reference["sha256"] and digest != reference["sha256"]:
            findings.append(
                {
                    "path": path,
                    "reason": f"committed blob sha256 {digest} does not match manifest {reference['sha256']}",
                }
            )
            continue
        if reference["bytes"] is not None and len(blob) != reference["bytes"]:
            findings.append(
                {
                    "path": path,
                    "reason": f"committed blob is {len(blob)} bytes, manifest claims {reference['bytes']}",
                }
            )
            continue
        verified += 1

    return {
        "check": "manifest",
        "manifest": str(manifest_path),
        "revision": rev,
        "referenced_count": len(references),
        "verified_count": verified,
        "findings": findings,
        "verdict": "FAIL" if findings else "PASS",
    }


def build_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "checks": checks,
        "manifests_checked": sum(
            1 for check in checks if check["check"] == "manifest" and check["verdict"] != "SKIP"
        ),
        "manifests_skipped": sum(
            1 for check in checks if check["check"] == "manifest" and check["verdict"] == "SKIP"
        ),
        "failing_checks": [check["check"] for check in checks if check["verdict"] == "FAIL"],
        "verdict": "FAIL" if any(check["verdict"] == "FAIL" for check in checks) else "PASS",
    }


def emit(report: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for check in report["checks"]:
            if check["check"] == "tree":
                for entry in check["dirty_entries"]:
                    print(f"UNCOMMITTED: {entry['status']} {entry['path']}")
            elif check["verdict"] == "SKIP":
                print(f"SKIPPED {check['manifest']}: {check['skip_reason']}")
            else:
                for finding in check["findings"]:
                    print(f"MANIFEST_UNVERIFIABLE: {finding['path']}: {finding['reason']}")
                print(
                    f"  ({check['verified_count']} of {check['referenced_count']} referenced path(s) "
                    f"in {Path(check['manifest']).name} verified against {check['revision']})"
                )
        if report["verdict"] == "FAIL":
            print(f"FAIL committed-only gate: {', '.join(report['failing_checks'])}")
        else:
            print("PASS committed-only gate")
    return 1 if report["verdict"] == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PO-03 uncommitted-file gate")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--rev", default="HEAD", help="revision whose blobs the manifest must match")
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="result document whose referenced paths must be committed (repeatable)",
    )
    parser.add_argument(
        "--manifest-dir",
        help="directory of result documents to check, non-recursive",
    )
    parser.add_argument("--skip-tree", action="store_true", help="check manifests only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    manifests = [Path(item) for item in args.manifest]
    if args.manifest_dir:
        manifests.extend(sorted(Path(args.manifest_dir).glob("*.json")))

    try:
        checks: list[dict[str, Any]] = []
        if not args.skip_tree:
            checks.append(check_tree(root))
        for manifest in manifests:
            checks.append(check_manifest(root, manifest, args.rev))
        if not checks:
            raise GateError("nothing to check: pass a manifest or omit --skip-tree")
        report = build_report(checks)
        if manifests and report["manifests_checked"] == 0:
            raise GateError(
                f"{len(manifests)} manifest path(s) given but none was a {RESULT_PROTOCOL} document"
            )
    except (GateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"COMMITTED_ONLY_ERROR: {exc}", file=sys.stderr)
        return 2
    return emit(report, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
