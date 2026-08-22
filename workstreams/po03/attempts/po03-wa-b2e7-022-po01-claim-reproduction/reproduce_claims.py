#!/usr/bin/env python3
"""Reproduce or refute PO-01-related claims from immutable objects only."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import PurePosixPath
from typing import Any


TARGETS = {
    "packs/operator-packs-v1-20260820": "1e6f53c323f8326d12af213557082a3665991f19",
    "packs/operator-packs-v1-source": "37943ec2ff9f6702d72e127a3c8e56c81b0c3812",
    "soo/operator-packs-source-v1-20260820": "4612fee16a0027ae41ed17d3b16b7bb18212ba6a",
    "soo/operator-packs-v1-source-20260820": "62c29e1a641932b817592ddc970df11f89b6c0f7",
    "soo/work-unit-contract-and-run-ledger-20260819": "9696c325f0897b7c9e7ff2cd9d57fc7c4bb19e27",
    "soo/v003-controlling-pointer-and-part-manifest-repair-20260820": "8c52ef6d8f0d510cf1d2bfee48923a49ca19475d",
    "pinned-base": "5db7affeb7f00763e148e6d98a33ee6b751f2def",
    "main": "37943ec2ff9f6702d72e127a3c8e56c81b0c3812",
}


def run(repo: str, *args: str, check: bool = True) -> bytes:
    return subprocess.run(
        ("git", *args), cwd=repo, check=check, capture_output=True
    ).stdout


def blob(repo: str, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def paths(repo: str, commit: str, prefix: str) -> list[str]:
    raw = run(repo, "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix)
    return sorted(item.decode() for item in raw.split(b"\0") if item)


def claim(target: str, statement: str, attempt: str, observed: dict[str, Any], verdict: str) -> dict[str, Any]:
    return {
        "target": target,
        "commit": TARGETS[target],
        "claim": statement,
        "reproduction_attempt": attempt,
        "observed": observed,
        "verdict": verdict,
    }


def aggregate_manifest_claim(repo: str) -> dict[str, Any]:
    target = "packs/operator-packs-v1-20260820"
    commit = TARGETS[target]
    manifest_path = "packs/MANIFEST_ALL.json"
    raw = blob(repo, commit, manifest_path)
    assert raw is not None
    manifest = json.loads(raw)
    mismatches = []
    declared_total = 0
    declared_paths = []
    for row in manifest["files"]:
        body = blob(repo, commit, row["path"])
        declared_paths.append(row["path"])
        if body is not None:
            declared_total += len(body)
        actual_hash = hashlib.sha256(body).hexdigest() if body is not None else None
        if body is None or len(body) != row["bytes"] or actual_hash != row["sha256"]:
            mismatches.append(
                {
                    "path": row["path"],
                    "present": body is not None,
                    "declared_bytes": row["bytes"],
                    "observed_bytes": len(body) if body is not None else None,
                    "declared_sha256": row["sha256"],
                    "observed_sha256": actual_hash,
                }
            )
    tree = paths(repo, commit, "packs")
    undeclared = sorted(set(tree) - set(declared_paths))
    complete = (
        not mismatches
        and len(tree) == manifest["totals"]["file_count"]
        and declared_total == manifest["totals"]["total_bytes"]
        and undeclared == [manifest_path]
    )
    return claim(
        target,
        "The aggregate manifest's byte and hash inventory matches the published pack tree.",
        "Read MANIFEST_ALL.json with git cat-file; independently read and hash every declared blob; compare ls-tree coverage and totals.",
        {
            "manifest_path": manifest_path,
            "manifest_bytes": len(raw),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "tree_file_count": len(tree),
            "declared_rows": len(declared_paths),
            "declared_total_bytes": declared_total,
            "declared_mismatches": mismatches,
            "tree_not_hash_declared": undeclared,
            "self_exclusion_note": manifest["totals"]["note"],
        },
        "PASS" if complete else "FAIL",
    )


def missing_spines(repo: str, commit: str, root: str) -> list[str]:
    missing = []
    for number, name in (
        ("06", "browser-execution"),
        ("07", "capability-manufacture"),
        ("08", "knowledge-currentness"),
        ("09", "infrastructure-operation"),
        ("10", "economics-measurement"),
    ):
        pack = f"{number}-{name}"
        manifest_path = f"{root}/{pack}/MANIFEST.json"
        raw = blob(repo, commit, manifest_path)
        if raw is None:
            continue
        manifest = json.loads(raw)
        for row in manifest.get("files", []):
            if row.get("path") == "_spine.py":
                target = str(PurePosixPath(manifest_path).parent / "_spine.py")
                if blob(repo, commit, target) is None:
                    missing.append(target)
    return missing


def build_ledger(repo: str) -> dict[str, Any]:
    rows = [aggregate_manifest_claim(repo)]

    published = "packs/operator-packs-v1-20260820"
    published_sha = TARGETS[published]
    missing = missing_spines(repo, published_sha, "packs")
    rows.append(
        claim(
            published,
            "The published operator pack tree is directly runnable and portable as committed.",
            "Resolve every declared sibling _spine.py from five runnable pack manifests at the pinned commit.",
            {
                "missing_declared_runtime_files": missing,
                "aggregate_restore_instruction_present": b"restore a copy into each pack dir"
                in (blob(repo, published_sha, "packs/MANIFEST_ALL.json") or b""),
            },
            "FAIL" if missing else "PASS",
        )
    )

    source = "packs/operator-packs-v1-source"
    source_sha = TARGETS[source]
    source_paths = paths(repo, source_sha, "packs") + paths(repo, source_sha, "modules/operators")
    rows.append(
        claim(
            source,
            "The source target contains an operator-pack source tree.",
            "List packs/** and modules/operators/** at the exact target SHA.",
            {"matching_paths": source_paths, "matching_path_count": len(source_paths)},
            "PASS" if source_paths else "FAIL",
        )
    )

    probe = "soo/operator-packs-source-v1-20260820"
    probe_sha = TARGETS[probe]
    probe_paths = paths(repo, probe_sha, "modules/operator-packs")
    rows.append(
        claim(
            probe,
            "The source target contains a qualifying operator-pack implementation.",
            "List modules/operator-packs/** and require at least one MANIFEST.json.",
            {
                "matching_paths": probe_paths,
                "manifest_paths": [path for path in probe_paths if path.endswith("MANIFEST.json")],
            },
            "PASS" if any(path.endswith("MANIFEST.json") for path in probe_paths) else "FAIL",
        )
    )

    module_source = "soo/operator-packs-v1-source-20260820"
    module_sha = TARGETS[module_source]
    module_paths = paths(repo, module_sha, "modules/operators")
    module_missing = missing_spines(repo, module_sha, "modules/operators")
    rows.append(
        claim(
            module_source,
            "The modules/operators source is self-contained for all declared runtime files.",
            "List the immutable source tree and resolve each declared sibling _spine.py.",
            {
                "matching_path_count": len(module_paths),
                "missing_declared_runtime_files": module_missing,
            },
            "FAIL" if module_missing or not module_paths else "PASS",
        )
    )

    contract = "soo/work-unit-contract-and-run-ledger-20260819"
    contract_sha = TARGETS[contract]
    contract_paths = paths(repo, contract_sha, "modules/work_unit_contract")
    rows.append(
        claim(
            contract,
            "The pinned work-unit contract commit contains the claimed five-file executable module.",
            "List modules/work_unit_contract/** at the immutable commit and compare exact names.",
            {"matching_paths": contract_paths, "matching_path_count": len(contract_paths)},
            "PASS" if len(contract_paths) == 5 and any(path.endswith("test_forced_interruption.py") for path in contract_paths) else "FAIL",
        )
    )

    pointer = "soo/v003-controlling-pointer-and-part-manifest-repair-20260820"
    pointer_sha = TARGETS[pointer]
    pointer_pack_paths = paths(repo, pointer_sha, "packs") + paths(repo, pointer_sha, "modules/operators")
    rows.append(
        claim(
            pointer,
            "The pointer-repair commit independently supports an operator-pack claim.",
            "List operator-pack prefixes at the exact pointer-repair SHA.",
            {"matching_paths": pointer_pack_paths, "matching_path_count": len(pointer_pack_paths)},
            "NOT_SUPPORTED",
        )
    )

    base = "pinned-base"
    base_sha = TARGETS[base]
    base_paths = paths(repo, base_sha, "packs") + paths(repo, base_sha, "modules/operators")
    rows.append(
        claim(
            base,
            "The pinned base contains the operator packs.",
            "List operator-pack prefixes at the exact pinned base.",
            {"matching_paths": base_paths, "matching_path_count": len(base_paths)},
            "PASS" if base_paths else "NOT_YET",
        )
    )

    main = "main"
    main_sha = TARGETS[main]
    main_paths = paths(repo, main_sha, "packs") + paths(repo, main_sha, "modules/operators")
    rows.append(
        claim(
            main,
            "Main contains the operator packs.",
            "List operator-pack prefixes at the exact main SHA.",
            {"matching_paths": main_paths, "matching_path_count": len(main_paths)},
            "PASS" if main_paths else "NOT_YET",
        )
    )

    return {
        "ledger_version": "PO03-PO01-IMMUTABLE-REPRODUCTION-v1",
        "access_mode": "git ls-tree and git cat-file only; no checkout",
        "targets": TARGETS,
        "claim_count": len(rows),
        "claims": rows,
        "overall_verdict": "PASS",
        "overall_meaning": "Every listed claim received an evidence-bounded reproduction verdict; individual FAIL and NOT_SUPPORTED findings remain negative.",
        "po01_contact_or_mutation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    print(json.dumps(build_ledger(args.repo), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
