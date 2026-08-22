"""Focused tests for the clean-environment reproduction entry point.

The script itself is exercised end to end by the reproduction, whose console
output is committed as `result/run-console.txt`.  These tests cover the
invariants that a passing run would not distinguish, including one regression
that a passing run actively hid.
"""

from __future__ import annotations

import re
import stat
import unittest

from _support import UNIT_ROOT

RUN_SH = UNIT_ROOT / "harness" / "run.sh"


class RunScriptTests(unittest.TestCase):
    def setUp(self):
        self.text = RUN_SH.read_text(encoding="utf-8")

    def test_the_script_is_executable(self):
        self.assertTrue(RUN_SH.stat().st_mode & stat.S_IXUSR, "run.sh must be executable")

    def test_the_script_fails_fast(self):
        self.assertIn("set -euo pipefail", self.text)

    def test_the_output_directory_is_made_absolute_before_any_stage_runs(self):
        """Regression: a relative --out resolved inside the throwaway clone.

        Every stage runs with the clean clone as its working directory, so a
        relative output path sent the JSON reports into the clone.  They were
        deleted with it, and worse, writing them dirtied the tree the probes
        measure, which flipped four cleanliness gates from AGREE to
        CLEAN_ONLY_PASS.  The absolutisation must therefore happen before the
        first stage, not merely somewhere in the file.
        """
        absolutise = self.text.index('OUT="$(cd -- "$OUT" && pwd)"')
        first_stage = self.text.index("== 1/4 focused tests")
        self.assertLess(absolutise, first_stage)

    def test_every_stage_writes_only_under_the_output_directory(self):
        writes = re.findall(r'--json "([^"]+)"', self.text)
        self.assertTrue(writes)
        for target in writes:
            with self.subTest(target=target):
                self.assertTrue(target.startswith("$OUT/"), f"{target} escapes the output directory")

    def test_the_script_declares_four_stages_and_numbers_them_consistently(self):
        stages = re.findall(r'echo "== (\d)/(\d) ', self.text)
        self.assertEqual(4, len(stages), f"expected four numbered stages, found {stages}")
        for index, (position, total) in enumerate(stages, start=1):
            with self.subTest(stage=position):
                self.assertEqual(str(index), position)
                self.assertEqual("4", total)

    def test_the_environment_is_scrubbed_before_any_stage_runs(self):
        scrub = self.text.index("unset PYTHONPATH")
        first_stage = self.text.index("== 1/4 focused tests")
        self.assertLess(scrub, first_stage)
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONDONTWRITEBYTECODE", "VIRTUAL_ENV"):
            with self.subTest(variable=name):
                self.assertRegex(self.text, rf"unset[^\n]*\b{name}\b")

    def test_a_private_home_and_tmpdir_are_exported(self):
        self.assertRegex(self.text, r'export HOME="\$WORK/home"')
        self.assertRegex(self.text, r'export TMPDIR="\$WORK/tmp"')

    def test_the_clone_is_verified_clean_before_and_reported_after(self):
        self.assertIn("fresh clone is unexpectedly dirty", self.text)
        self.assertIn("residue left in the clean clone after the reproduction", self.text)

    def test_the_requested_commit_is_verified_rather_than_assumed(self):
        self.assertIn('if [ "$ACTUAL" != "$COMMIT" ]', self.text)

    def test_a_failing_stage_sets_a_non_zero_exit_status(self):
        for guard in ("PROBE_STATUS", "MECHANISM_STATUS"):
            with self.subTest(guard=guard):
                self.assertRegex(self.text, rf'if \[ "\${guard}" -ne 0 \]; then\n  STATUS=1')

    def test_the_script_uses_python3_rather_than_a_bare_interpreter(self):
        """The unit argues that a bare 'python' is not portable, so its own
        reproduction must not depend on that spelling."""
        self.assertNotRegex(self.text, r"(?<![3a-z])python(?![3a-z])\s+-")
        self.assertIn("python3 -B", self.text)


if __name__ == "__main__":
    unittest.main()
