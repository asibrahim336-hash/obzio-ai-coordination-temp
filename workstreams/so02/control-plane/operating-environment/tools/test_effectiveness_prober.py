"""Tests for the generalised effectiveness prober.

Two kinds of test live here:

1. Unit tests of `classify`/`assert_effective` — pure, deterministic, no
   fixtures — proving the classifier itself never certifies EFFECTIVE
   without a probe result showing the control fired.
2. Smoke tests of each per-control probe against real (but disposable)
   fixtures, proving every probe is actually inert: none of them touches
   this repository's own history or its real `origin`.

Part 3's regression — a control asserted as enforcing while unreachable must
fail a test — lives in `RegressionAssertedEnforcingWhileUnreachableTests`
below.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
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


prober = _load("effectiveness_prober")

REPO_ROOT = Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).resolve().parent,
                   capture_output=True, text=True, timeout=30).stdout.strip()
)


class ClassifyNeverCertifiesWithoutAProbeTests(unittest.TestCase):
    """The core rule: EFFECTIVE requires installed AND a probe ran AND it fired."""

    def test_not_installed_is_its_own_verdict(self) -> None:
        result = prober.classify("X", installed=False, probe_ran=False, fired=None,
                                 method="m", detail="d")
        self.assertEqual(prober.NOT_INSTALLED, result.verdict)

    def test_installed_with_no_probe_result_is_unprobeable_not_effective(self) -> None:
        """The exact shortcut this module exists to close off."""
        result = prober.classify("X", installed=True, probe_ran=False, fired=None,
                                 method="m", detail="no inert probe exists")
        self.assertEqual(prober.UNPROBEABLE, result.verdict)

    def test_installed_with_fired_none_is_unprobeable_even_if_probe_ran_is_true(self) -> None:
        """probe_ran=True with fired=None is a contradiction the classifier must not paper over."""
        result = prober.classify("X", installed=True, probe_ran=True, fired=None,
                                 method="m", detail="d")
        self.assertEqual(prober.UNPROBEABLE, result.verdict)

    def test_installed_probed_and_fired_is_effective(self) -> None:
        result = prober.classify("X", installed=True, probe_ran=True, fired=True,
                                 method="m", detail="d")
        self.assertEqual(prober.EFFECTIVE, result.verdict)

    def test_installed_probed_and_not_fired_is_installed_not_effective(self) -> None:
        result = prober.classify("X", installed=True, probe_ran=True, fired=False,
                                 method="m", detail="d")
        self.assertEqual(prober.INSTALLED_NOT_EFFECTIVE, result.verdict)

    def test_an_unknown_verdict_string_cannot_be_constructed(self) -> None:
        with self.assertRaises(ValueError):
            prober.ProbeResult("X", "SORT_OF_EFFECTIVE", prober.DIRECTLY_REPRODUCED, "m", "d")

    def test_an_unknown_evidence_label_cannot_be_constructed(self) -> None:
        with self.assertRaises(ValueError):
            prober.ProbeResult("X", prober.EFFECTIVE, "VIBES", "m", "d")


class AssertEffectiveTests(unittest.TestCase):
    def test_assert_effective_passes_silently_for_an_effective_result(self) -> None:
        result = prober.classify("X", installed=True, probe_ran=True, fired=True,
                                 method="m", detail="d")
        prober.assert_effective(result)  # must not raise

    def test_assert_effective_raises_for_installed_not_effective(self) -> None:
        result = prober.classify("X", installed=True, probe_ran=True, fired=False,
                                 method="m", detail="d")
        with self.assertRaises(prober.ControlNotEffectiveError):
            prober.assert_effective(result)

    def test_assert_effective_raises_for_unprobeable(self) -> None:
        result = prober.classify("X", installed=True, probe_ran=False, fired=None,
                                 method="m", detail="d")
        with self.assertRaises(prober.ControlNotEffectiveError):
            prober.assert_effective(result)

    def test_assert_effective_raises_for_not_installed(self) -> None:
        result = prober.classify("X", installed=False, probe_ran=False, fired=None,
                                 method="m", detail="d")
        with self.assertRaises(prober.ControlNotEffectiveError):
            prober.assert_effective(result)


class AmbientHookWrapperTests(unittest.TestCase):
    """The manual-probe wrapper reproduces the exact NOT_FIRING arithmetic."""

    def test_zero_lines_added_is_installed_not_effective(self) -> None:
        result = prober.ambient_hook_result_from_manual_probe(
            armed_at="2026-08-27T06:23:35Z", checked_at="2026-08-27T06:24:01Z",
            audit_lines_before=3, audit_lines_after=3, control_passed_at_arm=True,
            commands_sent_through_shell_tool=["git status --porcelain"],
        )
        self.assertEqual(prober.INSTALLED_NOT_EFFECTIVE, result.verdict)
        self.assertEqual(prober.DIRECTLY_REPRODUCED, result.evidence_label)

    def test_lines_added_is_effective(self) -> None:
        result = prober.ambient_hook_result_from_manual_probe(
            armed_at="2026-08-27T06:23:35Z", checked_at="2026-08-27T06:24:01Z",
            audit_lines_before=3, audit_lines_after=4, control_passed_at_arm=True,
            commands_sent_through_shell_tool=["git status --porcelain"],
        )
        self.assertEqual(prober.EFFECTIVE, result.verdict)


class PerControlProbesAreInertTests(unittest.TestCase):
    """Every probe function returns EFFECTIVE here, using only disposable fixtures."""

    def test_write_admission_gate_probe_fires_correctly(self) -> None:
        result = prober.probe_write_admission_gate(REPO_ROOT)
        self.assertEqual(prober.EFFECTIVE, result.verdict, result.detail)
        self.assertEqual(prober.DIRECTLY_REPRODUCED, result.evidence_label)

    def test_evidence_integrity_validity_probe_fires_correctly(self) -> None:
        result = prober.probe_evidence_integrity_validity(REPO_ROOT)
        self.assertEqual(prober.EFFECTIVE, result.verdict, result.detail)

    def test_evidence_integrity_readback_probe_fires_correctly(self) -> None:
        result = prober.probe_evidence_integrity_readback(REPO_ROOT)
        self.assertEqual(prober.EFFECTIVE, result.verdict, result.detail)

    def test_lane_guard_probe_fires_correctly(self) -> None:
        result = prober.probe_lane_guard(REPO_ROOT)
        self.assertEqual(prober.EFFECTIVE, result.verdict, result.detail)

    def test_currentctl_probe_fires_correctly(self) -> None:
        result = prober.probe_currentctl(REPO_ROOT)
        self.assertEqual(prober.EFFECTIVE, result.verdict, result.detail)

    def test_no_probe_ever_writes_to_the_real_origin_remote(self) -> None:
        """Static check: none of the probe source touches `git push` to a non-scratch target
        without going through write_admission's own disposable rehearsal fixtures."""
        source = (Path(__file__).resolve().parent / "effectiveness_prober.py").read_text(encoding="utf-8")
        self.assertNotIn('"push", "origin", "main"', source)
        self.assertNotIn("push origin main", source)


