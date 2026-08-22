"""a1-u01 — the hash-chained ledger detects every tamper class.

Hypothesis under test (frozen in ``control/dispatch/a1-u01.json``): a
hash-chained append-only ledger detects every single-row mutation, reordering
and truncation without any external store.

The test is arranged so a passing run cannot be vacuous:

1. every tamper class is planted individually and the *specific* finding code
   that must catch it is asserted, so no class can pass by triggering some
   unrelated complaint;
2. a randomised campaign applies at least 1000 distinct tamper operations and
   requires 100% detection;
3. clean and benignly re-encoded ledgers must verify, so detection cannot be
   bought by flagging everything;
4. negative controls remove the anchor rule and the digest rule and assert the
   campaign then *fails*, which proves the campaign has discriminating power
   rather than merely returning success.
"""

from __future__ import annotations

import json
import random
import unittest

from test_a1_support import PO03_ROOT, ScratchCase, load_isolated_module

from engine import tamper
from engine.canonical import GENESIS_HASH, sha256_bytes
from engine.ledger import (
    OBZIO_EVENT_KINDS,
    HashChainedLedger,
    LedgerError,
    LedgerTampered,
    row_digest,
)

CAMPAIGN_MUTATIONS = 1050
CAMPAIGN_DISTINCT_TARGET = 1000


class LedgerBasicsTests(ScratchCase):
    def ledger(self, name: str = "ledger.jsonl") -> HashChainedLedger:
        return HashChainedLedger(self.scratch / name)

    def test_scratch_state_is_not_under_tmp(self):
        self.assertNotUnderTmp(self.scratch)

    def test_empty_ledger_verifies(self):
        verification = self.ledger().verify()
        self.assertTrue(verification.ok, verification.as_dict())
        self.assertEqual(0, verification.row_count)
        self.assertEqual(GENESIS_HASH, verification.head_sha256)

    def test_append_chains_and_seals(self):
        ledger = self.ledger()
        first = ledger.append("u1", "CREATED", actor="coordinator")
        second = ledger.append("u1", "LEASED", actor="coordinator", fence_token=1)
        self.assertEqual(GENESIS_HASH, first["prev_sha256"])
        self.assertEqual(first["row_sha256"], second["prev_sha256"])
        self.assertEqual(2, second["seq"])
        verification = ledger.verify()
        self.assertTrue(verification.ok, verification.as_dict())
        anchor = ledger.read_anchor()
        self.assertEqual(2, anchor["committed_seq"])
        self.assertEqual(second["row_sha256"], anchor["committed_head"])
        self.assertIsNone(anchor["pending_seq"])

    def test_unknown_event_kind_refused(self):
        with self.assertRaises(LedgerError):
            self.ledger().append("u1", "DEFINITELY_NOT_AN_EVENT", actor="coordinator")

    def test_rows_refuses_to_return_tampered_history(self):
        ledger = self.ledger()
        ledger.append("u1", "CREATED", actor="coordinator")
        ledger.path.write_text(
            ledger.path.read_text(encoding="utf-8").replace("coordinator", "impostor--"), encoding="utf-8"
        )
        with self.assertRaises(LedgerTampered):
            ledger.rows()

    def test_append_refuses_to_extend_a_tampered_ledger(self):
        ledger = self.ledger()
        ledger.append("u1", "CREATED", actor="coordinator")
        ledger.path.write_text(
            ledger.path.read_text(encoding="utf-8").replace('"seq":1', '"seq":9'), encoding="utf-8"
        )
        with self.assertRaises(LedgerTampered):
            ledger.append("u1", "RUNNING", actor="coordinator")

    def test_external_anchor_mismatch_is_reported(self):
        ledger = self.ledger()
        ledger.append("u1", "CREATED", actor="coordinator")
        verification = ledger.verify(expected_head="f" * 64)
        self.assertFalse(verification.ok)
        self.assertIn("EXTERNAL_ANCHOR_MISMATCH", verification.tamper_codes)

    def test_external_anchor_match_verifies(self):
        ledger = self.ledger()
        row = ledger.append("u1", "CREATED", actor="coordinator")
        self.assertTrue(ledger.verify(expected_head=row["row_sha256"]).ok)


