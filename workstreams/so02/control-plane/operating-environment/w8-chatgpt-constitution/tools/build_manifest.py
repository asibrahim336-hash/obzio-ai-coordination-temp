#!/usr/bin/env python3
"""Build the delivery manifest with declared closure.

Standard library only.

Closure is the point: the manifest must cover every file this lane wrote, and
anything excluded must be excluded by an explicit, named rule rather than by
having been forgotten. The only permitted exclusion is the manifest itself,
which cannot contain its own hash, and that exclusion is declared in the
manifest rather than assumed.

    python3 tools/build_manifest.py --repo-root /path/to/worktree
    python3 tools/build_manifest.py --repo-root /path/to/worktree --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

LANE = "OE-W8-CHATGPT-CONSTITUTION"
COMMISSION = "COM-CUR-ENV-01-20260822-v001"
BRANCH = "cursor/oe-w8-chatgpt-constitution-696d"

WRITE_SCOPE = [
    "workstreams/so02/control-plane/operating-environment/w8-chatgpt-constitution",
    "receipts/so02/2026-08-22/oe-w8-chatgpt-constitution",
]
MANIFEST_REL = "receipts/so02/2026-08-22/oe-w8-chatgpt-constitution/MANIFEST.json"

EXCLUDED = {
    MANIFEST_REL: "the manifest cannot contain its own hash. This is the only exclusion and it is declared, not assumed.",
}


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tracked_and_untracked(root: pathlib.Path, prefix: str) -> list[str]:
    """Every file under prefix that git can see, staged or not, minus ignored."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "--", prefix],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def collect(root: pathlib.Path) -> list[dict]:
    seen: set[str] = set()
    entries: list[dict] = []
    for prefix in WRITE_SCOPE:
        for rel in tracked_and_untracked(root, prefix):
            if rel in seen or rel in EXCLUDED:
                continue
            path = root / rel
            if not path.is_file():
                continue
            seen.add(rel)
            entries.append({
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of(path),
            })
    entries.sort(key=lambda e: e["path"])
    return entries


def bundle_sha256(entries: list[dict]) -> str:
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def head_sha(root: pathlib.Path) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def build(root: pathlib.Path) -> dict:
    entries = collect(root)
    return {
        "artifact_id": "OE-W8-DELIVERY-MANIFEST-20260822-v001",
        "lane": LANE,
        "commission": COMMISSION,
        "branch": BRANCH,
        "head_at_build": head_sha(root),
        "state": "READY_TO_COMMIT",
        "decision_changed": [],
        "closure": {
            "declared": "full",
            "write_scope": WRITE_SCOPE,
            "rule": "every file git can see under the write scope, tracked or untracked, excluding only what is named below",
            "excluded": EXCLUDED,
            "excluded_count": len(EXCLUDED),
        },
        "bundle_sha256_definition": "sha256 of json.dumps(entries, sort_keys=True, separators=(',',':'))",
        "entry_count": len(entries),
        "bundle_sha256": bundle_sha256(entries),
        "entries": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--check", action="store_true", help="recompute and compare against the committed manifest")
    args = ap.parse_args()

    root = pathlib.Path(args.repo_root).resolve()
    manifest = build(root)
    target = root / MANIFEST_REL

    if args.check:
        if not target.exists():
            print(f"FAIL no manifest at {MANIFEST_REL}", file=sys.stderr)
            return 1
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        mismatches = []
        if on_disk.get("bundle_sha256") != manifest["bundle_sha256"]:
            mismatches.append(f"bundle_sha256 {on_disk.get('bundle_sha256')} != {manifest['bundle_sha256']}")
        if on_disk.get("entry_count") != manifest["entry_count"]:
            mismatches.append(f"entry_count {on_disk.get('entry_count')} != {manifest['entry_count']}")
        old = {e["path"]: e["sha256"] for e in on_disk.get("entries", [])}
        new = {e["path"]: e["sha256"] for e in manifest["entries"]}
        for path in sorted(set(old) | set(new)):
            if old.get(path) != new.get(path):
                mismatches.append(f"{path}: {old.get(path)} -> {new.get(path)}")
        for m in mismatches:
            print(f"MISMATCH {m}")
        if mismatches:
            print(f"\nFAIL {len(mismatches)} mismatch(es)")
            return 1
        print(f"PASS manifest matches: {manifest['entry_count']} entries, bundle_sha256 {manifest['bundle_sha256']}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_REL}")
    print(f"entry_count   {manifest['entry_count']}")
    print(f"bundle_sha256 {manifest['bundle_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