class SweepShapeTests(unittest.TestCase):
    def test_sweep_without_ambient_hook_runs_only_programmatic_probes(self) -> None:
        report = prober.sweep(REPO_ROOT)
        self.assertEqual(len(prober.PROGRAMMATIC_PROBES), report["controls_probed"])
        ids = [r["control_id"] for r in report["results"]]
        self.assertNotIn("WRITE-SCOPE AMBIENT HOOK (.cursor/hooks/guard_write_scope.py via beforeShellExecution)", ids)

    def test_sweep_with_ambient_hook_includes_it_first(self) -> None:
        ambient = prober.ambient_hook_result_from_manual_probe(
            armed_at="a", checked_at="b", audit_lines_before=3, audit_lines_after=3,
            control_passed_at_arm=True, commands_sent_through_shell_tool=["x"],
        )
        report = prober.sweep(REPO_ROOT, ambient)
        self.assertEqual(len(prober.PROGRAMMATIC_PROBES) + 1, report["controls_probed"])
        self.assertEqual("WRITE-SCOPE AMBIENT HOOK (.cursor/hooks/guard_write_scope.py via beforeShellExecution)",
                         report["results"][0]["control_id"])

    def test_verdict_counts_reconcile_with_results(self) -> None:
        report = prober.sweep(REPO_ROOT)
        total = sum(report["verdict_counts"].values())
        self.assertEqual(report["controls_probed"], total)


