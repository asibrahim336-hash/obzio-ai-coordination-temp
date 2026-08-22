"""Adversarial audit of the coordinator's tools/control_plane.py (a10-u03).

Every case here runs the real, unmodified control_plane.py as a subprocess
against an isolated scratch copy (see
workstreams/po03/review/sonnet/attacks/scratch_control_plane.py). No shared
ledger, dispatch record or other cohort's path is touched. This follows the
frozen plan in workstreams/po03/review/sonnet/criteria-coordinator-control-plane.json.

Run with:
    python3 -I -m unittest workstreams.po03.tests.test_a10_control_plane_attacks -v
or via the full discovery gate:
    python3 -I -m unittest discover -s workstreams/po03/tests -p 'test_*.py'
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ATTACKS_DIR = Path(__file__).resolve().parents[1] / "review" / "sonnet" / "attacks"
sys.path.insert(0, str(_ATTACKS_DIR))

from scratch_control_plane import ScratchControlPlane, sha256_bytes  # noqa: E402


class ScratchCaseMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="a10-attack-")
        self.base = Path(self._tmp.name)
        self.scp = ScratchControlPlane(self.base)
        # Register the attacker as a legitimate owner of its own subtree so
        # ownership checks exercise the real boundary logic under test,
        # rather than failing every case on "unknown owner".
        self.scp.write_ownership(
            {
                "attacker": {
                    "owned_prefixes": ["workstreams/po03/control/units/attacker/"],
                },
                "legit-reviewer": {"owned_prefixes": []},
            }
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestInv1CompletionRequiresIngestion(ScratchCaseMixin):
    """INV-1: a producer must not reach COMPLETED without coordinator ingestion."""

    def test_complete_before_any_ingestion_is_rejected(self):
        dispatch = self.scp.create_unit("inv1-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        self.scp.lease("inv1-u1", "attacker")
        result = self.scp.complete("inv1-u1")
        self.assertNotEqual(result.returncode, 0, "HELD would require rejection; got success")
        self.assertIn("PARENT_INGESTED", result.stdout + result.stderr)


class TestInv2FenceToken(ScratchCaseMixin):
    """INV-2: a stale fence token must not commit after ownership transfer."""

    def test_a_stale_fence_after_release_is_rejected(self):
        dispatch = self.scp.create_unit("inv2a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease1 = self.scp.lease("inv2a-u1", "attacker")
        self.scp.lease("inv2a-u1", "attacker")  # simulates re-lease after expiry, bumps fence
        content = b'{"attempt": "stale"}'
        path = self.scp.write_file_at("workstreams/po03/control/units/attacker/inv2a.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease1["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv2a",
                    "content_uri": "workstreams/po03/control/units/attacker/inv2a.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="stale")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires the stale fence to be rejected")
        self.assertIn("stale", (outcome.stdout + outcome.stderr).lower())

    def test_b_never_leased_fence_token_is_accepted_BREAK(self):
        """BREAK: ingest_result only checks `incoming_fence < unit['fence_token']`
        (a monotonicity check), never that the fence token was actually granted
        by a `lease` call. A unit that has *never* been leased starts at
        fence_token == 0 in the projection, so any self-chosen fence_token >= 1
        is accepted, impersonating a lease holder that never existed."""
        dispatch = self.scp.create_unit("inv2b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        # Deliberately never call self.scp.lease(...): unit["fence_token"] stays 0.
        content = b'{"attempt": "never leased, fence fabricated"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv2b.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=1,  # never granted by any `lease` call
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv2b",
                    "content_uri": "workstreams/po03/control/units/attacker/inv2b.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="unleased")
        self.assertEqual(
            outcome.returncode,
            0,
            f"expected the BREAK (ingestion succeeds with a never-leased fence token); got rejection: {outcome.stdout} {outcome.stderr}",
        )
        rows = self.scp.ledger_rows()
        ingested = [r for r in rows if r["unit_id"] == "inv2b-u1" and r["event"] == "PARENT_INGESTED"]
        self.assertEqual(len(ingested), 1, "the never-leased fence token was committed into the ledger")


class TestInv3DuplicateCallbacks(ScratchCaseMixin):
    """INV-3: a duplicate callback must not produce two effects."""

    def test_a_byte_identical_duplicate_is_a_harmless_noop(self):
        dispatch = self.scp.create_unit("inv3a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv3a-u1", "attacker")
        content = b'{"v": 1}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv3a.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv3a",
                    "content_uri": "workstreams/po03/control/units/attacker/inv3a.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        first = self.scp.ingest(doc, tag="first")
        self.assertEqual(first.returncode, 0)
        second = self.scp.ingest(doc, tag="second")
        self.assertEqual(second.returncode, 0)
        rows = self.scp.ledger_rows()
        ingested = [r for r in rows if r["unit_id"] == "inv3a-u1" and r["event"] == "PARENT_INGESTED"]
        duplicates = [r for r in rows if r["unit_id"] == "inv3a-u1" and r["event"] == "DUPLICATE_IGNORED"]
        self.assertEqual(len(ingested), 1, "HELD requires exactly one PARENT_INGESTED row")
        self.assertEqual(len(duplicates), 1, "HELD requires the second call to be recorded as a duplicate")

    def test_b_non_identical_resubmission_after_completed_enables_second_completion_BREAK(self):
        """BREAK: dedup is keyed on sha256(canonical(full result document)), not on
        task_id alone. A unit already COMPLETED that receives a *different*
        result document (different artifact bytes, same dispatch/acceptance
        hashes) is NOT recognised as a duplicate, is re-ingested, and the
        generic `obzio_state = row['event']` fallback in project_units resets
        the projected state from COMPLETED back to PARENT_INGESTED -- allowing
        `complete` to run a second time and append a second COMPLETED row for
        the same unit with different underlying artifacts."""
        dispatch = self.scp.create_unit("inv3b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv3b-u1", "attacker")
        content_v1 = b'{"v": 1, "payload": "original"}'
        artifact_path = "workstreams/po03/control/units/attacker/inv3b.json"
        self.scp.write_file_at(artifact_path, content_v1)
        doc_v1 = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv3b",
                    "content_uri": artifact_path,
                    "sha256": sha256_bytes(content_v1),
                    "bytes": len(content_v1),
                }
            ],
            checkpoint_seq=1,
        )
        ingest1 = self.scp.ingest(doc_v1, tag="v1")
        self.assertEqual(ingest1.returncode, 0)
        complete1 = self.scp.complete("inv3b-u1")
        self.assertEqual(complete1.returncode, 0, "first completion must succeed to set up the attack")

        # Attacker overwrites their own artifact with different content after
        # COMPLETED and resubmits. Same fence token is still accepted (see
        # INV-2 finding); nothing requires a fresh lease post-completion.
        content_v2 = b'{"v": 2, "payload": "swapped after acceptance"}'
        self.scp.write_file_at(artifact_path, content_v2)
        doc_v2 = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv3b",
                    "content_uri": artifact_path,
                    "sha256": sha256_bytes(content_v2),
                    "bytes": len(content_v2),
                }
            ],
            checkpoint_seq=2,
            result_commit_id="e" * 40,
        )
        ingest2 = self.scp.ingest(doc_v2, tag="v2")
        self.assertEqual(
            ingest2.returncode,
            0,
            f"expected the BREAK (second, non-identical ingestion accepted after COMPLETED); got: {ingest2.stdout} {ingest2.stderr}",
        )
        complete2 = self.scp.complete("inv3b-u1")
        self.assertEqual(
            complete2.returncode,
            0,
            f"expected the BREAK (second completion accepted for an already-COMPLETED unit); got: {complete2.stdout} {complete2.stderr}",
        )
        rows = self.scp.ledger_rows()
        completed_rows = [r for r in rows if r["unit_id"] == "inv3b-u1" and r["event"] == "COMPLETED"]
        self.assertEqual(
            len(completed_rows),
            2,
            f"BREAK confirmed only if two distinct COMPLETED ledger rows exist for one unit; found {len(completed_rows)}",
        )
        self.assertNotEqual(
            completed_rows[0]["payload"].get("result_commit_id"),
            completed_rows[1]["payload"].get("result_commit_id"),
            "the two COMPLETED rows reference two different result_commit_id values for the same unit_id",
        )


class TestInv4ReadbackByteMismatch(ScratchCaseMixin):
    """INV-4: an artifact must not pass read-back without matching bytes."""

    def test_hash_mismatch_at_readback_is_rejected(self):
        dispatch = self.scp.create_unit("inv4-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv4-u1", "attacker")
        real_content = b'{"real": "content"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv4.json", real_content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv4",
                    "content_uri": "workstreams/po03/control/units/attacker/inv4.json",
                    "sha256": sha256_bytes(b"claimed different content"),
                    "bytes": len(real_content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="mismatch")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires hash-mismatched artifact rejection")
        self.assertIn("hash mismatch", outcome.stdout + outcome.stderr)

    def test_missing_artifact_at_readback_is_rejected(self):
        dispatch = self.scp.create_unit("inv4-u2", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv4-u2", "attacker")
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv4-missing",
                    "content_uri": "workstreams/po03/control/units/attacker/never-written.json",
                    "sha256": sha256_bytes(b"anything"),
                    "bytes": 8,
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="missing")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires missing-artifact rejection")
        self.assertIn("missing on read-back", outcome.stdout + outcome.stderr)


class TestInv5WrongDispatchManifest(ScratchCaseMixin):
    """INV-5: a result must not be accepted if it references a dispatch
    manifest it was not issued under."""

    def test_manifest_sha_copied_from_a_different_unit_is_rejected(self):
        dispatch_x = self.scp.create_unit("inv5-x", "attacker", ["workstreams/po03/control/units/attacker/"])
        dispatch_y = self.scp.create_unit("inv5-y", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease_x = self.scp.lease("inv5-x", "attacker")
        content = b'{"cross": "manifest"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv5.json", content)
        doc = self.scp.build_result_doc(
            dispatch_x,
            fence_token=lease_x["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv5",
                    "content_uri": "workstreams/po03/control/units/attacker/inv5.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
            manifest_sha_override=dispatch_y["immutable_input_manifest_sha256"],
        )
        outcome = self.scp.ingest(doc, tag="crossmanifest")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires rejection of a foreign manifest reference")
        self.assertIn("immutable input manifest", outcome.stdout + outcome.stderr)


class TestInv6AllowlistAndOwnershipEscape(ScratchCaseMixin):
    """INV-6: a write outside the allowlist or outside the owner's subtree
    must not pass ingestion."""

    def test_a_mid_string_traversal_is_rejected(self):
        dispatch = self.scp.create_unit("inv6a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv6a-u1", "attacker")
        content = b'{"escape": "attempt"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv6a.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv6a",
                    "content_uri": "workstreams/po03/control/units/attacker/../../a4/inv6a.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="midtraversal")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires a literal '..' segment to be rejected")

    def test_b_leading_dotslash_traversal_escapes_repo_root_BREAK(self):
        """BREAK: `path_in_allowlist`/`check_ownership` normalise with
        `path.strip().lstrip("./")`. `str.lstrip` treats its argument as a set
        of characters, not a prefix, so a leading run composed *only* of '.'
        and '/' characters (e.g. "../") is stripped in its entirety, leaving a
        normalised string that starts with an allowed/owned prefix and
        contains no residual '..' component -- while the RAW string used for
        the actual filesystem join (`artifact_root / relative`) still contains
        the traversal and is resolved by the OS exactly as written, walking
        out of the repo root before descending back into a path that merely
        *looks* like it is inside workstreams/po03/control/units/attacker/.
        """
        dispatch = self.scp.create_unit("inv6b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv6b-u1", "attacker")

        decoy_content = b'{"not_owned_by_attacker": true, "lives_outside_repo_root": true}'
        # Sibling of scp.root ("repo/"), i.e. genuinely outside the scratch
        # repository / allowlist / owner subtree.
        self.scp.write_file_outside(
            "workstreams/po03/control/units/attacker/escaped.json", decoy_content
        )

        traversal_uri = "../workstreams/po03/control/units/attacker/escaped.json"
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv6b-escaped",
                    "content_uri": traversal_uri,
                    "sha256": sha256_bytes(decoy_content),
                    "bytes": len(decoy_content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="leadingdotslash")
        self.assertEqual(
            outcome.returncode,
            0,
            f"expected the BREAK (traversal outside repo root passes ingestion); got rejection: {outcome.stdout} {outcome.stderr}",
        )
        # Prove the decoy file genuinely lives outside the repo root, so this
        # is not an accidental same-directory coincidence.
        decoy_path = self.scp.base / "workstreams/po03/control/units/attacker/escaped.json"
        self.assertTrue(decoy_path.exists())
        self.assertFalse(str(decoy_path).startswith(str(self.scp.root)))

    def test_c_string_level_divergence_absolute_path(self):
        """Companion, code-level demonstration (no subprocess needed): an
        absolute content_uri that happens to start with an allowed prefix once
        its leading '/' is lstripped is judged in-allowlist and in-ownership
        by the validator, while pathlib's `/` operator treats an absolute
        right operand as a full path override, discarding artifact_root
        entirely. This shows the class of bug is not limited to relative
        '../' traversal."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("scratch_cp", self.scp.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # nosec - executing our own scratch copy only

        absolute_uri = "/workstreams/po03/control/units/attacker/evil.json"
        self.assertTrue(
            module.path_in_allowlist(absolute_uri),
            "the absolute path is judged in-allowlist by the string check",
        )
        self.assertEqual(
            module.check_ownership("attacker", [absolute_uri]),
            [],
            "the absolute path is judged fully owned by the string check",
        )
        joined = self.scp.root / absolute_uri
        self.assertEqual(
            joined,
            Path(absolute_uri),
            "pathlib's `/` operator discards artifact_root entirely for an absolute operand",
        )
        self.assertFalse(str(joined).startswith(str(self.scp.root)))