class CrashWindowTests(ScratchCase):
    """The append/seal window must be recoverable without becoming a hole."""

    def _crashing_ledger(self, point: str) -> HashChainedLedger:
        class Injected(RuntimeError):
            pass

        def hook(fired: str) -> None:
            if fired == point:
                raise Injected(point)

        self.injected = Injected
        return HashChainedLedger(self.scratch / "ledger.jsonl", fault_hook=hook)

    def test_crash_before_intent_leaves_a_clean_ledger(self):
        ledger = self._crashing_ledger("before_anchor_intent")
        with self.assertRaises(self.injected):
            ledger.append("u1", "CREATED", actor="coordinator")
        self.assertTrue(ledger.verify().ok)
        self.assertEqual(0, ledger.verify().row_count)

    def test_crash_between_intent_and_append_leaves_a_clean_ledger(self):
        ledger = self._crashing_ledger("after_anchor_intent")
        with self.assertRaises(self.injected):
            ledger.append("u1", "CREATED", actor="coordinator")
        verification = ledger.verify()
        self.assertTrue(verification.ok, verification.as_dict())
        self.assertEqual(0, verification.row_count)

    def test_crash_between_append_and_seal_is_benign_and_resealable(self):
        plain = HashChainedLedger(self.scratch / "ledger.jsonl")
        plain.append("u1", "CREATED", actor="coordinator")
        crashing = self._crashing_ledger("after_append_before_seal")
        with self.assertRaises(self.injected):
            crashing.append("u1", "RUNNING", actor="coordinator")
        verification = plain.verify()
        self.assertTrue(verification.ok, verification.as_dict())
        self.assertIn("APPEND_IN_FLIGHT", [f.code for f in verification.findings])
        self.assertEqual(2, verification.row_count)
        resealed = plain.reseal()
        self.assertTrue(resealed.ok)
        self.assertNotIn("APPEND_IN_FLIGHT", [f.code for f in resealed.findings])

    def test_row_substituted_inside_the_crash_window_is_detected(self):
        """The window admits exactly the announced row and nothing else."""
        plain = HashChainedLedger(self.scratch / "ledger.jsonl")
        plain.append("u1", "CREATED", actor="coordinator")
        crashing = self._crashing_ledger("after_append_before_seal")
        with self.assertRaises(self.injected):
            crashing.append("u1", "RUNNING", actor="coordinator")
        self.assertTrue(plain.verify().ok)

        lines = plain.path.read_text(encoding="utf-8").splitlines()
        forged = json.loads(lines[-1])
        forged["event"] = "COMPLETED"
        forged["obzio_state"] = "COMPLETED"
        forged["row_sha256"] = row_digest(forged)
        lines[-1] = json.dumps(forged, sort_keys=True, separators=(",", ":"))
        plain.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        verification = plain.verify()
        self.assertFalse(verification.ok, verification.as_dict())
        self.assertIn("FORGED_APPEND", verification.tamper_codes)

    def test_reseal_refuses_to_launder_a_tampered_ledger(self):
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl")
        ledger.append("u1", "CREATED", actor="coordinator")
        ledger.append("u1", "RUNNING", actor="coordinator")
        lines = ledger.path.read_text(encoding="utf-8").splitlines()
        ledger.path.write_text(lines[0] + "\n", encoding="utf-8")
        self.assertFalse(ledger.verify().ok)
        with self.assertRaises(LedgerError):
            ledger.reseal()


class TamperClassTests(ScratchCase):
    """Each class is planted alone and must produce its own specific finding."""

    EXPECTED_CODES = {
        "MUTATE_FIELD": {"ROW_DIGEST_MISMATCH"},
        "MUTATE_AND_REHASH_ROW": {"CHAIN_BREAK", "ANCHOR_HEAD_MISMATCH"},
        "REWRITE_SUFFIX": {"ANCHOR_HEAD_MISMATCH"},
        "TRUNCATE_TAIL": {"TRUNCATED"},
        "DELETE_MIDDLE_ROW": {"SEQ_NOT_MONOTONIC", "TRUNCATED"},
        "SWAP_ROWS": {"SEQ_NOT_MONOTONIC"},
        "DUPLICATE_ROW": {"SEQ_DUPLICATED", "SEQ_NOT_MONOTONIC"},
        "INSERT_FORGED_ROW": {"SEQ_NOT_MONOTONIC", "SEQ_DUPLICATED", "CHAIN_BREAK"},
        "APPEND_FORGED_ROW": {"FORGED_APPEND"},
        "CORRUPT_BYTE": {
            "ROW_DIGEST_MISMATCH",
            "UNPARSABLE_ROW",
            "NOT_UTF8",
            "CHAIN_BREAK",
            "SEQ_NOT_MONOTONIC",
            "ROW_FIELDS_MISSING",
            "TRUNCATED",
            "ANCHOR_HEAD_MISMATCH",
        },
        "MUTATE_PREV_HASH": {"CHAIN_BREAK", "ROW_DIGEST_MISMATCH"},
        "MUTATE_ROW_HASH": {"ROW_DIGEST_MISMATCH"},
        "MUTATE_SEQ": {"SEQ_NOT_MONOTONIC", "ROW_DIGEST_MISMATCH"},
        "TRUNCATE_LINE": {"UNPARSABLE_ROW"},
        "REORDER_TAIL": {"SEQ_NOT_MONOTONIC"},
        "WIPE_LEDGER": {"TRUNCATED"},
        "ANCHOR_ROLLBACK": {"FORGED_APPEND"},
        "ANCHOR_HEAD_FORGE": {"ANCHOR_HEAD_MISMATCH"},
        "ANCHOR_DELETE": {"ANCHOR_ABSENT"},
    }

    def test_every_class_has_a_declared_expected_code(self):
        self.assertEqual(set(tamper.TAMPER_CLASSES), set(self.EXPECTED_CODES))

    def test_each_tamper_class_is_detected_by_its_own_finding(self):
        rng = random.Random(4242)
        for tamper_class in tamper.TAMPER_CLASSES:
            with self.subTest(tamper_class=tamper_class):
                ledger = HashChainedLedger(self.scratch / f"{tamper_class}.jsonl", verify_on_append=False)
                tamper.build_clean_ledger(ledger, 12, rng)
                self.assertTrue(ledger.verify().ok)
                op = tamper.apply_tamper(ledger, tamper_class, rng)
                self.assertIsNotNone(op, f"{tamper_class} produced no effective mutation")
                verification = ledger.verify()
                self.assertFalse(verification.ok, f"{tamper_class} went undetected: {verification.as_dict()}")
                self.assertTrue(
                    set(verification.tamper_codes) & self.EXPECTED_CODES[tamper_class],
                    f"{tamper_class} was caught only by unrelated findings "
                    f"{verification.tamper_codes}; expected one of {self.EXPECTED_CODES[tamper_class]}",
                )


