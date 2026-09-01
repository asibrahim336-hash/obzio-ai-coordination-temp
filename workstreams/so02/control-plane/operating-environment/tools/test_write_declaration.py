"""Failure injections for the write declaration.

Every test here answers one question: does the guard refuse a write because the
write was not declared and reasoned, rather than because its target appeared on
a list? The suite deliberately targets `main` in the admissible cases, because
under the founder's standing amendment of 2026-08-23 `main` is an ordinary
target and a guard that treats it otherwise has reintroduced the void category.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registering before exec_module is required: dataclasses resolves annotations
    # through sys.modules and raises AttributeError on an unregistered module.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wd = _load("write_declaration")


#: A declaration that passes every gate. Its target is `main` on purpose.
ADMISSIBLE = {
    "declaration_version": "1.0",
    "declaration_id": "WD-TEST-0001",
    "declared_by": "OE-W9-REASON-GATED-WRITES",
    "declared_at": "2026-08-23T04:00:00Z",
    "target": {
        "ref": "main",
        "paths": ["workstreams/so02/control-plane/operating-environment/tools/**"],
        "operation": "COMMIT_AND_PUSH",
    },
    "reason": {
        "code": "INTEGRATE_RETURNED_LANE",
        "statement": (
            "Lane OE-W9 returned and was accepted; integrating its head onto main so the "
            "reason-gated write guard is the version the estate runs."
        ),
        "lane_id": "OE-W9-REASON-GATED-WRITES",
        "lane_branch": "cursor/oe-w9-reason-gated-writes-696d",
        "lane_head_sha": "a" * 40,
    },
    "reversal": {
        "method": "RESTORE_REF_TO_RECORDED_SHA",
        "recorded_sha": "b" * 40,
        "custody_ref": "refs/tags/pre-write/main-20260823T0400Z",
        "command": ["git", "push", "--force-with-lease", "origin", f"{'b' * 40}:refs/heads/main"],
    },
    "evidence": {
        "asserts_result": True,
        "kind": "READBACK",
        "record": {"immutable_commit": "a" * 40, "result": "REMOTE_BYTE_FOR_BYTE_IDENTICAL"},
    },
    "concurrency": {
        "observed_at": "2026-08-23T03:59:30Z",
        "agents": [{"bcId": "bc-1", "branchName": "cursor/other", "status": "IDLE"}],
    },
}


def variant(**overrides):
    """A copy of the admissible declaration with one thing wrong."""
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


def codes(declaration, ratified=()):
    return {f.code for f in wd.validate_declaration(declaration, ratified)}


def blocking_codes(declaration, ratified=()):
    return {f.code for f in wd.blocking_findings(wd.validate_declaration(declaration, ratified))}


class AdmissibleBaselineTests(unittest.TestCase):
    def test_a_fully_declared_write_to_main_is_admissible(self) -> None:
        """The founder: 'Every surface [...] is writable under my authority.'"""
        findings = wd.validate_declaration(ADMISSIBLE)
        self.assertTrue(
            wd.is_admissible(findings),
            f"blocking findings on a well-formed declaration: {[f.code for f in wd.blocking_findings(findings)]}",
        )

    def test_the_target_name_never_changes_the_verdict(self) -> None:
        """No surface is off-limits because of a name on a list."""
        for ref in ("main", "cursor/po03-wave-a-factory-6e19", "so02/strategic-control-plane-migration-20260822-v001",
                    "cursor/scratch", "po03/repository-engineering-portable-runtime-20260822-v001"):
            declaration = copy.deepcopy(ADMISSIBLE)
            declaration["target"]["ref"] = ref
            declaration["reason"]["statement"] = f"Integrating the accepted OE-W9 head onto {ref} after acceptance."
            declaration["reversal"]["command"] = ["git", "push", "--force-with-lease", "origin", f"{'b' * 40}:refs/heads/{ref}"]
            self.assertTrue(wd.is_admissible(wd.validate_declaration(declaration)), ref)

    def test_no_module_level_list_of_forbidden_targets_exists(self) -> None:
        """A shorter denylist would mean the instruction was missed entirely."""
        source = (Path(__file__).resolve().parent / "write_declaration.py").read_text(encoding="utf-8")
        for retired in ("PROTECTED_REFS", "PROTECTED_PREFIXES", "protected_branch_globs", "guard_ref_is_protected"):
            self.assertNotIn(retired, source, f"{retired} reintroduces the voided category")


class UndeclaredWriteTests(unittest.TestCase):
    """Injection 1: an undeclared write."""

    def test_no_declaration_at_all_is_refused(self) -> None:
        for undeclared in ({}, None, "", [], 0):
            found = blocking_codes(undeclared)
            self.assertIn("NO_DECLARATION", found, repr(undeclared))

    def test_the_refusal_cites_founder_authority_not_a_target_list(self) -> None:
        finding = next(f for f in wd.validate_declaration({}) if f.code == "NO_DECLARATION")
        self.assertEqual(wd.FOUNDER_AUTHORED, finding.provenance)
        self.assertIn("declared and reasoned", finding.basis)

    def test_a_declaration_missing_its_target_is_refused(self) -> None:
        self.assertIn("TARGET_MISSING", blocking_codes(variant(target=_DELETE)))

    def test_an_operation_outside_the_vocabulary_is_refused(self) -> None:
        self.assertIn("OPERATION_NOT_IN_VOCABULARY", blocking_codes(variant(**{"target.operation": "SQUASH_EVERYTHING"})))


class VacuousReasonTests(unittest.TestCase):
    """Injection 2: an empty or vacuous reason."""

    def test_a_missing_reason_is_refused(self) -> None:
        self.assertIn("REASON_MISSING", blocking_codes(variant(reason=_DELETE)))

    def test_an_empty_statement_is_refused(self) -> None:
        for empty in ("", "   ", "\n\t "):
            self.assertIn("REASON_STATEMENT_EMPTY", blocking_codes(variant(**{"reason.statement": empty})), repr(empty))

    def test_a_reason_code_outside_the_closed_vocabulary_is_refused(self) -> None:
        for code in ("BECAUSE_I_SAID_SO", "OTHER", "", None, 42):
            self.assertIn("REASON_CODE_NOT_IN_VOCABULARY", blocking_codes(variant(**{"reason.code": code})), repr(code))

    def test_a_reason_whose_obligations_are_unmet_is_refused(self) -> None:
        """A closed vocabulary alone only shortens the list of strings that always pass."""
        for missing in ("lane_id", "lane_branch", "lane_head_sha"):
            found = blocking_codes(variant(**{f"reason.{missing}": _DELETE}))
            self.assertIn("REASON_OBLIGATIONS_UNMET", found, missing)

    def test_a_portable_reason_that_names_no_target_is_refused(self) -> None:
        """A statement equally true of every write distinguishes none of them."""
        for portable in (
            "Applying the change as instructed by the commission.",
            "This write is necessary and has been reviewed for correctness by the lane.",
            "Routine synchronisation of the repository with its intended state.",
        ):
            found = blocking_codes(variant(**{"reason.statement": portable}))
            self.assertIn("REASON_NOT_ANCHORED_TO_TARGET", found, portable)

    def test_anchoring_to_a_declared_path_also_satisfies_the_test(self) -> None:
        anchored = variant(**{
            "reason.statement": (
                "Publishing the guard under "
                "workstreams/so02/control-plane/operating-environment/tools/** after acceptance."
            )
        })
        self.assertNotIn("REASON_NOT_ANCHORED_TO_TARGET", blocking_codes(anchored))


class EvidenceGateTests(unittest.TestCase):
    """Injection 6: a result-asserting write with no evidence."""

    def test_a_result_asserting_write_with_no_evidence_is_refused(self) -> None:
        self.assertIn("EVIDENCE_MISSING", blocking_codes(variant(evidence=_DELETE)))

    def test_the_reason_code_decides_whether_a_result_is_asserted(self) -> None:
        """A write must not be able to self-certify that it asserts nothing."""
        sneaky = variant(**{"evidence.asserts_result": False})
        del sneaky["evidence"]["kind"]
        del sneaky["evidence"]["record"]
        self.assertIn("EVIDENCE_KIND_NOT_IN_VOCABULARY", blocking_codes(sneaky))

    def test_an_evidence_kind_outside_the_vocabulary_is_refused(self) -> None:
        self.assertIn("EVIDENCE_KIND_NOT_IN_VOCABULARY", blocking_codes(variant(**{"evidence.kind": "TRUST_ME"})))

    def test_a_declared_evidence_kind_with_no_record_is_refused(self) -> None:
        self.assertIn("EVIDENCE_RECORD_MISSING", blocking_codes(variant(**{"evidence.record": {}})))

    def test_a_reason_that_asserts_no_result_needs_no_evidence(self) -> None:
        """The gate expires with its reason; it is not a universal tax."""
        no_result = variant(**{
            "reason.code": "PUBLISH_LANE_DELIVERABLE",
            "reason.statement": "Publishing lane OE-W9's own commissioned output onto main.",
            "reason.commission_id": "COM-CUR-ENV-01-20260822-v001",
            "evidence": _DELETE,
        })
        self.assertNotIn("EVIDENCE_MISSING", blocking_codes(no_result))


class ReversalDeclarationTests(unittest.TestCase):
    """Injection 3: a write with no reversal."""

    def test_a_missing_reversal_is_refused(self) -> None:
        self.assertIn("REVERSAL_MISSING", blocking_codes(variant(reversal=_DELETE)))

    def test_a_reversal_method_outside_the_vocabulary_is_refused(self) -> None:
        self.assertIn("REVERSAL_METHOD_NOT_IN_VOCABULARY",
                      blocking_codes(variant(**{"reversal.method": "JUST_FIX_IT_AFTERWARDS"})))

    def test_a_reversal_with_no_custody_artifact_is_refused(self) -> None:
        for missing in ("recorded_sha", "custody_ref"):
            self.assertIn("REVERSAL_CUSTODY_MISSING", blocking_codes(variant(**{f"reversal.{missing}": _DELETE})), missing)

    def test_a_prose_reversal_is_refused(self) -> None:
        """Prose cannot be rehearsed, so it is never tested before it is needed."""
        for prose in ("restore the branch from the tag", "", None, ["git"] and "git push"):
            self.assertIn("REVERSAL_COMMAND_MISSING", blocking_codes(variant(**{"reversal.command": prose})), repr(prose))

    def test_an_abbreviated_recorded_sha_is_refused(self) -> None:
        self.assertIn("REVERSAL_RECORDED_SHA_MALFORMED", blocking_codes(variant(**{"reversal.recorded_sha": "b" * 7})))


class ConcurrencyDeclarationShapeTests(unittest.TestCase):
    def test_a_declaration_with_no_concurrency_observation_is_refused(self) -> None:
        self.assertIn("CONCURRENCY_OBSERVATION_MISSING", blocking_codes(variant(concurrency=_DELETE)))

    def test_an_untimed_observation_is_refused(self) -> None:
        self.assertIn("CONCURRENCY_OBSERVATION_UNTIMED", blocking_codes(variant(**{"concurrency.observed_at": _DELETE})))

    def test_an_asserted_rather_than_observed_idleness_is_refused(self) -> None:
        """Omitting the agent list asserts idleness instead of observing it."""
        self.assertIn("CONCURRENCY_OBSERVATION_EMPTY", blocking_codes(variant(**{"concurrency.agents": _DELETE})))

    def test_an_empty_agent_list_is_a_real_observation(self) -> None:
        self.assertNotIn("CONCURRENCY_OBSERVATION_EMPTY", blocking_codes(variant(**{"concurrency.agents": []})))


class ProvenanceEnforcementTests(unittest.TestCase):
    """The founder: 'An unclassified constraint is not in force.'"""

    def test_every_finding_carries_a_provenance_class_and_a_basis(self) -> None:
        seen = 0
        for broken in ({}, variant(reason=_DELETE), variant(reversal=_DELETE), variant(evidence=_DELETE),
                       variant(**{"reason.statement": "as instructed"}), variant(**{"target.operation": "X"})):
            for finding in wd.validate_declaration(broken):
                seen += 1
                self.assertIn(finding.provenance, {wd.FOUNDER_AUTHORED, wd.EARNED, wd.ASSISTANT_AUTHORED})
                self.assertTrue(finding.basis.strip(), f"{finding.code} has no basis")
        self.assertGreater(seen, 0)

    def test_founder_findings_quote_him_verbatim(self) -> None:
        for finding in wd.validate_declaration(variant(reversal=_DELETE)):
            if finding.provenance == wd.FOUNDER_AUTHORED:
                self.assertIn("Ahmed Sadek", finding.basis)
                self.assertIn('"', finding.basis)

    def test_assistant_authored_checks_never_refuse_a_write(self) -> None:
        """Void unless he ratifies it — so it is reported, and it does not block."""
        terse = variant(**{"reason.statement": "main cleanup"})
        found = codes(terse)
        self.assertIn("REASON_READS_AS_BOILERPLATE", found)
        self.assertIn("REASON_STATEMENT_TERSE", found)
        blocking = blocking_codes(terse)
        self.assertNotIn("REASON_READS_AS_BOILERPLATE", blocking)
        self.assertNotIn("REASON_STATEMENT_TERSE", blocking)

    def test_ratification_is_an_explicit_act_that_makes_a_check_binding(self) -> None:
        terse = variant(**{"reason.statement": "main cleanup"})
        self.assertNotIn("REASON_STATEMENT_TERSE", blocking_codes(terse))
        ratified = blocking_codes(terse, ratified=["REASON_STATEMENT_TERSE"])
        self.assertIn("REASON_STATEMENT_TERSE", ratified)
        self.assertNotIn("REASON_READS_AS_BOILERPLATE", ratified)

    def test_only_founder_and_earned_classes_can_block(self) -> None:
        self.assertEqual({wd.FOUNDER_AUTHORED, wd.EARNED}, set(wd.BLOCKING_PROVENANCE))


class ReportShapeTests(unittest.TestCase):
    def test_the_report_separates_refusals_from_advisories(self) -> None:
        result = wd.report(wd.validate_declaration(variant(**{"reason.statement": "main cleanup"})))
        self.assertTrue(result["admissible"])
        self.assertEqual("DECLARATION_ADMISSIBLE", result["verdict"])
        self.assertEqual(0, result["blocking_count"])
        self.assertGreaterEqual(result["advisory_count"], 2)

    def test_a_refused_declaration_reports_its_refusals(self) -> None:
        result = wd.report(wd.validate_declaration({}))
        self.assertFalse(result["admissible"])
        self.assertEqual("DECLARATION_REFUSED", result["verdict"])
        self.assertTrue(all("blocking" in item for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
