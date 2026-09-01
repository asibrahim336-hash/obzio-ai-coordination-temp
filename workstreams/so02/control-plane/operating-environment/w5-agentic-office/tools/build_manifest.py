#!/usr/bin/env python3
"""Build the OE-W5 delivery manifest with full closure.

Closure here means three things a verifier can check without trusting this lane:

  1. Namespace closure. Entries cover every file this lane delivered: the launch
     guide, everything under w5-agentic-office/, and everything under the lane's
     receipts directory. The covered set is recomputed from the filesystem on
     every run rather than accumulated as files are written, because an
     accumulated list is only ever as complete as the writer remembered to be —
     which is the failure an earlier bundle in this estate actually shipped.

  2. Self-exclusion, declared. The manifest cannot contain its own hash. It
     therefore excludes exactly itself, says so, and is verified by the commit
     that carries it. Nothing else is excluded on a judgement call: the only
     other omission is compiled bytecode, which is gitignored transport debris.

  3. Material closure. Every file OUTSIDE the delivery namespaces that a claim in
     the guide rests on is pinned by git blob SHA, so a third party can fetch the
     exact bytes the claim was made against rather than whatever the path holds
     later. Without this, "the partition validators pass" is unverifiable at the
     version that was actually run.

`--check` re-derives all of it from disk and recomputes bundle_sha256. It is the
command a reviewer runs; it does not read this lane's word for anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

GUIDE = "workstreams/so02/control-plane/operating-environment/AGENTIC-OFFICE-LAUNCH-GUIDE.md"
NAMESPACES = (
    "workstreams/so02/control-plane/operating-environment/w5-agentic-office",
    "receipts/so02/2026-08-22/oe-w5-agentic-office",
)
MANIFEST_PATH = "receipts/so02/2026-08-22/oe-w5-agentic-office/MANIFEST.json"

# Files outside the delivery namespaces that claims in the guide rest on.
# Pinned by git blob SHA at HEAD so the exact input can be fetched.
MATERIAL_CLAIM_INPUTS = [
    (".cursor/rules/00-founder-standing-authority.mdc",
     "Always-applied standing authority. Governs this lane and is cited in the guide's header."),
    ("workstreams/so02/control-plane/operating-environment/FOUNDER-STANDING-INSTRUCTION-20260822.md",
     "The founder's words verbatim. The source of the guide's framing and of the void-planner correction."),
    ("workstreams/so02/control-plane/operating-environment/FOUNDER-AUTHORITY-20260822T2225Z.json",
     "The authority envelope. Every 'you may proceed without asking' in the guide rests on it."),
    ("workstreams/so02/control-plane/operating-environment/w4-platform-roles/PLATFORM-ROLE-REGISTER-20260822-v001.json",
     "The decision-class partition the eight seats strictly refine. Section 4 is unverifiable without it."),
    ("workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/rolectl.py",
     "The 14 invariants the guide tells the office to run at every dispatch."),
    ("workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/negative_tests.py",
     "The 20 proven rejections cited as evidence the partition actually refuses."),
    ("workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/ledger/admission-ladder.json",
     "The six rungs and the non-admissible evidence list. Section 5 is a reading of this file."),
    ("workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tools/currentctl.py",
     "The compiler that reports UNDIFFERENTIATED_COMMISSION_OVERLAP=7, the guide's first ranked ceiling."),
    ("workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/BASELINE-FINDINGS.md",
     "Source of the exit-zero push finding and the detached-HEAD collision the guide treats as load-bearing."),
    ("workstreams/so02/control-plane/operating-environment/w2-cursor-config/W2-FINDINGS-20260822-v001.md",
     "Source of the inert environment.json finding (B2) and the hooks-in-worktrees finding (B3)."),
    ("workstreams/so02/control-plane/operating-environment/w3-credential-estate/CURSOR-API-KEY-RECOVERY-ROUTES.json",
     "The mirror-the-existing-key route in stage 2a, and the reason a new key is refused."),
    ("workstreams/so02/control-plane/operating-environment/SYNTHESIS-OE-20260822-v001.md",
     "Prior synthesis the guide folds in rather than restates."),
    ("AGENTS.md",
     "Repository-wide operator instructions the guide operates under, notably rules 6, 7 and 9."),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha(root: Path, rel: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"HEAD:{rel}"],
            capture_output=True, text=True, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except OSError:
        return None


def covered_paths(root: Path) -> list[str]:
    """Recompute the covered set from the filesystem, never from memory."""
    found: list[str] = []

    if (root / GUIDE).is_file():
        found.append(GUIDE)

    for namespace in NAMESPACES:
        base = root / namespace
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel == MANIFEST_PATH:
                continue
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            found.append(rel)
    return sorted(set(found))


def build(root: Path) -> dict:
    entries = [
        {
            "path": rel,
            "size_bytes": (root / rel).stat().st_size,
            "sha256": sha256_file(root / rel),
        }
        for rel in covered_paths(root)
    ]

    bundle_sha256 = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    material = []
    for rel, why in MATERIAL_CLAIM_INPUTS:
        blob = git_blob_sha(root, rel)
        material.append({
            "path": rel,
            "git_blob_sha": blob,
            "present_in_head": blob is not None,
            "why_material": why,
        })

    return {
        "manifest_id": "OE-W5-AGENTIC-OFFICE-MANIFEST-20260822-v001",
        "lane": "OE-W5-AGENTIC-OFFICE-GUIDE",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "branch": "cursor/oe-w5-agentic-office-696d",
        "state": "READY_TO_COMMIT",
        "is_a_proposal_not_a_binding": True,
        "deliverable": GUIDE,

        "closure": {
            "covered": [GUIDE, *NAMESPACES],
            "self_exclusion_rule": (
                "This manifest excludes itself and nothing else. A file cannot "
                "contain its own hash, so the exclusion is declared rather than "
                "implied. The manifest is verified by the commit that carries it."
            ),
            "excluded_by_rule": [MANIFEST_PATH],
            "also_excluded": (
                "Compiled bytecode (__pycache__, *.pyc, *.pyo). Transport debris "
                "regenerated on import, not evidence, and gitignored in this tree."
            ),
            "read_back_record_is_covered": (
                "receipts/so02/2026-08-22/oe-w5-agentic-office/READ-BACK-20260822-v001.json "
                "is a manifest entry, not an exception. Full closure was required "
                "because an earlier bundle in this estate hashed its listed files "
                "correctly while omitting the read-back record its own claims "
                "depended on."
            ),
            "closure_assertion": (
                "entries == the guide, plus every file under the covered "
                "namespaces, minus excluded_by_rule, minus also_excluded"
            ),
            "closure_check": (
                "python3 workstreams/so02/control-plane/operating-environment/"
                "w5-agentic-office/tools/build_manifest.py --check "
                + MANIFEST_PATH
            ),
        },

        "entry_count": len(entries),
        "bundle_sha256": bundle_sha256,
        "bundle_sha256_definition": (
            'sha256 of json.dumps(entries, sort_keys=True, separators=(",",":"))'
        ),
        "entries": entries,

        "material_claim_inputs": {
            "rule": (
                "Every file outside the delivery namespaces that a claim in the "
                "guide rests on, pinned by git blob SHA at HEAD so a third party "
                "can fetch the exact bytes the claim was made against."
            ),
            "count": len(material),
            "inputs": material,
        },

        "verify_the_bundle": {
            "closure_and_hashes": (
                "python3 workstreams/so02/control-plane/operating-environment/"
                "w5-agentic-office/tools/build_manifest.py --check " + MANIFEST_PATH
            ),
            "office_invariants": [
                "python3 workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/officectl.py check",
                "python3 workstreams/so02/control-plane/operating-environment/w5-agentic-office/tools/negative_tests.py",
            ],
            "constitution_still_holds": [
                "python3 workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/rolectl.py check",
                "python3 workstreams/so02/control-plane/operating-environment/w4-platform-roles/tools/negative_tests.py",
            ],
            "the_first_ranked_ceiling": (
                "python3 workstreams/so02/control-plane/operating-environment/"
                "l4-currentness-recovery/tools/currentctl.py compile --repo-root . "
                "--out /tmp/projection.json   # read the findings line"
            ),
            "re_fetch_every_cited_page": (
                "bash workstreams/so02/control-plane/operating-environment/"
                "w5-agentic-office/tools/refetch_docs.sh"
            ),
            "all_expected_exit_codes": 0,
        },
    }


def check(root: Path, manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text())
    problems: list[str] = []

    listed = {e["path"] for e in manifest["entries"]}
    actual = set(covered_paths(root))
    for missing in sorted(actual - listed):
        problems.append(f"UNMANIFESTED: {missing} exists in a covered namespace and is not in the manifest")
    for phantom in sorted(listed - actual):
        problems.append(f"PHANTOM: {phantom} is manifested and does not exist")

    for entry in manifest["entries"]:
        target = root / entry["path"]
        if not target.exists():
            continue
        if sha256_file(target) != entry["sha256"]:
            problems.append(f"HASH_MISMATCH: {entry['path']}")
        if target.stat().st_size != entry["size_bytes"]:
            problems.append(f"SIZE_MISMATCH: {entry['path']}")

    if manifest["entry_count"] != len(manifest["entries"]):
        problems.append(
            f"COUNT_MISMATCH: entry_count {manifest['entry_count']} != {len(manifest['entries'])} entries"
        )

    recomputed = hashlib.sha256(
        json.dumps(manifest["entries"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if recomputed != manifest["bundle_sha256"]:
        problems.append(
            f"BUNDLE_SHA_MISMATCH: recomputed {recomputed} != declared {manifest['bundle_sha256']}"
        )

    if manifest["deliverable"] not in listed:
        problems.append("DELIVERABLE_UNMANIFESTED: the launch guide is not in the manifest")

    read_back = "receipts/so02/2026-08-22/oe-w5-agentic-office/READ-BACK-20260822-v001.json"
    if (root / read_back).exists() and read_back not in listed:
        problems.append("READ_BACK_UNMANIFESTED: the read-back record exists and is not covered")

    for item in manifest["material_claim_inputs"]["inputs"]:
        if not (root / item["path"]).exists():
            problems.append(f"MATERIAL_INPUT_ABSENT: {item['path']}")

    for problem in problems:
        print(f"ERROR: {problem}")
    if problems:
        print(f"FAIL: {len(problems)} manifest closure problem(s)")
        return 1
    print(
        f"PASS: {manifest['entry_count']} entries, "
        f"{manifest['material_claim_inputs']['count']} material claim inputs, "
        f"bundle_sha256 {manifest['bundle_sha256']} recomputed and matching"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--check")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.check:
        return check(root, Path(args.check))

    if not args.out:
        parser.error("one of --out or --check is required")

    manifest = build(root)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    print(
        f"wrote {args.out} entries={manifest['entry_count']} "
        f"material_inputs={manifest['material_claim_inputs']['count']} "
        f"bundle_sha256={manifest['bundle_sha256']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