class CampaignTests(ScratchCase):
    """The randomised property test named in the frozen acceptance contract."""

    def test_campaign_detects_at_least_1000_distinct_mutations(self):
        result = tamper.run_campaign(
            self.scratch / "campaign",
            mutations=CAMPAIGN_MUTATIONS,
            distinct_target=CAMPAIGN_DISTINCT_TARGET,
            seed=20260822,
        )
        self.assertGreaterEqual(result.mutations_applied, 1000, result.as_dict())
        self.assertGreaterEqual(result.distinct_signatures, 1000, result.as_dict())
        self.assertEqual(result.mutations_applied, result.detected, result.missed[:5])
        self.assertEqual([], result.missed)
        self.assertEqual([], result.false_positives)
        for name, stats in result.per_class.items():
            self.assertGreater(stats["applied"], 0, f"{name} was never exercised")
            self.assertEqual(stats["applied"], stats["detected"], f"{name}: {stats}")
        self.assertTrue(result.ok, result.as_dict())

    def test_campaign_fails_when_the_anchor_rule_is_removed(self):
        """Negative control: without the sealed anchor, tail attacks survive."""
        result = tamper.run_campaign(
            self.scratch / "no-anchor",
            mutations=200,
            distinct_target=150,
            min_per_class=6,
            seed=99,
            verifier=_chain_only_verify,
        )
        self.assertFalse(result.ok)
        missed_classes = {entry["tamper_class"] for entry in result.missed}
        self.assertTrue(
            {"TRUNCATE_TAIL", "REWRITE_SUFFIX"} & missed_classes,
            f"chain-only verification should miss tail attacks, missed {missed_classes}",
        )

    def test_campaign_fails_when_the_digest_rule_is_removed(self):
        """Negative control: without row digests, in-place edits survive."""
        result = tamper.run_campaign(
            self.scratch / "no-digest",
            mutations=200,
            distinct_target=150,
            min_per_class=6,
            seed=101,
            verifier=_anchor_only_verify,
        )
        self.assertFalse(result.ok)
        missed_classes = {entry["tamper_class"] for entry in result.missed}
        self.assertIn("MUTATE_FIELD", missed_classes)


def _chain_only_verify(ledger: HashChainedLedger):
    """Verification with the sealed anchor ignored entirely."""
    from engine.ledger import TAMPER, Verification

    rows, findings = ledger.read_rows()
    findings = list(findings) + ledger._verify_chain(rows)
    head = rows[-1].get("row_sha256", GENESIS_HASH) if rows else GENESIS_HASH
    ok = not any(f.severity == TAMPER for f in findings)
    return Verification(ok=ok, row_count=len(rows), head_sha256=head, findings=tuple(findings))


def _anchor_only_verify(ledger: HashChainedLedger):
    """Verification with per-row digests ignored, anchor rules retained."""
    from engine.ledger import TAMPER, Verification

    rows, findings = ledger.read_rows()
    findings = list(findings) + ledger._verify_anchor(rows, require_anchor=True)
    head = rows[-1].get("row_sha256", GENESIS_HASH) if rows else GENESIS_HASH
    ok = not any(f.severity == TAMPER for f in findings)
    return Verification(ok=ok, row_count=len(rows), head_sha256=head, findings=tuple(findings))


