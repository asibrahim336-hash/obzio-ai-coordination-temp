"""Focused tests for changed-path ownership admission and static overlap detection."""

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

from ownership import (  # noqa: E402
    ALLOW,
    DENY,
    OwnershipDocumentError,
    OwnershipEngine,
    REASON_ALLOWED,
    REASON_FENCE_AHEAD,
    REASON_SHARED_WORKTREE,
    REASON_STALE_FENCE,
    REASON_UNKNOWN_WRITER,
    Change,
    changes_from_document,
    main,
    parse_name_status_z,
)


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def composed_engine():
    return OwnershipEngine.from_registry_and_task_input(
        load_json(REGISTRY_PATH),
        load_json(TASK_INPUT_PATH),
        source_document=f"{REGISTRY_PATH}+{TASK_INPUT_PATH}",
    )


class StaticOverlapTest(unittest.TestCase):
    def test_disjoint_registry_reports_no_blocking_finding(self):
        engine = OwnershipEngine.from_ownership_document(load_fixture("registry-disjoint.json"))
        self.assertEqual(engine.detect_grant_overlaps(), [])
        self.assertEqual(engine.blocking_findings(), [])

    def test_overlapping_registry_reports_exactly_the_preregistered_pairs(self):
        fixture = load_fixture("registry-overlapping.json")
        engine = OwnershipEngine.from_ownership_document(fixture)
        findings = engine.detect_grant_overlaps()
        observed = {frozenset((f.left_owner, f.right_owner)) for f in findings}
        expected = {frozenset(pair) for pair in fixture["expected_overlap_pairs"]}
        self.assertEqual(observed, expected)
        self.assertEqual(len(findings), len(expected))

    def test_every_overlap_finding_carries_a_verifiable_witness(self):
        engine = OwnershipEngine.from_ownership_document(load_fixture("registry-overlapping.json"))
        findings = engine.detect_grant_overlaps()
        self.assertTrue(findings)
        for finding in findings:
            with self.subTest(witness=finding.witness_path):
                self.assertIsNotNone(finding.witness_path)
                left = next(
                    glob
                    for owner in engine.owners
                    if owner.owner_id == finding.left_owner
                    for glob in owner.owned_globs
                    if glob.pattern == finding.left_glob
                )
                right = next(
                    glob
                    for owner in engine.owners
                    if owner.owner_id == finding.right_owner
                    for glob in owner.owned_globs
                    if glob.pattern == finding.right_glob
                )
                self.assertTrue(left.matches(finding.witness_path))
                self.assertTrue(right.matches(finding.witness_path))

    def test_overlap_is_detected_before_any_path_exists(self):
        """The witness names a path that is absent from the working tree."""
        engine = OwnershipEngine.from_ownership_document(load_fixture("registry-overlapping.json"))
        findings = engine.detect_grant_overlaps()
        self.assertTrue(findings)
        for finding in findings:
            self.assertFalse((REPO_ROOT / finding.witness_path).exists())

    def test_seeded_po03_registry_is_disjoint(self):
        engine = OwnershipEngine.from_ownership_document(load_json(REGISTRY_PATH))
        self.assertEqual(engine.detect_grant_overlaps(), [])

    def test_seeded_registry_agrees_with_the_immutable_task_input(self):
        self.assertEqual(composed_engine().detect_grant_divergence(), [])

    def test_grant_divergence_is_a_blocking_finding(self):
        task_input = load_json(TASK_INPUT_PATH)
        task_input["ownership"]["allowed_write_globs"] = [
            "workstreams/po03/wave-a/units/wa-010/result/**"
        ]
        engine = OwnershipEngine.from_registry_and_task_input(load_json(REGISTRY_PATH), task_input)
        findings = engine.detect_grant_divergence()
        self.assertEqual([f.kind for f in findings], ["GRANT_DIVERGENCE"])
        self.assertEqual(findings[0].severity, "ERROR")
        self.assertIn(findings[0], engine.blocking_findings())

    def test_deny_shadowed_grant_is_advisory_not_blocking(self):
        document = load_fixture("registry-disjoint.json")
        document["subordinate_owners"][0]["owned_globs"].append("state/wa-010/**")
        engine = OwnershipEngine.from_ownership_document(document)
        kinds = {finding.kind for finding in engine.audit()}
        self.assertIn("DENY_SHADOWED_GRANT", kinds)
        self.assertEqual(engine.blocking_findings(), [])

    def test_implicit_deny_globs_do_not_raise_a_shadow_advisory(self):
        """A recursive grant always intersects '**/.git/**', which says nothing."""
        engine = OwnershipEngine.from_ownership_document(load_fixture("registry-disjoint.json"))
        self.assertEqual(engine.detect_shadowed_grants(), [])
        implicit = [glob for glob in engine.implicit_deny_globs if glob.pattern == "**/.git/**"]
        self.assertTrue(implicit)
        grant = engine.owners[-1].owned_globs[0]
        self.assertIsNotNone(grant.intersection_witness(implicit[0]))

    def test_the_seeded_registry_raises_no_shadow_advisory(self):
        engine = composed_engine()
        self.assertEqual(engine.detect_shadowed_grants(), [])
        self.assertEqual(engine.audit(), [])

    def test_a_bare_deny_glob_is_flagged_as_too_narrow(self):
        document = load_fixture("registry-disjoint.json")
        document["global_deny_globs"].append("secrets.json")
        engine = OwnershipEngine.from_ownership_document(document)
        findings = engine.detect_narrow_deny_patterns()
        self.assertEqual([finding.kind for finding in findings], ["NARROW_DENY_PATTERN"])
        self.assertIn("**/secrets.json", findings[0].detail)
        self.assertEqual(engine.blocking_findings(), [])

    def test_the_narrow_deny_reading_is_the_one_that_is_flagged(self):
        """The advisory describes real behaviour: the bare pattern misses subdirectories."""
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["control/**"]},
                "global_deny_globs": ["secrets.json"],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["units/**"],
                    }
                ],
            }
        )
        nested = engine.check_changes(
            "lease-t", [Change(status="ADD", path="units/a/secrets.json")], declared_fence=1
        )
        self.assertFalse(nested.blocked)
        self.assertTrue(engine.detect_narrow_deny_patterns())

    def test_deny_globs_with_a_separator_are_not_flagged(self):
        engine = composed_engine()
        self.assertEqual(engine.detect_narrow_deny_patterns(), [])

    def test_case_only_difference_is_reported_as_an_advisory_collision(self):
        document = load_fixture("registry-disjoint.json")
        document["subordinate_owners"][1]["owned_globs"] = [
            "workstreams/po03/wave-a/units/WA-010/**"
        ]
        engine = OwnershipEngine.from_ownership_document(document)
        collisions = engine.detect_case_insensitive_collisions()
        self.assertTrue(collisions)
        self.assertEqual(engine.detect_grant_overlaps(), [])
        self.assertEqual({finding.severity for finding in collisions}, {"ADVISORY"})

    def test_redundant_self_grant_is_reported(self):
        document = load_fixture("registry-disjoint.json")
        document["subordinate_owners"][0]["owned_globs"].append(
            "workstreams/po03/wave-a/units/wa-010/result/**"
        )
        engine = OwnershipEngine.from_ownership_document(document)
        kinds = [finding.kind for finding in engine.detect_self_overlaps()]
        self.assertEqual(kinds, ["REDUNDANT_SELF_GRANT"])


