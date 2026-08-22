"""Hidden adversarial case generator for the route-07 frozen review rubric.

Each generator synthesises a complete producer result slot in a caller-supplied
temporary directory and pre-registers the verdict the frozen rubric must return.
The cases are compiled from frozen criteria only and are hashed together with
rubric_v1.py before any producer conclusion is read, so a producer cannot tune a
slot to them and the rubric cannot be relaxed after the fact.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

GENERATOR_ID = "PO03-WA-ROUTE07-HIDDEN-CASES-v1"

OWNED_PREFIX = "slots"
TASK_ID = "HIDDEN-TASK-001"
HYPOTHESIS = "A stale fence token cannot stage or commit a result."
ACCEPTANCE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64

COMPONENT = '''"""Synthetic custody component used only by hidden review cases."""

LEGAL = {
    "CREATED": {"LEASED"},
    "LEASED": {"RUNNING"},
    "RUNNING": {"RESULT_STAGED"},
    "RESULT_STAGED": {"RESULT_COMMITTED"},
    "RESULT_COMMITTED": set(),
}


class FenceError(RuntimeError):
    pass


class Custody:
    def __init__(self, fence):
        self.state = "CREATED"
        self.fence = fence

    def advance(self, target, fence):
        if fence < self.fence:
            raise FenceError(f"stale fence {fence} < {self.fence}")
        if target not in LEGAL[self.state]:
            raise ValueError(f"illegal transition {self.state} -> {target}")
        self.fence = fence
        self.state = target
        return self.state
'''

TESTS = '''import unittest

from component import Custody, FenceError


class StaleFenceTests(unittest.TestCase):
    def test_legal_sequence_commits(self):
        c = Custody(2)
        self.assertEqual(c.advance("LEASED", 2), "LEASED")
        self.assertEqual(c.advance("RUNNING", 2), "RUNNING")
        self.assertEqual(c.advance("RESULT_STAGED", 2), "RESULT_STAGED")
        self.assertEqual(c.advance("RESULT_COMMITTED", 2), "RESULT_COMMITTED")

    def test_stale_fence_cannot_stage(self):
        c = Custody(5)
        c.advance("LEASED", 5)
        c.advance("RUNNING", 5)
        with self.assertRaises(FenceError):
            c.advance("RESULT_STAGED", 4)

    def test_stale_fence_cannot_commit(self):
        c = Custody(5)
        for target in ("LEASED", "RUNNING", "RESULT_STAGED"):
            c.advance(target, 5)
        with self.assertRaises(FenceError):
            c.advance("RESULT_COMMITTED", 1)

    def test_skipped_state_is_rejected(self):
        c = Custody(1)
        with self.assertRaises(ValueError):
            c.advance("RESULT_COMMITTED", 1)


if __name__ == "__main__":
    unittest.main()
'''

OBSERVED = """$ python3 -m unittest discover -s . -p 'test_*.py' -v
test_legal_sequence_commits ... ok
test_skipped_state_is_rejected ... ok
test_stale_fence_cannot_commit ... ok
test_stale_fence_cannot_stage ... ok

Ran 4 tests in 0.001s

OK
"""

FINDING = """# Hidden fixture finding