class TestInv7SelfAcceptance(ScratchCaseMixin):
    """INV-7: a producer must not accept its own work."""

    def test_a_exact_owner_string_is_rejected(self):
        dispatch = self.scp.create_unit("inv7a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv7a-u1", "attacker")
        content = b'{"self": "accept"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv7a.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv7a",
                    "content_uri": "workstreams/po03/control/units/attacker/inv7a.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        self.scp.ingest(doc, tag="selfaccept")
        self.scp.complete("inv7a-u1")
        outcome = self.scp.review("inv7a-u1", "ACCEPTED", reviewer="attacker")
        self.assertNotEqual(outcome.returncode, 0, "HELD requires literal self-id rejection")
        self.assertIn("cannot accept or reject its own work", outcome.stdout + outcome.stderr)

    def test_b_alias_reviewer_id_is_accepted_BOUNDARY(self):
        """BOUNDARY (not a full break, but a real gap): the self-acceptance
        guard is a byte-equality check against dispatch['owner']. There is no
        mechanism binding the --reviewer argument to any authenticated
        identity, so the *same* actor can self-review by passing any string
        other than the exact owner id."""
        dispatch = self.scp.create_unit("inv7b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv7b-u1", "attacker")
        content = b'{"self": "accept via alias"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv7b.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv7b",
                    "content_uri": "workstreams/po03/control/units/attacker/inv7b.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        self.scp.ingest(doc, tag="aliasaccept")
        self.scp.complete("inv7b-u1")
        outcome = self.scp.review("inv7b-u1", "ACCEPTED", reviewer="attacker-alias-not-byte-equal")
        self.assertEqual(
            outcome.returncode,
            0,
            "documents the boundary: any non-exact-match reviewer string is accepted with no identity check",
        )


