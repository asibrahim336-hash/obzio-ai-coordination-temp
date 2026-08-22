#!/usr/bin/env python3
"""Test the frozen hypothesis against real immutable commits.

The hypothesis under test: the source-lock receipt can be independently regenerated
from the pinned base without producer narrative. Trees are materialised out of Git
object storage into a scratch directory, then handed to the hermetic mechanism, which
itself never touches Git. Git is used only as a materialiser and as an independent
oracle for blob object names.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

UNIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UNIT_ROOT / "tools"))

import source_lock  # noqa: E402

RECEIPT_PATH = "workstreams/po03/evidence/source-lock.json"
COMMANDS: list[dict[str, object]] = []


def run_git(repo: Path, *args: str) -> bytes:
    command = ("git", "-C", str(repo), *args)
    result = subprocess.run(command, check=True, capture_output=True)
    COMMANDS.append({"argv": list(command[3:]), "exit_code": result.returncode, "tool": "git"})
    return result.stdout


def materialise(repo: Path, sha: str, paths: list[str], dest: Path) -> list[str]:
    """Extract exactly the declared paths at an immutable commit, without a checkout."""
    archive = run_git(repo, "archive", "--format=tar", sha, "--", *paths)
    extracted: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe archive member: {member.name}")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = bundle.extractfile(member)
            if handle is None:
                continue
            target.write_bytes(handle.read())
            extracted.append(str(name))
    return sorted(extracted)


def read_blob(repo: Path, sha: str, path: str) -> bytes:
    return run_git(repo, "show", f"{sha}:{path}")


def blob_oracle(repo: Path, sha: str, paths: list[str]) -> dict[str, str]:
    """Ask Git for each blob object name so the stdlib computation can be checked."""
    return {path: run_git(repo, "rev-parse", f"{sha}:{path}").decode().strip() for path in paths}


def experiment_regenerate(repo: Path, spec: dict, tree_sha: str, receipt: bytes) -> dict:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "tree"
        materialise(repo, tree_sha, list(spec["source_paths"]), root)
        rebuilt = source_lock.canonical_json(source_lock.regenerate(root, spec)).encode("utf-8")
        oracle = blob_oracle(repo, tree_sha, list(spec["source_paths"]))
        computed = {
            entry["path"]: entry["git_blob_sha"]
            for entry in json.loads(rebuilt.decode("utf-8"))["sources"]
        }
    return {
        "blob_oracle_agreement": computed == oracle,
        "blob_oracle_disagreements": sorted(
            path for path, value in computed.items() if oracle.get(path) != value
        ),
        "byte_identical": rebuilt == receipt,
        "committed_receipt_bytes": len(receipt),
        "committed_receipt_sha256": hashlib.sha256(receipt).hexdigest(),
        "regenerated_bytes": len(rebuilt),
        "regenerated_sha256": hashlib.sha256(rebuilt).hexdigest(),
        "status": "PASS" if rebuilt == receipt and computed == oracle else "FAIL",
        "tree_sha": tree_sha,
    }


def experiment_verify(repo: Path, lock: dict, tree_sha: str) -> dict:
    paths = [entry["path"] for entry in lock["sources"]]
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "tree"
        materialise(repo, tree_sha, paths, root)
        report = source_lock.verify(root, lock)
    report["tree_sha"] = tree_sha
    return report


def experiment_coverage(repo: Path, lock: dict, tree_sha: str, prefix: str) -> dict:
    """Measure how much of the governed subtree the receipt actually pins."""
    listing = run_git(repo, "ls-tree", "-r", "--name-only", "-z", tree_sha, "--", prefix)
    present = sorted(item for item in listing.decode("utf-8").split("\0") if item)
    declared = {entry["path"] for entry in lock["sources"]}
    return {
        "declared_inside_prefix": sorted(declared & set(present)),
        "declared_total": len(declared),
        "prefix": prefix,
        "tracked_files_in_prefix": len(present),
        "undeclared_files_in_prefix": len([item for item in present if item not in declared]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--receipt-commit", required=True, help="commit holding the receipt file")
    parser.add_argument("--drift-commit", required=True, help="commit to test the receipt against")
    parser.add_argument("--coverage-prefix", default="workstreams/po03/")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        spec = source_lock.load_spec(args.spec)
        tree_sha = str(spec["metadata"]["head_sha"])
        receipt = read_blob(args.repo, args.receipt_commit, RECEIPT_PATH)
        lock = json.loads(receipt.decode("utf-8"))

        regeneration = experiment_regenerate(args.repo, spec, tree_sha, receipt)
        at_pinned = experiment_verify(args.repo, lock, tree_sha)
        at_drift = experiment_verify(args.repo, lock, args.drift_commit)
        coverage = experiment_coverage(args.repo, lock, args.drift_commit, args.coverage_prefix)

        supported = (
            regeneration["status"] == "PASS"
            and at_pinned["status"] == "PASS"
            and at_drift["status"] == "FAIL"
        )
        document = {
            "commands": COMMANDS,
            "coverage_probe": coverage,
            "drift_commit": args.drift_commit,
            "experiments": {
                "e1_byte_identical_regeneration_at_pinned_tree": regeneration,
                "e2_verification_at_pinned_tree": at_pinned,
                "e3_verification_at_drift_commit": at_drift,
            },
            "git_version": run_git(args.repo, "--version").decode().strip(),
            "hypothesis": (
                "The source-lock receipt can be independently regenerated from the "
                "pinned base without producer narrative."
            ),
            "hypothesis_outcome": "SUPPORTED_WITH_BOUNDARY" if supported else "NOT_SUPPORTED",
            "python_version": sys.version.split()[0],
            "receipt_commit": args.receipt_commit,
            "receipt_path": RECEIPT_PATH,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(source_lock.canonical_json(document), encoding="utf-8")
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"PO03_REPRODUCTION_ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"PO03_REPRODUCTION_OUTCOME {document['hypothesis_outcome']}")
    print(f"PO03_REPRODUCTION_E1 {regeneration['status']} byte_identical={regeneration['byte_identical']}")
    print(f"PO03_REPRODUCTION_E2 {at_pinned['status']} findings={len(at_pinned['findings'])}")
    print(f"PO03_REPRODUCTION_E3 {at_drift['status']} drifted={at_drift['mismatched_paths']}")
    return 0 if supported else 1


if __name__ == "__main__":
    raise SystemExit(main())
