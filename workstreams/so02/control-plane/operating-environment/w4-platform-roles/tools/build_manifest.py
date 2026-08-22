#!/usr/bin/env python3
"""Build the OE-W4 delivery manifest with material closure.

Two earlier bundles in this estate manifested their own listed files correctly
and still failed acceptance, because a read-back record that a claim depended on
was left out of the manifest that was supposed to cover it (EC-03, from AC-03
FAIL). Listing what you happen to have written is not closure.

So this manifest asserts two things a verifier can check:

  1. Namespace closure. Entries cover every file under both delivery namespaces,
     minus the manifest itself. The exclusion is declared, not implied, and the
     covered set is recomputed from the filesystem rather than accumulated as
     files are added.

  2. Material closure. Every file OUTSIDE those namespaces that a claim in this
     bundle rests on is recorded with its git blob SHA, so a third party can
     fetch exactly the input the claim was made against. Without this, a claim
     about, say, the founder authority record is unverifiable at the version it
     was actually read.

The manifest cannot contain its own hash, so it excludes itself by a stated rule
rather than pretending otherwise. Verification of the manifest itself is by the
commit that carries it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

NAMESPACES = (
    "workstreams/so02/control-plane/operating-environment/w4-platform-roles",
    "receipts/so02/2026-08-22/oe-w4-platform-roles",
)
MANIFEST_PATH = "receipts/so02/2026-08-22/oe-w4-platform-roles/MANIFEST.json"

# Files outside the delivery namespaces that claims in this bundle rest on.
# Each is pinned by git blob SHA so the exact bytes a claim was made against can
# be fetched, rather than whatever the path holds later.
MATERIAL_CLAIM_INPUTS = [
    ("workstreams/so02/control-plane/operating-environment/FOUNDER-AUTHORITY-20260822T2225Z.json",
     "The controlling authority. Every ASSISTANT_IMPOSED verdict rests on it."),
    ("workstreams/so02/control-plane/operating-environment/FOUNDER-TRANCHE-01.md",
     "Introduces AI-01, AI-02, AI-03 and AI-13."),
    ("workstreams/so02/control-plane/operating-environment/SYNTHESIS-OE-20260822-v001.md",
     "Records the one-agent rule as scoped and not inherited (AI-08)."),
    ("workstreams/so02/control-plane/state/control-plane.json",
     "Live routing surface. Carries AI-19 and AI-20; scanned for re-inheritance."),
    ("workstreams/so02/control-plane/state/FOUNDER-OPERATING-DIRECTIVES-20260822.md",
     "Source for the majority of the 27 FOUNDER_BOUND constraints."),
    ("workstreams/so02/control-plane/commissions/CURSOR-OPERATING-ENVIRONMENT-01.md",
     "This lane's commission. Introduces AI-21; source of FB-26 and FB-27."),
    ("workstreams/so02/control-plane/commissions/CHATGPT-SIR-01.md",
     "Introduces AI-06 and AI-07; source of FB-03 and FB-06."),
    ("workstreams/so02/control-plane/commissions/CURSOR-SCP-01.md",
     "Supersedes AI-08 and AI-09. The negation source the scanner must not misread."),
    ("workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/BASELINE-FINDINGS.md",
     "Defect evidence for EC-09, EC-18 through EC-22; introduces AI-04 and AI-11."),
    ("workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/GAP-ANALYSIS-AND-IMPROVEMENT-SPEC.json",
     "Gap set behind several EARNED_CONTROL entries."),
    ("workstreams/so02/control-plane/operating-environment/l1-cursor-baseline/CONTROL-SURFACE-ACTIVATION-PROGRAMME.json",
     "Introduces AI-12 and AI-17."),
    ("workstreams/so02/control-plane/operating-environment/l2-capability-research/TOPOLOGY-COMPARISON.md",
     "Capability asymmetries behind the role architecture; introduces AI-16."),
    ("workstreams/so02/control-plane/operating-environment/l3-independent-acceptance/VERDICT.json",
     "The refusal. Defect evidence for EC-03 through EC-08, EC-16 and EC-27."),
    ("workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/diagnosis/DIAGNOSIS-L4-20260822-v001.md",
     "Defect evidence for EC-11 through EC-15, EC-24 and EC-25."),
    ("workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale/CHATGPT-SCALE-OPERATING-PROGRAMME-20260822-v001.md",
     "Introduces AI-10, AI-14, AI-15, AI-18 and AI-22. Overruled in four places."),
    ("workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale/FUNCTION-TOPOLOGY-REGISTER-20260822-v001.json",
     "The register re-validated in l5-register-checks.txt."),
    ("workstreams/so02/control-plane/operating-environment/l5-chatgpt-scale/OPENAI-API-SURFACE-FINDINGS-20260822-v001.md",
     "Source of EC-26 and of the five items excluded from classification."),
    ("workstreams/so02/control-plane/operating-environment/GROUP-MANIFEST-OE-20260822-v001.json",
     "Records the one-agent restriction as completed and not inherited."),
    ("AGENTS.md",
     "Rules 3, 6, 8 and 9, which the visibility mechanism implements rather than competes with."),
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
    """Recompute the covered set from the filesystem.

    Deliberately not accumulated as files are written: an accumulated list can
    only ever be as complete as the writer remembered to be, which is the
    failure EC-03 records.
    """
    found: list[str] = []
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
    return sorted(found)


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
        "manifest_id": "OE-W4-PLATFORM-ROLES-MANIFEST-20260822-v001",
        "lane": "OE-W4-PLATFORM-ROLES",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "branch": "cursor/oe-w4-platform-roles-696d",
        "base_commit": "3f3ee110cf9b769e60c664f758c437dcc582afd3",
        "state": "READY_TO_COMMIT",
        "is_a_proposal_not_a_binding": True,

        "closure": {
            "namespaces_covered": list(NAMESPACES),
            "self_exclusion_rule": (
                "This manifest excludes itself and nothing else. A file cannot "
                "contain its own hash, so the exclusion is declared rather than "
                "implied. The manifest is verified by the commit that carries it."
            ),
            "excluded_by_rule": [MANIFEST_PATH],
            "also_excluded": "Compiled bytecode (__pycache__, *.pyc). Transport debris, not evidence; gitignored in this tree.",
            "closure_assertion": (
                "entries == every file under namespaces_covered, minus "
                "excluded_by_rule, minus also_excluded"
            ),
            "closure_check": (
                "python3 workstreams/so02/control-plane/operating-environment/"
                "w4-platform-roles/tools/build_manifest.py --check "
                "receipts/so02/2026-08-22/oe-w4-platform-roles/MANIFEST.json"
            ),
            "why_material_closure_exists": (
                "EC-03, from AC-03 FAIL: an earlier bundle hashed its listed "
                "entries correctly while omitting a read-back record its own "
                "claims depended on. Listing what was written is not closure; "
                "covering what the claims rest on is."
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
                "Every file outside the delivery namespaces that a claim in this "
                "bundle rests on, pinned by git blob SHA at HEAD so a third party "
                "can fetch the exact bytes the claim was made against."
            ),
            "count": len(material),
            "inputs": material,
        },

        "reproduce": {
            "rebuild_registers": [
                "python3 tools/build_derestriction_register.py --out /tmp/a.json",
                "python3 tools/build_role_register.py --out /tmp/b.json",
            ],
            "validate": [
                "python3 tools/derestrictctl.py verify",
                "python3 tools/rolectl.py check",
                "python3 tools/negative_tests.py",
            ],
            "expected_nonzero_exit": {
                "command": "python3 tools/derestrictctl.py scan",
                "why": (
                    "Three removed restrictions (AI-06, AI-20, AI-21) are still "
                    "live in commissions and control-plane state that lie outside "
                    "this lane's write scope. A non-zero exit is the correct "
                    "result and becomes zero once the holder of those paths acts."
                ),
            },
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
        actual_sha = sha256_file(target)
        if actual_sha != entry["sha256"]:
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
