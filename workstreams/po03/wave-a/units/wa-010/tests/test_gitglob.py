"""Focused tests for the anchored git-style glob layer."""

import itertools
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

from gitglob import (  # noqa: E402
    GlobSyntaxError,
    PathGlob,
    PathSyntaxError,
    compile_segment,
    normalize_path,
    segment_intersection_witness,
    segment_matches,
)


class SegmentSemanticsTest(unittest.TestCase):
    def test_star_stays_inside_one_segment(self):
        self.assertTrue(segment_matches(compile_segment("*.yml"), "po03-contracts.yml"))
        self.assertFalse(segment_matches(compile_segment("*.yml"), "sub/a.yml"))

    def test_star_matches_the_empty_string(self):
        self.assertTrue(segment_matches(compile_segment("a*b"), "ab"))
        self.assertTrue(segment_matches(compile_segment("*"), ""))

    def test_question_mark_matches_exactly_one_character(self):
        items = compile_segment("wa-01?")
        self.assertTrue(segment_matches(items, "wa-010"))
        self.assertFalse(segment_matches(items, "wa-01"))
        self.assertFalse(segment_matches(items, "wa-0100"))

    def test_character_class_ranges_and_negation(self):
        self.assertTrue(segment_matches(compile_segment("[a-c]x"), "bx"))
        self.assertFalse(segment_matches(compile_segment("[a-c]x"), "dx"))
        self.assertTrue(segment_matches(compile_segment("[!a-c]x"), "dx"))
        self.assertFalse(segment_matches(compile_segment("[^a-c]x"), "ax"))

    def test_leading_bracket_and_literal_close_bracket(self):
        self.assertTrue(segment_matches(compile_segment("[]]"), "]"))
        self.assertTrue(segment_matches(compile_segment("[!]]"), "a"))
        self.assertFalse(segment_matches(compile_segment("[!]]"), "]"))

    def test_unterminated_bracket_is_a_literal(self):
        self.assertTrue(segment_matches(compile_segment("a[bc"), "a[bc"))

    def test_escapes_disarm_metacharacters(self):
        items = compile_segment(r"wa-01\*")
        self.assertTrue(segment_matches(items, "wa-01*"))
        self.assertFalse(segment_matches(items, "wa-010"))

    def test_dangling_escape_and_inverted_range_are_rejected(self):
        with self.assertRaises(GlobSyntaxError):
            compile_segment("a\\")
        with self.assertRaises(GlobSyntaxError):
            compile_segment("[z-a]")

    def test_segment_pattern_rejects_separator(self):
        with self.assertRaises(GlobSyntaxError):
            compile_segment("a/b")