class TestInv8LedgerTamper(ScratchCaseMixin):
    """INV-8: a tampered ledger row must not pass chain verification."""

    def test_a_in_place_edit_without_rehash_is_rejected(self):
        dispatch = self.scp.create_unit("inv8a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        self.scp.lease("inv8a-u1", "attacker")
        rows = self.scp.ledger_rows()
        self.assertGreaterEqual(len(rows), 2)
        rows[0]["payload"]["tampered"] = True  # edit without recomputing row_sha256
        self.scp.write_ledger_rows(rows)
        outcome = self.scp.verify()
        self.assertNotEqual(outcome.returncode, 0, "HELD requires an un-rehashed edit to break the chain")

    def test_b_cascade_rehashed_tamper_passes_verification_BREAK(self):
        """BREAK: verify_chain only checks internal self-consistency (each
        row's own hash, and that it chains to the row before it). It has no
        external anchor (no previously-recorded/pinned head hash outside the
        file itself), so an actor with write access to the ledger file can
        rewrite a row's payload and cascade-recompute every subsequent row's
        row_sha256/prev_sha256, producing a fully self-consistent chain that
        `verify_chain`/`cmd_verify` reports as valid despite the tamper.
        Because this is git-tracked content, the real deployment argues this
        is *evident* via git diff -- but nothing in the code itself detects
        it, which is exactly what this unit was asked to attack.
        """
        import hashlib as _hashlib

        def _canon(obj):
            return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        def _sha(text):
            return _hashlib.sha256(text.encode("utf-8")).hexdigest()

        dispatch = self.scp.create_unit("inv8b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        self.scp.lease("inv8b-u1", "attacker")
        content = b'{"v": 1}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv8b.json", content)
        lease_row_fence = 1
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease_row_fence,
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv8b",
                    "content_uri": "workstreams/po03/control/units/attacker/inv8b.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
        )
        self.scp.ingest(doc, tag="pretamper")
        self.scp.complete("inv8b-u1")
        # A legitimate reviewer rejects it.
        self.scp.review("inv8b-u1", "REJECTED", reviewer="legit-reviewer", receipt="receipt://legit")

        rows = self.scp.ledger_rows()
        pre_verify = self.scp.verify()
        self.assertEqual(pre_verify.returncode, 0, "sanity: untampered chain verifies clean")

        target_index = next(i for i, r in enumerate(rows) if r["event"] == "REJECTED")
        rows[target_index]["event"] = "ACCEPTED"
        rows[target_index]["payload"]["rationale"] = "silently swapped from REJECTED"

        previous_hash = rows[target_index - 1]["row_sha256"] if target_index > 0 else "0" * 64
        for i in range(target_index, len(rows)):
            rows[i]["prev_sha256"] = previous_hash
            body = {k: v for k, v in rows[i].items() if k != "row_sha256"}
            rows[i]["row_sha256"] = _sha(_canon(body))
            previous_hash = rows[i]["row_sha256"]

        self.scp.write_ledger_rows(rows)
        outcome = self.scp.verify()
        self.assertEqual(
            outcome.returncode,
            0,
            f"expected the BREAK (cascade-rehashed tamper still verifies clean); got: {outcome.stdout} {outcome.stderr}",
        )
        tampered_rows = self.scp.ledger_rows()
        self.assertEqual(tampered_rows[target_index]["event"], "ACCEPTED")


class TestInv9ProviderCompletedUncommitted(ScratchCaseMixin):
    """INV-9: a PROVIDER_COMPLETED_UNCOMMITTED unit must never be reported as
    COMPLETED."""

    def test_schema_forces_the_label_when_result_commit_id_is_empty(self):
        dispatch = self.scp.create_unit("inv9a-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv9a-u1", "attacker")
        content = b'{"uncommitted": true}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv9a.json", content)
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv9a",
                    "content_uri": "workstreams/po03/control/units/attacker/inv9a.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
            obzio_state="COMPLETED",
            result_commit_id="",
        )
        doc["result_transaction"]["result_commit_id"] = None
        import sys as _sys

        sys.path.insert(0, str(_ATTACKS_DIR))
        import importlib.util

        vspec = importlib.util.spec_from_file_location(
            "scratch_validate", self.scp.root / "workstreams/po03/tools/validate_contracts.py"
        )
        vmodule = importlib.util.module_from_spec(vspec)
        vspec.loader.exec_module(vmodule)
        errors = vmodule.validate_result(doc)
        self.assertTrue(
            any("PROVIDER_COMPLETED_UNCOMMITTED" in e for e in errors),
            f"HELD requires the schema validator to force the honest label; errors={errors}",
        )

    def test_fabricated_result_commit_id_over_uncommitted_working_tree_file_reaches_completed_BREAK(self):
        """BREAK: `ingest_result` never checks that `result_commit_id` refers
        to a real git commit. It only re-hashes whatever file currently sits
        on disk at the claimed path. This scratch repo has no `.git` at all,
        so *no* result_commit_id here could possibly be real, yet a
        syntactically well-formed, entirely fabricated commit id is accepted
        at face value and the unit reaches COMPLETED -- the exact
        PROVIDER_COMPLETED_UNCOMMITTED-as-COMPLETED failure mode the
        commission names as the reason this control plane exists.
        """
        self.assertFalse((self.scp.root / ".git").exists(), "sanity: scratch repo genuinely has no git history")
        dispatch = self.scp.create_unit("inv9b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv9b-u1", "attacker")
        content = b'{"claimed_committed": true, "actually": "just a loose file, never git-committed"}'
        self.scp.write_file_at("workstreams/po03/control/units/attacker/inv9b.json", content)
        fabricated_commit_id = "f" * 40  # never created by any `git commit`
        doc = self.scp.build_result_doc(
            dispatch,
            fence_token=lease["fence_token"],
            artifacts=[
                {
                    "artifact_id": "a1",
                    "logical_name": "inv9b",
                    "content_uri": "workstreams/po03/control/units/attacker/inv9b.json",
                    "sha256": sha256_bytes(content),
                    "bytes": len(content),
                }
            ],
            obzio_state="RESULT_COMMITTED",
            result_commit_id=fabricated_commit_id,
        )
        ingest_outcome = self.scp.ingest(doc, tag="fakecommit")
        self.assertEqual(ingest_outcome.returncode, 0, "ingest_result never validates result_commit_id against git")
        complete_outcome = self.scp.complete("inv9b-u1")
        self.assertEqual(
            complete_outcome.returncode,
            0,
            f"expected the BREAK (COMPLETED reached on a fabricated, unverified result_commit_id in a repo with no git history at all); got: {complete_outcome.stdout} {complete_outcome.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
