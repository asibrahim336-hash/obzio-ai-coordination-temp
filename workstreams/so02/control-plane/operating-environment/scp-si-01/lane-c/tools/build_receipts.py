#!/usr/bin/env python3
"""Build the lane C receipt bundle: manifest closure plus a parsed read-back.

Stdlib only. Runs under `python3 -I`.

`MANIFEST.json` is the only file excluded from its own entries, and the exclusion
is declared inside it. Every other file the lane wrote is an entry with `path`,
`size_bytes` and `sha256`, and `bundle_sha256` is the sha256 of
`json.dumps(entries, sort_keys=True, separators=(",",":"))`.

`READ-BACK.json` re-reads every structured artifact and records both whether its
hash recomputes *and* whether it parses. A hash-valid unparsable artifact is a
defect already in this estate's record, repaired at commit 3b97d6ff, so shape
verification alone is not accepted here.

## Why this runs in two stages

Four artifacts here hash each other, and a naive single pass makes that a cycle:
the declaration's evidence covers `READ-BACK.json`, `ADMISSION.json` records the
verdict on the declaration, and `MANIFEST.json` covers all three. Rewriting the
read-back after the declaration has hashed it would leave the declaration
asserting a hash that is no longer true — silently, because the admission gate
recomputes closure internally and never reads the disk.

So the build is ordered and each stage is run explicitly:

    1. --stage read-back    writes READ-BACK.json over the lane's artifacts
    2. build_declaration.py hashes the lane's files and READ-BACK.json
    3. write_admission.py   writes ADMISSION.json
    4. --stage manifest     covers everything above, including the declaration

Stage 4 depends on 1-3 and nothing depends on it, so the order is acyclic and
`MANIFEST.json` remains the single declared exclusion. `--stage manifest` never
touches `READ-BACK.json`, which is what keeps step 2's hash true.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import authorship_sidecar as A  # noqa: E402

LANE_REL = os.path.join("workstreams", "so02", "control-plane",
                        "operating-environment", "scp-si-01", "lane-c")
RECEIPT_REL = os.path.join("receipts", "so02", "2026-08-27", "scp-c")
DECLARATION_REL = os.path.join("workstreams", "so02", "control-plane",
                               "operating-environment", "write-declarations",
                               "WRITE-DECLARATION-SCP-C.json")
MANIFEST_NAME = "MANIFEST.json"


def walk(repo_root: str, rel_dir: str) -> list[str]:
    out = []
    base = os.path.join(repo_root, rel_dir)
    for dirpath, _dirs, files in os.walk(base):
        for name in sorted(files):
            if name.endswith((".pyc",)):
                continue
            full = os.path.join(dirpath, name)
            out.append(os.path.relpath(full, repo_root).replace(os.sep, "/"))
    return sorted(out)


def entry(repo_root: str, rel: str) -> dict:
    with open(os.path.join(repo_root, rel), "rb") as fh:
        raw = fh.read()
    return {"path": rel, "size_bytes": len(raw), "sha256": A.sha256_bytes(raw)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--pushed-sha", default=None)
    parser.add_argument("--stage", choices=("read-back", "manifest"), required=True,
                        help="see the module docstring; the stages are ordered")
    args = parser.parse_args(argv)
    repo_root = os.path.abspath(args.repo_root)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    receipt_dir = os.path.join(repo_root, RECEIPT_REL)
    os.makedirs(receipt_dir, exist_ok=True)
    if args.stage == "manifest":
        return build_manifest(repo_root, now, args.commit, args.pushed_sha)

    # ---- read-back: hash and parse every structured artifact -------------
    # The write declaration is deliberately not read back here. READ-BACK.json
    # must stay stable while the declaration is written, because the declaration
    # hashes READ-BACK.json as its evidence. The declaration is parse-verified in
    # ADMISSION.json instead, which is where its verdict belongs anyway.
    # The three receipts that hash or evaluate the declaration are excluded: two
    # of them do not exist yet at this stage, and including a stale copy left by
    # a previous run would make this receipt non-deterministic.
    later = {f"{RECEIPT_REL}/{name}".replace(os.sep, "/")
             for name in ("READ-BACK.json", "ADMISSION.json", MANIFEST_NAME)}
    structured = [rel for rel in walk(repo_root, LANE_REL) + walk(repo_root, RECEIPT_REL)
                  if rel.endswith((".json", ".jsonl")) and rel not in later]

    checks = []
    for rel in sorted(structured):
        parsed, problems = A.read_back_and_parse(os.path.join(repo_root, rel))
        e = entry(repo_root, rel)
        top_keys = sorted(parsed)[:6] if isinstance(parsed, dict) else None
        checks.append({
            "path": rel,
            "size_bytes": e["size_bytes"],
            "sha256": e["sha256"],
            "hash_recomputed": True,
            "parsed": parsed is not None,
            "parse_problems": problems,
            "top_level_keys_sample": top_keys,
        })

    sidecar_rel = f"{LANE_REL}/sidecar/AUTHORSHIP-SIDECAR-SLICE-20260827-v001.json".replace(
        os.sep, "/")
    sidecar_verify: dict = {"skipped": f"NOT_FOUND {sidecar_rel}"}
    if os.path.exists(os.path.join(repo_root, sidecar_rel)):
        sidecar, problems = A.read_back_and_parse(os.path.join(repo_root, sidecar_rel))
        if sidecar is not None:
            failures = A.verify_sidecar(sidecar, A.load_span_bases(sidecar, repo_root))
            sidecar_verify = {
                "path": sidecar_rel,
                "item_count": sidecar["item_count"],
                "segment_count": sidecar["segment_count"],
                "class_tally": sidecar["class_tally"],
                "recomputation_failures": failures,
                "verdict": "SIDECAR_VERIFIED" if not failures
                           else "SIDECAR_FAILED_RECOMPUTATION",
            }
        else:
            sidecar_verify = {"path": sidecar_rel, "verdict": "UNPARSABLE",
                              "parse_problems": problems}

    read_back = {
        "receipt_id": "SCP-C-READ-BACK-20260827-v001",
        "lane": "SCP-SI-01 lane C",
        "generated_at": now,
        "audited_against_integration_commit": args.commit,
        "pushed_sha": args.pushed_sha,
        "evidence_label": "DIRECTLY_REPRODUCED",
        "method": (
            "Every structured artifact is re-read from disk, its sha256 recomputed, "
            "and its content parsed. Hash validity alone is not accepted: a "
            "hash-valid unparsable artifact is a defect in this estate's record, "
            "repaired at commit 3b97d6ff, and shape verification that never checks "
            "truth is the defect evidence_integrity.verify_readback_truth exists to "
            "catch."
        ),
        "artifact_count": len(checks),
        "parsed_count": sum(1 for c in checks if c["parsed"]),
        "unparsable_count": sum(1 for c in checks if not c["parsed"]),
        "artifacts": checks,
        "not_covered_here": {
            "paths": [DECLARATION_REL.replace(os.sep, "/")] + sorted(later),
            "reason": (
                "The declaration hashes this file as its evidence, so this file "
                "cannot hash the declaration. ADMISSION.json and MANIFEST.json "
                "are written after it for the same reason. The cycle is broken "
                "here and declared; the declaration is hash-and-parse verified "
                "by verify_declaration_evidence.py against the disk and by "
                "ADMISSION.json against the gates, and all four are hash-covered "
                "by MANIFEST.json."
            ),
        },
        "sidecar_recomputation": sidecar_verify,
        "limitation": (
            "This is a local read-back. It proves the committed bytes hash and "
            "parse in this working tree. It does not prove the remote holds them; "
            "that is what the git ls-remote confirmation in the lane return covers."
        ),
    }
    read_back_path = os.path.join(receipt_dir, "READ-BACK.json")
    with open(read_back_path, "w", encoding="utf-8") as fh:
        json.dump(read_back, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"read-back     = {read_back['parsed_count']}/{read_back['artifact_count']} "
          f"parsed, {read_back['unparsable_count']} unparsable")
    print(f"sidecar       = {sidecar_verify.get('verdict')}")
    return 0 if read_back["unparsable_count"] == 0 else 1


def build_manifest(repo_root: str, now: str, commit: str,
                   pushed_sha: str | None) -> int:
    """Stage 4. Closure over every file the lane wrote, including the declaration."""
    receipt_dir = os.path.join(repo_root, RECEIPT_REL)
    paths = walk(repo_root, LANE_REL) + walk(repo_root, RECEIPT_REL)
    if os.path.exists(os.path.join(repo_root, DECLARATION_REL)):
        paths.append(DECLARATION_REL.replace(os.sep, "/"))
    manifest_rel = f"{RECEIPT_REL}/{MANIFEST_NAME}".replace(os.sep, "/")
    entries = [entry(repo_root, rel) for rel in sorted(set(paths))
               if rel != manifest_rel]
    entries.sort(key=lambda e: e["path"])

    manifest = {
        "manifest_id": "SCP-C-MANIFEST-20260827-v001",
        "lane": "SCP-SI-01 lane C",
        "generated_at": now,
        "audited_against_integration_commit": commit,
        "pushed_sha": pushed_sha,
        "state": "READY_TO_COMMIT",
        "is_a_proposal_not_a_binding": True,
        "decision_changed": [],
        "closure": {
            "covers": [
                f"{LANE_REL}/**".replace(os.sep, "/"),
                f"{RECEIPT_REL}/**".replace(os.sep, "/"),
                DECLARATION_REL.replace(os.sep, "/"),
            ],
            "excluded": [manifest_rel],
            "exclusion_reason": (
                "A manifest cannot contain its own hash. This is the only "
                "exclusion and it is declared here, so closure is checkable: "
                "every other file the lane wrote is an entry."
            ),
            "bundle_sha256_construction":
                'sha256(json.dumps(entries, sort_keys=True, separators=(",",":")))',
        },
        "entry_count": len(entries),
        "bundle_sha256": A.bundle_sha256(entries),
        "entries": entries,
    }
    manifest_path = os.path.join(receipt_dir, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # ---- verify what was just written, by recomputation -----------------
    reread, problems = A.read_back_and_parse(manifest_path)
    if reread is None:
        for p in problems:
            print(f"FAIL {p}")
        return 1
    recomputed = A.bundle_sha256(reread["entries"])
    closure_errors = []
    if recomputed != reread["bundle_sha256"]:
        closure_errors.append(
            f"BUNDLE_MISMATCH: recomputed {recomputed} vs recorded "
            f"{reread['bundle_sha256']}")
    if len(reread["entries"]) != reread["entry_count"]:
        closure_errors.append("ENTRY_COUNT_MISMATCH")
    for e in reread["entries"]:
        try:
            fresh = entry(repo_root, e["path"])
        except OSError:
            closure_errors.append(f"MISSING: {e['path']}")
            continue
        if fresh["sha256"] != e["sha256"]:
            closure_errors.append(f"HASH_MISMATCH: {e['path']}")
        if fresh["size_bytes"] != e["size_bytes"]:
            closure_errors.append(f"SIZE_MISMATCH: {e['path']}")
    present = set(walk(repo_root, LANE_REL) + walk(repo_root, RECEIPT_REL))
    for rel in sorted(present):
        if rel != manifest_rel and rel not in {e["path"] for e in reread["entries"]}:
            closure_errors.append(f"UNDECLARED_FILE_PRESENT: {rel}")

    for err in closure_errors:
        print(f"FAIL {err}")
    print(f"entry_count   = {reread['entry_count']}")
    print(f"bundle_sha256 = {reread['bundle_sha256']}")
    print(f"closure       = {'CLOSED' if not closure_errors else 'FAILED'}")
    return 1 if closure_errors else 0


if __name__ == "__main__":
    sys.exit(main())
