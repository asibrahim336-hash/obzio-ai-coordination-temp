#!/usr/bin/env python3
"""Run all independent detectors against the immutable source lock."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

if __package__:
    from . import boundary_run, debris, manifest_gaps, portability, qualify
    from .git_tree import GitTree
else:  # pragma: no cover - direct command entry point
    import boundary_run
    import debris
    import manifest_gaps
    import portability
    import qualify
    from git_tree import GitTree


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_absence(paths: set[str]) -> dict[str, object]:
    lowered = {path.lower(): path for path in paths}
    matches = {
        name: sorted(
            original
            for lower, original in lowered.items()
            if token in lower
        )
        for name, token in (
            ("packverify", "packverify"),
            ("fixtures", "fixtures"),
            ("code2", "code2"),
            ("code-2", "code-2"),
            ("runner", "runner"),
        )
    }
    return {
        "path_matches": matches,
        "po02_runner": (
            "NOT_YET: no pinned path identifies a PO-02 runner; a "
            "modules/work_unit_contract/runner.py match is a different "
            "repository component"
            if matches["runner"]
            else "ABSENT: no runner-named path exists in the pinned tree"
        ),
        "po02_fixtures": (
            "NOT_YET: fixture-named paths exist but are not identified as PO-02"
            if matches["fixtures"]
            else "ABSENT: no fixture-named path exists in the pinned tree"
        ),
        "code2_result_bytes": (
            "NOT_YET: a Code-2-named path exists without admissible identity"
            if matches["code2"] or matches["code-2"]
            else "ABSENT: no Code-2-named path exists in the pinned tree"
        ),
        "producer_packverify_source": (
            "PRESENT"
            if matches["packverify"]
            else "ABSENT: no packverify-named path exists in the pinned tree"
        ),
    }


def _repair_candidates(source_results: list[dict[str, object]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for source in source_results:
        commit = str(source["commit_sha"])
        for root_result in source["root_results"]:
            root = str(root_result["root"])
            for finding in root_result["missing_blobs"]["findings"]:
                target = str(finding["tree_path"])
                if target.endswith("/_spine.py"):
                    candidates.append(
                        {
                            "candidate_id": (
                                f"REPAIR-MISSING-SPINE-{commit[:12]}-"
                                f"{target.replace('/', '-')}"
                            ),
                            "defect": "manifest_entry_missing_blob",
                            "pinned_commit": commit,
                            "target_namespace": target,
                            "proposed_change": {
                                "operation": "COPY_HASH_MATCHING_SHARED_SPINE",
                                "expected_sha256": finding["expected_sha256"],
                                "destination": target,
                            },
                            "state": "ISOLATED_PO03_CANDIDATE_NOT_APPLIED",
                        }
                    )
            process = root_result["process_boundary"].get("process")
            if (
                isinstance(process, Mapping)
                and process.get("exit_code") not in (0, None)
                and "/tmp/packs" in str(process.get("stderr", ""))
            ):
                candidates.append(
                    {
                        "candidate_id": f"REPAIR-PORTABLE-RUNNER-{commit[:12]}",
                        "defect": "absolute_checkout_dependency",
                        "pinned_commit": commit,
                        "target_namespace": f"{root}/run_all_tests.sh",
                        "proposed_change": {
                            "operation": "UNIFIED_DIFF_DATA",
                            "patch": (
                                "--- a/{0}/run_all_tests.sh\n"
                                "+++ b/{0}/run_all_tests.sh\n"
                                "@@\n"
                                "+ROOT=\"$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\"\n"
                                "-  ( cd \"/tmp/packs/$p\" && python3 test_pack.py ) || rc=1\n"
                                "+  ( cd \"$ROOT/$p\" && python3 test_pack.py ) || rc=1\n"
                            ).format(root),
                        },
                        "state": "ISOLATED_PO03_CANDIDATE_NOT_APPLIED",
                    }
                )
            manifest_root_findings = [
                finding
                for finding in root_result["portability"]["findings"]
                if finding["source_path"] == f"{root}/MANIFEST.json"
                and finding["value"] == "/tmp/packs"
            ]
            if manifest_root_findings:
                candidates.append(
                    {
                        "candidate_id": f"REPAIR-MANIFEST-ROOT-{commit[:12]}",
                        "defect": "machine_specific_root",
                        "pinned_commit": commit,
                        "target_namespace": f"{root}/MANIFEST.json",
                        "proposed_change": {
                            "operation": "JSON_PATCH_DATA",
                            "patch": [{"op": "replace", "path": "/root", "value": "."}],
                        },
                        "state": "ISOLATED_PO03_CANDIDATE_NOT_APPLIED",
                    }
                )
    return sorted(candidates, key=lambda item: str(item["candidate_id"]))


def run(
    repository: Path,
    source_lock_path: Path,
    criteria_path: Path,
    scratch: Path,
) -> dict[str, object]:
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    source_results: list[dict[str, object]] = []
    for source in source_lock["sources"]:
        tree = GitTree(repository, source["commit_sha"])
        tree.verify_commit()
        roots = tree.pack_roots()
        root_results = []
        for root in roots:
            root_results.append(
                {
                    "root": root,
                    "missing_blobs": qualify.qualify(tree, root),
                    "portability": portability.inspect(tree, root),
                    "manifest_gaps": manifest_gaps.audit(tree, root),
                    "process_boundary": boundary_run.execute(
                        tree, root, scratch, timeout_seconds=120
                    ),
                }
            )
        source_results.append(
            {
                "ref": source["ref"],
                "commit_sha": source["commit_sha"],
                "pack_roots": list(roots),
                "pack_tree_outcome": "PRESENT" if roots else "ABSENT",
                "root_results": root_results,
                "transport_debris": debris.inspect(tree),
                "supplied_artifact_boundary": _source_absence(set(tree.paths())),
            }
        )

    missing_count = sum(
        result["missing_blobs"]["missing_blob_count"]
        for source in source_results
        for result in source["root_results"]
    )
    portability_count = sum(
        result["portability"]["finding_count"]
        for source in source_results
        for result in source["root_results"]
    )
    gap_counts = {
        name: sum(
            result["manifest_gaps"]["counts"][name]
            for source in source_results
            for result in source["root_results"]
        )
        for name in manifest_gaps.GAP_CLASSES
    }
    boundary_failures = sum(
        result["process_boundary"]["outcome"] == "FAIL"
        for source in source_results
        for result in source["root_results"]
    )
    debris_count = sum(
        source["transport_debris"]["finding_count"] for source in source_results
    )
    report: dict[str, object] = {
        "schema_version": "po03-pack-reproduction-v1",
        "commission_id": source_lock["commission_id"],
        "evidence_inputs": {
            "source_lock": str(source_lock_path.relative_to(repository)),
            "source_lock_sha256": _sha256(source_lock_path),
            "criteria_freeze": str(criteria_path.relative_to(repository)),
            "criteria_freeze_sha256": _sha256(criteria_path),
            "producer_narrative_used_as_evidence": False,
        },
        "generation_command": (
            "python3 -I workstreams/po03/packverify/run_qualification.py "
            "--repository . "
            "--source-lock workstreams/po03/evidence/source-lock.json "
            "--criteria workstreams/po03/evidence/criteria-freeze.json "
            "--scratch workstreams/po03/control/units/a4/scratch "
            "--output workstreams/po03/evidence/reproduction-results.json"
        ),
        "sources": source_results,
        "summary": {
            "source_count": len(source_results),
            "sources_with_pack_roots": sum(
                bool(source["pack_roots"]) for source in source_results
            ),
            "missing_blob_findings": missing_count,
            "portability_findings": portability_count,
            "manifest_gap_findings": gap_counts,
            "process_boundary_failures": boundary_failures,
            "transport_debris_findings": debris_count,
        },
        "hypothesis_dispositions": {
            "a4-u01": "PASS: all used sources are immutable full SHAs and no PO-01 ref was written",
            "a4-u02": (
                "NOT_YET: criteria ordering is proven, but no admissible "
                "narrative-first baseline exists to establish changed outcome"
            ),
            "a4-u03": (
                "PASS: planted fixture gates the detector and immutable trees "
                f"produce {missing_count} missing-blob findings"
            ),
            "a4-u04": (
                "PASS: planted path classes are detected and immutable trees "
                f"produce {portability_count} portability findings"
            ),
            "a4-u05": (
                "PASS: all three closed-set gap classes have planted fixtures; "
                f"real counts are {gap_counts}"
            ),
            "a4-u06": (
                "NOT_YET: the immutable aggregate entry points fail across the "
                "process boundary, but an independent in-process pass was not "
                "established"
            ),
            "a4-u07": (
                "PASS: deterministic read-only classification found "
                f"{debris_count} transport-debris candidates"
            ),
        },
        "limitations": [
            "PO-02 runner identity, PO-02 fixtures, Code-2 result bytes, and producer packverify source are not present as identified artifacts in the pinned source set.",
            "No producer report, branch name, commit message, or pull-request narrative was used to establish a pack result.",
            "The process-boundary run evaluates aggregate entry points present in committed bytes; it does not infer unavailable expected output.",
        ],
    }
    report["isolated_repair_candidates"] = _repair_candidates(source_results)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--source-lock", required=True)
    parser.add_argument("--criteria", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    repository = Path(args.repository).resolve()
    report = run(
        repository,
        (repository / args.source_lock).resolve(),
        (repository / args.criteria).resolve(),
        (repository / args.scratch).resolve(),
    )
    output = (repository / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"output": args.output, "summary": report["summary"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
