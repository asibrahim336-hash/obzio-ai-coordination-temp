#!/usr/bin/env python3
"""Refusal tests for the typed improvement chain.

The happy path is one test. Everything else here is an attempt to get a broken
chain admitted, because a gate is only worth what its refusals are worth — and
because the control this replaces, the non-admissible `LESSON_DOCUMENTED` class,
was a correct statement with no way to find a violation.

Each negative test names the shape it is trying to sneak through:

* a defect with no mechanism change
* a mechanism change with no regression test
* a regression test that was never re-run
* a verdict with no rerun
* a currentness promotion with no verdict
* a pending declaration used as a substitute for a missing foundation
* a pending declaration with no reason or no owner
* an out-of-order edge, a cross-chain edge, an edge to nothing, a cycle
* an unrecognised node kind, an unlabelled claim, an unclassified provenance
* a founder-provenance claim with no quoted founder utterance
* an acceptance-class promotion resting on a producer's own verdict
* a promotion that misreports the verdict it rests on
* a citation whose bytes have moved, are absent, or are malformed

Run: `python3 -I test_improvement_chain.py`
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[7]
CONTROL_PLANE = REPO_ROOT / "workstreams/so02/control-plane"
MODULE_PATH = CONTROL_PLANE / "tools/improvement_chain.py"
SCCTL_PATH = CONTROL_PLANE / "tools/scctl.py"
EVENTS_PATH = CONTROL_PLANE / "state/events.jsonl"
SEED_PATH = (CONTROL_PLANE / "operating-environment/scp-si-01/lane-b/chains"
             / "SCP-B-CHAIN-SEED-20260827-v001.json")
SEEDED = json.loads(SEED_PATH.read_text(encoding="utf-8"))
SEEDED_IDS = [chain["chain_id"] for chain in SEEDED["chains"]]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ic = _load("improvement_chain", MODULE_PATH)
scctl = _load("scctl", SCCTL_PATH)


# ---------------------------------------------------------------------------
# fixture construction
# ---------------------------------------------------------------------------


def node(node_id: str, kind: str, derives_from: list[str] | None = None,
         chain_id: str = "CH", occurred_at: str = "2026-01-01T00:00:00Z",
         **overrides: Any) -> dict[str, Any]:
    """A minimally valid link, so a test only has to state the one thing it breaks."""
    link: dict[str, Any] = {
        "chain_id": chain_id,
        "node_id": node_id,
        "node_kind": kind,
        "derives_from": list(derives_from or []),
        "occurred_at": occurred_at,
        "title": f"{kind} {node_id}",
        "statement": f"fixture {kind}",
        "evidence_label": "DOCUMENTED",
        "provenance_class": "EARNED",
        "provenance_basis": "fixture defect",
        "evidence_citations": [{"locator": "fixture:artifact"}],
    }
    if kind == "VERDICT":
        link["verdict"] = {"verdict_value": "MECHANISM_HOLDS_UNDER_RERUN", "independent": False}
    if kind == "CURRENTNESS_PROMOTION":
        link["promotion"] = {
            "promoted_subject": "fixture",
            "promoted_state": "MECHANISM_LIVE",
            "promoted_from_verdict_value": "MECHANISM_HOLDS_UNDER_RERUN",
        }
    link.update(overrides)
    return link


def events(*links: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": f"FIX-{position:04d}",
            "event_type": ic.LINK_EVENT_TYPE,
            "event_sha256": f"{position:064d}",
            "sequence": position,
            "occurred_at": link.get("occurred_at"),
            "subject": f"fixture/{link['node_id']}",
            "payload": {"new_state": "LINK", "decision_changed": [],
                        ic.LINK_PAYLOAD_KEY: link},
        }
        for position, link in enumerate(links, 1)
    ]


def complete_chain(**last_overrides: Any) -> list[dict[str, Any]]:
    """observation -> ... -> promotion, chronological, fully cited."""
    return events(
        node("N1", "OBSERVATION", occurred_at="2026-01-01T00:00:00Z"),
        node("N2", "DEFECT", ["N1"], occurred_at="2026-01-02T00:00:00Z"),
        node("N3", "MECHANISM_CHANGE", ["N2"], occurred_at="2026-01-03T00:00:00Z"),
        node("N4", "REGRESSION_TEST", ["N3"], occurred_at="2026-01-04T00:00:00Z"),
        node("N5", "RERUN", ["N4"], occurred_at="2026-01-05T00:00:00Z"),
        node("N6", "VERDICT", ["N5"], occurred_at="2026-01-06T00:00:00Z"),
        node("N7", "CURRENTNESS_PROMOTION", ["N6"], occurred_at="2026-01-07T00:00:00Z",
             **last_overrides),
    )


def codes(findings: list[Any]) -> list[str]:
    return [finding.code for finding in findings]


def errors(findings: list[Any]) -> list[str]:
    return [finding.code for finding in findings if finding.severity == ic.ERROR]


def check(event_list: list[dict[str, Any]], repo_root: Path | None = None) -> list[Any]:
    _, findings = ic.check_all(event_list, repo_root)
    return findings


# ---------------------------------------------------------------------------
# the one happy path
# ---------------------------------------------------------------------------


class CompleteChainTests(unittest.TestCase):
    def test_a_complete_cited_chain_is_admitted(self) -> None:
        chains, findings = ic.check_all(complete_chain())
        self.assertEqual([], errors(findings))
        self.assertEqual("CLOSED_THROUGH_PROMOTION", chains["CH"]["chain_state"])
        self.assertIsNone(chains["CH"]["next_required_node_kind"])

    def test_the_projection_is_a_pure_function_of_the_event_list(self) -> None:
        event_list = complete_chain()
        first = ic.summarise(*ic.check_all(event_list)[::1])
        chains, findings = ic.check_all(event_list)
        second = ic.summarise(chains, findings)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


# ---------------------------------------------------------------------------
# the four refusals the deliverable names
# ---------------------------------------------------------------------------


class MissingSuccessorTests(unittest.TestCase):
    def test_a_defect_with_no_mechanism_change_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
        ))
        self.assertIn("CHAIN_LINK_DANGLING", errors(findings))

    def test_a_mechanism_change_with_no_regression_test_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
        ))
        dangling = [f for f in findings if f.code == "CHAIN_LINK_DANGLING"]
        self.assertIn("N3", [f.node_id for f in dangling])

    def test_a_regression_test_never_re_run_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
        ))
        dangling = [f for f in findings if f.code == "CHAIN_LINK_DANGLING"]
        self.assertIn("N4", [f.node_id for f in dangling])

    def test_a_mechanism_change_is_not_excused_by_the_defect_declaring_it_pending(self) -> None:
        # The defect waived its own successor, then a mechanism appeared anyway
        # and skipped the test. Waiving one rung does not waive the next.
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"], pending_successor={
                "node_kind": "MECHANISM_CHANGE", "state": "PENDING",
                "reason": "stale", "owner": "someone"}),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
        ))
        self.assertIn("CHAIN_LINK_DANGLING", errors(findings))
        self.assertIn("CHAIN_PENDING_ALREADY_SATISFIED", codes(findings))


class MissingPredecessorTests(unittest.TestCase):
    """A missing foundation is never waivable, however it is dressed up."""

    def test_a_verdict_with_no_rerun_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
            node("N6", "VERDICT", []),
        ))
        foundation = [f for f in findings if f.code == "CHAIN_FOUNDATION_MISSING"]
        self.assertIn("N6", [f.node_id for f in foundation])

    def test_a_currentness_promotion_with_no_verdict_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
            node("N5", "RERUN", ["N4"]),
            node("N7", "CURRENTNESS_PROMOTION", []),
        ))
        foundation = [f for f in findings if f.code == "CHAIN_FOUNDATION_MISSING"]
        self.assertIn("N7", [f.node_id for f in foundation])

    def test_a_promotion_deriving_from_the_rerun_directly_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
            node("N5", "RERUN", ["N4"]),
            node("N7", "CURRENTNESS_PROMOTION", ["N5"]),
        ))
        self.assertIn("CHAIN_EDGE_KIND_NOT_ALLOWED", errors(findings))
        self.assertIn("CHAIN_FOUNDATION_MISSING", errors(findings))

    def test_a_defect_with_no_observation_is_refused(self) -> None:
        findings = check(events(node("N2", "DEFECT", [])))
        self.assertIn("CHAIN_FOUNDATION_MISSING", errors(findings))

    def test_a_pending_declaration_cannot_supply_a_missing_predecessor(self) -> None:
        # The shape this forecloses: declaring the rerun "pending" on the
        # verdict, so the verdict looks admitted while resting on nothing.
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"]),
            node("N3", "MECHANISM_CHANGE", ["N2"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
            node("N6", "VERDICT", [], pending_successor={
                "node_kind": "RERUN", "state": "PENDING",
                "reason": "will rerun later", "owner": "me"}),
        ))
        self.assertIn("CHAIN_FOUNDATION_MISSING", errors(findings))


# ---------------------------------------------------------------------------
# the open chain is legal, but only when it is declared properly
# ---------------------------------------------------------------------------


class OpenChainTests(unittest.TestCase):
    def base(self, **pending: Any) -> list[dict[str, Any]]:
        return events(
            node("N1", "OBSERVATION"),
            node("N2", "DEFECT", ["N1"], pending_successor=pending or None),
        )

    def test_a_declared_pending_mechanism_is_a_warning_not_a_refusal(self) -> None:
        chains, findings = ic.check_all(self.base(
            node_kind="MECHANISM_CHANGE", state="PENDING",
            reason="the fix belongs to another owner", owner="coordinator"))
        self.assertEqual([], errors(findings))
        self.assertIn("CHAIN_SUCCESSOR_PENDING", codes(findings))
        self.assertEqual("OPEN_SUCCESSOR_PENDING", chains["CH"]["chain_state"])
        self.assertEqual("MECHANISM_CHANGE", chains["CH"]["next_required_node_kind"])

    def test_a_pending_declaration_with_no_reason_is_refused(self) -> None:
        findings = check(self.base(node_kind="MECHANISM_CHANGE", state="PENDING",
                                   reason="  ", owner="coordinator"))
        self.assertIn("CHAIN_PENDING_UNREASONED", errors(findings))

    def test_a_pending_declaration_with_no_owner_is_refused(self) -> None:
        findings = check(self.base(node_kind="MECHANISM_CHANGE", state="PENDING",
                                   reason="a real reason", owner=""))
        self.assertIn("CHAIN_PENDING_UNOWNED", errors(findings))

    def test_a_pending_declaration_naming_the_wrong_kind_is_refused(self) -> None:
        findings = check(self.base(node_kind="CURRENTNESS_PROMOTION", state="PENDING",
                                   reason="skip ahead", owner="coordinator"))
        self.assertIn("CHAIN_PENDING_WRONG_KIND", errors(findings))

    def test_a_pending_declaration_that_is_not_pending_is_refused(self) -> None:
        findings = check(self.base(node_kind="MECHANISM_CHANGE", state="DONE",
                                   reason="a real reason", owner="coordinator"))
        self.assertIn("CHAIN_PENDING_STATE_INVALID", errors(findings))


# ---------------------------------------------------------------------------
# edges
# ---------------------------------------------------------------------------


class EdgeTests(unittest.TestCase):
    def test_an_edge_that_skips_a_kind_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N3", "MECHANISM_CHANGE", ["N1"]),
        ))
        self.assertIn("CHAIN_EDGE_KIND_NOT_ALLOWED", errors(findings))

    def test_a_backwards_edge_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION", ["N2"]),
            node("N2", "DEFECT", ["N1"]),
        ))
        self.assertIn("CHAIN_EDGE_KIND_NOT_ALLOWED", errors(findings))

    def test_an_edge_to_a_node_that_does_not_exist_is_refused(self) -> None:
        findings = check(events(node("N2", "DEFECT", ["GHOST"])))
        self.assertIn("CHAIN_EDGE_TARGET_MISSING", errors(findings))

    def test_an_edge_into_another_chain_does_not_resolve(self) -> None:
        # Grouping is by chain_id, so a cross-chain parent is simply not there.
        # The refusal is the same one an invented parent gets, which is correct:
        # neither is reachable inside the chain being checked.
        findings = check(events(
            node("A1", "OBSERVATION", chain_id="CH-A"),
            node("B2", "DEFECT", ["A1"], chain_id="CH-B"),
        ))
        self.assertIn("CHAIN_EDGE_TARGET_MISSING", errors(findings))

    def test_a_cycle_is_refused(self) -> None:
        findings = check(events(
            node("N3", "MECHANISM_CHANGE", ["N4"]),
            node("N4", "REGRESSION_TEST", ["N3"]),
        ))
        self.assertIn("CHAIN_CYCLE", errors(findings))

    def test_a_malformed_edge_list_is_refused(self) -> None:
        findings = check(events(node("N2", "DEFECT", chain_id="CH", derives_from=None)))
        broken = check(events(node("N2", "DEFECT")))
        self.assertIn("CHAIN_FOUNDATION_MISSING", errors(broken))
        link = node("N2", "DEFECT")
        link["derives_from"] = "N1"
        self.assertIn("CHAIN_EDGE_LIST_MALFORMED", errors(check(events(link))))
        self.assertIsInstance(findings, list)

    def test_a_duplicate_node_id_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("N1", "OBSERVATION"),
        ))
        self.assertIn("CHAIN_DUPLICATE_NODE_ID", errors(findings))


class ChronologyTests(unittest.TestCase):
    def test_an_undeclared_backwards_timestamp_is_refused(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION", occurred_at="2026-02-01T00:00:00Z"),
            node("N2", "DEFECT", ["N1"], occurred_at="2026-01-01T00:00:00Z",
                 pending_successor={"node_kind": "MECHANISM_CHANGE", "state": "PENDING",
                                    "reason": "r", "owner": "o"}),
        ))
        self.assertIn("CHAIN_EDGE_NOT_CHRONOLOGICAL", errors(findings))

    def test_a_declared_backwards_timestamp_is_a_warning(self) -> None:
        findings = check(events(
            node("N1", "OBSERVATION", occurred_at="2026-02-01T00:00:00Z"),
            node("N2", "DEFECT", ["N1"], occurred_at="2026-01-01T00:00:00Z",
                 non_chronological_reason="the fix predates this reproduction",
                 pending_successor={"node_kind": "MECHANISM_CHANGE", "state": "PENDING",
                                    "reason": "r", "owner": "o"}),
        ))
        self.assertEqual([], errors(findings))
        self.assertIn("CHAIN_EDGE_NOT_CHRONOLOGICAL", codes(findings))


# ---------------------------------------------------------------------------
# vocabulary, labels and provenance
# ---------------------------------------------------------------------------


class VocabularyTests(unittest.TestCase):
    def test_an_unrecognised_node_kind_is_refused_not_ignored(self) -> None:
        # The allowlist inversion, applied to itself. A denylist here would let
        # LESSON_LEARNED or REVIEW_COMPLETED through as a node kind and the
        # chain would look longer while proving less.
        findings = check(events(
            node("N1", "OBSERVATION"),
            node("NX", "LESSON_LEARNED", ["N1"]),
        ))
        self.assertIn("CHAIN_NODE_KIND_UNKNOWN", errors(findings))

    def test_every_declared_kind_is_reachable_from_the_edge_allowlist(self) -> None:
        reachable = {ic.NODE_KINDS[0]}
        for kind in ic.NODE_KINDS:
            reachable |= ic.ALLOWED_EDGES[kind]
        self.assertEqual(set(ic.NODE_KINDS), reachable)

    def test_an_unlabelled_claim_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", evidence_label=None)))
        self.assertIn("CHAIN_EVIDENCE_LABEL_INVALID", errors(findings))

    def test_an_invented_evidence_label_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", evidence_label="VERIFIED")))
        self.assertIn("CHAIN_EVIDENCE_LABEL_INVALID", errors(findings))

    def test_an_uncited_documented_link_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", evidence_citations=[])))
        self.assertIn("CHAIN_LINK_UNCITED", errors(findings))

    def test_an_uncited_link_may_be_recorded_only_as_a_hypothesis(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", evidence_label="HYPOTHESIS",
                                     evidence_citations=[])))
        self.assertEqual([], errors(findings))

    def test_a_hypothesis_cannot_carry_a_currentness_promotion(self) -> None:
        chain = complete_chain()
        chain[5]["payload"][ic.LINK_PAYLOAD_KEY]["evidence_label"] = "HYPOTHESIS"
        chain[5]["payload"][ic.LINK_PAYLOAD_KEY]["evidence_citations"] = []
        self.assertIn("CHAIN_PROMOTION_RESTS_ON_HYPOTHESIS", errors(check(chain)))

    def test_an_unclassified_provenance_is_not_in_force(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", provenance_class=None)))
        self.assertIn("CHAIN_PROVENANCE_UNCLASSIFIED", errors(findings))

    def test_founder_provenance_without_a_quote_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION",
                                     provenance_class="FOUNDER_AUTHORED")))
        self.assertIn("CHAIN_FOUNDER_PROVENANCE_UNQUOTED", errors(findings))

    def test_founder_provenance_with_a_quote_is_accepted(self) -> None:
        findings = check(events(node("N1", "OBSERVATION",
                                     provenance_class="FOUNDER_AUTHORED",
                                     founder_quote="Untouched is not a virtue. Correct is.")))
        self.assertEqual([], errors(findings))

    def test_earned_provenance_that_names_no_defect_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", provenance_basis="")))
        self.assertIn("CHAIN_EARNED_PROVENANCE_NAMES_NO_DEFECT", errors(findings))

    def test_assistant_authored_provenance_is_recorded_without_a_quote(self) -> None:
        findings = check(events(node("N1", "OBSERVATION",
                                     provenance_class="ASSISTANT_AUTHORED")))
        self.assertEqual([], errors(findings))


# ---------------------------------------------------------------------------
# promotions and independence
# ---------------------------------------------------------------------------


class PromotionTests(unittest.TestCase):
    def test_an_acceptance_class_promotion_on_a_producer_verdict_is_refused(self) -> None:
        chain = complete_chain(promotion={
            "promoted_subject": "fixture",
            "promoted_state": "ACCEPTED",
            "promoted_from_verdict_value": "MECHANISM_HOLDS_UNDER_RERUN",
        })
        self.assertIn("CHAIN_PROMOTION_ON_NON_INDEPENDENT_VERDICT", errors(check(chain)))

    def test_an_acceptance_class_promotion_on_an_independent_verdict_is_admitted(self) -> None:
        chain = complete_chain(promotion={
            "promoted_subject": "fixture",
            "promoted_state": "ACCEPTED",
            "promoted_from_verdict_value": "MECHANISM_HOLDS_UNDER_RERUN",
        })
        chain[5]["payload"][ic.LINK_PAYLOAD_KEY]["verdict"]["independent"] = True
        self.assertEqual([], errors(check(chain)))

    def test_a_non_acceptance_promotion_may_rest_on_a_producer_verdict(self) -> None:
        # Independence gates upward promotion. Recording that a control is live,
        # or that a claim was refused, never needed it.
        self.assertEqual([], errors(check(complete_chain())))

    def test_a_promotion_that_misreports_its_verdict_is_refused(self) -> None:
        chain = complete_chain(promotion={
            "promoted_subject": "fixture",
            "promoted_state": "MECHANISM_LIVE",
            "promoted_from_verdict_value": "PASSED",
        })
        self.assertIn("CHAIN_PROMOTION_CONTRADICTS_VERDICT", errors(check(chain)))

    def test_a_promotion_that_names_no_state_is_refused(self) -> None:
        chain = complete_chain(promotion={"promoted_subject": "fixture"})
        self.assertIn("CHAIN_PROMOTION_UNSTATED", errors(check(chain)))

    def test_a_verdict_with_no_verdict_object_is_refused(self) -> None:
        chain = complete_chain()
        chain[5]["payload"][ic.LINK_PAYLOAD_KEY].pop("verdict")
        self.assertIn("CHAIN_VERDICT_UNSTATED", errors(check(chain)))


# ---------------------------------------------------------------------------
# citations
# ---------------------------------------------------------------------------


class CitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="chain-citations-")
        self.root = Path(self.tmp.name)
        self.payload = b'{"real": true}\n'
        (self.root / "artifact.json").write_bytes(self.payload)
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.addCleanup(self.tmp.cleanup)

    def cited(self, **citation: Any) -> list[Any]:
        return check(events(node("N1", "OBSERVATION", evidence_citations=[citation])),
                     self.root)

    def test_a_matching_citation_is_accepted(self) -> None:
        self.assertEqual([], errors(self.cited(artifact_path="artifact.json",
                                               sha256=self.digest)))

    def test_a_citation_whose_bytes_have_moved_is_refused(self) -> None:
        (self.root / "artifact.json").write_bytes(b'{"real": false}\n')
        self.assertIn("CHAIN_CITATION_HASH_MISMATCH",
                      errors(self.cited(artifact_path="artifact.json", sha256=self.digest)))

    def test_a_citation_to_an_absent_artifact_is_refused(self) -> None:
        self.assertIn("CHAIN_CITATION_ABSENT",
                      errors(self.cited(artifact_path="gone.json", sha256=self.digest)))

    def test_a_malformed_digest_is_refused_before_it_is_trusted(self) -> None:
        self.assertIn("CHAIN_CITATION_HASH_MALFORMED",
                      errors(self.cited(artifact_path="artifact.json", sha256="not-a-hash")))

    def test_a_citation_addressing_nothing_at_all_is_refused(self) -> None:
        self.assertIn("CHAIN_CITATION_UNADDRESSABLE", errors(self.cited(note="trust me")))

    def test_a_commit_pinned_citation_is_recorded_not_silently_verified(self) -> None:
        findings = self.cited(commit="0" * 40, artifact_path="gone.json")
        self.assertEqual([], errors(findings))

    def test_a_malformed_citation_object_is_refused(self) -> None:
        findings = check(events(node("N1", "OBSERVATION", evidence_citations=["a string"])),
                         self.root)
        self.assertIn("CHAIN_CITATION_MALFORMED", errors(findings))


# ---------------------------------------------------------------------------
# backward compatibility, asserted rather than claimed
# ---------------------------------------------------------------------------


class BackwardCompatibilityTests(unittest.TestCase):
    def test_an_event_with_no_improvement_link_contributes_nothing(self) -> None:
        plain = [{"event_id": "E1", "payload": {"new_state": "X", "decision_changed": []}}]
        chains, findings = ic.check_all(plain)
        self.assertEqual({}, chains)
        self.assertEqual([], findings)

    def test_an_event_with_no_payload_at_all_is_skipped(self) -> None:
        self.assertEqual([], ic.collect_links([{"event_id": "E1"}, {"payload": None}]))

    def test_the_twenty_one_pre_existing_events_project_zero_chains(self) -> None:
        real = scctl.read_jsonl(EVENTS_PATH)
        original = [event for event in real if event["sequence"] <= 21]
        self.assertEqual(21, len(original))
        chains, findings = ic.check_all(original, REPO_ROOT)
        self.assertEqual({}, chains)
        self.assertEqual([], findings)

    def test_a_control_plane_document_without_the_contract_still_validates(self) -> None:
        control = scctl.read_json(CONTROL_PLANE / "state/control-plane.json")
        self.assertIn("improvement_chain_contract", control)
        stripped = {k: v for k, v in control.items() if k != "improvement_chain_contract"}
        errors_found: list[str] = []
        scctl.validate_improvement_chains(
            CONTROL_PLANE, stripped, scctl.read_jsonl(EVENTS_PATH), errors_found)
        self.assertEqual([], errors_found)

    def test_the_recorded_contract_matches_the_enforced_rules(self) -> None:
        control = scctl.read_json(CONTROL_PLANE / "state/control-plane.json")
        self.assertEqual([], ic.validate_contract(control["improvement_chain_contract"]))

    def test_a_contract_that_drifts_from_the_code_is_caught(self) -> None:
        control = scctl.read_json(CONTROL_PLANE / "state/control-plane.json")
        drifted = json.loads(json.dumps(control["improvement_chain_contract"]))
        drifted["required_predecessor"].pop("CURRENTNESS_PROMOTION")
        self.assertTrue(any("required_predecessor" in item
                            for item in ic.validate_contract(drifted)))

    def test_a_contract_claiming_a_new_store_is_caught(self) -> None:
        control = scctl.read_json(CONTROL_PLANE / "state/control-plane.json")
        drifted = json.loads(json.dumps(control["improvement_chain_contract"]))
        drifted["new_store_created"] = True
        self.assertTrue(any("new_store_created" in item
                            for item in ic.validate_contract(drifted)))

    def test_a_non_object_contract_is_refused(self) -> None:
        self.assertEqual(1, len(ic.validate_contract("a contract")))


# ---------------------------------------------------------------------------
# the seeded estate history
# ---------------------------------------------------------------------------


class SeededHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = scctl.read_jsonl(EVENTS_PATH)
        cls.chains, cls.findings = ic.check_all(cls.events, REPO_ROOT)

    def test_the_real_seeded_chains_are_not_refused(self) -> None:
        self.assertEqual([], errors(self.findings))

    def test_every_citation_digest_matches_the_checkout(self) -> None:
        # The whole point of a digest on a citation. Kept as its own test so a
        # failure names the cause instead of arriving as a generic refusal.
        stale = [finding for finding in self.findings
                 if finding.code == "CHAIN_CITATION_HASH_MISMATCH"]
        self.assertEqual([], [finding.detail for finding in stale])

    def test_no_link_cites_a_report_that_grades_the_chain_itself(self) -> None:
        """Circular evidence: a link citing the verdict of the suite that tests it.

        Found by hitting it. Adding the chain's own suites to the cited regression
        report made the artifact's bytes depend on whether the chain validated,
        while the chain's validity depended on that artifact's digest. Re-anchor
        and rebuild then oscillate between a passing and a failing digest and
        never settle. The fix was to keep the chain's own suites out of the cited
        report; this test is what stops them being put back.
        """
        self_grading = {"SUITE-IMPROVEMENT-CHAIN", "SUITE-SCCTL"}
        for chain_id, chain in self.chains.items():
            for node_id, node in chain["nodes"].items():
                for citation in node.get("evidence_citations", []):
                    path = citation.get("artifact_path")
                    if not path or not path.endswith(".json"):
                        continue
                    target = REPO_ROOT / path
                    if not target.is_file():
                        continue
                    try:
                        parsed = json.loads(target.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if not isinstance(parsed, dict):
                        continue
                    cited_suites = {suite.get("suite_id")
                                    for suite in parsed.get("suites", [])
                                    if isinstance(suite, dict)}
                    self.assertEqual(
                        set(), cited_suites & self_grading,
                        f"{chain_id}/{node_id} cites {path}, which reports the verdict of "
                        "the suite that tests this very link")

    def test_a_cited_artifact_is_byte_stable_when_regenerated(self) -> None:
        """The cited regression report must not move when re-run.

        A citation is a digest. An artifact whose bytes change every time it is
        produced cannot be cited by an append-only log at all: the citation goes
        stale on the next run and the only way to keep it valid is to never
        re-run the suites. So the cited report carries no wall-clock instant and
        no elapsed time, and this test asserts that property directly rather than
        trusting the comment that says so.
        """
        cited = REPO_ROOT / "receipts/so02/2026-08-27/scp-b/reproductions/REGRESSION-RERUN.json"
        parsed = json.loads(cited.read_text(encoding="utf-8"))

        # Keys, not prose. An earlier version of this test scanned the raw text
        # and failed on the report's own explanation of why it has no timestamps.
        volatile = ("produced_at", "recorded_at", "observed_at", "started_at",
                    "finished_at", "duration", "duration_seconds", "elapsed",
                    "elapsed_seconds", "summary_tail")

        def walk(node: Any, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(key, volatile, f"{trail}.{key} is volatile")
                    walk(value, f"{trail}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{trail}[{index}]")

        walk(parsed, "REGRESSION-RERUN")

    def test_every_seeded_chain_reaches_the_projection(self) -> None:
        # Derived from the seed, not pinned. Counting literals here is what broke
        # three tests in test_scctl.py and two of these when history grew.
        self.assertEqual(sorted(SEEDED_IDS), sorted(self.chains))

    def test_each_chain_is_either_closed_or_openly_pending(self) -> None:
        # The real invariant: no chain sits in a third state. A chain is finished,
        # or it says out loud what it is waiting for. Nothing is quietly stalled.
        for chain_id, chain in self.chains.items():
            self.assertIn(chain["chain_state"],
                          ("CLOSED_THROUGH_PROMOTION", "OPEN_SUCCESSOR_PENDING"), chain_id)

    def test_the_open_chains_are_exactly_the_ones_the_seed_declares_open(self) -> None:
        declared = set(SEEDED["open_chains_with_a_pending_mechanism"])
        projected = {chain_id for chain_id, chain in self.chains.items()
                     if chain["chain_state"] == "OPEN_SUCCESSOR_PENDING"}
        self.assertEqual(declared, projected)
        self.assertTrue(declared, "the seed claims to model unfinished work; none is present")

    def test_every_open_chain_is_pending_a_mechanism_change(self) -> None:
        for chain_id in SEEDED["open_chains_with_a_pending_mechanism"]:
            chain = self.chains[chain_id]
            self.assertEqual("MECHANISM_CHANGE", chain["next_required_node_kind"], chain_id)
            self.assertEqual("MECHANISM_CHANGE", chain["pending"][0]["node_kind"], chain_id)

    def test_the_open_chains_route_to_an_owner_who_is_not_this_lane(self) -> None:
        # A pending successor owned by the lane that declared it is a lane
        # promising itself a fix. The waiver is only honest when it routes.
        for chain_id in SEEDED["open_chains_with_a_pending_mechanism"]:
            owner = self.chains[chain_id]["pending"][0]["owner"]
            self.assertTrue(owner.strip(), chain_id)
            self.assertNotIn(owner.strip().lower(), ("lane b", "lane-b", "b"), chain_id)

    def test_every_seeded_node_is_cited_and_provenance_classified(self) -> None:
        for chain in self.chains.values():
            for node_id, seeded in chain["nodes"].items():
                self.assertIn(seeded["evidence_label"], ic.EVIDENCE_LABELS, node_id)
                self.assertIn(seeded["provenance_class"], ic.PROVENANCE_CLASSES, node_id)
                self.assertTrue(seeded["evidence_citations"], node_id)

    def test_no_seeded_chain_reaches_an_acceptance_class_promotion(self) -> None:
        # Not a formatting choice. No independent acceptor has re-examined any
        # of these fixes, so the rule that gates acceptance on independence
        # returns the same answer for all five closed chains.
        for chain in self.chains.values():
            for promoted in chain["promoted_states"]:
                self.assertNotIn(promoted, ic.ACCEPTANCE_CLASS_PROMOTIONS, chain["chain_id"])

    def test_the_hash_chain_still_validates_after_the_append(self) -> None:
        found: list[str] = []
        scctl.validate_events(self.events, found)
        self.assertEqual([], found)

    def test_tampering_with_a_seeded_link_breaks_the_hash_chain(self) -> None:
        import copy
        tampered = copy.deepcopy(self.events)
        target = next(event for event in tampered
                      if event["event_type"] == ic.LINK_EVENT_TYPE)
        target["payload"][ic.LINK_PAYLOAD_KEY]["statement"] = "rewritten"
        found: list[str] = []
        scctl.validate_events(tampered, found)
        self.assertTrue(any("event hash mismatch" in item for item in found))

    def test_scctl_validate_passes_from_the_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", str(SCCTL_PATH), "validate"],
            cwd=str(CONTROL_PLANE), capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_the_registry_projection_exposes_the_chain(self) -> None:
        # Counted from the seed rather than pinned to a literal. Three tests in
        # test_scctl.py broke when this lane appended events precisely because
        # they hardcoded a total, and a test that has to be edited every time
        # history grows is a test that will be edited without being read.
        seeded = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        expected_chains = len(seeded["chains"])
        expected_nodes = sum(len(chain["nodes"]) for chain in seeded["chains"])
        projection = scctl.project(CONTROL_PLANE)
        summary = projection["improvement_chains"]
        self.assertEqual(expected_chains, summary["chain_count"])
        self.assertEqual(expected_nodes, summary["node_count"])
        self.assertFalse(summary["refused"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