Limitations: synthetic in-memory model only; no durable git sink is exercised.
Disposition: PASS
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(slot: Path, skip=None, corrupt_hash=None, corrupt_bytes=None):
    entries = []
    for path in sorted(slot.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(slot).as_posix()
        if skip and rel == skip:
            continue
        entry = {"path": rel, "sha256": _sha(path), "bytes": path.stat().st_size}
        if corrupt_hash and rel == corrupt_hash:
            entry["sha256"] = "0" * 64
        if corrupt_bytes and rel == corrupt_bytes:
            entry["bytes"] = entry["bytes"] + 1
        entries.append(entry)
    doc = {
        "task_id": TASK_ID,
        "acceptance_contract_sha256": ACCEPTANCE_SHA,
        "immutable_input_manifest_sha256": MANIFEST_SHA,
        "artifacts": entries,
        "artifact_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
    }
    (slot / "manifest.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def _base_slot(root: Path, name: str) -> Path:
    slot = root / OWNED_PREFIX / name
    slot.mkdir(parents=True, exist_ok=True)
    (slot / "component.py").write_text(COMPONENT)
    (slot / "test_component.py").write_text(TESTS)
    (slot / "evidence").mkdir(exist_ok=True)
    (slot / "evidence" / "observed-output.txt").write_text(OBSERVED)
    (slot / "FINDING.md").write_text(FINDING)
    (slot / "result.json").write_text(
        json.dumps(
            {
                "task_id": TASK_ID,
                "acceptance_contract_sha256": ACCEPTANCE_SHA,
                "immutable_input_manifest_sha256": MANIFEST_SHA,
                "disposition": "PASS",
                "obzio_state": "RESULT_STAGED",
                "subordinate_terminal_state": "READY_TO_COMMIT",
                "completion_actor": "producer-worker",
                "limitations": ["synthetic fixture"],
                "independent_acceptance": {
                    "state": "NOT_TESTED",
                    "reviewer_id": None,
                    "receipt_uri": None,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return slot


# --------------------------------------------------------------------------- #
# Case builders: each returns (slot_name, expected_recommendation, expected_fail_dims)
# --------------------------------------------------------------------------- #


def case_golden(root: Path):
    slot = _base_slot(root, "golden")
    _write_manifest(slot)
    return "golden", "RECOMMEND_ACCEPT", set()


def case_prose_only(root: Path):
    slot = root / OWNED_PREFIX / "prose_only"
    (slot / "evidence").mkdir(parents=True, exist_ok=True)
    (slot / "FINDING.md").write_text(FINDING)
    (slot / "evidence" / "observed-output.txt").write_text(OBSERVED)
    (slot / "result.json").write_text(
        json.dumps(
            {
                "task_id": TASK_ID,
                "acceptance_contract_sha256": ACCEPTANCE_SHA,
                "disposition": "PASS",
                "limitations": ["prose only"],
            },
            indent=2,
        )
        + "\n"
    )
    _write_manifest(slot)
    return "prose_only", "RECOMMEND_REJECT", {"R1_EXECUTABLE_UNIT", "R2_TESTS_RERUN"}


def case_manifest_omits_artifact(root: Path):
    slot = _base_slot(root, "manifest_omission")
    _write_manifest(slot, skip="component.py")
    return "manifest_omission", "RECOMMEND_REJECT", {"R4_MANIFEST_COMPLETE"}


def case_manifest_hash_corrupt(root: Path):
    slot = _base_slot(root, "manifest_hash_corrupt")
    _write_manifest(slot, corrupt_hash="component.py")
    return "manifest_hash_corrupt", "RECOMMEND_REJECT", {"R4_MANIFEST_COMPLETE"}


def case_manifest_bytes_corrupt(root: Path):
    slot = _base_slot(root, "manifest_bytes_corrupt")
    _write_manifest(slot, corrupt_bytes="test_component.py")
    return "manifest_bytes_corrupt", "RECOMMEND_REJECT", {"R4_MANIFEST_COMPLETE"}


def case_failing_test(root: Path):
    slot = _base_slot(root, "failing_test")
    (slot / "component.py").write_text(COMPONENT.replace("if fence < self.fence:", "if False:"))
    _write_manifest(slot)
    return "failing_test", "RECOMMEND_REJECT", {"R2_TESTS_RERUN"}


def case_illegal_disposition(root: Path):
    slot = _base_slot(root, "illegal_disposition")
    doc = json.loads((slot / "result.json").read_text())
    doc["disposition"] = "ACCEPTED"
    (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    _write_manifest(slot)
    return "illegal_disposition", "RECOMMEND_REJECT", {"R5_DISPOSITION_LEGAL"}


def case_self_acceptance(root: Path):
    slot = _base_slot(root, "self_acceptance")
    doc = json.loads((slot / "result.json").read_text())
    doc["independent_acceptance"] = {
        "state": "ACCEPTED",
        "reviewer_id": "producer-worker",
        "receipt_uri": "self.json",
    }
    (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    _write_manifest(slot)
    return "self_acceptance", "RECOMMEND_REJECT", {"R8_NO_SELF_ACCEPTANCE"}


def case_terminal_overreach(root: Path):
    slot = _base_slot(root, "terminal_overreach")
    doc = json.loads((slot / "result.json").read_text())
    doc["subordinate_terminal_state"] = "COMPLETED"
    (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    _write_manifest(slot)
    return "terminal_overreach", "RECOMMEND_REJECT", {"R8_NO_SELF_ACCEPTANCE"}


def case_wrong_contract_hash(root: Path):
    slot = _base_slot(root, "wrong_contract_hash")
    doc = json.loads((slot / "result.json").read_text())
    doc["acceptance_contract_sha256"] = "c" * 64
    (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    _write_manifest(slot)
    return "wrong_contract_hash", "RECOMMEND_REJECT", {"R9_CONTRACT_ECHO"}


def case_escaping_symlink(root: Path):
    slot = _base_slot(root, "escaping_symlink")
    outside = root / "outside.txt"
    outside.write_text("out of subtree payload\n")
    link = slot / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return None
    _write_manifest(slot)
    return "escaping_symlink", "RECOMMEND_REJECT", {"R7_PATH_CONFINEMENT"}


def case_missing_limitations(root: Path):
    slot = _base_slot(root, "missing_limitations")
    doc = json.loads((slot / "result.json").read_text())
    doc["limitations"] = []
    (slot / "result.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    (slot / "FINDING.md").write_text("# Hidden fixture finding\n\nDisposition: PASS\n")
    _write_manifest(slot)
    return "missing_limitations", "RETEST", {"R6_LIMITATIONS_PRESENT"}


def case_thin_tests(root: Path):
    slot = _base_slot(root, "thin_tests")
    (slot / "test_component.py").write_text(
        "import unittest\n\nfrom component import Custody\n\n\n"
        "class Thin(unittest.TestCase):\n"
        "    def test_smoke(self):\n"
        "        self.assertEqual(Custody(1).state, 'CREATED')\n\n\n"
        "if __name__ == '__main__':\n    unittest.main()\n"
    )
    _write_manifest(slot)
    return "thin_tests", "RETEST", {"R10_HYPOTHESIS_EXERCISED"}


def case_no_observed_output(root: Path):
    slot = _base_slot(root, "no_observed_output")
    (slot / "evidence" / "observed-output.txt").unlink()
    (slot / "evidence").rmdir()
    _write_manifest(slot)
    return "no_observed_output", "RETEST", {"R3_COMMANDS_AND_OBSERVED"}


def case_duplicate_of_golden(root: Path):
    slot = _base_slot(root, "duplicate_unit")
    _write_manifest(slot)
    return "duplicate_unit", "RETEST", {"R11_NOT_DUPLICATED"}


def case_unmanifested_extra(root: Path):
    slot = _base_slot(root, "unmanifested_extra")
    _write_manifest(slot)
    (slot / "sneaky.py").write_text("VALUE = 1\n")
    return "unmanifested_extra", "RECOMMEND_REJECT", {"R4_MANIFEST_COMPLETE"}


ALL_CASES = (
    case_golden,
    case_prose_only,
    case_manifest_omits_artifact,
    case_manifest_hash_corrupt,
    case_manifest_bytes_corrupt,
    case_failing_test,
    case_illegal_disposition,
    case_self_acceptance,
    case_terminal_overreach,
    case_wrong_contract_hash,
    case_escaping_symlink,
    case_missing_limitations,
    case_thin_tests,
    case_no_observed_output,
    case_duplicate_of_golden,
    case_unmanifested_extra,
)


def build_all(root: Path) -> list:
    """Materialise every hidden case; return the pre-registered expectations."""
    expectations = []
    for builder in ALL_CASES:
        out = builder(root)
        if out is None:
            continue
        name, recommendation, fail_dims = out
        expectations.append(
            {
                "case": name,
                "slot": f"{OWNED_PREFIX}/{name}",
                "expected_recommendation": recommendation,
                "expected_failed_dimensions": sorted(fail_dims),
            }
        )
    return expectations


def generator_self_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


if __name__ == "__main__":
    print(json.dumps({"generator_id": GENERATOR_ID, "sha256": generator_self_hash()}, indent=2))