class ControlPlaneInteropTests(ScratchCase):
    """The coordinator's verifier and this one must accept each other's rows.

    Interoperability is asserted, not assumed: if the row format drifted, a
    ledger written by a subordinate would stop being verifiable by the
    integration controller, and result custody would silently split in two.
    """

    def setUp(self) -> None:
        super().setUp()
        self.plane = load_isolated_module(
            PO03_ROOT / "tools" / "control_plane.py", "a1_interop_control_plane"
        )
        self.plane.LEDGER_PATH = self.scratch / "control" / "events" / "ledger.jsonl"
        self.plane.REGISTRY_PATH = self.scratch / "control" / "work-unit-registry.jsonl"
        self.plane.RECOVERY_PATH = self.scratch / "control" / "recovery-state.json"
        self.plane.DISPATCH_DIR = self.scratch / "control" / "dispatch"
        self.plane.PATH_OWNERSHIP_PATH = self.scratch / "control" / "path-ownership.json"

    def test_engine_event_kinds_cover_the_control_plane_kinds(self):
        self.assertEqual(set(self.plane.EVENT_KINDS), set(OBZIO_EVENT_KINDS))

    def test_engine_verifier_accepts_a_control_plane_ledger(self):
        for event in ("CREATED", "LEASED", "RUNNING", "RESULT_COMMITTED"):
            self.plane.append_event("u1", event, actor="coordinator", fence_token=1)
        engine_ledger = HashChainedLedger(self.plane.LEDGER_PATH)
        verification = engine_ledger.verify(require_anchor=False)
        self.assertTrue(verification.ok, verification.as_dict())
        self.assertEqual(4, verification.row_count)

    def test_control_plane_verifier_accepts_an_engine_ledger(self):
        engine_ledger = HashChainedLedger(self.plane.LEDGER_PATH, event_kinds=OBZIO_EVENT_KINDS)
        for event in ("CREATED", "LEASED", "RUNNING", "RESULT_COMMITTED"):
            engine_ledger.append("u1", event, actor="coordinator", fence_token=1)
        rows = self.plane.ledger_rows()
        self.assertEqual([], self.plane.verify_chain(rows))
        self.assertEqual(4, len(rows))

    def test_both_verifiers_reject_the_same_tamper(self):
        engine_ledger = HashChainedLedger(self.plane.LEDGER_PATH, event_kinds=OBZIO_EVENT_KINDS)
        for event in ("CREATED", "LEASED", "RUNNING"):
            engine_ledger.append("u1", event, actor="coordinator", fence_token=1)
        lines = self.plane.LEDGER_PATH.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[1])
        row["actor"] = "impostor"
        lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
        self.plane.LEDGER_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertFalse(engine_ledger.verify().ok)
        self.assertNotEqual([], self.plane.verify_chain(self.plane.ledger_rows()))

    def test_digest_rule_is_identical_in_both_implementations(self):
        body = {
            "seq": 1,
            "ts": "2026-08-22T07:00:00Z",
            "unit_id": "u1",
            "event": "CREATED",
            "obzio_state": "CREATED",
            "provider_state": None,
            "actor": "coordinator",
            "fence_token": None,
            "payload": {"a": 1},
            "prev_sha256": GENESIS_HASH,
        }
        self.assertEqual(self.plane.sha256_text(self.plane.canonical(body)), row_digest(body))


class DeterminismTests(ScratchCase):
    def test_campaign_is_reproducible_from_its_seed(self):
        first = tamper.run_campaign(
            self.scratch / "a", mutations=60, distinct_target=40, min_per_class=3, clean_ledgers=9, seed=7
        )
        second = tamper.run_campaign(
            self.scratch / "b", mutations=60, distinct_target=40, min_per_class=3, clean_ledgers=9, seed=7
        )
        self.assertEqual(first.mutations_applied, second.mutations_applied)
        self.assertEqual(first.detected, second.detected)
        self.assertEqual(
            {name: stats["applied"] for name, stats in first.per_class.items()},
            {name: stats["applied"] for name, stats in second.per_class.items()},
        )

    def test_row_digest_is_stable_across_key_order(self):
        body = {"b": 2, "a": 1, "payload": {"z": 1, "y": 2}}
        self.assertEqual(row_digest(body), row_digest({"payload": {"y": 2, "z": 1}, "a": 1, "b": 2}))
        self.assertNotEqual(row_digest(body), row_digest({**body, "a": 2}))

    def test_sha256_helper_matches_hashlib(self):
        import hashlib

        self.assertEqual(hashlib.sha256(b"obzio").hexdigest(), sha256_bytes(b"obzio"))


if __name__ == "__main__":
    unittest.main()