class RegressionAssertedEnforcingWhileUnreachableTests(unittest.TestCase):
    """Part 3: a control asserted as enforcing while unreachable must fail a test.

    This is the regression the founder asked for. It has two halves:

    1. The FAILING-BEFORE state, reproduced directly rather than assumed: a
       naive belief that `require_write_declaration: true` in the shipped
       config means a bare `git push` is gated is falsified by actually
       running one, with nothing in the path invoking any guard at all —
       exactly what happens when the ambient hook does not fire. This half
       is expected to demonstrate the vulnerability, not to hide it: if this
       ever stops failing under `--no-guard`, whatever changed made a bare
       `git push` self-gating, which would be a different and equally
       reportable event.
    2. The classifier itself must never let such a control through as
       EFFECTIVE. `assert_effective` on the real, live-probed ambient-hook
       result (fed from this lane's own DIRECTLY_REPRODUCED probe, not a
       hypothetical) must raise. If a future change to `classify` ever made
       this pass silently, that change reintroduced the exact defect named
       `INSTALLED_NOT_EFFECTIVE`.
    """

    def _git(self, args, cwd, timeout=30):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)

    def test_before_any_explicit_gate_a_bare_push_is_not_stopped_by_config_alone(self) -> None:
        """FAILING-BEFORE state: config asserting enforcement, with nothing invoking the guard,
        does not stop a write. Reproduced against a disposable fixture, never this repo's remote."""
        with tempfile.TemporaryDirectory(prefix="regression-before-") as workdir:
            root = Path(workdir)
            remote = root / "origin.git"
            repo = root / "repo"
            self._git(["init", "--quiet", "--bare", str(remote)], root)
            self._git(["init", "--quiet", "-b", "main", str(repo)], root)
            for key, value in (("user.email", "t@obzio.invalid"), ("user.name", "T"),
                               ("commit.gpgsign", "false")):
                self._git(["config", key, value], repo)
            self._git(["remote", "add", "origin", str(remote)], repo)
            (repo / "f.txt").write_text("x\n", encoding="utf-8")
            self._git(["add", "-A"], repo)
            self._git(["commit", "--quiet", "-m", "seed"], repo)

            # This is the "asserted enforcing" half: a write-scope config exists,
            # sitting right next to this checkout, and it says declarations are
            # required. Nothing in this test invokes it, which is exactly what
            # happens when the ambient hook that would invoke it never fires.
            (repo / ".cursor").mkdir()
            (repo / ".cursor" / "write-scope.json").write_text(
                '{"require_write_declaration": true, '
                '"write_declarations_dir": ".cursor/write-declarations"}',
                encoding="utf-8",
            )
            # No declaration exists to admit. If the control were reachable,
            # this push would have to be refused.

            result = self._git(["push", "origin", "main"], repo)

            self.assertEqual(
                0, result.returncode,
                "a bare `git push`, with nothing invoking the guard, unexpectedly failed on its "
                "own here; that would mean something other than an actual gate is intercepting "
                "git pushes in this environment, which is itself worth investigating"
            )
            remote_head = self._git(["rev-parse", "main"], remote).stdout.strip()
            local_head = self._git(["rev-parse", "HEAD"], repo).stdout.strip()
            self.assertEqual(
                local_head, remote_head,
                "the undeclared, config-asserted-enforcing write reached the remote unrefused"
            )

    def test_the_live_probed_ambient_hook_result_fails_assert_effective(self) -> None:
        """The other half: our own classifier must refuse to certify this control effective."""
        ambient = prober.ambient_hook_result_from_manual_probe(
            # These are this lane's own DIRECTLY_REPRODUCED numbers, recorded in
            # AMBIENT-HOOK-PROBE-INPUT-20260827.json, not a hypothetical fixture.
            armed_at="2026-08-27T06:23:35Z", checked_at="2026-08-27T06:24:01Z",
            audit_lines_before=3, audit_lines_after=3, control_passed_at_arm=True,
            commands_sent_through_shell_tool=[
                "git status --porcelain", "git rebase --abort", "gh workflow list"],
        )
        self.assertEqual(prober.INSTALLED_NOT_EFFECTIVE, ambient.verdict)
        with self.assertRaises(prober.ControlNotEffectiveError) as ctx:
            prober.assert_effective(ambient)
        self.assertIn("INSTALLED_NOT_EFFECTIVE", str(ctx.exception))
        self.assertIn("WRITE-SCOPE AMBIENT HOOK", str(ctx.exception))

    def test_a_regression_guard_a_naive_classifier_that_trusts_config_alone_would_pass_wrongly(self) -> None:
        """Documents the exact wrong shortcut by name and shows it produces the wrong answer,
        so nobody re-derives it under a different name and calls it a fix."""

        def naive_wrong_classifier(require_write_declaration_configured: bool) -> str:
            # This is the belief the coordinator itself held and reported to the
            # founder on 2026-08-23, corrected on 2026-08-27: "enabling it would
            # make every push require an admitted declaration." It trusts
            # installation as a proxy for effectiveness.
            return prober.EFFECTIVE if require_write_declaration_configured else prober.NOT_INSTALLED

        naive_verdict = naive_wrong_classifier(True)
        correct_verdict = prober.classify(
            "WRITE-SCOPE AMBIENT HOOK", installed=True, probe_ran=True, fired=False,
            method="probe_hook_firing.py", detail="NOT_FIRING, DIRECTLY_REPRODUCED",
        ).verdict

        self.assertEqual(prober.EFFECTIVE, naive_verdict)  # the wrong belief, made explicit
        self.assertEqual(prober.INSTALLED_NOT_EFFECTIVE, correct_verdict)  # what a probe shows
        self.assertNotEqual(
            naive_verdict, correct_verdict,
            "if these ever match, either the naive shortcut stopped being wrong (verify the "
            "ambient hook actually fires now) or the real classifier regressed into it"
        )


if __name__ == "__main__":
    unittest.main()
