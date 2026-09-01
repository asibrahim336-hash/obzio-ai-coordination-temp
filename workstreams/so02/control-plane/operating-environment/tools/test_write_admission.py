"""End-to-end failure injections for the composed write guard.

The delivery contract names six injections. All six are exercised here against
the composed guard, in addition to the unit-level coverage in the per-gate
suites:

1. an undeclared write
2. a write with an empty or vacuous reason
3. a write with no reversal
4. a reversal that does not actually reverse
5. a write to a branch with a live run
6. a result-asserting write with no evidence

Each must be refused. None is refused because of the name of its target.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_lane_d_fix(name: str):
    """SCP-SI-01 lane D's proposed mechanism, loaded from its own namespace.

    Not merged into `write_admission.py` by this lane (out of write scope);
    see `scp-si-01/lane-d/patches/write_admission.py.patch` for the proposed
    one-call fix this test demonstrates is both necessary and sufficient.
    """
    lane_d = (
        Path(__file__).resolve().parents[1]
        / "scp-si-01" / "lane-d" / "fixes" / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(name, lane_d)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wa = _load("write_admission")
rr = _load("reversal_rehearsal")
ei_module = _load("evidence_integrity")


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# The gate now OPENS every declared file rather than asking the record about
# itself, so a fixture that names a path which does not exist is refused — and
# should be. These fixtures previously encoded the blind behaviour. The honest
# repair is to make the fixture write real bytes, not to relax the gate.
_FIXTURE_REPO_HANDLE = tempfile.TemporaryDirectory()
FIXTURE_REPO = Path(_FIXTURE_REPO_HANDLE.name)
_FIXTURE_REL = "receipts/so02/2026-08-23/oe-w9-reason-gated-writes/EXAMPLE.json"


def _manifest_evidence():
    """A real, recomputable manifest closure record backed by bytes on disk."""
    # A file named .json must contain JSON. The gate parses as well as hashes.
    payload = b'{"deliverable": "bytes"}'
    target = FIXTURE_REPO / _FIXTURE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    entries = [{
        "path": _FIXTURE_REL,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }]
    bundle = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "asserts_result": True,
        "kind": "MANIFEST_CLOSURE",
        "record": {"entries": entries, "bundle_sha256": bundle},
        "present_paths": [entries[0]["path"]],
    }


PRE_SHA = "a" * 40
POST_SHA = "b" * 40


def _ago(seconds: int) -> str:
    """Timestamps are taken relative to now.

    A fixture pinned to a wall-clock literal silently becomes an observation
    from the future once the clock passes it, and the guard correctly refuses
    that — which would make this suite fail for a reason unrelated to what it
    is testing.
    """
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


ADMISSIBLE = {
    "declaration_version": "1.0",
    "declaration_id": "WD-ADMISSION-TEST-0001",
    "declared_by": "OE-W9-REASON-GATED-WRITES",
    "declared_at": _ago(60),
    "target": {
        "ref": "main",
        "paths": ["workstreams/so02/control-plane/operating-environment/tools/**"],
        "operation": "COMMIT_AND_PUSH",
    },
    "reason": {
        "code": "CORRECT_PUBLISHED_ERROR",
        "statement": (
            "The published guard on main refuses writes by target name, a category the founder "
            "voided on 2026-08-23; correcting it on main is the correction."
        ),
        "defect_reference": "protected-surface category voided by standing amendment 2026-08-23",
        "defect_observed_at": "2026-08-23T03:34:00Z",
    },
    "reversal": {
        "method": "RESTORE_REF_TO_RECORDED_SHA",
        "recorded_sha": PRE_SHA,
        "post_write_sha": POST_SHA,
        "custody_ref": "refs/tags/pre-write/main-20260823T0400Z",
        "command": rr.build_reversal("RESTORE_REF_TO_RECORDED_SHA", "main",
                                     recorded_sha=PRE_SHA, post_write_sha=POST_SHA)["command"],
    },
    "evidence": _manifest_evidence(),
    "concurrency": {
        "observed_at": _ago(30),
        "agents": [
            {"bcId": "bc-idle", "branchName": "main", "status": "IDLE"},
            {"bcId": "bc-busy", "branchName": "cursor/somewhere-else", "status": "RUNNING"},
        ],
    },
}


def variant(**overrides):
    out = copy.deepcopy(ADMISSIBLE)
    for dotted, value in overrides.items():
        keys = dotted.split(".")
        node = out
        for key in keys[:-1]:
            node = node[key]
        if value is _DELETE:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return out


class _Delete:
    pass


_DELETE = _Delete()


def decide(declaration, **kwargs):
    kwargs.setdefault("check_ref_movement", False)
    kwargs.setdefault("rehearse_reversal", True)
    return wa.admit(declaration, FIXTURE_REPO, **kwargs)


@unittest.skipUnless(_git_available(), "git is required to re-execute the rollback")
class AdmissibleWriteTests(unittest.TestCase):
    def test_a_fully_declared_write_to_main_is_admitted(self) -> None:
        """'Write to main.' — the founder, 2026-08-23."""
        report = decide(ADMISSIBLE)
        self.assertTrue(report["admitted"], wa.summarise(report))
        self.assertEqual(wa.ADMITTED, report["verdict"])
        self.assertEqual([], report["failed_gates"])

    def test_all_four_gates_actually_ran(self) -> None:
        report = decide(ADMISSIBLE)
        self.assertEqual(
            [wa.GATE_DECLARATION, wa.GATE_CONCURRENCY, wa.GATE_REVERSIBILITY, wa.GATE_EVIDENCE],
            [g["gate"] for g in report["gates"]],
        )
        self.assertTrue(all(g["passed"] for g in report["gates"]))

    def test_the_verdict_cites_founder_authority_and_no_target_list(self) -> None:
        report = decide(ADMISSIBLE)
        self.assertIn("you need a reason and a rollback", report["authority_basis"])
        self.assertIn("protected-surface category is void", report["authority_basis"])

    def test_the_target_name_is_never_what_decides(self) -> None:
        for ref in ("main", "cursor/po03-wave-a-factory-6e19", "so02/strategic-control-plane-migration-20260822-v001",
                    "cursor/operating-environment-return-20260822-v001", "scratch"):
            declaration = copy.deepcopy(ADMISSIBLE)
            declaration["target"]["ref"] = ref
            declaration["reason"]["statement"] = (
                f"The published guard on {ref} refuses writes by target name, a category the founder "
                "voided on 2026-08-23; correcting it there is the correction."
            )
            declaration["reversal"]["command"] = rr.build_reversal(
                "RESTORE_REF_TO_RECORDED_SHA", ref, recorded_sha=PRE_SHA, post_write_sha=POST_SHA)["command"]
            declaration["concurrency"]["agents"] = [{"bcId": "bc-idle", "branchName": ref, "status": "IDLE"}]
            report = decide(declaration)
            self.assertTrue(report["admitted"], f"{ref}: {wa.summarise(report)}")

    def test_the_guard_holds_no_list_of_forbidden_targets(self) -> None:
        source = (Path(__file__).resolve().parent / "write_admission.py").read_text(encoding="utf-8")
        for forbidden in ("PROTECTED_REFS", "PROTECTED_PREFIXES", "protected_branch_globs",
                          "guard_ref_is_protected", "PROTECTED_REF_DRIFT_FAIL"):
            self.assertNotIn(forbidden, source)


@unittest.skipUnless(_git_available(), "git is required to re-execute the rollback")
class TheSixInjectionsTests(unittest.TestCase):
    """The delivery contract, one test per named injection."""

    def _refused_on(self, declaration, gate, **kwargs):
        report = decide(declaration, **kwargs)
        self.assertFalse(report["admitted"], wa.summarise(report))
        self.assertEqual(wa.REFUSED, report["verdict"])
        self.assertIn(gate, report["failed_gates"], wa.summarise(report))
        return report

    def test_injection_1_an_undeclared_write_is_refused(self) -> None:
        for undeclared in ({}, None, "", []):
            report = self._refused_on(undeclared, wa.GATE_DECLARATION)
            self.assertTrue(any("NO_DECLARATION" in f for f in report["gates"][0]["findings"]))

    def test_injection_2_a_vacuous_reason_is_refused(self) -> None:
        self._refused_on(variant(**{"reason.statement": ""}), wa.GATE_DECLARATION)
        self._refused_on(variant(**{"reason.statement": "   "}), wa.GATE_DECLARATION)
        self._refused_on(
            variant(**{"reason.statement": "Making the necessary changes as instructed."}),
            wa.GATE_DECLARATION,
        )
        self._refused_on(variant(**{"reason.code": "JUST_BECAUSE"}), wa.GATE_DECLARATION)
        self._refused_on(variant(**{"reason.defect_reference": _DELETE}), wa.GATE_DECLARATION)

    def test_injection_3_a_write_with_no_reversal_is_refused(self) -> None:
        self._refused_on(variant(reversal=_DELETE), wa.GATE_DECLARATION)
        self._refused_on(variant(**{"reversal.command": _DELETE}), wa.GATE_DECLARATION)
        self._refused_on(variant(**{"reversal.custody_ref": _DELETE}), wa.GATE_DECLARATION)

    def test_injection_4_a_reversal_that_does_not_reverse_is_refused(self) -> None:
        """The declaration's own 'rehearsed: true' is ignored; the rollback is re-run."""
        lying = variant(**{
            "reversal.command": ["git", "push", "origin", "main"],
            "reversal.rehearsed": True,
            "reversal.rehearsal_receipt": {"result": "REVERSAL_EXECUTED_AND_VERIFIED"},
        })
        report = self._refused_on(lying, wa.GATE_REVERSIBILITY)
        self.assertTrue(any("never the command that was rehearsed" in f
                            for f in report["gates"][2]["findings"]))

    def test_injection_4b_a_method_that_cannot_be_rehearsed_is_refused(self) -> None:
        unrehearsable = variant(**{
            "reversal.method": "RESTORE_FROM_ARCHIVE",
            "reversal.archive_path": "/tmp/custody.bundle",
            "reversal.archive_sha256": "c" * 64,
        })
        unrehearsable["reversal"]["command"] = rr.build_reversal(
            "RESTORE_FROM_ARCHIVE", "main", recorded_sha=PRE_SHA, archive_path="/tmp/custody.bundle")["command"]
        report = self._refused_on(unrehearsable, wa.GATE_REVERSIBILITY)
        self.assertTrue(any("described rather than demonstrated" in f
                            for f in report["gates"][2]["findings"]))

    def test_injection_5_a_write_to_a_branch_with_a_live_run_is_refused(self) -> None:
        live = variant(**{"concurrency.agents": [
            {"bcId": "bc-live", "branchName": "main", "status": "RUNNING", "name": "another lane"},
        ]})
        report = self._refused_on(live, wa.GATE_CONCURRENCY)
        gate = report["gates"][1]
        self.assertEqual("IN_FLIGHT_LIVE_AGENT_HOLDS_TARGET", gate["verdict"])
        self.assertIn("waits for that lane to finish", gate["gate_expires_when"])

    def test_injection_5b_the_same_write_is_admitted_once_that_run_settles(self) -> None:
        """'When it completes, the gate is gone.' The gate expires; it is not permanent."""
        live = variant(**{"concurrency.agents": [
            {"bcId": "bc-live", "branchName": "main", "status": "RUNNING"}]})
        settled = variant(**{"concurrency.agents": [
            {"bcId": "bc-live", "branchName": "main", "status": "IDLE"}]})
        self.assertFalse(decide(live)["admitted"])
        self.assertTrue(decide(settled)["admitted"])

    def test_injection_6_a_result_asserting_write_with_no_evidence_is_refused(self) -> None:
        self._refused_on(variant(evidence=_DELETE), wa.GATE_DECLARATION)

    def test_injection_6b_evidence_that_fails_recomputation_is_refused(self) -> None:
        """A record that is internally consistent is not thereby true."""
        forged = variant()
        forged["evidence"]["record"]["bundle_sha256"] = "0" * 64
        report = self._refused_on(forged, wa.GATE_EVIDENCE)
        self.assertEqual("EVIDENCE_FAILED_RECOMPUTATION", report["gates"][3]["verdict"])
        self.assertTrue(any("bundle_sha256 does not bind" in f for f in report["gates"][3]["findings"]))

    def test_injection_6c_an_uncovered_file_breaks_manifest_closure(self) -> None:
        leaky = variant()
        leaky["evidence"]["present_paths"] = leaky["evidence"]["present_paths"] + ["an/uncovered/file.json"]
        report = self._refused_on(leaky, wa.GATE_EVIDENCE)
        self.assertTrue(any("not covered by any hash" in f for f in report["gates"][3]["findings"]))

    def test_injection_6d_a_hash_valid_but_unparsable_artifact_is_now_refused(self) -> None:
        """SCP-SI-01 lane D, DEF-SCP-D-02.

        History, kept rather than erased: `verify_manifest_closure` checks
        path coverage and that `bundle_sha256` binds the entry list as
        written; it never reads the referenced file.
        `evidence_integrity.verify_artifact_validity` already existed and
        would catch a truncated JSON artifact, but `check_evidence_gate`'s
        `MANIFEST_CLOSURE` branch never called it — the live failure named in
        the SCP-SI-01 lane D brief: "a lane published truncated JSON whose
        digest matched its manifest exactly and passed closure."

        This lane reproduced that failure directly and built the fix at
        `scp-si-01/lane-d/fixes/evidence_gate_wiring.py` (still exercised
        below, in `test_injection_6e`). While this was in progress, the
        coordinator independently reproduced the identical class of defect
        against its own declaration (a fabricated sixty-four-zero digest) and
        landed a fix directly in `write_admission.py` and
        `evidence_integrity.verify_manifest_truth`/`verify_artifact_validity`
        (commit `29abd58b`, "repair the evidence gate — it certified a
        forged manifest", found by Lane C). Re-run against the now-merged
        canonical file: the truncated artifact this lane's fixture builds is
        REFUSED by the real, unpatched-by-this-lane `write_admission.py`
        shipped in this tree. `DIRECTLY_REPRODUCED`, this run — two
        independent diagnoses of the same defect converge on the same
        outcome. This case no longer needs this lane's own patch to close;
        `scp-si-01/lane-d/patches/write_admission.py.patch` is retained as a
        record of the independently-designed, functionally-equivalent fix
        this lane proposed before observing that the canonical file had
        already been repaired.
        """
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            truncated = b'{"artifact_id": "DEFECT-2-TRUNCATED", "entries": [1, 2, 3'
            (repo / "truncated-evidence.json").write_bytes(truncated)
            digest = hashlib.sha256(truncated).hexdigest()
            entries = [{"path": "truncated-evidence.json", "size_bytes": len(truncated), "sha256": digest}]
            bundle = hashlib.sha256(
                json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            declaration = variant(**{
                "evidence.record": {"entries": entries, "bundle_sha256": bundle},
                "evidence.present_paths": ["truncated-evidence.json"],
            })
            report = wa.admit(declaration, repo, check_ref_movement=False, rehearse_reversal=True)
        self.assertFalse(
            report["admitted"],
            "if this fails, write_admission.py has regressed on DEF-SCP-D-02: "
            + wa.summarise(report),
        )
        self.assertEqual("EVIDENCE_FAILED_RECOMPUTATION", report["gates"][3]["verdict"])
        self.assertTrue(any("does not parse as JSON" in f for f in report["gates"][3]["findings"]))

    def test_injection_6e_the_lane_d_mechanism_fix_correctly_refuses_it(self) -> None:
        """This lane's own fix module, kept and still exercised directly even
        though the canonical file converged on an equivalent fix (see 6d):
        the diagnosis and the mechanism were both independently correct."""
        fix = _load_lane_d_fix("evidence_gate_wiring")
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            truncated = b'{"artifact_id": "DEFECT-2-TRUNCATED", "entries": [1, 2, 3'
            (repo / "truncated-evidence.json").write_bytes(truncated)
            digest = hashlib.sha256(truncated).hexdigest()
            entries = [{"path": "truncated-evidence.json", "size_bytes": len(truncated), "sha256": digest}]
            bundle = hashlib.sha256(
                json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            declaration = variant(**{
                "evidence.record": {"entries": entries, "bundle_sha256": bundle},
                "evidence.present_paths": ["truncated-evidence.json"],
            })
            gate = fix.check_evidence_gate_with_artifact_validity(declaration, repo)
        self.assertFalse(gate["passed"], gate)
        self.assertEqual("EVIDENCE_FAILED_RECOMPUTATION", gate["verdict"])
        self.assertTrue(any("does not parse as JSON" in f for f in gate["findings"]), gate["findings"])

    def test_injection_6f_the_fix_does_not_regress_a_genuinely_valid_manifest(self) -> None:
        fix = _load_lane_d_fix("evidence_gate_wiring")
        gate = fix.check_evidence_gate_with_artifact_validity(ADMISSIBLE, Path("."))
        self.assertTrue(gate["passed"], gate)


@unittest.skipUnless(_git_available(), "git is required to re-execute the rollback")
class NothingIsTrustedTests(unittest.TestCase):
    """The verify_readback_truth lesson, applied to the declaration's own claims."""

    def test_evidence_that_cannot_be_recomputed_here_fails_closed(self) -> None:
        readback = variant(**{
            "evidence.kind": "READBACK",
            "evidence.record": {"immutable_commit": "0" * 40, "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL"},
            "evidence.present_paths": _DELETE,
        })
        report = decide(readback, remote_url=None)
        self.assertFalse(report["admitted"])
        self.assertEqual("EVIDENCE_UNVERIFIABLE_HERE", report["gates"][3]["verdict"])

    def test_an_unknown_evidence_kind_has_no_recomputation_route_and_is_refused(self) -> None:
        report = decide(variant(**{"evidence.kind": "SIGNED_OFF_BY_ME"}))
        self.assertFalse(report["admitted"])

    def test_later_gates_report_not_evaluated_rather_than_passing(self) -> None:
        """Absence of a check result is not a pass."""
        report = decide({})
        for gate in report["gates"][1:]:
            self.assertEqual("NOT_EVALUATED", gate["verdict"])
            self.assertFalse(gate["passed"])

    def test_the_concurrency_gate_states_its_limit_on_every_admission(self) -> None:
        report = decide(ADMISSIBLE)
        self.assertIn("not proof that nobody is writing", report["gates"][1]["limit"])

    def test_the_reversibility_gate_states_what_the_rehearsal_does_not_prove(self) -> None:
        report = decide(ADMISSIBLE)
        self.assertIn("does not prove the live remote will accept the push",
                      report["gates"][2]["note"])

    def test_evidence_integrity_is_reused_not_reimplemented(self) -> None:
        report = decide(ADMISSIBLE)
        # The gate now names three verifiers, not one: closure is a shape check and
        # was passing forged records, so truth and validity were added beside it.
        # What this test guards is that every verifier is borrowed from
        # evidence_integrity rather than reimplemented here — assert the intent,
        # not a literal that changes whenever a real check is added.
        verified_by = report["gates"][3]["verified_by"]
        named = [n.strip() for n in verified_by.replace("evidence_integrity.", "").split("+")]
        self.assertIn("verify_manifest_closure", named)
        self.assertIn("verify_manifest_truth", named)
        self.assertTrue(verified_by.startswith("evidence_integrity."))
        for fn in named:
            self.assertTrue(hasattr(ei_module, fn), f"{fn} is not an evidence_integrity function")
        source = (Path(__file__).resolve().parent / "write_admission.py").read_text(encoding="utf-8")
        self.assertIn('_load("evidence_integrity")', source)
        for reimplemented in ("def verify_manifest_closure", "def verify_readback_truth"):
            self.assertNotIn(reimplemented, source)


@unittest.skipUnless(_git_available(), "git is required to re-execute the rollback")
class AdvisoryVersusRefusalTests(unittest.TestCase):
    def test_an_assistant_authored_finding_is_reported_without_refusing(self) -> None:
        terse = variant(**{"reason.statement": (
            "main is where the voided guard is published, so the correction as instructed goes there."
        )})
        report = decide(terse)
        self.assertTrue(report["admitted"], wa.summarise(report))
        self.assertTrue(report["gates"][0]["advisories"])

    def test_the_summary_marks_advisories_as_not_in_force(self) -> None:
        terse = variant(**{"reason.statement": (
            "main is where the voided guard is published, so the correction as instructed goes there."
        )})
        text = wa.summarise(decide(terse))
        self.assertIn("assistant-authored, not in force", text)


if __name__ == "__main__":
    unittest.main()


class ConcurrencyFailOpenTests(unittest.TestCase):
    """ICH-08, found by Lane B by tripping it, not by reading the code.

    A gate that passes because it could not run is the INSTALLED_NOT_EFFECTIVE
    class. It was the third instance in this gate in one session: closure asking
    the record about itself, obligation truthiness swallowing a true zero, and
    this — an absent observation skipping the movement check instead of failing it.
    """

    def _decl(self, **concurrency):
        return {
            "target": {"ref": "cursor/operating-environment-return-20260822-v001"},
            "concurrency": {"observed_at": _ago(60), "agents": [], **concurrency},
            "reversal": {},
        }

    def test_an_absent_observation_is_refused_not_skipped(self) -> None:
        gate = wa.check_concurrency_gate(self._decl(), None)
        self.assertFalse(gate["passed"])
        self.assertEqual("CONCURRENCY_NOT_OBSERVED", gate["verdict"])

    def test_an_empty_observation_string_is_also_refused(self) -> None:
        gate = wa.check_concurrency_gate(self._decl(ref_sha_at_observation="   "), None)
        self.assertFalse(gate["passed"])
        self.assertEqual("CONCURRENCY_NOT_OBSERVED", gate["verdict"])

    def test_asserting_idleness_is_not_observing_it(self) -> None:
        """An agents list plus a confident note is not an observation of the ref."""
        gate = wa.check_concurrency_gate(
            self._decl(note="no lane holds this ref"), None)
        self.assertFalse(gate["passed"])

    def test_the_gate_never_passes_by_being_unable_to_run(self) -> None:
        for decl in (self._decl(), self._decl(ref_sha_at_observation=""),
                     self._decl(ref_sha_at_observation=None)):
            self.assertFalse(wa.check_concurrency_gate(decl, None)["passed"])
