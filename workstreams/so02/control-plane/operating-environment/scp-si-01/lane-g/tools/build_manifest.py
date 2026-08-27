#!/usr/bin/env python3
"""Build Lane G's manifest with full closure over everything it changed.

Reused pattern, not reinvented: `workstreams/so02/control-plane/operating-environment/
w9-reason-gated-writes/build_manifest.py` established that the denominator must come
from git rather than a hand-written list, because a hand list is a manifest that can
omit a file and still look complete. This is the same derivation
(`git diff --name-only <base>..HEAD` plus untracked files inside the lane's declared
namespaces) applied to Lane G's own base and namespaces.

`bundle_sha256` binds the entry list exactly as `evidence_integrity` recomputes it:

    sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")))

Only `MANIFEST.json` itself is excluded, and the exclusion is declared in the
document rather than left implicit.

    python3 build_manifest.py --base <sha> --out <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    cur = start
    for _ in range(12):
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    raise RuntimeError("could not locate repository root by walking up from " + str(cur))


HERE = Path(__file__).resolve().parent
REPO = _find_repo_root(HERE)
MANIFEST_PATH = "receipts/so02/2026-08-27/scp-g/MANIFEST.json"

#: The namespaces Lane G was commissioned to write, plus the one write declaration
#: file its hard boundary permits outside them. Used only to sweep up untracked
#: files; it is not a permission check and it refuses nothing.
LANE_NAMESPACES = (
    "workstreams/so02/control-plane/operating-environment/scp-si-01/lane-g/",
    "receipts/so02/2026-08-27/scp-g/",
    "workstreams/so02/control-plane/operating-environment/write-declarations/WRITE-DECLARATION-SCP-G.json",
)


def run(args: list[str]) -> str:
    done = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {done.stderr}")
    return done.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: Build artifacts are regenerated from the sources already covered, so hashing
#: them would bind a byte sequence that differs by interpreter version while
#: adding nothing a reviewer can check. Excluded here and declared in the output.
ARTIFACT_MARKERS = ("__pycache__/", ".pyc", ".pyo", ".cursor/.run/")


def is_artifact(path: str) -> bool:
    return any(marker in path or path.endswith(marker) for marker in ARTIFACT_MARKERS)


def in_namespace(path: str) -> bool:
    return any(path == ns or path.startswith(ns) for ns in LANE_NAMESPACES)


def collect(base: str) -> tuple[list[str], list[str]]:
    changed = [p for p in run(["git", "diff", "--name-only", f"{base}..HEAD"]).splitlines() if p.strip()]
    untracked = [p for p in run(["git", "ls-files", "--others", "--exclude-standard"]).splitlines()
                 if p.strip() and in_namespace(p)]
    staged = [p for p in run(["git", "diff", "--name-only", "--cached"]).splitlines() if p.strip()]
    every = sorted(p for p in {*changed, *untracked, *staged} if not is_artifact(p))
    outside = [p for p in every if not in_namespace(p)]
    return every, outside


def build(base: str) -> dict:
    every, outside = collect(base)
    entries = []
    missing = []
    for path in every:
        if path == MANIFEST_PATH:
            continue
        full = REPO / path
        if not full.is_file():
            missing.append(path)
            continue
        entries.append({
            "path": path,
            "size_bytes": full.stat().st_size,
            "sha256": sha256_file(full),
        })

    bundle = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    return {
        "schema_version": "1.0",
        "manifest_id": "SCP-G-ACCEPTED-UNIT-ECONOMICS-MANIFEST",
        "lane": "SCP-G-ACCEPTED-UNIT-ECONOMICS",
        "commission": "SCP-SI-01",
        "branch": "cursor/scp-g-accepted-unit-696d",
        "base_sha": base,
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bundle_root": "receipts/so02/2026-08-27/scp-g",
        "closure_scope": (
            "every file this lane changed against its base, derived from "
            "`git diff --name-only <base>..HEAD` plus untracked files inside the lane's "
            "namespaces — not a hand-written list, so it cannot omit a file and still look complete"
        ),
        "manifest_self_excluded_from_entries": True,
        "build_artifacts_excluded": list(ARTIFACT_MARKERS),
        "why_artifacts_excluded": ("regenerated from sources already covered here, and their bytes "
                                   "differ by interpreter version, so hashing them binds nothing a "
                                   "reviewer can check"),
        "manifest_self_path": MANIFEST_PATH,
        "files_outside_lane_namespace": outside,
        "files_listed_but_absent_from_the_tree": missing,
        "bundle_sha256_recipe": 'sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")))',
        "entries": entries,
        "entry_count": len(entries),
        "bundle_sha256": bundle,
        "decision_changed": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Lane G manifest")
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", default=str(REPO / MANIFEST_PATH))
    args = parser.parse_args(argv)

    manifest = build(args.base)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"entries {manifest['entry_count']}  bundle_sha256 {manifest['bundle_sha256']}")
    if manifest["files_outside_lane_namespace"]:
        print(f"outside lane namespace: {manifest['files_outside_lane_namespace']}", file=sys.stderr)
        return 1
    if manifest["files_listed_but_absent_from_the_tree"]:
        print(f"listed but absent: {manifest['files_listed_but_absent_from_the_tree']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
