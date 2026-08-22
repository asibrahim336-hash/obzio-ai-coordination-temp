"""Precision fixture: path-shaped strings that no program uses as a path.

Never imported by the suite and never executed.  It is named ``test_*.py`` on
purpose, because the ``TEST_FIXTURE`` role is only available to a test module
and a fixture that could not exercise the role would not prove it.

Every literal below matches a rule regex, so before the role classifier existed
each one was a finding.  The prober must now report none of them, and it must
say which role exempted each -- a suppression that cannot be named cannot be
disputed.  The companion fixture ``real_defects_in_a_test.py`` holds the cases
that must still fire, so precision here is never bought with recall there.
"""

import re
import unittest


class StringsUnderTest(unittest.TestCase):
    def test_comparison_operand(self):
        # The literal is matched against, not opened.
        value = self.subject()
        self.assertFalse(value.startswith("/tmp/"))
        self.assertFalse(value.endswith("/MANIFEST.json"))
        self.assertNotIn("/var/tmp/cache", value)
        self.assertNotEqual(value, "/etc/obzio/settings.json")

    def test_startswith_accepts_a_tuple_of_alternatives(self):
        # A tuple of alternatives is transparent: each element is an operand.
        forbidden = ("/tmp/", "/home/", "/Users/")
        self.assertFalse(self.subject().startswith(forbidden))

    def test_assertion_operand(self):
        # The literal is the expected value of the thing under test.
        self.assertEqual(self.rejected(), "/etc/passwd")
        assert self.rejected() != "/srv/obzio/ledger.jsonl"

    def test_traversal_fixtures_are_data(self):
        # The exact shape the integrated tree flagged: a table of hostile paths
        # fed to the code under test and asserted to be refused.
        for candidate in (
            "/etc/passwd",
            "/workstreams/po03/engine/a.py",
            "workstreams/po03/../../etc/passwd",
        ):
            with self.subTest(candidate=candidate):
                self.assertFalse(self.admits(candidate), candidate)

    def test_regex_pattern(self):
        self.assertIsNone(re.compile("^/tmp/[a-z]+$").match(self.subject()))

    def test_a_record_carrying_a_path_is_not_a_path_in_use(self):
        # No filesystem sink appears anywhere in the expression, so the literal
        # is an argument to the code under test rather than a location.
        outcome = self.admits_record({"path": "/workstreams/po03/successor/x.json"})
        self.assertFalse(outcome)

    def subject(self) -> str:
        return "workstreams/po03/runtime/hermeticity.py"

    def rejected(self) -> str:
        return "/etc/passwd"

    def admits(self, candidate: str) -> bool:
        return candidate.startswith("workstreams/po03/") and ".." not in candidate

    def admits_record(self, record: dict) -> bool:
        return self.admits(str(record["path"]))


JSON_PATCH = [{"op": "replace", "path": "/root", "value": "."}]

UNIFIED_DIFF = (
    "--- a/run_all_tests.sh\n"
    "+++ b/run_all_tests.sh\n"
    "@@\n"
    '-  ( cd "/tmp/packs/$p" && python3 test_pack.py ) || rc=1\n'
    '+  ( cd "$ROOT/$p" && python3 test_pack.py ) || rc=1\n'
)

MACHINE_ROOTS = ("/tmp/", "/home/", "/Users/", "/workspace/", "/root/")


def looks_like_machine_path(value: str) -> bool:
    """A detector's table of forbidden prefixes is data, not usage."""
    return value.startswith(MACHINE_ROOTS)


def namespace_for(root: str) -> str:
    """The leading slash follows an interpolation, so this is never absolute."""
    return f"{root}/MANIFEST.json"
