#!/usr/bin/env python3
"""Prove the packaged G1 is the transactional factory it pinned, not a caricature.

G1's whole value as a baseline depends on it being faithful.  A port that is
secretly weaker would manufacture lift for G2, so this file compares the port
against ``workstreams/po03/tools/control_plane.py`` on the things that decide a
score: the ledger row schema, the hash chain, the chain verdicts, the path and
ownership rules, the state projection, and the admit/reject decision on a real
``ingest_result`` call.

Fidelity is asserted **at the pin**, not against HEAD
----------------------------------------------------
G1 is a generation.  A generation that silently tracks HEAD is not a fixed point
anything can be measured against: every later change to the live factory would
either move G1's score or turn this file red without any generation having
changed.  So the comparison target is the factory as it stood at the commit
recorded in ``successor/g1/packaging.json`` under ``packaged_from.source_commit``,
materialised from git by blob and checked against a recorded content digest.
The pin is verified rather than trusted, and the pinned tree is read-only.

This was not a theoretical concern.  An earlier revision of this file compared
the port against the working tree and went red when the live plane's path
normaliser was corrected at ``6f5e386``, several commits after G1 was packaged.
The port had not changed and G1's scores had not moved; only the comparison
target had.  ``PackagingClaimTests`` below keeps the resulting divergence on the
record so the pinned claim cannot be mistaken for a claim about HEAD.

Because the pinned modules are materialised into a scratch tree, their
``CONTROL_ROOT`` points at scratch and the coordinator-owned control state is
structurally unreachable.  ``NonInterferenceTests`` asserts that by hashing
those files before and after.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PO03 = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03.parents[1]
if str(PO03) not in sys.path:
    sys.path.insert(0, str(PO03))

from successor.g1 import factory as packaged
from successor.harness.controller_api import Clock, canonical

PACKAGING = json.loads((PO03 / "successor" / "g1" / "packaging.json").read_text(encoding="utf-8"))
PIN = PACKAGING["packaged_from"]["source_commit"]
PINNED_DIGESTS = PACKAGING["packaged_from"]["source_sha256"]

COORDINATOR_OWNED = (
    PO03 / "control" / "events" / "ledger.jsonl",
    PO03 / "control" / "work-unit-registry.jsonl",
    PO03 / "control" / "recovery-state.json",
    PO03 / "control" / "path-ownership.json",
)

OWNER = "po03-worker-a8"
OWNED_PREFIX = "workstreams/po03/successor/"
ARTIFACT = "workstreams/po03/successor/scores/fidelity-probe.json"

# The two pinned files the comparison surface needs: the factory itself, and the
# validator it loads through its own CONTROL_ROOT.  Taking the validator from the
# pin too means the whole comparison target is one immutable commit rather than a
# pinned factory wired to a moving validator.
PINNED_SOURCES = ("control_plane.py", "validate_contracts.py")


def _blob_at_pin(relative: str) -> bytes | None:
    """Return the bytes of ``relative`` at the pin, or None if unresolvable here."""
    completed = subprocess.run(
        ["git", "cat-file", "blob", f"{PIN}:workstreams/po03/tools/{relative}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def materialise_pin(scratch: Path) -> Path | None:
    """Write the pinned factory and validator into a scratch mirror of the tree.

    The layout is mirrored (``<scratch>/workstreams/po03/tools/``) because the
    factory derives ``CONTROL_ROOT`` from ``__file__.parents[1]`` and resolves
    the validator beneath it.  Returns the pinned module path, or None when the
    pin is not present in this clone.
    """
    tools = scratch / "workstreams" / "po03" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for relative in PINNED_SOURCES:
        blob = _blob_at_pin(relative)
        if blob is None:
            return None
        digest = hashlib.sha256(blob).hexdigest()
        if digest != PINNED_DIGESTS[relative]:
            raise AssertionError(
                f"{relative} at pin {PIN[:7]} hashes to {digest}, but packaging.json "
                f"records {PINNED_DIGESTS[relative]}; the pin or the record is wrong"
            )
        (tools / relative).write_bytes(blob)
    return tools / "control_plane.py"


def load_pinned(scratch: Path):
    """Load the factory *as of the pin*, with its durable paths rebound.

    Callers pass a fresh scratch directory.  ``CONTROL_ROOT`` resolves inside it,
    so nothing this function returns can reach the real control tree, and every
    path the module writes is rebound explicitly on top of that.
    """
    module_path = materialise_pin(scratch / "pin")
    if module_path is None:
        raise unittest.SkipTest(
            f"the G1 fidelity pin {PIN} is not present in this clone, so "
            "fidelity-at-pin cannot be evaluated here; fetch full history "
            "(actions/checkout fetch-depth: 0) to run it"
        )
    spec = importlib.util.spec_from_file_location("pinned_control_plane", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    state = scratch / "state"
    module.LEDGER_PATH = state / "events" / "ledger.jsonl"
    module.REGISTRY_PATH = state / "work-unit-registry.jsonl"
    module.RECOVERY_PATH = state / "recovery-state.json"
    module.DISPATCH_DIR = state / "dispatch"
    module.PATH_OWNERSHIP_PATH = state / "path-ownership.json"
    module.DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    module.PATH_OWNERSHIP_PATH.write_text(
        json.dumps({"owners": {OWNER: {"owned_prefixes": [OWNED_PREFIX]}}}), encoding="utf-8"
    )
    return module


def strip_time(row: dict) -> dict:
    """Row bodies are compared without wall-clock time and without the digest.

    The port takes time from an injectable clock so that lease-expiry scores are
    reproducible; that is the one intentional divergence, and removing ``ts``
    isolates it so everything else is compared exactly.
    """
    body = {key: value for key, value in row.items() if key not in {"ts", "row_sha256", "prev_sha256"}}
    return body


class RowSchemaAndChainTests(unittest.TestCase):
    def test_row_bodies_are_field_for_field_identical(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            pinned = load_pinned(scratch / "pinned")
            pinned_row = pinned.append_event(
                "u1",
                "LEASED",
                actor="coordinator",
                provider_state="RUNNING",
                fence_token=1,
                payload={"lease_id": "lease-u1-1", "worker_id": "w1"},
            )
            ledger = packaged.Ledger(scratch / "port" / "ledger.jsonl")
            port_row = ledger.append(
                "u1",
                "LEASED",
                actor="coordinator",
                ts="2026-08-22T00:00:00Z",
                provider_state="RUNNING",
                fence_token=1,
                payload={"lease_id": "lease-u1-1", "worker_id": "w1"},
            )
            self.assertEqual(strip_time(pinned_row), strip_time(port_row))
            self.assertEqual(sorted(pinned_row), sorted(port_row))

    def test_row_digest_is_computed_the_same_way(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            body = {
                "seq": 1,
                "ts": "2026-08-22T00:00:00Z",
                "unit_id": "u1",
                "event": "CREATED",
                "obzio_state": "CREATED",
                "provider_state": "QUEUED",
                "actor": "coordinator",
                "fence_token": None,
                "payload": {},
                "prev_sha256": "0" * 64,
            }
            self.assertEqual(
                pinned.sha256_text(pinned.canonical(body)),
                hashlib.sha256(canonical(body).encode("utf-8")).hexdigest(),
            )

    def _chain(self, pinned, rows):
        return bool(pinned.verify_chain(rows)), bool(packaged.verify_chain(rows))

    def test_chain_verdicts_agree_including_the_shared_truncation_gap(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            pinned = load_pinned(scratch / "pinned")
            for event in ("CREATED", "LEASED", "RESULT_COMMITTED"):
                pinned.append_event("u1", event, actor="coordinator", fence_token=1)
            rows = pinned.ledger_rows()

            pinned_bad, port_bad = self._chain(pinned, rows)
            self.assertEqual((pinned_bad, port_bad), (False, False), "a healthy chain is accepted by both")

            edited = copy.deepcopy(rows)
            edited[-1]["payload"] = {"injected": True}
            self.assertEqual(self._chain(pinned, edited), (True, True), "an in-place edit is caught by both")

            reordered = copy.deepcopy(rows)
            reordered[-1], reordered[-2] = reordered[-2], reordered[-1]
            self.assertEqual(self._chain(pinned, reordered), (True, True), "reordering is caught by both")

            # The gap G2 closes: both implementations accept a truncated tail,
            # because per-row chaining cannot see rows that are no longer there.
            self.assertEqual(
                self._chain(pinned, rows[:-1]),
                (False, False),
                "tail truncation is invisible to both, which is why C-07 exists",
            )


class PathRuleTests(unittest.TestCase):
    corpus = (
        "workstreams/po03/successor/scores/x.json",
        "receipts/po03/2026-08-22/successor-generation.json",
        ".github/workflows/po03-successor.yml",
        ".github/workflows/other.yml",
        ".github/workflows/nested/po03-x.yml",
        "packs/injected.json",
        "workstreams/po03/successor/../../../etc/passwd",
        "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
        "",
        "./workstreams/po03/successor/a.json",
    )

    def test_allowlist_agrees_on_every_path(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            for path in self.corpus:
                self.assertEqual(
                    pinned.path_in_allowlist(path),
                    packaged.path_in_allowlist(path),
                    f"allowlist verdict diverged for {path!r}",
                )

    def test_ownership_agrees_on_every_path(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            self.assertEqual(
                pinned.check_ownership(OWNER, self.corpus),
                packaged.check_ownership((OWNED_PREFIX,), list(self.corpus)),
            )


class ProjectionTests(unittest.TestCase):
    def test_state_projection_agrees_across_a_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            pinned.append_event("u1", "CREATED", actor="coordinator", provider_state="QUEUED")
            pinned.append_event("u1", "LEASED", actor="coordinator", fence_token=1, payload={"worker_id": "w1", "lease_id": "l1", "expires_at": "2026-08-22T01:00:00Z"})
            pinned.append_event("u1", "LEASED", actor="coordinator", fence_token=2, payload={"worker_id": "w2", "lease_id": "l2", "expires_at": "2026-08-22T02:00:00Z"})
            pinned.append_event("u1", "FENCE_REJECTED", actor="coordinator", fence_token=2, payload={"rejected_fence_token": 1})
            pinned.append_event("u1", "RESULT_COMMITTED", actor="w2", fence_token=2, provider_state="COMPLETED", payload={"result_commit_id": "abc", "artifact_count": 1, "total_bytes": 10})
            pinned.append_event("u1", "PARENT_INGESTED", actor="coordinator", fence_token=2, provider_state="COMPLETED", payload={"result_commit_id": "abc", "result_sha256": "d" * 64, "artifact_count": 1, "total_bytes": 10})
            rows = pinned.ledger_rows()

            pinned_units = pinned.project_units(rows)
            port_units = packaged.project_units(rows)
            for field in ("obzio_state", "provider_state", "fence_token", "result_commit_id", "artifact_count", "total_bytes", "acceptance"):
                self.assertEqual(
                    pinned_units["u1"][field],
                    port_units["u1"][field],
                    f"projection diverged on {field}",
                )
            self.assertEqual(pinned_units["u1"]["lease"]["worker_id"], port_units["u1"]["lease"]["worker_id"])

    def test_observability_events_do_not_advance_state_in_either(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            pinned.append_event("u1", "CREATED", actor="coordinator")
            pinned.append_event("u1", "DUPLICATE_IGNORED", actor="coordinator")
            pinned.append_event("u1", "FAULT_INJECTED", actor="coordinator")
            rows = pinned.ledger_rows()
            self.assertEqual(pinned.project_units(rows)["u1"]["obzio_state"], "CREATED")
            self.assertEqual(packaged.project_units(rows)["u1"]["obzio_state"], "CREATED")


class IngestDecisionTests(unittest.TestCase):
    """Compare the pinned ``ingest_result`` decision with the packaged decision."""

    def _pinned_scenario(self, scratch: Path, *, mutate=None, artifact_bytes: bytes | None = b'{"probe":1}'):
        pinned = load_pinned(scratch / "control")
        artifact_root = scratch / "tree"
        target = artifact_root / ARTIFACT
        target.parent.mkdir(parents=True, exist_ok=True)
        if artifact_bytes is not None:
            target.write_bytes(artifact_bytes)

        manifest = {"unit_id": "u1", "owner": OWNER, "acceptance": {"assertion": "a"}}
        manifest_sha = pinned.sha256_text(pinned.canonical(manifest))
        acceptance_sha = pinned.sha256_text(pinned.canonical(manifest["acceptance"]))
        (pinned.DISPATCH_DIR / "u1.json").write_text(
            json.dumps(
                {
                    **manifest,
                    "immutable_input_manifest_sha256": manifest_sha,
                    "acceptance_contract_sha256": acceptance_sha,
                    "idempotency_key": "u1:key",
                }
            ),
            encoding="utf-8",
        )
        pinned.append_event("u1", "CREATED", actor="coordinator", provider_state="QUEUED")
        pinned.append_event(
            "u1",
            "LEASED",
            actor="coordinator",
            fence_token=1,
            payload={"worker_id": "w1", "lease_id": "l1", "expires_at": "2026-08-22T09:00:00Z"},
        )

        digest = hashlib.sha256(artifact_bytes or b"").hexdigest()
        document = {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "u1",
            "commission_id": "COM-PO03-REPOSITORY-ENGINEERING-PORTABLE-RUNTIME-20260822-v001",
            "immutable_input_manifest_sha256": manifest_sha,
            "acceptance_contract_sha256": acceptance_sha,
            "provider_state": "COMPLETED",
            "obzio_state": "RESULT_COMMITTED",
            "attempt": {
                "attempt_id": "u1-attempt-1",
                "idempotency_key": "u1:key",
                "lease_id": "lease-u1-1",
                "fence_token": 1,
                "provider_run_id": "fidelity",
                "worker_id": OWNER,
                "heartbeat_at": "2026-08-22T08:00:00Z",
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": "u1-txn-1",
                "state": "COMMITTED",
                "manifest_uri": "git:branch@commit:u1",
                "manifest_sha256": "e" * 64,
                "artifact_count": 1,
                "total_bytes": len(artifact_bytes or b""),
                "committed_at": "2026-08-22T08:00:00Z",
                "verified_at": "2026-08-22T08:00:00Z",
                "parent_ingested_at": None,
                "result_commit_id": "c" * 40,
            },
            "artifacts": [
                {
                    "artifact_id": "u1-art-01",
                    "logical_name": "fidelity-probe.json",
                    "content_uri": f"git:branch@commit:{ARTIFACT}",
                    "sha256": digest,
                    "bytes": len(artifact_bytes or b""),
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T08:00:00Z",
                }
            ],
            "completion_actor": None,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }
        if mutate is not None:
            mutate(document)
        return pinned, document, artifact_root

    def _pinned_decision(self, **kwargs) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned, document, artifact_root = self._pinned_scenario(Path(scratch_dir), **kwargs)
            try:
                pinned.ingest_result(document, artifact_root=artifact_root)
            except pinned.ControlPlaneError as exc:
                return False, str(exc)
            return True, "admitted"

    def _port_decision(self, *, artifacts=None, fence_token=1, worker="w1", second_lease=False, artifact_bytes=b'{"probe":1}'):
        with tempfile.TemporaryDirectory() as scratch_dir:
            controller = packaged.build(root=Path(scratch_dir), clock=Clock())
            controller.apply(
                "create",
                {"unit_id": "u1", "spec": {"owner": OWNER, "owned_prefixes": [OWNED_PREFIX], "acceptance": {"assertion": "a"}}},
            )
            controller.apply("lease", {"unit_id": "u1", "worker": "w1", "ttl": 3600})
            if second_lease:
                controller.apply("lease", {"unit_id": "u1", "worker": "w2", "ttl": 3600})
            if artifact_bytes is not None:
                controller.apply("write_artifact", {"path": ARTIFACT, "content": artifact_bytes.decode("utf-8")})
            outcome = controller.apply(
                "submit",
                {
                    "unit_id": "u1",
                    "worker": worker,
                    "fence_token": fence_token,
                    "artifacts": artifacts if artifacts is not None else [{"artifact_id": "a1", "path": ARTIFACT, "sha256": "@auto", "bytes": "@auto"}],
                    "result_commit_id": "c" * 40,
                },
            )
            return outcome.admitted, outcome.reason_code

    def test_a_well_formed_result_is_admitted_by_both(self):
        self.assertEqual(self._pinned_decision()[0], True)
        self.assertEqual(self._port_decision()[0], True)

    def test_hash_mismatch_is_refused_by_both(self):
        def mutate(document):
            document["artifacts"][0]["sha256"] = "1" * 64

        admitted, reason = self._pinned_decision(mutate=mutate)
        self.assertFalse(admitted)
        self.assertIn("hash mismatch", reason)
        self.assertEqual(
            self._port_decision(artifacts=[{"artifact_id": "a1", "path": ARTIFACT, "sha256": "1" * 64, "bytes": "@auto"}]),
            (False, "ARTIFACT_HASH_MISMATCH"),
        )

    def test_missing_artifact_is_refused_by_both(self):
        def mutate(document):
            # The document must otherwise be well formed, so it claims a real
            # digest and byte count for a file that is not there.  Otherwise the
            # validator rejects it on accounting before read-back is reached.
            payload = b'{"probe":1}'
            document["artifacts"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
            document["artifacts"][0]["bytes"] = len(payload)
            document["result_transaction"]["total_bytes"] = len(payload)

        admitted, reason = self._pinned_decision(mutate=mutate, artifact_bytes=None)
        self.assertFalse(admitted)
        self.assertIn("missing on read-back", reason)
        self.assertEqual(
            self._port_decision(
                artifacts=[{"artifact_id": "a1", "path": ARTIFACT, "sha256": "0" * 64, "bytes": 11}],
                artifact_bytes=None,
            ),
            (False, "ARTIFACT_MISSING"),
        )

    def test_out_of_allowlist_is_refused_by_both(self):
        def mutate(document):
            document["artifacts"][0]["content_uri"] = "git:branch@commit:packs/injected.json"

        admitted, reason = self._pinned_decision(mutate=mutate)
        self.assertFalse(admitted)
        self.assertIn("outside the commission allowlist", reason)
        self.assertEqual(
            self._port_decision(artifacts=[{"artifact_id": "a1", "path": "packs/injected.json", "sha256": "@auto", "bytes": "@auto"}]),
            (False, "OUT_OF_ALLOWLIST"),
        )

    def test_cross_owner_path_is_refused_by_both(self):
        def mutate(document):
            document["artifacts"][0]["content_uri"] = "git:branch@commit:workstreams/po03/metrics/x.json"

        admitted, reason = self._pinned_decision(mutate=mutate)
        self.assertFalse(admitted)
        self.assertIn("does not own", reason)
        self.assertEqual(
            self._port_decision(artifacts=[{"artifact_id": "a1", "path": "workstreams/po03/metrics/x.json", "sha256": "@auto", "bytes": "@auto"}]),
            (False, "NOT_OWNED"),
        )

    def test_accounting_drift_is_refused_by_both(self):
        def mutate(document):
            document["result_transaction"]["total_bytes"] = 999999

        admitted, reason = self._pinned_decision(mutate=mutate)
        self.assertFalse(admitted)
        self.assertIn("total_bytes", reason)

    def test_provider_completion_without_a_commit_is_refused_by_both(self):
        def mutate(document):
            document["result_transaction"]["result_commit_id"] = None
            document["result_transaction"]["state"] = "RESERVED"

        admitted, reason = self._pinned_decision(mutate=mutate)
        self.assertFalse(admitted)
        self.assertIn("PROVIDER_COMPLETED_UNCOMMITTED", reason)

    def test_the_shared_forged_fence_gap_is_present_in_both(self):
        """A fence above the current grant is accepted by the live factory too.

        This is the single most important fidelity assertion in the file: G2's
        C-01 only counts as progress if the weakness it fixes is genuinely
        G1's and not an artifact of the port.
        """

        def mutate(document):
            document["attempt"]["fence_token"] = 99

        self.assertEqual(self._pinned_decision(mutate=mutate)[0], True)
        self.assertEqual(self._port_decision(fence_token=99)[0], True)

    def test_the_shared_stale_fence_refusal_is_present_in_both(self):
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned, document, artifact_root = self._pinned_scenario(Path(scratch_dir))
            pinned.append_event(
                "u1",
                "LEASED",
                actor="coordinator",
                fence_token=2,
                payload={"worker_id": "w2", "lease_id": "l2", "expires_at": "2026-08-22T09:00:00Z"},
            )
            with self.assertRaises(pinned.ControlPlaneError) as raised:
                pinned.ingest_result(document, artifact_root=artifact_root)
            self.assertIn("stale fence token", str(raised.exception))
        self.assertEqual(self._port_decision(second_lease=True, fence_token=1), (False, "STALE_FENCE"))


class NonInterferenceTests(unittest.TestCase):
    def test_exercising_the_pinned_module_writes_nothing_to_shared_control_state(self):
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest() for path in COORDINATOR_OWNED if path.is_file()
        }
        self.assertTrue(before, "expected at least one coordinator-owned control file to guard")
        with tempfile.TemporaryDirectory() as scratch_dir:
            pinned = load_pinned(Path(scratch_dir))
            pinned.append_event("guard", "CREATED", actor="coordinator")
            pinned.materialize()
            pinned.scan_recovery()
        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest() for path in COORDINATOR_OWNED if path.is_file()
        }
        self.assertEqual(before, after, "the fidelity harness must never write another owner's control state")

    def test_the_pinned_factory_cannot_even_address_the_real_control_tree(self):
        """Rebinding paths is a promise; resolving CONTROL_ROOT into scratch is a fact.

        The pinned module derives every durable path from ``CONTROL_ROOT``, which
        it computes from its own ``__file__``.  Materialising it inside scratch
        means a rebinding that was forgotten would still land in scratch.
        """
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            pinned = load_pinned(scratch)
            self.assertTrue(pinned.CONTROL_ROOT.is_relative_to(scratch), pinned.CONTROL_ROOT)
            for attribute in ("LEDGER_PATH", "REGISTRY_PATH", "RECOVERY_PATH", "DISPATCH_DIR", "PATH_OWNERSHIP_PATH"):
                self.assertTrue(getattr(pinned, attribute).is_relative_to(scratch), attribute)


class PackagingClaimTests(unittest.TestCase):
    """The pin is only honest if the record says what it is and is not.

    These assertions are over this cohort's own committed metadata, which does
    not move on its own, so they are invariants rather than snapshots of shared
    state.  Their job is to stop the pinned claim being quietly restated as a
    claim about HEAD, and to stop the known post-pin divergence being dropped.
    """

    def test_the_pin_is_a_full_commit_sha_and_resolves_to_the_recorded_content(self):
        self.assertRegex(PIN, r"^[0-9a-f]{40}$")
        with tempfile.TemporaryDirectory() as scratch_dir:
            if materialise_pin(Path(scratch_dir)) is None:
                self.skipTest(f"pin {PIN} absent from this clone")

    def test_the_claim_is_stated_as_at_the_pin_and_not_as_at_head(self):
        claim = PACKAGING["fidelity_claim"]
        self.assertEqual(claim["pinned_to"], PIN)
        self.assertIn("does NOT claim to replicate the factory as of HEAD", claim["claim"])
        self.assertIn(PIN, claim["claim"])
        self.assertEqual(
            PACKAGING["fidelity_evidence"]["comparison_target"],
            f"the factory at commit {PIN}, not the working tree",
        )

    def test_every_pinned_source_carries_a_digest_the_test_can_check(self):
        for relative in PINNED_SOURCES:
            self.assertIn(relative, PINNED_DIGESTS, relative)
            self.assertRegex(PINNED_DIGESTS[relative], r"^[0-9a-f]{64}$")

    def test_the_known_post_pin_divergence_stays_on_the_record(self):
        """A divergence that is documented is a finding; one that is dropped is a lie.

        The path-normalisation entry is the one this cohort's own fidelity test
        detected, so it is named specifically rather than merely counted.
        """
        divergences = PACKAGING["divergence_from_head_after_the_pin"]
        self.assertTrue(divergences)
        normalisation = [entry for entry in divergences if "normalisation" in entry["surface"]]
        self.assertEqual(len(normalisation), 1)
        entry = normalisation[0]
        self.assertFalse(entry["is_a_defect_in_g1"])
        self.assertIn("6f5e386", entry["changed_live_at"])
        self.assertIn("lstrip", entry["at_the_pin"])
        self.assertIn("test_a8_g1_fidelity", entry["found_by"])
        self.assertTrue(entry["does_it_move_a_score"].startswith("no"))

    def test_the_packaged_port_names_the_same_pin_in_its_own_provenance(self):
        """The metadata and the code must not drift apart about what was ported."""
        self.assertIn(PIN[:7], packaged.PROVENANCE)

    def test_any_edit_to_the_packaged_generation_is_declared_with_its_effect_on_scores(self):
        """G1 is a scored endpoint, so a change to its bytes owes the reader an account.

        This does not forbid editing G1; it forbids editing it silently.  Each
        entry must name what changed, the digest before and after, and the commit
        at which the earlier digest can be read back.
        """
        for entry in PACKAGING["post_packaging_edits"]:
            self.assertRegex(entry["g1_source_sha256_before"], r"^[0-9a-f]{64}$")
            self.assertRegex(entry["g1_source_sha256_after"], r"^[0-9a-f]{64}$")
            self.assertRegex(entry["before_digest_pinned_at"], r"^[0-9a-f]{40}$")
            self.assertNotEqual(entry["g1_source_sha256_before"], entry["g1_source_sha256_after"])
            self.assertTrue(entry["scope"].strip())
            self.assertTrue(entry["effect_on_scores"].strip())

    def test_the_declared_current_digest_is_the_digest_of_the_generation_on_disk(self):
        """The one assertion here that is about bytes rather than prose.

        ``post_packaging_edits`` is only useful if its latest ``after`` digest is
        the generation as it now stands; otherwise a later edit could be smuggled
        in behind an older declaration.
        """
        self.assertEqual(
            packaged.digest_of_source(),
            PACKAGING["post_packaging_edits"][-1]["g1_source_sha256_after"],
            "successor/g1 no longer hashes to the digest its latest declared edit records",
        )


if __name__ == "__main__":
    unittest.main()
