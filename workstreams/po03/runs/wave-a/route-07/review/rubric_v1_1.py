"""Erratum layer v1.1 over the frozen route-07 review rubric.

rubric_v1 is immutable and its stage-1 verdicts are committed verbatim under
review/stage1/. Reviewing the 24 target slots mechanically exposed four
reviewer-side defects in rubric_v1 that are provable from frozen criteria alone,
without consulting any producer conclusion:

  E1  R4 demanded that the transactional result receipt appear inside its own
      manifest. The receipt carries the manifest hash, so listing the receipt in
      the manifest is a circular-hash impossibility. The frozen acceptance
      contract requires a complete *artifact* manifest, not self-inclusion.
  E2  R4 hard-coded the manifest filename `manifest.json`. No frozen criterion
      names a manifest file; `artifact-manifest.json` is equally conformant.
  E3  R2 used one `unittest discover` invocation rooted at the slot. A slot laid
      out as `src/` + `tests/` collects zero tests under that single invocation
      even though its tests run, because `tests/` is not an importable package.
      "Tests actually rerun by the reviewer" is the frozen requirement, not one
      particular invocation.
  E4  R9 required every JSON document in a slot to carry the slot's task_id. A
      sanitized reproduction fixture legitimately carries its own identifier.
      The frozen binding requirement is on the result/manifest/receipt documents
      that assert the acceptance contract, not on fixture data.

Each correction is narrow, is expressed as a verifiable predicate, and is
guarded by additional hidden abuse cases in test_rubric_v1_1.py which prove that
the erratum cannot be used to smuggle a false PASS past rubric_v1's guarantees.

Standard library only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rubric_v1 as rb  # noqa: E402

ERRATUM_ID = "PO03-ROUTE07-REVIEW-RUBRIC-v1.1-ERRATUM"
SUPERSEDES = "PO03-WA-ROUTE07-REVIEW-RUBRIC-v1"

BINDING_DOC_PATTERNS = (
    re.compile(r"^result.*\.json$", re.IGNORECASE),
    re.compile(r".*manifest.*\.json$", re.IGNORECASE),
    re.compile(r"^receipt.*\.json$", re.IGNORECASE),
)


def _is_manifest(path: Path) -> bool:
    return path.suffix == ".json" and "manifest" in path.name.lower()


def _find_manifest(files: list):
    manifests = [f for f in files if _is_manifest(f)]
    if not manifests:
        return None
    exact = [f for f in manifests if f.name.lower() == "manifest.json"]
    return (exact or manifests)[0]


def _declared_manifest_hash(doc) -> str | None:
    """Return the manifest sha256 a result receipt claims, if it claims one."""
    if not isinstance(doc, dict):
        return None
    direct = doc.get("manifest_sha256")
    if isinstance(direct, str):
        return direct
    txn = doc.get("result_transaction")
    if isinstance(txn, dict) and isinstance(txn.get("manifest_sha256"), str):
        return txn["manifest_sha256"]
    return None


def r4_manifest_complete_v1_1(slot: Path, files: list) -> rb.DimensionResult:
    manifest_path = _find_manifest(files)
    if manifest_path is None:
        return rb.DimensionResult("R4_MANIFEST_COMPLETE", "FAIL", "slot has no artifact manifest")
    doc = rb._read_json(manifest_path)
    if isinstance(doc, dict) and "__parse_error__" in doc:
        return rb.DimensionResult(
            "R4_MANIFEST_COMPLETE", "FAIL", "manifest is not parseable JSON", [doc["__parse_error__"]]
        )
    entries = rb._manifest_entries(doc)
    if not entries:
        return rb.DimensionResult(
            "R4_MANIFEST_COMPLETE", "FAIL", "manifest declares no artifact entries"
        )

    manifest_sha = rb.sha256_file(manifest_path)
    by_rel = {rb._rel_to_slot(f, slot): f for f in files}
    by_name: dict = {}
    for f in files:
        by_name.setdefault(f.name, []).append(f)

    defects, checked, listed = [], 0, set()
    for entry in entries:
        rel = entry.get("path") or entry.get("content_uri") or entry.get("uri")
        digest = entry.get("sha256")
        size = entry.get("bytes", entry.get("size_bytes"))
        if not rel or not digest:
            defects.append(f"entry missing path or sha256: {entry}")
            continue
        rel = str(rel)
        target = by_rel.get(rel)
        if target is None:
            hits = [f for r, f in by_rel.items() if rel.endswith("/" + r) or r == rel]
            if len(hits) == 1:
                target = hits[0]
        name = Path(rel).name
        if target is None and len(by_name.get(name, [])) == 1:
            target = by_name[name][0]
        if target is None or not target.exists():
            defects.append(f"manifested artifact absent from slot: {rel}")
            continue
        listed.add(target.resolve())
        actual_digest = rb.sha256_file(target)
        actual_bytes = target.stat().st_size
        if not rb._SHA256_RE.match(str(digest)):
            defects.append(f"malformed sha256 for {rel}: {digest}")
        elif actual_digest != digest:
            defects.append(f"sha256 mismatch for {rel}: manifest={digest} actual={actual_digest}")
        if size is None:
            defects.append(f"no byte count for {rel}")
        elif int(size) != actual_bytes:
            defects.append(f"byte count mismatch for {rel}: manifest={size} actual={actual_bytes}")
        checked += 1

    exempt = {manifest_path.resolve()}
    exempt_reasons = []
    for f in files:
        if f.resolve() in listed or f.resolve() in exempt or f.suffix != ".json":
            continue
        declared = _declared_manifest_hash(rb._read_json(f))
        if declared is None:
            continue
        # E1: a receipt that binds this manifest by hash cannot list itself.
        if declared == manifest_sha:
            exempt.add(f.resolve())
            exempt_reasons.append(
                f"{rb._rel_to_slot(f, slot)} exempt: binds manifest by sha256 {declared[:12]}..."
            )
        else:
            defects.append(
                f"{rb._rel_to_slot(f, slot)} claims manifest sha256 {declared} but manifest is {manifest_sha}"
            )

    unlisted = sorted(
        rb._rel_to_slot(f, slot) for f in files if f.resolve() not in listed and f.resolve() not in exempt
    )
    if unlisted:
        defects.append(f"artifacts present but not manifested: {unlisted}")
    if defects:
        return rb.DimensionResult(
            "R4_MANIFEST_COMPLETE", "FAIL", "manifest reconciliation failed", defects
        )
    return rb.DimensionResult(
        "R4_MANIFEST_COMPLETE",
        "PASS",
        f"{checked} artifact(s) reconciled by sha256 and bytes via {manifest_path.name}",
        exempt_reasons,
    )


def _invocations(slot: Path, test: Path) -> list:
    """Standard, producer-independent ways a reviewer may rerun a test module."""
    rel_parent = test.parent
    return [
        (
            "unittest-discover-slot",
            [sys.executable, "-m", "unittest", "discover", "-s", str(slot), "-p", test.name, "-v"],
            str(slot),
        ),
        (
            "unittest-discover-testdir",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(rel_parent),
                "-t",
                str(slot),
                "-p",
                test.name,
                "-v",
            ],
            str(slot),
        ),
        ("direct-module-run", [sys.executable, str(test), "-v"], str(rel_parent)),
    ]


def r2_tests_rerun_v1_1(slot: Path, files: list, timeout: int = 300) -> rb.DimensionResult:
    tests = [f for f in files if f.suffix == ".py" and f.name.startswith("test_")]
    if not tests:
        return rb.DimensionResult("R2_TESTS_RERUN", "FAIL", "no test_*.py present in slot")
    evidence, failed = [], []
    for test in tests:
        best = None
        for label, argv, cwd in _invocations(slot, test):
            proc = subprocess.run(  # noqa: S603
                argv, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
            out = (proc.stderr or "") + (proc.stdout or "")
            ran = rb._unittest_count(out)
            record = {
                "test": rb._rel_to_slot(test, slot),
                "invocation": label,
                "argv": " ".join(Path(a).name if a == sys.executable else a for a in argv),
                "returncode": proc.returncode,
                "ran": ran,
                "summary": (out.strip().splitlines() or [""])[-1],
            }
            if ran > 0:
                best = record
                break
            best = best or record
        evidence.append(best)
        if best["returncode"] != 0 or best["ran"] == 0:
            failed.append(best)
    if failed:
        return rb.DimensionResult(
            "R2_TESTS_RERUN", "FAIL", "reviewer rerun failed or collected zero tests", evidence
        )
    total = sum(e["ran"] for e in evidence)
    return rb.DimensionResult(
        "R2_TESTS_RERUN", "PASS", f"{total} test(s) rerun green by reviewer", evidence
    )


def _is_binding_doc(path: Path) -> bool:
    return any(p.match(path.name) for p in BINDING_DOC_PATTERNS)


def r9_contract_echo_v1_1(
    slot: Path, files: list, expected_acceptance_sha: str, expected_manifest_sha: str, task_id: str
) -> rb.DimensionResult:
    defects, echoed = [], []
    for f in files:
        if f.suffix != ".json":
            continue
        doc = rb._read_json(f)
        if not isinstance(doc, dict):
            continue
        rel = rb._rel_to_slot(f, slot)
        acc = doc.get("acceptance_contract_sha256")
        if acc is not None:
            echoed.append(rel)
            if acc != expected_acceptance_sha:
                defects.append(
                    f"{rel}: acceptance_contract_sha256={acc} != frozen {expected_acceptance_sha}"
                )
        man = doc.get("immutable_input_manifest_sha256")
        if man is not None and man != expected_manifest_sha:
            defects.append(
                f"{rel}: immutable_input_manifest_sha256={man} != frozen {expected_manifest_sha}"
            )
        # E4: only documents that assert the contract, or are named as the
        # result/manifest/receipt of the slot, are bound to the slot task_id.
        binding = _is_binding_doc(f) or acc is not None
        tid = doc.get("task_id")
        if binding and tid is not None and tid != task_id:
            defects.append(f"{rel}: task_id={tid} != {task_id}")
    if not echoed:
        return rb.DimensionResult(
            "R9_CONTRACT_ECHO", "FAIL", "no artifact binds the slot to its frozen acceptance contract"
        )
    if defects:
        return rb.DimensionResult("R9_CONTRACT_ECHO", "FAIL", "frozen contract binding broken", defects)
    return rb.DimensionResult("R9_CONTRACT_ECHO", "PASS", "frozen contract hashes echoed", echoed)


def review_slot_v1_1(
    repo_root: Path,
    slot_rel: str,
    task_id: str,
    hypothesis: str,
    acceptance_sha: str,
    manifest_sha: str,
    owned_prefix: str,
    cohort: dict | None = None,
) -> rb.SlotReview:
    slot = repo_root / slot_rel
    review = rb.SlotReview(
        task_id=task_id,
        slot=slot_rel,
        frozen_hypothesis=hypothesis,
        acceptance_contract_sha256=acceptance_sha,
    )
    if not slot.is_dir():
        review.dimensions = [
            rb.DimensionResult(name, "FAIL", "result slot does not exist") for name in rb.DIMENSIONS
        ]
        review.recommendation = "RECOMMEND_REJECT"
        review.defects = [f"missing slot {slot_rel}"]
        return review
    files = rb._walk_files(slot)
    dims = [
        rb.r1_executable_unit(slot, files),
        r2_tests_rerun_v1_1(slot, files),
        r4_manifest_complete_v1_1(slot, files),
        rb.r5_disposition_legal(slot, files),
        rb.r7_path_confinement(slot, files, owned_prefix, repo_root),
        rb.r8_no_self_acceptance(slot, files),
        r9_contract_echo_v1_1(slot, files, acceptance_sha, manifest_sha, task_id),
        rb.r3_commands_and_observed(slot, files),
        rb.r6_limitations_present(slot, files),
        rb.r10_hypothesis_exercised(slot, files, hypothesis),
        rb.r11_not_duplicated(slot, files, cohort or {}, task_id),
    ]
    review.dimensions = dims
    review.recommendation = rb.recommend(dims)
    review.defects = [f"{d.dimension}: {d.detail}" for d in dims if d.verdict == "FAIL"]
    review.limitations = [f"{d.dimension}: {d.detail}" for d in dims if d.verdict == "NOT_SUPPORTED"]
    return review


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "erratum_id": ERRATUM_ID,
                "supersedes": SUPERSEDES,
                "sha256": rb.sha256_file(Path(__file__)),
            },
            indent=2,
        )
    )