class PathGlobSemanticsTest(unittest.TestCase):
    def test_grant_owns_paths_inside_its_subtree_only(self):
        glob = PathGlob("workstreams/po03/wave-a/units/wa-010/**")
        self.assertTrue(glob.matches("workstreams/po03/wave-a/units/wa-010/result/result.json"))
        self.assertTrue(glob.matches("workstreams/po03/wave-a/units/wa-010/a"))
        self.assertFalse(glob.matches("workstreams/po03/wave-a/units/wa-010"))

    def test_trailing_double_star_needs_a_component(self):
        self.assertFalse(PathGlob("a/**").matches("a"))
        self.assertTrue(PathGlob("a/**").matches("a/b"))
        self.assertTrue(PathGlob("a/**").matches("a/b/c/d"))

    def test_interior_double_star_matches_zero_directories(self):
        glob = PathGlob("a/**/b")
        self.assertTrue(glob.matches("a/b"))
        self.assertTrue(glob.matches("a/x/b"))
        self.assertTrue(glob.matches("a/x/y/b"))
        self.assertFalse(glob.matches("a/x/y"))

    def test_leading_double_star_matches_at_every_depth(self):
        glob = PathGlob("**/result.json")
        self.assertTrue(glob.matches("result.json"))
        self.assertTrue(glob.matches("a/b/result.json"))
        self.assertFalse(glob.matches("result.json.bak"))

    def test_lone_double_star_matches_every_path(self):
        glob = PathGlob("**")
        self.assertTrue(glob.matches("a"))
        self.assertTrue(glob.matches("a/b/c"))

    def test_sibling_prefix_confusion_is_rejected(self):
        glob = PathGlob("workstreams/po03/wave-a/units/wa-010/**")
        for path in (
            "workstreams/po03/wave-a/units/wa-0100/result.json",
            "workstreams/po03/wave-a/units/wa-010x/result.json",
            "workstreams/po03/wave-a/units/WA-010/result.json",
        ):
            with self.subTest(path=path):
                self.assertFalse(glob.matches(path))

    def test_repeated_double_star_collapses(self):
        self.assertEqual(PathGlob("a/**/**/b").tokens, PathGlob("a/**/b").tokens)

    def test_pattern_syntax_is_constrained(self):
        for pattern in ("", "/a/b", "a/b/", "a//b", "a/b**", "a/./b", "a/../b"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(GlobSyntaxError):
                    PathGlob(pattern)


class PathNormalisationTest(unittest.TestCase):
    def test_plain_relative_path_splits_into_segments(self):
        self.assertEqual(normalize_path("a/b/c.json"), ("a", "b", "c.json"))

    def test_hostile_shapes_are_refused(self):
        hostile = [
            "",
            "/a",
            "a/",
            "a//b",
            "a/./b",
            "a/../b",
            "..",
            "a\\b",
            "C:/a",
            '"a/b"',
            "a/\x00b",
            "a/\nb",
            "a/\x7fb",
        ]
        for raw in hostile:
            with self.subTest(raw=raw):
                with self.assertRaises(PathSyntaxError):
                    normalize_path(raw)

    def test_non_string_is_refused(self):
        for raw in (None, 7, ["a"]):
            with self.subTest(raw=raw):
                with self.assertRaises(PathSyntaxError):
                    normalize_path(raw)


class IntersectionTest(unittest.TestCase):
    def assert_witness(self, left, right):
        left_glob, right_glob = PathGlob(left), PathGlob(right)
        witness = left_glob.intersection_witness(right_glob)
        self.assertIsNotNone(witness, f"{left} and {right} should overlap")
        self.assertTrue(left_glob.matches(witness), f"{left} must match its own witness {witness!r}")
        self.assertTrue(
            right_glob.matches(witness), f"{right} must match its own witness {witness!r}"
        )
        return witness

    def assert_disjoint(self, left, right):
        self.assertIsNone(PathGlob(left).intersection_witness(PathGlob(right)))
        self.assertIsNone(PathGlob(right).intersection_witness(PathGlob(left)))

    def test_sibling_unit_grants_are_disjoint(self):
        self.assert_disjoint(
            "workstreams/po03/wave-a/units/wa-010/**",
            "workstreams/po03/wave-a/units/wa-011/**",
        )

    def test_ancestor_grant_overlaps_descendant_grant(self):
        witness = self.assert_witness(
            "workstreams/po03/wave-a/units/wa-010/**", "workstreams/po03/**"
        )
        self.assertTrue(witness.startswith("workstreams/po03/wave-a/units/wa-010/"))

    def test_wildcard_segment_grant_captures_numbered_siblings(self):
        self.assert_witness(
            "workstreams/po03/wave-a/units/wa-01?/**",
            "workstreams/po03/wave-a/units/wa-011/**",
        )

    def test_character_class_intersection(self):
        self.assert_witness("a/[0-9]x", "a/[5-8]x")
        self.assert_disjoint("a/[0-9]x", "a/[a-z]x")
        self.assert_disjoint("a/[!0-9]x", "a/5x")
        self.assert_witness("a/[!0-9]x", "a/[a-z]x")

    def test_negated_class_against_negated_class(self):
        self.assert_witness("a/[!a]", "a/[!b]")

    def test_fixed_paths_only_overlap_when_equal(self):
        self.assert_witness("a/b/c.json", "a/b/c.json")
        self.assert_disjoint("a/b/c.json", "a/b/d.json")

    def test_double_star_crossing(self):
        self.assert_witness("a/**/b", "a/b/**")
        self.assert_disjoint("a/**", "b/**")

    def test_length_mismatch_is_disjoint(self):
        self.assert_disjoint("a/?", "a/??")

    def test_deny_and_grant_are_disjoint_for_this_unit(self):
        for deny in ("state/**", "dispatch/**", ".cursor/environment.json"):
            with self.subTest(deny=deny):
                self.assert_disjoint(deny, "workstreams/po03/wave-a/units/wa-010/**")

    def test_empty_common_match_is_not_an_overlap(self):
        self.assertIsNone(segment_intersection_witness(compile_segment(""), compile_segment("*")))
        self.assertEqual(
            segment_intersection_witness(compile_segment("*"), compile_segment("*")), "a"
        )


class IntersectionPropertyTest(unittest.TestCase):
    """Cross-check the decision procedure against brute-force enumeration.

    Two directions are checked without assuming the enumerated space is
    complete: a witness must genuinely be matched by both patterns, and any
    common path found by enumeration must have produced a witness.
    """

    SEGMENT_TOKENS = ("a", "b", "*", "?", "a*", "[ab]", "[!a]", "**")
    ALPHABET = ("a", "b", "c")

    def _patterns(self):
        for length in (1, 2, 3):
            for tokens in itertools.product(self.SEGMENT_TOKENS, repeat=length):
                pattern = "/".join(tokens)
                try:
                    yield PathGlob(pattern)
                except GlobSyntaxError:
                    continue

    def _paths(self):
        segments = [
            "".join(chars)
            for size in (1, 2)
            for chars in itertools.product(self.ALPHABET, repeat=size)
        ]
        for depth in (1, 2, 3):
            for parts in itertools.product(segments, repeat=depth):
                yield "/".join(parts)

    def test_witness_agrees_with_enumeration(self):
        patterns = list(self._patterns())
        paths = list(self._paths())
        matched = {
            glob.pattern: frozenset(path for path in paths if glob.matches(path))
            for glob in patterns
        }
        self.assertGreater(len(patterns), 400)
        self.assertGreater(len(paths), 700)
        checked = 0
        for left, right in itertools.combinations(patterns, 2):
            witness = left.intersection_witness(right)
            shared = matched[left.pattern] & matched[right.pattern]
            if witness is None:
                self.assertEqual(
                    shared,
                    frozenset(),
                    f"{left.pattern} and {right.pattern} were called disjoint but share {sorted(shared)[:3]}",
                )
            else:
                self.assertTrue(
                    left.matches(witness),
                    f"{left.pattern} does not match its witness {witness!r}",
                )
                self.assertTrue(
                    right.matches(witness),
                    f"{right.pattern} does not match its witness {witness!r}",
                )
            checked += 1
        self.assertGreater(checked, 100000)


@unittest.skipIf(shutil.which("git") is None, "git is not available")
class GitDifferentialTest(unittest.TestCase):
    """Compare the matcher against git's own ``:(glob)`` pathspec engine.

    This is the only check that can show the dialect is right rather than merely
    self-consistent, so the file set and pattern set deliberately include the
    cases the two dialects disagree about.
    """

    FILES = (
        "a/f.txt",
        "a/b/f.txt",
        "a/b/c/f.txt",
        "a/b/c/g.jpg",
        "a/bb/f.txt",
        "d/e/f.txt",
        "f.txt",
        "state/x/p.json",
        ".cursor/environment.json",
        ".github/workflows/po03-contracts.yml",
        ".github/workflows/po01-x.yml",
        "workstreams/po03/wave-a/units/wa-010/result/r.json",
        "workstreams/po03/wave-a/units/wa-010/README.md",
        "workstreams/po03/wave-a/units/wa-0100/z.json",
        "workstreams/po03/wave-a/units/wa-011/result/r.json",
        "workstreams/po03/control/path-ownership.json",
    )

    PATTERNS = (
        "a/**",
        "a/**/f.txt",
        "**/f.txt",
        "**",
        "a/*/f.txt",
        "a/*",
        "a/b*/f.txt",
        "a/?/f.txt",
        "a/b/c/*.jpg",
        "state/**",
        ".cursor/environment.json",
        ".github/workflows/po03-*.yml",
        "workstreams/po03/wave-a/units/wa-010/**",
        "workstreams/po03/wave-a/units/wa-01?/**",
        "workstreams/**/control/**",
        "workstreams/po03/**/r.json",
        "f.txt",
        "[ad]/**",
        "a/b/[cd]/g.jpg",
    )

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls._tmp.name) / "repo"
        cls.repo.mkdir()
        cls._git("init", "-q", ".")
        cls._git("config", "user.email", "po03@obzio.invalid")
        cls._git("config", "user.name", "PO-03 WA-010")
        cls._git("config", "core.ignorecase", "false")
        for relative in cls.FILES:
            target = cls.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")
        cls._git("add", "-A")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _git(cls, *args):
        return subprocess.run(
            ["git", "-C", str(cls.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def test_matcher_agrees_with_git_pathspec(self):
        tracked = sorted(
            line for line in self._git("ls-files").splitlines() if line.strip()
        )
        self.assertEqual(tracked, sorted(self.FILES))
        for pattern in self.PATTERNS:
            with self.subTest(pattern=pattern):
                expected = sorted(
                    line
                    for line in self._git("ls-files", "--", f":(glob){pattern}").splitlines()
                    if line.strip()
                )
                actual = sorted(path for path in tracked if PathGlob(pattern).matches(path))
                self.assertEqual(actual, expected)

    def test_git_confirms_a_grant_excludes_its_own_root_and_numeric_siblings(self):
        matched = self._git(
            "ls-files", "--", ":(glob)workstreams/po03/wave-a/units/wa-010/**"
        ).splitlines()
        self.assertIn("workstreams/po03/wave-a/units/wa-010/README.md", matched)
        self.assertNotIn("workstreams/po03/wave-a/units/wa-0100/z.json", matched)


if __name__ == "__main__":
    unittest.main()