class AdmittedChangeTest(unittest.TestCase):
    def test_every_change_inside_the_grant_is_admitted(self):
        fixture = load_fixture("changes-admitted.json")
        engine = composed_engine()
        report = engine.check_changes(
            fixture["writer"],
            changes_from_document(fixture),
            declared_fence=fixture["fence_token"],
        )
        self.assertEqual(report.outcome, fixture["expected_outcome"])
        self.assertEqual(report.denials, [])
        self.assertEqual(set(report.reason_counts()), {REASON_ALLOWED})

    def test_rename_inside_the_grant_checks_both_sides(self):
        engine = composed_engine()
        change = Change(
            status="RENAME",
            old_path="workstreams/po03/wave-a/units/wa-010/a.json",
            path="workstreams/po03/wave-a/units/wa-010/b.json",
        )
        report = engine.check_changes("lease-po03-wa-010-a02", [change], declared_fence=2)
        self.assertEqual([d.side for d in report.decisions], ["source", "target"])
        self.assertTrue(all(d.allowed for d in report.decisions))


class ProhibitedChangeTest(unittest.TestCase):
    def test_each_prohibited_write_is_denied_for_the_preregistered_reason(self):
        fixture = load_fixture("changes-prohibited.json")
        engine = composed_engine()
        for expected in fixture["expected"]:
            with self.subTest(path=expected["path"]):
                change = Change(status="ADD" if expected["status"] == "A" else "MODIFY",
                                path=expected["path"])
                report = engine.check_changes(
                    fixture["writer"], [change], declared_fence=fixture["fence_token"]
                )
                self.assertEqual(report.outcome, "BLOCKED")
                self.assertEqual(len(report.decisions), 1)
                decision = report.decisions[0]
                self.assertEqual(decision.decision, DENY)
                self.assertEqual(decision.reason, expected["reason"], decision.detail)

    def test_the_whole_prohibited_set_blocks_in_one_pass(self):
        fixture = load_fixture("changes-prohibited.json")
        engine = composed_engine()
        changes = [
            Change(status="ADD" if entry["status"] == "A" else "MODIFY", path=entry["path"])
            for entry in fixture["expected"]
        ]
        report = engine.check_changes(fixture["writer"], changes, declared_fence=2)
        self.assertTrue(report.blocked)
        self.assertEqual(len(report.denials), len(changes))
        self.assertNotIn(REASON_ALLOWED, report.reason_counts())

    def test_one_prohibited_path_blocks_an_otherwise_clean_batch(self):
        engine = composed_engine()
        changes = [
            Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/result/result.json"),
            Change(status="MODIFY", path="state/ACTIVE_CONTROL_POINTER_CURRENT.json"),
        ]
        report = engine.check_changes("lease-po03-wa-010-a02", changes, declared_fence=2)
        self.assertTrue(report.blocked)
        self.assertEqual(len(report.denials), 1)

    def test_deny_outranks_the_writer_s_own_grant(self):
        engine = OwnershipEngine.from_ownership_document(
            {
                "controller": {"branch": "c", "run_id": "r", "owned_globs": ["controller/**"]},
                "global_deny_globs": ["owned/secret/**"],
                "subordinate_owners": [
                    {
                        "task_id": "T",
                        "lease_id": "lease-t",
                        "fence_token": 1,
                        "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                        "owned_globs": ["owned/**"],
                    }
                ],
            }
        )
        report = engine.check_changes(
            "lease-t", [Change(status="ADD", path="owned/secret/key.pem")], declared_fence=1
        )
        self.assertTrue(report.blocked)
        self.assertEqual(report.decisions[0].reason, "DENY_PROHIBITED_PATH")
        self.assertEqual(report.decisions[0].matched_glob, "owned/secret/**")


class RenameAndDeleteTest(unittest.TestCase):
    def test_each_case_matches_its_preregistered_side_reasons(self):
        fixture = load_fixture("changes-rename-and-delete.json")
        engine = composed_engine()
        for case in fixture["expected"]:
            with self.subTest(case=case["case"]):
                status = {"R": "RENAME", "D": "DELETE", "C": "COPY"}[case["status"]]
                change = Change(
                    status=status, path=case.get("path"), old_path=case.get("old_path")
                )
                report = engine.check_changes(
                    fixture["writer"], [change], declared_fence=fixture["fence_token"]
                )
                by_side = {decision.side: decision for decision in report.decisions}
                for side in ("source", "target"):
                    expected_reason = case[f"{side}_reason"]
                    if expected_reason is None:
                        self.assertNotIn(side, by_side, f"{side} should not be checked")
                        continue
                    self.assertIn(side, by_side, f"{side} should be checked")
                    self.assertEqual(by_side[side].reason, expected_reason, by_side[side].detail)

    def test_at_least_one_rename_case_is_blocked_and_one_admitted(self):
        fixture = load_fixture("changes-rename-and-delete.json")
        reasons = {
            case[f"{side}_reason"]
            for case in fixture["expected"]
            for side in ("source", "target")
            if case[f"{side}_reason"] is not None
        }
        self.assertIn(REASON_ALLOWED, reasons)
        self.assertTrue({reason for reason in reasons if reason.startswith("DENY_")})

    def test_delete_of_an_unowned_path_uses_the_delete_reason(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-010-a02",
            [Change(status="DELETE", path="workstreams/po03/wave-a/units/wa-011/result.json")],
            declared_fence=2,
        )
        self.assertEqual(report.decisions[0].reason, "DENY_DELETE_NOT_OWNED")
        self.assertEqual(report.decisions[0].side, "source")

    def test_copy_does_not_require_source_ownership(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-010-a02",
            [
                Change(
                    status="COPY",
                    old_path="workstreams/po03/COMMISSION.md",
                    path="workstreams/po03/wave-a/units/wa-010/copy.md",
                )
            ],
            declared_fence=2,
        )
        self.assertEqual([d.side for d in report.decisions], ["target"])
        self.assertFalse(report.blocked)


class FenceAndWriterTest(unittest.TestCase):
    def test_stale_fence_is_refused_even_inside_the_writer_s_own_subtree(self):
        engine = composed_engine()
        own_path = "workstreams/po03/wave-a/units/wa-010/result/result.json"
        report = engine.check_changes(
            "lease-po03-wa-010-a02", [Change(status="ADD", path=own_path)], declared_fence=1
        )
        self.assertTrue(report.blocked)
        self.assertEqual(report.decisions[0].reason, REASON_STALE_FENCE)

    def test_current_fence_is_admitted(self):
        engine = composed_engine()
        own_path = "workstreams/po03/wave-a/units/wa-010/result/result.json"
        report = engine.check_changes(
            "lease-po03-wa-010-a02", [Change(status="ADD", path=own_path)], declared_fence=2
        )
        self.assertFalse(report.blocked)

    def test_fence_ahead_of_the_registry_is_refused(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-010-a02",
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/x")],
            declared_fence=3,
        )
        self.assertEqual(report.decisions[0].reason, REASON_FENCE_AHEAD)

    def test_unregistered_writer_is_refused_for_every_change(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-999-a01",
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/x")],
            declared_fence=1,
        )
        self.assertEqual(report.decisions[0].reason, REASON_UNKNOWN_WRITER)

    def test_unregistered_writer_with_no_changes_still_reports_a_denial(self):
        engine = composed_engine()
        report = engine.check_changes("nobody", [], declared_fence=1)
        self.assertTrue(report.blocked)

    def test_shared_worktree_is_refused_when_isolation_is_required(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-010-a02",
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-010/x")],
            declared_fence=2,
            isolated_worktree=False,
        )
        self.assertEqual(report.decisions[0].reason, REASON_SHARED_WORKTREE)

    def test_foreign_owner_is_named_in_the_denial(self):
        engine = composed_engine()
        report = engine.check_changes(
            "lease-po03-wa-010-a02",
            [Change(status="ADD", path="workstreams/po03/wave-a/units/wa-011/result/result.json")],
            declared_fence=2,
        )
        decision = report.decisions[0]
        self.assertEqual(decision.reason, "DENY_FOREIGN_OWNER")
        self.assertEqual(decision.conflicting_owner, "lease-po03-wa-011-a02")


class GitParsingTest(unittest.TestCase):
    def test_name_status_z_covers_every_supported_status(self):
        payload = (
            b"A\x00added.txt\x00"
            b"M\x00modified.txt\x00"
            b"D\x00deleted.txt\x00"
            b"T\x00typechanged.txt\x00"
            b"R096\x00old.txt\x00new.txt\x00"
            b"C075\x00src.txt\x00dst.txt\x00"
        )
        changes = parse_name_status_z(payload)
        self.assertEqual(
            [(c.status, c.path, c.old_path) for c in changes],
            [
                ("ADD", "added.txt", None),
                ("MODIFY", "modified.txt", None),
                ("DELETE", "deleted.txt", None),
                ("TYPECHANGE", "typechanged.txt", None),
                ("RENAME", "new.txt", "old.txt"),
                ("COPY", "dst.txt", "src.txt"),
            ],
        )
        self.assertEqual(changes[4].similarity, 96)

    def test_paths_with_spaces_and_tabs_survive_nul_parsing(self):
        payload = b"A\x00dir/a b\tc.txt\x00"
        self.assertEqual(parse_name_status_z(payload)[0].path, "dir/a b\tc.txt")

    def test_unmerged_status_is_refused(self):
        with self.assertRaises(ValueError):
            parse_name_status_z(b"U\x00conflict.txt\x00")

    def test_truncated_rename_record_is_refused(self):
        with self.assertRaises(ValueError):
            parse_name_status_z(b"R100\x00only-one-path\x00")


class DocumentValidationTest(unittest.TestCase):
    def test_duplicate_owner_ids_are_refused(self):
        document = load_fixture("registry-disjoint.json")
        document["subordinate_owners"][1]["lease_id"] = document["subordinate_owners"][0][
            "lease_id"
        ]
        with self.assertRaises(OwnershipDocumentError):
            OwnershipEngine.from_ownership_document(document)

    def test_missing_or_bad_fence_token_is_refused(self):
        for value in (None, 0, "2", True):
            with self.subTest(value=value):
                document = load_fixture("registry-disjoint.json")
                document["subordinate_owners"][0]["fence_token"] = value
                with self.assertRaises(OwnershipDocumentError):
                    OwnershipEngine.from_ownership_document(document)

    def test_empty_owned_globs_are_refused(self):
        document = load_fixture("registry-disjoint.json")
        document["subordinate_owners"][0]["owned_globs"] = []
        with self.assertRaises(OwnershipDocumentError):
            OwnershipEngine.from_ownership_document(document)

    def test_task_input_view_carries_the_declared_grant(self):
        engine = OwnershipEngine.from_task_input(load_json(TASK_INPUT_PATH))
        self.assertEqual(len(engine.owners), 1)
        self.assertEqual(engine.owners[0].owner_id, "lease-po03-wa-010-a02")
        self.assertEqual(engine.owners[0].fence_token, 2)
        self.assertEqual(
            [glob.pattern for glob in engine.owners[0].owned_globs],
            ["workstreams/po03/wave-a/units/wa-010/**"],
        )

    def test_task_input_without_a_registry_grant_is_refused(self):
        task_input = load_json(TASK_INPUT_PATH)
        task_input["attempt"]["lease_id"] = "lease-po03-wa-nonexistent-a01"
        with self.assertRaises(OwnershipDocumentError):
            OwnershipEngine.from_registry_and_task_input(load_json(REGISTRY_PATH), task_input)


class CliTest(unittest.TestCase):
    def test_audit_exits_zero_for_a_disjoint_registry(self):
        out = HERE / "_cli-audit-clean.json"
        try:
            code = main(
                ["audit", str(FIXTURES / "registry-disjoint.json"), "--out", str(out)]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["outcome"], "DISJOINT")
            self.assertEqual(payload["blocking_count"], 0)
        finally:
            out.unlink(missing_ok=True)

    def test_audit_exits_nonzero_for_an_overlapping_registry(self):
        out = HERE / "_cli-audit-overlap.json"
        try:
            code = main(
                ["audit", str(FIXTURES / "registry-overlapping.json"), "--out", str(out)]
            )
            self.assertEqual(code, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["outcome"], "OVERLAP_DETECTED")
            self.assertGreater(payload["blocking_count"], 0)
        finally:
            out.unlink(missing_ok=True)

    def test_check_exits_nonzero_for_a_prohibited_change_set(self):
        changes = HERE / "_cli-changes.json"
        out = HERE / "_cli-check.json"
        try:
            fixture = load_fixture("changes-prohibited.json")
            changes.write_text(
                json.dumps(
                    {
                        "changes": [
                            {"status": entry["status"], "path": entry["path"]}
                            for entry in fixture["expected"]
                        ]
                    }
                ),
                encoding="utf-8",
            )
            code = main(
                [
                    "check",
                    str(REGISTRY_PATH),
                    "--task-input",
                    str(TASK_INPUT_PATH),
                    "--owner",
                    "lease-po03-wa-010-a02",
                    "--fence",
                    "2",
                    "--changes",
                    str(changes),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 1)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["outcome"], "BLOCKED")
        finally:
            changes.unlink(missing_ok=True)
            out.unlink(missing_ok=True)

    def test_check_exits_zero_for_an_admitted_change_set(self):
        out = HERE / "_cli-check-ok.json"
        try:
            code = main(
                [
                    "check",
                    str(REGISTRY_PATH),
                    "--task-input",
                    str(TASK_INPUT_PATH),
                    "--owner",
                    "lease-po03-wa-010-a02",
                    "--fence",
                    "2",
                    "--changes",
                    str(FIXTURES / "changes-admitted.json"),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["report"]["outcome"], "ADMITTED")
        finally:
            out.unlink(missing_ok=True)

    def test_unreadable_document_exits_two(self):
        self.assertEqual(main(["audit", str(HERE / "does-not-exist.json")]), 2)


if __name__ == "__main__":
    unittest.main()
