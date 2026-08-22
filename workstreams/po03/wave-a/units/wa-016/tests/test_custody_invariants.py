"""Recurrence test for M1: the strengthening layer over the seeded validator.

Each case names a document the read-only seeded validator admits while it still
asserts a completion whose evidence is internally impossible.  If a gap is closed
upstream, the paired assertion here says so rather than passing silently.
"""

from __future__ import annotations

import copy
import unittest

import _bootstrap  # noqa: F401

from harness import custody_invariants
from harness.custody_invariants import (
    GAP_FIXTURES,
    STATE_COHERENCE,
    TXN_STATES,
    added_invariants,
    measure_gaps,
    validate_result_strict,
)
from harness.custody_machine import STATES
from harness.seeded import load_validator


class CompositionTests(unittest.TestCase):
    def test_the_layer_is_additive_over_the_seeded_validator(self):
        """Every seeded error survives; the layer only appends."""
        broken = {"protocol_version": "WRONG", "obzio_state": "COMPLETED"}
        seeded = load_validator().validate_result(broken)
        strict = validate_result_strict(broken)
        self.assertTrue(seeded)
        self.assertEqual(seeded, strict[: len(seeded)])

    def test_the_baseline_document_passes_both_layers(self):
        doc = custody_invariants._committed_baseline()
        self.assertEqual([], load_validator().validate_result(doc))
        self.assertEqual([], added_invariants(doc))

    def test_the_declared_transaction_states_match_the_schema_enum(self):
        import json

        from harness.seeded import repository_root

        schema = json.loads(
            (repository_root() / "workstreams/po03/contracts/transactional-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        enum = schema["properties"]["result_transaction"]["properties"]["state"]["enum"]
        self.assertEqual(list(enum), list(TXN_STATES))

    def test_state_coherence_covers_every_lifecycle_state(self):
        self.assertEqual(set(STATES), set(STATE_COHERENCE))
        for state, allowed in STATE_COHERENCE.items():
            self.assertTrue(allowed <= set(TXN_STATES), state)


class GapTests(unittest.TestCase):
    def test_every_declared_gap_is_admitted_upstream_and_rejected_here(self):
        for row in measure_gaps():
            with self.subTest(gap=row["gap_id"]):
                self.assertTrue(
                    row["seeded_validator_admits"],
                    f"{row['gap_id']} is no longer a gap: the seeded validator now reports "
                    f"{row['seeded_validator_errors']}",
                )
                self.assertTrue(row["strengthened_rejects"], row["gap_id"])
                self.assertTrue(row["closes_gap"])

    def test_each_gap_carries_a_rationale(self):
        self.assertEqual(len(GAP_FIXTURES), len(measure_gaps()))
        for row in measure_gaps():
            self.assertTrue(row["rationale"].strip())


class AddedInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = custody_invariants._committed_baseline()

    def test_a1_rejects_a_transaction_state_the_schema_never_declared(self):
        self.doc["result_transaction"]["state"] = "ALMOST_DONE"
        self.assertTrue(any("not a declared transaction state" in e for e in added_invariants(self.doc)))

    def test_a2_rejects_a_completed_result_claiming_a_reserved_transaction(self):
        self.doc["result_transaction"]["state"] = "RESERVED"
        self.assertTrue(any("incoherent with obzio_state COMPLETED" in e for e in added_invariants(self.doc)))

    def test_a3_rejects_a_readback_earlier_than_the_commit_it_read(self):
        self.doc["artifacts"][0]["readback_verified_at"] = "2026-08-22T07:20:00Z"
        self.assertTrue(any("precedes committed_at" in e for e in added_invariants(self.doc)))

    def test_a3_rejects_an_ingestion_earlier_than_its_commit(self):
        self.doc["result_transaction"]["parent_ingested_at"] = "2026-08-22T07:20:00Z"
        self.assertTrue(
            any("parent_ingested_at: precedes committed_at" in e for e in added_invariants(self.doc))
        )

    def test_a3_allows_a_staged_verification_before_the_commit(self):
        """A result not yet read back legitimately verified before committing."""
        self.doc["obzio_state"] = "RESULT_COMMITTED"
        self.doc["result_transaction"]["state"] = "COMMITTED"
        self.doc["result_transaction"]["verified_at"] = "2026-08-22T07:20:00Z"
        self.doc["result_transaction"]["parent_ingested_at"] = None
        self.doc["artifacts"][0]["readback_verified_at"] = None
        self.doc["completion_actor"] = None
        self.assertEqual([], added_invariants(self.doc))

    def test_a4_rejects_one_logical_name_counted_twice(self):
        clone = copy.deepcopy(self.doc["artifacts"][0])
        clone["artifact_id"] = "art-2"
        self.doc["artifacts"].append(clone)
        errors = added_invariants(self.doc)
        self.assertTrue(any("duplicate logical name" in e for e in errors))
        self.assertTrue(any("duplicate content uri" in e for e in errors))

    def test_a5_rejects_an_artifact_located_at_a_different_commit(self):
        self.doc["artifacts"][0]["content_uri"] = "refs/po03/po03-wa-016@elsewhere:canary.txt"
        self.assertTrue(any("does not reference result_commit_id" in e for e in added_invariants(self.doc)))

    def test_a6_requires_a_digest_whenever_a_manifest_is_located(self):
        self.doc["result_transaction"]["manifest_sha256"] = None
        self.assertTrue(any("required whenever manifest_uri is claimed" in e for e in added_invariants(self.doc)))

    def test_a_document_without_the_required_shape_is_refused_outright(self):
        self.assertEqual(
            ["$: strengthened layer requires result_transaction and artifacts"],
            added_invariants({"obzio_state": "COMPLETED"}),
        )

    def test_absent_timestamps_are_not_treated_as_out_of_order(self):
        self.doc["result_transaction"]["parent_ingested_at"] = None
        self.doc["obzio_state"] = "RESULT_COMMITTED"
        self.doc["result_transaction"]["state"] = "COMMITTED"
        self.doc["completion_actor"] = None
        self.assertEqual([], added_invariants(self.doc))


if __name__ == "__main__":
    unittest.main()
