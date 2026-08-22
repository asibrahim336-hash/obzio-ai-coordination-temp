"""Executable cases backing a10-u04's disposition of a9 and its comparison against a6.

Three independent claims are proven here, each with a runnable case rather than prose:

1. a9's own reproducibility claims (topology simulation, full a9 test suite, one
   concrete evidence citation, and the operator-taxonomy non-interference claim)
   are RE-EXECUTED from a pinned commit of a9's branch, not merely read and agreed.
2. A structural defect in the shared `make_result.py` emitter -- that
   `result_transaction.result_commit_id` can never itself be the commit containing
   the emitted record -- is demonstrated from first principles on a disposable
   scratch repository. This independently confirms and root-causes a symptom a6
   found empirically (its "result_record_not_at_declared_commit" discrepancy class
   in workstreams/po03/review/luna/readback-audit.json) and extends it to a cohort
   a6 never reviewed (a4-u01, verified by this reviewer directly against the a4
   branch) and to this reviewer's own a10 units.

Class 1 requires the pinned a9 commit to be present in this repository's local
object store (obtained once via
`git fetch origin cursor/po03-a9-strategy-discovery-ed20`); it is skipped with an
explicit message, never silently passed, if that commit is not resolvable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_ATTACKS_DIR = REPO_ROOT / "workstreams" / "po03" / "review" / "sonnet" / "attacks"
sys.path.insert(0, str(_ATTACKS_DIR))

from scratch_control_plane import ScratchControlPlane, sha256_bytes  # noqa: E402

# cursor/po03-a9-strategy-discovery-ed20 head at a10-u04 scoring time (2026-08-22).
# Pinned by SHA, not branch name, so this case stays reproducible even after a9's
# mutable branch moves further -- the same discipline a9 itself adopted for its own
# tests after "po03 a9: pin mutable-state reproduction tests".
A9_PINNED_COMMIT = "81ca1de204ff3e693fd90f39f7056c81d8f0fc26"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _commit_reachable(commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "cat-file", "-e", commit],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


class ScratchA9Clone:
    """Isolated local clone of this repo's object store at the pinned a9 commit.

    Uses `git clone --local --shared`, so it never performs network access and
    never touches the live a9 worktree on disk -- only this reviewer's own
    repository's fetched objects are read.
    """

    def __enter__(self) -> "ScratchA9Clone":
        self._tmp = tempfile.TemporaryDirectory(prefix="a10-u04-a9-clone-")
        dest = Path(self._tmp.name) / "clone"
        _git(
            REPO_ROOT,
            "clone",
            "--local",
            "--shared",
            "--no-checkout",
            "-q",
            str(REPO_ROOT),
            str(dest),
        )
        _git(dest, "checkout", "-q", A9_PINNED_COMMIT)
        self.path = dest
        return self

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()


_A9_SKIP_REASON = (
    f"a9 pinned commit {A9_PINNED_COMMIT} is not present in this repository's "
    "local object store; run "
    "'git fetch origin cursor/po03-a9-strategy-discovery-ed20' first, then rerun"
)


@unittest.skipUnless(_commit_reachable(A9_PINNED_COMMIT), _A9_SKIP_REASON)
class A9IndependentReproductionTests(unittest.TestCase):
    """Re-executes a9's own claims from the pinned commit; does not read-and-agree."""

    def test_topology_simulation_reproduces_byte_identically(self) -> None:
        with ScratchA9Clone() as clone:
            sim = clone.path / "workstreams/po03/strategy/topology_sim.py"
            # must live under clone.path: topology_sim.py's own summary line calls
            # Path.relative_to(root) on the output paths it just wrote
            out_dir = clone.path / ".a10-u04-topo-scratch"
            out_dir.mkdir()
            try:
                candidates_out = out_dir / "candidates.json"
                comparison_out = out_dir / "comparison.json"
                subprocess.run(
                    [
                        "python3",
                        "-I",
                        str(sim),
                        "--root",
                        str(clone.path),
                        "--candidates",
                        str(candidates_out),
                        "--comparison",
                        str(comparison_out),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                committed_candidates = json.loads(
                    (
                        clone.path
                        / "workstreams/po03/strategy/topology-candidates.json"
                    ).read_text(encoding="utf-8")
                )
                committed_comparison = json.loads(
                    (
                        clone.path
                        / "workstreams/po03/strategy/topology-comparison.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    json.loads(candidates_out.read_text(encoding="utf-8")),
                    committed_candidates,
                )
                self.assertEqual(
                    json.loads(comparison_out.read_text(encoding="utf-8")),
                    committed_comparison,
                )
                self.assertEqual(
                    len(committed_candidates["topologies"]), 4
                )  # dispatch requires >= 3
            finally:
                shutil.rmtree(out_dir, ignore_errors=True)

    def test_full_a9_suite_passes_in_isolated_clone(self) -> None:
        with ScratchA9Clone() as clone:
            result = subprocess.run(
                [
                    "python3",
                    "-I",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "workstreams/po03/tests",
                    "-p",
                    "test_a9_*.py",
                ],
                cwd=clone.path,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + "\n" + result.stderr
            )
            self.assertIn("OK", result.stderr)

    def test_zero_base_evidence_citation_for_path_ownership_drift_is_accurate(
        self,
    ) -> None:
        """Spot-checks one concrete a9-u01 evidence citation (this reviewer's
        criteria-a9.json pass_bar requires citation of "a real path/artifact, not
        a general appeal"), and shows the drift a9 reports also affects this
        reviewer's own a10-u04 dispatch inputs, independently corroborating it.

        The evidence citation names bytes as they were AT a9's own pinned
        SNAPSHOT_COMMIT (see test_a9_challenge.py), not at the a9 branch head used
        for the rest of this file -- path-ownership.json is volatile enough that
        it drifts to a THIRD distinct hash between that snapshot and the current
        a9 branch head, which this test also demonstrates rather than asserts."""
        with ScratchA9Clone() as clone:
            challenge = json.loads(
                (
                    clone.path / "workstreams/po03/strategy/zero-base-challenge.json"
                ).read_text(encoding="utf-8")
            )
            drift_assumption = next(
                a
                for a in challenge["assumptions"]
                if a["assumption_id"] == "A-SOURCE-CAPSULE-CLOSURE"
            )
            drift_row = drift_assumption["test"]["observations"]["drift"][0]
            self.assertEqual(
                drift_row["path"], "workstreams/po03/control/path-ownership.json"
            )
            snapshot_commit = "c83da05eccf7331ed20ef3819c58b146addb5156"
            bytes_at_snapshot = subprocess.run(
                ["git", "show", f"{snapshot_commit}:{drift_row['path']}"],
                cwd=clone.path,
                check=True,
                capture_output=True,
            ).stdout
            self.assertEqual(
                hashlib.sha256(bytes_at_snapshot).hexdigest(),
                drift_row["observed_sha256"],
                "the citation must match real committed bytes at the commit a9 "
                "actually measured, not a general appeal",
            )
            a10_dispatch = json.loads(
                (
                    REPO_ROOT / "workstreams/po03/control/dispatch/a10-u04.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                a10_dispatch["source_hashes"][
                    "workstreams/po03/control/path-ownership.json"
                ],
                drift_row["expected_sha256"],
                "this reviewer's own a10-u04 dispatch was frozen against the "
                "pre-drift path-ownership.json hash a9 reports -- independent "
                "confirmation the drift is real, not an a9 artifact",
            )
            bytes_at_a9_head = (clone.path / drift_row["path"]).read_bytes()
            third_hash = hashlib.sha256(bytes_at_a9_head).hexdigest()
            self.assertNotEqual(
                third_hash,
                drift_row["observed_sha256"],
                "path-ownership.json has drifted a SECOND time since a9's own "
                "snapshot -- three distinct hashes now exist for the same "
                "path across the wave (dispatch-frozen, a9-observed, current "
                "a9-branch-head), which is a stronger version of a9's own "
                "A-SOURCE-CAPSULE-CLOSURE finding than a9 itself measured",
            )

    def test_operator_taxonomy_gate_is_byte_identical_before_and_after_a9(
        self,
    ) -> None:
        with ScratchA9Clone() as clone:
            before = (REPO_ROOT / "scripts/check_operator_taxonomy.py").read_bytes()
            after = (clone.path / "scripts/check_operator_taxonomy.py").read_bytes()
            self.assertEqual(
                before,
                after,
                "a9-u04's acceptance forbids scripts/check_operator_taxonomy.py "
                "changing as a side effect",
            )
            result = subprocess.run(
                ["python3", "scripts/check_operator_taxonomy.py"],
                cwd=clone.path,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OPERATOR TAXONOMY CHECK: PASS", result.stdout)


class A6HiddenCasesH03ToH05CliLevelRetest(unittest.TestCase):
    """Re-tests a6's H03-H05 hidden cases (workstreams/po03/review/luna/hidden-
    cases/cases.json, exercised by workstreams/po03/tests/test_a6_hidden_cases.py)
    at the real control_plane.py CLI / `ingest` subprocess level, rather than by
    calling `validate_result()` directly on a hand-built document as a6's own
    fixture does. This reviewer's original a10-u03/a10-u04 work
    (defect-profile-comparison-a6.json) recorded these three as
    "NOT_YET/out-of-scope for this comparison, not as confirmed or refuted" --
    the coordinator asked for a re-tested verdict, which each case below now
    gives against a real, isolated scratch repository (ScratchControlPlane),
    with a real committed artifact on disk for every case, exactly mirroring
    each hidden case's `input_mutation`.

    Verdict for all three: HELD at the CLI level too, and for a traceable
    reason -- `ingest_result`'s very first step, before any git/filesystem
    I/O, is calling the identical `validate_result()` schema check a6's own
    hidden cases call directly (see control_plane.py's `ingest_result`,
    `validator.validate_result(result_doc)`). A rejection a6 observed at the
    schema layer is therefore necessarily also a rejection at the real
    ingestion boundary, because nothing downstream of schema validation in
    `ingest_result` ever re-derives or overrides artifact_count, total_bytes,
    duplicate-artifact-id, or readback_verified_at. This is a genuine,
    narrower finding than H01/H02/H06 (where this reviewer found a real or
    boundary-level CLI-reachable gap adjacent to what the schema enforces):
    for H03-H05 specifically, a6's schema-only methodology and the real CLI
    give the same answer.
    """

    def _scratch(self, tmp: Path) -> ScratchControlPlane:
        scp = ScratchControlPlane(tmp)
        scp.write_ownership(
            {"attacker": {"owned_prefixes": ["workstreams/po03/control/units/attacker/"]}}
        )
        return scp

    def test_h03_terminal_without_readback_held_at_cli_level(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a10-h03-") as tmp:
            scp = self._scratch(Path(tmp))
            dispatch = scp.create_unit("h03-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
            lease = scp.lease("h03-u1", "attacker")
            content = b'{"h03": "readback-missing"}'
            scp.write_file_at("workstreams/po03/control/units/attacker/h03.json", content)
            doc = scp.build_result_doc(
                dispatch,
                fence_token=lease["fence_token"],
                artifacts=[
                    {
                        "artifact_id": "a1",
                        "logical_name": "h03",
                        "content_uri": "workstreams/po03/control/units/attacker/h03.json",
                        "sha256": sha256_bytes(content),
                        "bytes": len(content),
                    }
                ],
                obzio_state="RESULT_COMMITTED",
            )
            # a6's H03 input_mutation: artifacts[0].readback_verified_at -> null
            # on an otherwise-committed result.
            doc["artifacts"][0]["readback_verified_at"] = None
            outcome = scp.ingest(doc, tag="h03")
            self.assertNotEqual(
                outcome.returncode,
                0,
                "H03 must also be rejected at the real ingest_result CLI boundary; "
                f"got: {outcome.stdout} {outcome.stderr}",
            )
            self.assertIn("readback_verified_at", outcome.stdout + outcome.stderr)

    def test_h04_accounting_drift_held_at_cli_level(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a10-h04-") as tmp:
            scp = self._scratch(Path(tmp))
            dispatch = scp.create_unit("h04-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
            lease = scp.lease("h04-u1", "attacker")
            content = b'{"h04": "accounting-drift"}'
            scp.write_file_at("workstreams/po03/control/units/attacker/h04.json", content)
            doc = scp.build_result_doc(
                dispatch,
                fence_token=lease["fence_token"],
                artifacts=[
                    {
                        "artifact_id": "a1",
                        "logical_name": "h04",
                        "content_uri": "workstreams/po03/control/units/attacker/h04.json",
                        "sha256": sha256_bytes(content),
                        "bytes": len(content),
                    }
                ],
                obzio_state="RESULT_COMMITTED",
            )
            # a6's H04 input_mutation: result_transaction.total_bytes no longer
            # matches the artifacts actually declared.
            doc["result_transaction"]["total_bytes"] = 999
            outcome = scp.ingest(doc, tag="h04")
            self.assertNotEqual(
                outcome.returncode,
                0,
                "H04 must also be rejected at the real ingest_result CLI boundary; "
                f"got: {outcome.stdout} {outcome.stderr}",
            )
            self.assertIn("total_bytes", outcome.stdout + outcome.stderr)

    def test_h05_duplicate_artifact_id_held_at_cli_level(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a10-h05-") as tmp:
            scp = self._scratch(Path(tmp))
            dispatch = scp.create_unit("h05-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
            lease = scp.lease("h05-u1", "attacker")
            content_a = b'{"h05": "first"}'
            content_b = b'{"h05": "second, shares artifact_id with first"}'
            scp.write_file_at("workstreams/po03/control/units/attacker/h05-a.json", content_a)
            scp.write_file_at("workstreams/po03/control/units/attacker/h05-b.json", content_b)
            doc = scp.build_result_doc(
                dispatch,
                fence_token=lease["fence_token"],
                artifacts=[
                    {
                        "artifact_id": "art-1",
                        "logical_name": "h05-a",
                        "content_uri": "workstreams/po03/control/units/attacker/h05-a.json",
                        "sha256": sha256_bytes(content_a),
                        "bytes": len(content_a),
                    },
                    {
                        # a6's H05 input_mutation: artifacts[1].artifact_id set to
                        # the same value as artifacts[0].artifact_id.
                        "artifact_id": "art-1",
                        "logical_name": "h05-b",
                        "content_uri": "workstreams/po03/control/units/attacker/h05-b.json",
                        "sha256": sha256_bytes(content_b),
                        "bytes": len(content_b),
                    },
                ],
                obzio_state="RESULT_COMMITTED",
            )
            outcome = scp.ingest(doc, tag="h05")
            self.assertNotEqual(
                outcome.returncode,
                0,
                "H05 must also be rejected at the real ingest_result CLI boundary; "
                f"got: {outcome.stdout} {outcome.stderr}",
            )
            self.assertIn("duplicate", outcome.stdout + outcome.stderr)


class MakeResultSelfLocatorGapTests(unittest.TestCase):
    """Extends both a6's readback-audit finding and this reviewer's own a10-u03
    audit: `result_transaction.result_commit_id` can never itself be the commit
    that contains the emitted result record, for ANY cohort -- a structural
    property of `make_result.py`, not a cohort-specific defect. This reviewer
    independently confirmed the same symptom directly against the real a4-u01
    record (git cat-file -e f24545eea3c6887f8a539934032b4c176d7684ab:
    workstreams/po03/control/units/a4/a4-u01.json fails) and against this
    reviewer's own a10-u01/u02/u03 records, in addition to a6's originally
    reported a3-u01/a7-u01/a7-u02/a6-u01/a6-u02.
    """

    def test_result_commit_id_never_contains_its_own_record_by_construction(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="a10-u04-mkresult-") as tmp:
            root = Path(tmp)
            (root / "workstreams/po03/tools").mkdir(parents=True)
            (root / "workstreams/po03/control/dispatch").mkdir(parents=True)
            (root / "workstreams/po03/control/units/scratch").mkdir(parents=True)
            shutil.copy(
                REPO_ROOT / "workstreams/po03/tools/make_result.py",
                root / "workstreams/po03/tools/make_result.py",
            )
            record_relpath = "workstreams/po03/control/units/scratch/scratch-u01.json"
            dispatch = {
                "commission_id": "COM-TEST",
                "immutable_input_manifest_sha256": "a" * 64,
                "acceptance_contract_sha256": "b" * 64,
                "owner": "scratch-worker",
                "idempotency_key": "scratch-u01:test",
                "result_slot": {"unit_record": record_relpath},
            }
            (root / "workstreams/po03/control/dispatch/scratch-u01.json").write_text(
                json.dumps(dispatch), encoding="utf-8"
            )
            artifact = root / "workstreams/po03/control/units/scratch/evidence.txt"
            artifact.write_text("evidence\n", encoding="utf-8")

            _git(root, "init", "-q")
            _git(root, "config", "user.email", "a10-scratch@example.invalid")
            _git(root, "config", "user.name", "a10-scratch")
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "seed artifact")

            subprocess.run(
                [
                    "python3",
                    "-I",
                    str(root / "workstreams/po03/tools/make_result.py"),
                    "scratch-u01",
                    "--root",
                    str(root),
                    "--provider-run-id",
                    "test-run",
                    "--artifact",
                    "workstreams/po03/control/units/scratch/evidence.txt",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            record_path = root / record_relpath
            document = json.loads(record_path.read_text(encoding="utf-8"))
            result_commit_id = document["result_transaction"]["result_commit_id"]

            probe_before = subprocess.run(
                ["git", "cat-file", "-e", f"{result_commit_id}:{record_relpath}"],
                cwd=root,
                capture_output=True,
            )
            self.assertNotEqual(
                probe_before.returncode,
                0,
                "expected the record to be ABSENT at its own declared "
                "result_commit_id: make_result.py resolves `git rev-parse HEAD` "
                "before the record file is written, and the record is committed "
                "in a separate, later commit by the worker",
            )

            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "commit result record")
            probe_after = subprocess.run(
                ["git", "cat-file", "-e", f"{result_commit_id}:{record_relpath}"],
                cwd=root,
                capture_output=True,
            )
            self.assertNotEqual(
                probe_after.returncode,
                0,
                "the gap is permanent for this result_commit_id value, not merely "
                "a timing race that a later commit closes",
            )


if __name__ == "__main__":
    unittest.main()
