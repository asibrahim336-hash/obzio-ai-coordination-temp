#!/usr/bin/env python3
"""Regenerate and verify a PO-03 source-lock receipt from bytes alone.

The mechanism reads a declarative spec plus a materialised source tree. It never
reads a producer narrative, never spawns a subprocess and never opens a socket,
so a receipt can be reproduced by any party holding the same immutable tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

LOCK_VERSION = "PO03-SOURCE-LOCK-v1"
DERIVED_FIELDS = ("bytes", "git_blob_sha", "sha256")
EMPTY_BLOB_SHA1 = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


class SpecError(ValueError):
    """The spec or lock document is not usable as a reproduction input."""


def canonical_json(document: object) -> str:
    """Serialise deterministically: sorted keys, no padding, one trailing newline."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def normalize(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise SpecError(f"source path must be a non-empty string: {path!r}")
    if "\\" in path or "\x00" in path:
        raise SpecError(f"non-canonical source path: {path!r}")
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or str(value) != path:
        raise SpecError(f"non-canonical source path: {path!r}")
    return path


def git_blob_sha1(payload: bytes) -> str:
    """Reproduce Git's blob object name without invoking Git."""
    header = b"blob %d\0" % len(payload)
    return hashlib.sha1(header + payload).hexdigest()


def digest(root: Path, path: str) -> dict[str, object]:
    payload = (root / normalize(path)).read_bytes()
    return {
        "bytes": len(payload),
        "git_blob_sha": git_blob_sha1(payload),
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def load_spec(spec_path: Path) -> dict[str, object]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    metadata = spec.get("metadata")
    paths = spec.get("source_paths")
    if not isinstance(metadata, dict):
        raise SpecError("spec.metadata must be a JSON object")
    if not isinstance(paths, list) or not paths:
        raise SpecError("spec.source_paths must be a non-empty ordered list")
    if "sources" in metadata:
        raise SpecError("spec.metadata must not predeclare derived sources")
    seen: set[str] = set()
    for path in paths:
        canonical = normalize(path)
        if canonical in seen:
            raise SpecError(f"duplicate source path in spec: {canonical}")
        seen.add(canonical)
    return spec


def regenerate(root: Path, spec: dict[str, object]) -> dict[str, object]:
    """Rebuild the receipt: declarative metadata from the spec, everything else from bytes."""
    document = dict(spec["metadata"])
    document["sources"] = [digest(root, path) for path in spec["source_paths"]]
    return document


def load_lock(lock_path: Path) -> dict[str, object]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict):
        raise SpecError("lock must be a JSON object")
    sources = lock.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SpecError("lock.sources must be a non-empty list")
    for entry in sources:
        if not isinstance(entry, dict):
            raise SpecError("lock.sources entries must be JSON objects")
        missing = [field for field in ("path", *DERIVED_FIELDS) if field not in entry]
        if missing:
            raise SpecError(f"lock source entry missing {missing}")
        normalize(entry["path"])
    return lock


def verify(root: Path, lock: dict[str, object], head_sha: str | None = None) -> dict[str, object]:
    """Recompute every declared source and report each disagreement individually."""
    findings: list[dict[str, object]] = []
    if head_sha is not None and lock.get("head_sha") != head_sha:
        findings.append(
            {
                "actual": head_sha,
                "expected": lock.get("head_sha"),
                "kind": "HEAD_SHA_MISMATCH",
                "path": None,
            }
        )
    for entry in lock["sources"]:
        path = entry["path"]
        target = root / path
        if not target.is_file():
            findings.append(
                {
                    "actual": "DIRECTORY" if target.is_dir() else "ABSENT",
                    "expected": "FILE",
                    "kind": "NOT_A_FILE" if target.exists() else "MISSING",
                    "path": path,
                }
            )
            continue
        observed = digest(root, path)
        for field in DERIVED_FIELDS:
            if observed[field] != entry[field]:
                findings.append(
                    {
                        "actual": observed[field],
                        "expected": entry[field],
                        "kind": f"{field.upper()}_MISMATCH",
                        "path": path,
                    }
                )
    return {
        "declared_sources": len(lock["sources"]),
        "findings": findings,
        "mismatched_paths": sorted({str(item["path"]) for item in findings if item["path"]}),
        "status": "FAIL" if findings else "PASS",
        "verifier_version": LOCK_VERSION,
    }


def _emit(document: object, out: Path | None) -> None:
    text = canonical_json(document)
    if out is None:
        sys.stdout.write(text)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild = sub.add_parser("regenerate", help="rebuild a receipt from a spec and a source tree")
    rebuild.add_argument("--spec", required=True, type=Path)
    rebuild.add_argument("--root", required=True, type=Path)
    rebuild.add_argument("--out", type=Path)

    check = sub.add_parser("verify", help="recompute a receipt against a source tree")
    check.add_argument("--lock", required=True, type=Path)
    check.add_argument("--root", required=True, type=Path)
    check.add_argument("--head-sha")
    check.add_argument("--report", type=Path)

    compare = sub.add_parser("compare", help="byte-compare a regenerated receipt with a receipt")
    compare.add_argument("--spec", required=True, type=Path)
    compare.add_argument("--root", required=True, type=Path)
    compare.add_argument("--expected", required=True, type=Path)
    compare.add_argument("--report", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "regenerate":
            _emit(regenerate(args.root, load_spec(args.spec)), args.out)
            return 0
        if args.command == "verify":
            report = verify(args.root, load_lock(args.lock), args.head_sha)
            _emit(report, args.report)
            if report["status"] != "PASS":
                print(
                    f"PO03_SOURCE_LOCK_FAIL findings={len(report['findings'])}",
                    file=sys.stderr,
                )
                return 1
            print(f"PO03_SOURCE_LOCK_PASS sources={report['declared_sources']}")
            return 0
        rebuilt = canonical_json(regenerate(args.root, load_spec(args.spec))).encode("utf-8")
        expected = args.expected.read_bytes()
        report = {
            "expected_bytes": len(expected),
            "expected_sha256": hashlib.sha256(expected).hexdigest(),
            "identical": rebuilt == expected,
            "regenerated_bytes": len(rebuilt),
            "regenerated_sha256": hashlib.sha256(rebuilt).hexdigest(),
            "status": "PASS" if rebuilt == expected else "FAIL",
        }
        _emit(report, args.report)
        if not report["identical"]:
            print("PO03_SOURCE_LOCK_BYTE_MISMATCH", file=sys.stderr)
            return 1
        print(f"PO03_SOURCE_LOCK_BYTE_IDENTICAL sha256={report['expected_sha256']}")
        return 0
    except (OSError, SpecError, json.JSONDecodeError) as exc:
        print(f"PO03_SOURCE_LOCK_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
