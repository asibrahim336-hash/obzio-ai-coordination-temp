"""Adversarial cases: attempts to obtain a write the grant does not authorise.

Each test states the evasion it models.  A permissive engine that merely compares
string prefixes, resolves traversal, folds case or trusts the caller's path
passes none of them.
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
REPO_ROOT = HERE.parents[5]
REGISTRY_PATH = REPO_ROOT / "workstreams/po03/control/path-ownership.json"
TASK_INPUT_PATH = REPO_ROOT / "workstreams/po03/control/inputs/wave-a/wa-010-a02.json"

sys.path.insert(0, str(HERE.parent / "engine"))

from gitglob import PathGlob  # noqa: E402
from ownership import (  # noqa: E402
    IMPLICIT_DENY_GLOBS,
    OwnershipEngine,
    Change,
)

GRANT = "workstreams/po03/wave-a/units/wa-010/**"
OWNER = "lease-po03-wa-010-a02"
FENCE = 2


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def composed_engine():
    return OwnershipEngine.from_registry_and_task_input(
        load_json(REGISTRY_PATH), load_json(TASK_INPUT_PATH)
    )


def decide(engine, path, status="ADD", old_path=None, fence=FENCE, owner=OWNER):
    report = engine.check_changes(
        owner, [Change(status=status, path=path, old_path=old_path)], declared_fence=fence
    )
    return report


class AdversarialPathFixtureTest(unittest.TestCase):
    def test_every_crafted_path_is_denied_for_its_preregistered_reason(self):
        fixture = json.loads(
            (FIXTURES / "changes-adversarial.json").read_text(encoding="utf-8")
        )
        engine = composed_engine()
        self.assertGreaterEqual(len(fixture["expected"]), 15)
        for expected in fixture["expected"]:
            with self.subTest(path=repr(expected["path"])):
                report = decide(engine, expected["path"], status="ADD")
                self.assertTrue(report.blocked, f"{expected['path']!r} was admitted")
                self.assertEqual(
                    report.decisions[0].reason, expected["reason"], report.decisions[0].detail
                )

    def test_no_crafted_path_is_silently_rewritten_into_an_admitted_path(self):
        """A denial must never be accompanied by a matched grant."""
        fixture = json.loads(
            (FIXTURES / "changes-adversarial.json").read_text(encoding="utf-8")
        )
        engine = composed_engine()
        for expected in fixture["expected"]:
            with self.subTest(path=repr(expected["path"])):
                report = decide(engine, expected["path"])
                self.assertNotEqual(report.decisions[0].matched_glob, GRANT)


class TraversalAndNormalisationTest(unittest.TestCase):
    def test_traversal_is_refused_rather_than_resolved(self):
        engine = composed_engine()
        escape = "workstreams/po03/wave-a/units/wa-010/../wa-011/result.json"
        report = decide(engine, escape)
        self.assertEqual(report.decisions[0].reason, "DENY_MALFORMED_PATH")
        resolved = "workstreams/po03/wave-a/units/wa-011/result.json"
        self.assertFalse(PathGlob(GRANT).matches(resolved))

    def test_traversal_that_would_resolve_back_inside_is_still_refused(self):
        engine = composed_engine()
        loop = "workstreams/po03/wave-a/units/wa-010/sub/../result.json"
        self.assertEqual(decide(engine, loop).decisions[0].reason, "DENY_MALFORMED_PATH")

    def test_deep_traversal_out_of_the_repository_is_refused(self):
        engine = composed_engine()
        for path in ("../../../etc/passwd", "workstreams/../../etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(
                    decide(engine, path).decisions[0].reason, "DENY_MALFORMED_PATH"
                )


class CaseAndUnicodeTest(unittest.TestCase):
    def test_case_variants_of_the_granted_directory_are_not_granted(self):
        engine = composed_engine()
        for segment in ("WA-010", "Wa-010", "wA-010"):
            path = f"workstreams/po03/wave-a/units/{segment}/result.json"
            with self.subTest(segment=segment):
                self.assertTrue(decide(engine, path).blocked)

    def test_case_variant_of_a_denied_prefix_does_not_evade_the_grant_check(self):
        """Uppercasing 'state' does not produce an owned path either."""
        engine = composed_engine()
        report = decide(engine, "State/pointer.json")
        self.assertTrue(report.blocked)
        self.assertEqual(report.decisions[0].reason, "DENY_UNOWNED_PATH")

    def test_decomposed_unicode_does_not_match_a_composed_grant(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": [],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["units/caf\u00e9/**"],
                    }
                ],
            }
        )
        composed = "units/caf\u00e9/a.json"
        decomposed = "units/cafe\u0301/a.json"
        self.assertFalse(
            engine.check_changes(
                "lease-t", [Change(status="ADD", path=composed)], declared_fence=1
            ).blocked
        )
        self.assertTrue(
            engine.check_changes(
                "lease-t", [Change(status="ADD", path=decomposed)], declared_fence=1
            ).blocked
        )

    def test_non_nfc_grant_is_flagged(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": [],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["units/cafe\u0301/**"],
                    }
                ],
            }
        )
        self.assertEqual(
            [finding.kind for finding in engine.detect_non_nfc_patterns()], ["NON_NFC_GRANT"]
        )


class WildcardInDataTest(unittest.TestCase):
    def test_metacharacters_in_a_changed_path_are_matched_literally(self):
        engine = composed_engine()
        for path in (
            "workstreams/po03/wave-a/units/wa-01?/result.json",
            "workstreams/po03/wave-a/units/wa-01*/result.json",
            "workstreams/po03/wave-a/units/wa-0[01]0/result.json",
            "workstreams/po03/wave-a/units/**/result.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(decide(engine, path).blocked, f"{path} was admitted")

    def test_a_literal_star_path_is_owned_only_by_an_escaped_grant(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": [],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["units/star\\*/**"],
                    }
                ],
            }
        )
        self.assertFalse(
            engine.check_changes(
                "lease-t", [Change(status="ADD", path="units/star*/a.json")], declared_fence=1
            ).blocked
        )
        self.assertTrue(
            engine.check_changes(
                "lease-t", [Change(status="ADD", path="units/starX/a.json")], declared_fence=1
            ).blocked
        )


class DenyPrecedenceTest(unittest.TestCase):
    def test_implicit_deny_survives_an_empty_registry_deny_list(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": [],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["**"],
                    }
                ],
            }
        )
        for path in (".git/config", "units/a/.git/hooks/pre-commit", ".gitmodules"):
            with self.subTest(path=path):
                report = engine.check_changes(
                    "lease-t", [Change(status="ADD", path=path)], declared_fence=1
                )
                self.assertTrue(report.blocked)
                self.assertEqual(report.decisions[0].reason, "DENY_PROHIBITED_PATH")

    def test_a_writer_granted_everything_still_cannot_reach_denied_paths(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": ["state/**", "dispatch/**"],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["**"],
                    }
                ],
            }
        )
        report = engine.check_changes(
            "lease-t",
            [
                Change(status="MODIFY", path="state/pointer.json"),
                Change(status="ADD", path="dispatch/queue.json"),
            ],
            declared_fence=1,
        )
        self.assertEqual(len(report.denials), 2)

    def test_a_grant_of_everything_collides_with_every_other_owner(self):
        document = json.loads(
            (FIXTURES / "registry-disjoint.json").read_text(encoding="utf-8")
        )
        document["subordinate_owners"].append(
            {
                "task_id": "GREEDY",
                "lease_id": "lease-greedy-a01",
                "fence_token": 1,
                "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                "owned_globs": ["**"],
            }
        )
        engine = OwnershipEngine.from_ownership_document(document)
        findings = engine.detect_grant_overlaps()
        self.assertTrue(findings)
        involved = {finding.right_owner for finding in findings} | {
            finding.left_owner for finding in findings
        }
        self.assertIn("lease-greedy-a01", involved)
        # One finding per colliding glob pair, so the controller's three grants
        # each produce their own, alongside the three single-grant subordinates.
        self.assertEqual(len(findings), 6)
        self.assertTrue(
            all("lease-greedy-a01" in (f.left_owner, f.right_owner) for f in findings)
        )

    def test_implicit_deny_globs_are_not_mutable_through_the_returned_tuple(self):
        engine = composed_engine()
        self.assertEqual(
            [glob.pattern for glob in engine.implicit_deny_globs], list(IMPLICIT_DENY_GLOBS)
        )
        self.assertIsInstance(engine.deny_globs, tuple)


class FenceEvasionTest(unittest.TestCase):
    def test_a_superseded_writer_cannot_commit_after_ownership_advances(self):
        engine = composed_engine()
        own = "workstreams/po03/wave-a/units/wa-010/result/result.json"
        self.assertTrue(decide(engine, own, fence=1).blocked)
        self.assertTrue(decide(engine, own, fence=0).blocked)
        self.assertFalse(decide(engine, own, fence=2).blocked)

    def test_a_non_integer_fence_is_refused(self):
        engine = composed_engine()
        for fence in ("2", 2.0, True):
            with self.subTest(fence=fence):
                report = engine.check_changes(
                    OWNER,
                    [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/x")],
                    declared_fence=fence,
                )
                self.assertTrue(report.blocked)

    def test_omitting_the_fence_does_not_grant_a_bypass_of_path_rules(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER,
            [Change(status="ADD", path="state/pointer.json")],
            declared_fence=None,
        )
        self.assertTrue(report.blocked)

    def test_owner_id_case_variants_are_not_the_owner(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER.upper(),
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/x")],
            declared_fence=2,
        )
        self.assertEqual(report.decisions[0].reason, "DENY_UNKNOWN_WRITER")


class ChangeStatusEvasionTest(unittest.TestCase):
    def test_an_unrecognised_status_cannot_smuggle_a_write(self):
        engine = composed_engine()
        for status in ("UNMERGED", "X", "", "allow"):
            with self.subTest(status=status):
                report = engine.check_changes(
                    OWNER,
                    [Change(status=status, path="workstreams/po03/wave-a/units/wa-011/x")],
                    declared_fence=2,
                )
                self.assertTrue(report.blocked)
                self.assertEqual(report.decisions[0].reason, "DENY_UNKNOWN_STATUS")

    def test_a_rename_without_a_source_is_refused(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER,
            [
                Change(
                    status="RENAME",
                    path="workstreams/po03/wave-a/units/wa-010/x",
                    old_path=None,
                )
            ],
            declared_fence=2,
        )
        self.assertEqual(report.decisions[0].reason, "DENY_MISSING_RENAME_SOURCE")

    def test_a_none_path_is_refused(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER, [Change(status="ADD", path=None)], declared_fence=2
        )
        self.assertTrue(report.blocked)
        self.assertEqual(report.decisions[0].reason, "DENY_MALFORMED_PATH")


class ReportIntegrityTest(unittest.TestCase):
    def test_every_checked_side_appears_in_the_report(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER,
            [
                Change(
                    status="RENAME",
                    old_path="workstreams/po03/wave-a/units/wa-011/a",
                    path="state/b",
                )
            ],
            declared_fence=2,
        )
        self.assertEqual(len(report.decisions), 2)
        self.assertEqual(len(report.denials), 2)

    def test_report_serialises_to_json_without_loss(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER,
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-011/x")],
            declared_fence=2,
        )
        payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["outcome"], "BLOCKED")
        self.assertEqual(payload["denied_sides"], 1)

    def test_a_control_character_path_serialises_safely(self):
        engine = composed_engine()
        report = engine.check_changes(
            OWNER,
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/a\nb")],
            declared_fence=2,
        )
        payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
        self.assertEqual(payload["decisions"][0]["reason"], "DENY_MALFORMED_PATH")


class ScaleTest(unittest.TestCase):
    def test_the_real_registry_audit_stays_tractable(self):
        engine = OwnershipEngine.from_ownership_document(load_json(REGISTRY_PATH))
        self.assertGreaterEqual(len(engine.owners), 60)
        self.assertEqual(engine.detect_grant_overlaps(), [])

    def test_a_deeply_nested_path_is_decided_without_blowing_up(self):
        engine = composed_engine()
        deep = "workstreams/po03/wave-a/units/wa-010/" + "/".join(["a"] * 200) + "/x.json"
        self.assertFalse(decide(engine, deep).blocked)
        outside = "workstreams/po03/wave-a/units/wa-011/" + "/".join(["a"] * 200) + "/x.json"
        self.assertTrue(decide(engine, outside).blocked)

    def test_a_long_segment_is_decided_without_blowing_up(self):
        engine = composed_engine()
        long_name = "z" * 4000
        self.assertFalse(
            decide(engine, f"workstreams/po03/wave-a/units/wa-010/{long_name}.json").blocked
        )


if __name__ == "__main__":
    unittest.main()
