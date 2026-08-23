"""Failure injections for the reversibility gate.

Injection 4 of the delivery contract — a reversal that does not actually reverse
— lives here. These tests run real git against real disposable remotes; none of
them touch `origin`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rr = _load("reversal_rehearsal")

METHODS = ("RESTORE_REF_TO_RECORDED_SHA", "REVERT_COMMIT_RANGE", "DELETE_CREATED_REF")


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_git_available(), "git is required to execute a reversal")
class ReversalActuallyReversesTests(unittest.TestCase):
    """Constructed and executed, not described."""

    def test_every_method_restores_the_state_it_claims_to_restore(self) -> None:
        for method in METHODS:
            receipt = rr.rehearse_reversal(method, ref="main")
            self.assertEqual(rr.EXECUTED_AND_VERIFIED, receipt["result"],
                             f"{method}: {receipt.get('detail')}")
            self.assertTrue(receipt["tree_restored"], method)

    def test_a_rehearsal_never_touches_origin(self) -> None:
        receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main")
        self.assertFalse(receipt["touches_origin"])
        self.assertIn("reversal-rehearsal-", receipt["fixture_remote"])

    def test_the_verdict_is_recomputed_from_the_remote_not_from_an_exit_code(self) -> None:
        receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main")
        self.assertIn("exit code is recorded but is not the verdict", receipt["verified_by"])
        self.assertTrue(all(step["exit_code"] == 0 for step in receipt["execution"]))

    def test_a_forward_revert_restores_the_tree_under_a_different_commit(self) -> None:
        """Comparing commit SHAs would fail every correct revert."""
        receipt = rr.rehearse_reversal("REVERT_COMMIT_RANGE", ref="main")
        self.assertEqual(rr.EXECUTED_AND_VERIFIED, receipt["result"])
        self.assertTrue(receipt["tree_restored"])
        self.assertFalse(receipt["commit_restored"])
        self.assertNotEqual(receipt["pre_write"]["commit"], receipt["post_reversal"]["commit"])
        self.assertEqual(receipt["pre_write"]["tree"], receipt["post_reversal"]["tree"])

    def test_deleting_a_created_ref_leaves_the_remote_without_it(self) -> None:
        receipt = rr.rehearse_reversal("DELETE_CREATED_REF", ref="main")
        self.assertEqual(rr.EXECUTED_AND_VERIFIED, receipt["result"])
        self.assertIsNone(receipt["post_reversal"]["commit"])
        self.assertIsNone(receipt["pre_write"]["commit"], "the ref's absence is the pre-write state")


@unittest.skipUnless(_git_available(), "git is required to execute a reversal")
class ReversalThatDoesNotReverseTests(unittest.TestCase):
    """Injection 4: a reversal that does not actually reverse must be refused.

    A rehearsal that cannot fail is not evidence of anything, so each sabotage
    mode is a proof that this one can.
    """

    def test_a_reversal_that_runs_but_restores_nothing_is_refused(self) -> None:
        for mode in ("noop", "unrelated_command"):
            receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main", sabotage=mode)
            self.assertEqual(rr.DID_NOT_RESTORE, receipt["result"], mode)
            self.assertFalse(receipt["tree_restored"], mode)

    def test_a_reversal_that_exits_zero_is_still_refused_when_the_tree_is_wrong(self) -> None:
        """The exit code lies; the tree does not."""
        receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main", sabotage="noop")
        self.assertTrue(all(step["exit_code"] == 0 for step in receipt["execution"]))
        self.assertEqual(rr.DID_NOT_RESTORE, receipt["result"])

    def test_a_reversal_restoring_the_wrong_sha_is_refused(self) -> None:
        receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main", sabotage="wrong_sha")
        self.assertEqual(rr.DID_NOT_RESTORE, receipt["result"])
        self.assertIn("did not restore the state it claims to restore", receipt["detail"])

    def test_a_partial_restore_that_looks_successful_is_refused(self) -> None:
        """The failure mode hardest to spot by reading: most of it worked."""
        receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main", sabotage="partial_restore")
        self.assertEqual(rr.DID_NOT_RESTORE, receipt["result"])
        self.assertFalse(receipt["tree_restored"])

    def test_a_deletion_that_does_not_delete_is_refused(self) -> None:
        receipt = rr.rehearse_reversal("DELETE_CREATED_REF", ref="main", sabotage="noop")
        self.assertEqual(rr.DID_NOT_RESTORE, receipt["result"])
        self.assertIsNotNone(receipt["post_reversal"]["commit"])

    def test_the_no_commit_regression_stays_fixed(self) -> None:
        """The first REVERT_COMMIT_RANGE draft used --no-commit, so the revert was
        staged, the push published the unchanged commit and exited 0, and nothing
        was restored. The rehearsal caught it; this keeps it caught."""
        plan = rr.build_reversal("REVERT_COMMIT_RANGE", "main", recorded_sha="a" * 40, post_write_sha="b" * 40)
        self.assertNotIn("--no-commit", plan["command"])


@unittest.skipUnless(_git_available(), "git is required to execute a reversal")
class VacuousRehearsalTests(unittest.TestCase):
    def test_a_write_that_changed_nothing_proves_nothing(self) -> None:
        """A reversal passes trivially if there was nothing to reverse."""
        original = rr._apply_write

        def empty_write(work, ref, origin, message):
            rr.run(["git", "commit", "--quiet", "--allow-empty", "-m", message], cwd=work)
            rr.run(["git", "push", "--quiet", "origin", f"{ref}:refs/heads/{ref}"], cwd=work)

        rr._apply_write = empty_write
        try:
            receipt = rr.rehearse_reversal("RESTORE_REF_TO_RECORDED_SHA", ref="main")
        finally:
            rr._apply_write = original
        self.assertEqual(rr.PROVED_NOTHING, receipt["result"])
        self.assertIn("demonstrates nothing", receipt["detail"])


class ConstructorTests(unittest.TestCase):
    """One constructor produces the argv for both the rehearsal and the declaration."""

    def test_an_unknown_method_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ValueError):
            rr.build_reversal("HOPE_FOR_THE_BEST", "main")

    def test_a_restore_without_a_recorded_sha_cannot_be_constructed(self) -> None:
        with self.assertRaises(ValueError):
            rr.build_reversal("RESTORE_REF_TO_RECORDED_SHA", "main")

    def test_the_lease_pins_the_expected_post_write_value(self) -> None:
        """A concurrent writer must break the rollback, not be silently discarded."""
        plan = rr.build_reversal("RESTORE_REF_TO_RECORDED_SHA", "main",
                                 recorded_sha="a" * 40, post_write_sha="b" * 40)
        self.assertIn(f"--force-with-lease=main:{'b' * 40}", plan["command"])

    def test_the_constructor_holds_no_list_of_target_names(self) -> None:
        source = (Path(__file__).resolve().parent / "reversal_rehearsal.py").read_text(encoding="utf-8")
        for forbidden in ("PROTECTED_REFS", "PROTECTED_PREFIXES", "protected_branch_globs"):
            self.assertNotIn(forbidden, source)

    def test_the_same_constructor_serves_every_target_name(self) -> None:
        for ref in ("main", "cursor/po03-wave-a-factory-6e19", "scratch"):
            plan = rr.build_reversal("RESTORE_REF_TO_RECORDED_SHA", ref,
                                     recorded_sha="a" * 40, post_write_sha="b" * 40)
            self.assertIn(f"{'a' * 40}:refs/heads/{ref}", plan["command"])


class CommandDriftTests(unittest.TestCase):
    """What was rehearsed must be what will run."""

    BASE = {
        "target": {"ref": "main"},
        "reversal": {
            "method": "RESTORE_REF_TO_RECORDED_SHA",
            "recorded_sha": "a" * 40,
            "post_write_sha": "b" * 40,
            "custody_ref": "refs/tags/pre-write/main",
        },
    }

    def _with_command(self, command):
        payload = {"target": dict(self.BASE["target"]), "reversal": dict(self.BASE["reversal"])}
        payload["reversal"]["command"] = command
        return payload

    def test_a_command_matching_the_constructor_is_accepted(self) -> None:
        expected = rr.build_reversal("RESTORE_REF_TO_RECORDED_SHA", "main",
                                     recorded_sha="a" * 40, post_write_sha="b" * 40)["command"]
        self.assertEqual([], rr.command_matches_constructor(self._with_command(expected)))

    def test_a_hand_edited_command_is_refused(self) -> None:
        for tampered in (
            ["git", "push", "--force", "origin", f"{'a' * 40}:refs/heads/main"],
            ["git", "push", "origin", "main"],
            ["echo", "reverted"],
            [],
        ):
            findings = rr.command_matches_constructor(self._with_command(tampered))
            self.assertTrue(findings, tampered)
            self.assertIn("never the command that was rehearsed", findings[0])

    def test_a_declaration_with_no_method_cannot_be_re_derived(self) -> None:
        self.assertTrue(rr.command_matches_constructor({"target": {"ref": "main"}, "reversal": {}}))


if __name__ == "__main__":
    unittest.main()
