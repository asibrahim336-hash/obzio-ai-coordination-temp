#!/usr/bin/env python3
"""Regenerate every MANIFEST.json plus the top-level one.

Run after ANY edit to a pack or the spine. A stale manifest reports a tamper
that did not happen, which trains people to ignore manifests."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from obzio_spine import manifest
from obzio_spine.artefacts import sha256_file

PACKS = ["strategic-orchestration", "founder-intent-processing",
         "repository-engineering", "independent-acceptance",
         "continuity-recovery"]
SPINE = os.path.join(ROOT, "obzio_spine")


def main():
    total_files = total_bytes = 0
    top = {"manifest_version": "obzio.manifest.v2", "root": ROOT,
           "packs": {}, "shared_spine": {}, "loose_files": {}}

    for rel in manifest.pack_files(SPINE):
        full = os.path.join(SPINE, rel)
        top["shared_spine"][f"obzio_spine/{rel}"] = {
            "bytes": os.path.getsize(full), "sha256": sha256_file(full)}

    for p in PACKS:
        d = os.path.join(ROOT, p)
        m = manifest.write(d, p, spine_dir=SPINE)
        ok, problems = manifest.verify(d)
        total_files += m["file_count"]
        total_bytes += m["total_bytes"]
        top["packs"][p] = {"file_count": m["file_count"],
                           "total_bytes": m["total_bytes"],
                           "verifies": ok, "problems": problems}
        print(f"{p}: {m['file_count']} files, {m['total_bytes']} bytes, "
              f"verify={'OK' if ok else problems}")

    for fn in sorted(os.listdir(ROOT)):
        full = os.path.join(ROOT, fn)
        if os.path.isfile(full) and fn != "MANIFEST.json":
            top["loose_files"][fn] = {"bytes": os.path.getsize(full),
                                      "sha256": sha256_file(full)}

    top["totals"] = {
        "pack_files": total_files,
        "pack_bytes": total_bytes,
        "spine_files": len(top["shared_spine"]),
        "spine_bytes": sum(v["bytes"] for v in top["shared_spine"].values()),
    }
    with open(os.path.join(ROOT, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(top, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\ntop-level MANIFEST.json written: {total_files} pack files + "
          f"{top['totals']['spine_files']} spine files")


if __name__ == "__main__":
    main()
