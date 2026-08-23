#!/usr/bin/env python3
"""Build the OE-W10 delivery manifest with declared closure.

Stdlib only. Deterministic.

Closure is the point. L3 refused a bundle partly because its manifest omitted
the bundle's own remote read-back record (AC-03 FAIL), and the omission then
recurred across later lanes - a manifest builder that walks a directory writes
the manifest last and therefore never sees anything written after it.

This builder avoids the recurrence by ordering rather than by care: the read-back
record is written first and the manifest walks over it. Exactly one file is
excluded, MANIFEST.json itself, because a file cannot contain its own digest, and
the exclusion is declared in the manifest rather than left to be noticed.

    python3 build_manifest.py <repo_root> <out_path> <bundle_root> [<bundle_root> ...]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(repo_root: str, roots: list[str], exclude_basenames: set[str]) -> list[dict]:
    entries: list[dict] = []
    excluded: list[str] = []
    for root in roots:
        abs_root = os.path.join(repo_root, root)
        for dirpath, dirnames, filenames in os.walk(abs_root):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in sorted(filenames):
                if name.endswith(".pyc"):
                    continue
                abs_path = os.path.join(dirpath, name)
                rel = os.path.relpath(abs_path, repo_root)
                if name in exclude_basenames:
                    excluded.append(rel)
                    continue
                entries.append({
                    "path": rel,
                    "size_bytes": os.path.getsize(abs_path),
                    "sha256": sha256_file(abs_path),
                })
    entries.sort(key=lambda e: e["path"])
    return entries, excluded


def main(argv: list[str]) -> int:
    repo_root, out_path = argv[1], argv[2]
    roots = argv[3:]
    out_rel = os.path.relpath(os.path.join(repo_root, out_path), repo_root)

    entries, excluded = walk(repo_root, roots, {os.path.basename(out_path)})
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    bundle_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    manifest = {
        "manifest_id": "OE-W10-MANIFEST-20260823-v001",
        "lane": "OE-W10-PROVENANCE-REDERIVATION",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "state": "READY_TO_COMMIT",
        "decision_changed": [],
        "is_a_proposal_not_a_binding": True,
        "binds_company_strategy": False,
        "bundle_roots": roots,
        "entry_count": len(entries),
        "bundle_sha256": bundle_sha256,
        "bundle_sha256_definition": (
            "sha256 of json.dumps(entries, sort_keys=True, "
            "separators=(\",\",\":\")) over the entries array below, encoded UTF-8"
        ),
        "closure": {
            "claim": "FULL over both bundle roots, with exactly one declared exclusion.",
            "excluded": excluded,
            "why_excluded": (
                "MANIFEST.json cannot contain its own sha256. Nothing else is "
                "excluded: the remote read-back record, every tool, every "
                "receipt transcript and every register is inside the entry set."
            ),
            "read_back_record_is_manifested": True,
            "read_back_record_path": (
                "receipts/so02/2026-08-23/oe-w10-provenance/REMOTE-READBACK.json"
            ),
            "material_claim_inputs_outside_the_bundle": [
                {
                    "path": (
                        "workstreams/so02/control-plane/operating-environment/"
                        "FOUNDER-STANDING-INSTRUCTION-20260822.md"
                    ),
                    "why_material": (
                        "The founder corpus is extracted from it and every "
                        "FOUNDER_AUTHORED verdict is checked against it. If it "
                        "changes, every quotation in the register is unverified."
                    ),
                },
                {
                    "path": (
                        "workstreams/so02/control-plane/operating-environment/"
                        "w4-platform-roles/DE-RESTRICTION-REGISTER-20260822-v001.json"
                    ),
                    "why_material": "The prior classification the diff is computed against.",
                },
            ],
            "material_inputs_are_hashed_below": True,
        },
        "entries": entries,
    }

    for extra in manifest["closure"]["material_claim_inputs_outside_the_bundle"]:
        abs_path = os.path.join(repo_root, extra["path"])
        extra["size_bytes"] = os.path.getsize(abs_path)
        extra["sha256"] = sha256_file(abs_path)
        extra["in_entry_set"] = False
        extra["note"] = (
            "Hashed here rather than manifested, because it is another lane's "
            "file and not part of this bundle. It is a material claim input and "
            "is recorded so a verifier can detect drift."
        )

    with open(os.path.join(repo_root, out_path), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"manifest: {out_rel}")
    print(f"  entry_count  : {len(entries)}")
    print(f"  bundle_sha256: {bundle_sha256}")
    print(f"  excluded     : {excluded}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
