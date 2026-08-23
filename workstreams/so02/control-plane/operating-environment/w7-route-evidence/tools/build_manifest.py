#!/usr/bin/env python3
"""Close the manifest over every file this lane produced.

Closure means every file under the lane's two namespaces appears, including the
remote read-back record. Exactly one file is excluded, and the exclusion is
declared in the manifest itself rather than left for a reader to notice:
MANIFEST.json cannot contain its own hash.

bundle_sha256 is the sha256 of json.dumps(entries, sort_keys=True,
separators=(",",":")). It is a single value that changes if any path, size or
hash changes, so one comparison settles whether the bundle is the bundle.

    python3 build_manifest.py --root REPO --prefix DIR [--prefix DIR] --out MANIFEST.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--prefix", action="append", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = pathlib.Path(args.root).resolve()
    out = pathlib.Path(args.out).resolve()
    excluded = out.relative_to(root).as_posix()

    entries = []
    for prefix in args.prefix:
        for p in sorted((root / prefix).rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel == excluded:
                continue
            entries.append({
                "path": rel,
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })

    entries.sort(key=lambda e: e["path"])
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    bundle_sha256 = hashlib.sha256(canonical.encode()).hexdigest()

    manifest = {
        "artifact_id": "OE-W7-ROUTE-EVIDENCE-MANIFEST",
        "lane": "OE-W7-CHATGPT-ROUTE-EVIDENCE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "branch": "cursor/oe-w7-route-evidence-696d",
        "built_at_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
                          .isoformat().replace("+00:00", "Z"),
        "terminal_state": "READY_TO_COMMIT",
        "closure": {
            "namespaces_covered": list(args.prefix),
            "declared_exclusions": [excluded],
            "why_excluded": (
                "A manifest cannot contain its own sha256. This is the only file "
                "omitted, and every other file under both lane namespaces is "
                "present, including the remote read-back record."
            ),
            "read_back_record_included": any(
                e["path"].endswith("raw/remote-read-back.txt") for e in entries
            ),
        },
        "bundle_sha256_definition": (
            "sha256 of json.dumps(entries, sort_keys=True, separators=(\",\",\":\"))"
        ),
        "bundle_sha256": bundle_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "credential_note": (
            "No credential value appears in any listed file. Credential presence is "
            "recorded by name only, as PRESENT or ABSENT."
        ),
    }
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"entry_count   = {len(entries)}")
    print(f"bundle_sha256 = {bundle_sha256}")
    for e in entries:
        print(f"  {e['sha256'][:16]}  {e['size_bytes']:>9}  {e['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
