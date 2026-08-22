"""Adversarial audit of the coordinator's tools/control_plane.py (a10-u03).

Every case here runs the real, unmodified control_plane.py as a subprocess
against an isolated scratch copy (see
workstreams/po03/review/sonnet/attacks/scratch_control_plane.py). No shared
ledger, dispatch record or other cohort's path is touched. This follows the
frozen plan in workstreams/po03/review/sonnet/criteria-coordinator-control-plane.json.

v2 revision note (post coordinator follow-up on the v1 a10-u03/u01/u02/u04
results): two structural fixes and a rewrite of every BREAK/BOUNDARY case's
assertion direction.

1. The scratch harness (scratch_control_plane.py) used to stage only two
   hand-picked files. Cohort a12 made validate_contracts.py load its schema
   from a sibling file at import time, and every subprocess here started
   dying with FileNotFoundError before reaching the code under attack --
   including every positive control, not a stale assertion. Root-caused and
   fixed there as DEF-19; see that module's docstring.
2. INV-6's original BREAK was reproduced against a pre-fix snapshot; the real
   fix landed at commit 6f5e386 before the coordinator ingested this
   reviewer's v1 result (a snapshot-coupling defect in the audit direction,
   per workstreams/po03/evidence/snapshot-coupling.json). Every BREAK/BOUNDARY
   case below now follows the binding rule stated by the coordinator: assert
   an invariant, or assert reproduction at an explicit immutable pin --
   never assert that a defect currently exists against a moving HEAD. Cases
   for defects already fixed are pinned to the last pre-fix commit; cases for
   defects still live with a named future remediation unit are rewritten as
   `@unittest.expectedFailure` guards asserting the desired, fixed behaviour
   (exactly as cohort a2 did for its eight), so they read red today and an
   *unexpected success* -- not a silent pass -- is the signal that the
   remediation landed.

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

# Last commit before 6f5e386 ("po03: fix allowlist path normalisation and
# cover custody invariants"), which replaced the str.lstrip('./') normaliser
# this reviewer's original INV-6 finding exploited. Pinning here means the
# historical finding stays provable forever regardless of what HEAD contains.
INV6_PRE_FIX_COMMIT = "dd2fcc63694bea365153a5930472816037b6e4ff"

# origin/cursor/po03-wave-a-transactional-factory-ed20 as merged into this
# reviewer's branch for this v2 audit cycle -- an already-pushed, shared,
# immutable commit. Used to pin findings that are still live but have no
# named remediation unit yet (so an expected-failure guard would have no
# remediation to name), and for a boundary whose remediation contract
# explicitly permits more than one shape of fix.
AUDIT_SNAPSHOT_COMMIT = "083ff506cde258cc9cbfde2b49c3f61aa6c2401c"


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

    @unittest.expectedFailure
    def test_defect_never_leased_fence_token_must_be_rejected(self):
        """Desired invariant, not yet held. Remediation dispatched as
        a11-u03 ("hardened fence check plus recurrence test"; a2 measured 10
        of 10 unissued higher fences accepted before the fix). Currently
        BROKEN against current HEAD: ingest_result only checks
        `incoming_fence < unit['fence_token']` (a monotonicity check), never
        that the fence token was actually granted by a `lease` call. A unit
        that has *never* been leased starts at fence_token == 0 in the
        projection, so any self-chosen fence_token >= 1 is accepted,
        impersonating a lease holder that never existed. Written for the
        FIXED behaviour per the binding pin-or-invariant rule: fails today
        (expected), and will surface as an *unexpected success* -- not a
        silent pass -- the moment a11-u03 lands, which is the signal to
        remove this decorator and promote it to a plain positive control.
        """
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
        self.assertNotEqual(
            outcome.returncode,
            0,
            "desired: ingestion must reject a fence token that no `lease` call ever issued",
        )


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

    @unittest.expectedFailure
    def test_defect_a_unit_must_never_accumulate_two_completed_events(self):
        """Desired invariant, not yet held. This reviewer's original finding
        (v1 a10-u03) was independently reproduced by the coordinator and is
        now the single most severe finding of the wave -- registered as
        a11-u14 at CRITICAL, above fabricated completion, because it
        rewrites the content of an already-accepted deliverable while every
        gate reports clean. Root causes, in the coordinator's own words:
        dedup keys on sha256(canonical(the whole result document)) rather
        than unit identity; ingestion has no terminal-state guard; the
        projection lets a later event regress a unit out of COMPLETED; and
        `cmd_complete` checks only the current state, never whether the unit
        was EVER completed. This asserts the invariant a11-u14 is required
        to hold -- at most one COMPLETED event may ever exist per unit --
        rather than which specific call (ingest or complete) must be the one
        to refuse the second attempt, so it stays meaningful regardless of
        which of those four root causes a11 closes first. Per the binding
        pin-or-invariant rule this is written for the desired behaviour, not
        the current break, so it fails today (expected) and an unexpected
        success is the signal a11-u14 landed.
        """
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
        # Neither call's return code is asserted here: a11-u14 may close this
        # by having `ingest` refuse the non-identical resubmission, by having
        # `complete` refuse to run a second time, or both. What must hold
        # regardless is the final ledger state.
        self.scp.ingest(doc_v2, tag="v2")
        self.scp.complete("inv3b-u1")
        rows = self.scp.ledger_rows()
        completed_rows = [r for r in rows if r["unit_id"] == "inv3b-u1" and r["event"] == "COMPLETED"]
        self.assertEqual(
            len(completed_rows),
            1,
            "desired invariant (a11-u14): at most one COMPLETED event may ever "
            f"exist for one unit; found {len(completed_rows)}",
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
    must not pass ingestion.

    This reviewer's v1 audit found `path_in_allowlist`/`check_ownership`
    normalising with `path.strip().lstrip("./")`. Because `str.lstrip` treats
    its argument as a character set, not a prefix, a leading run composed
    only of '.' and '/' characters (e.g. "../") was stripped away entirely,
    leaving a normalised string that looked safely inside an allowed/owned
    prefix while the RAW string used for the actual filesystem join in
    `ingest_result` still contained the traversal, resolved by the OS exactly
    as written. That was fixed at commit 6f5e386, before the coordinator
    ingested this reviewer's v1 result: `normalise_path` now returns None --
    treated as "not in allowlist / not owned" by every caller -- for anything
    absolute, empty, or containing a literal '.' or '..' *segment*, instead
    of repairing it.

    Per the binding "assert an invariant, or assert reproduction at an
    explicit immutable pin" rule, the original finding is preserved forever
    by pinning it to INV6_PRE_FIX_COMMIT rather than re-asserted against a
    HEAD where it no longer reproduces. test_d/test_e below confirm the
    corrected state against current code as live invariants, and test_f
    reports one residual, still-live divergence in the same function this
    reviewer's v1 audit did not find.
    """

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

    def test_b_leading_dotslash_traversal_pinned_historical_BREAK(self):
        """Pinned-historical: reproduces, forever, exactly as this reviewer
        found it at INV6_PRE_FIX_COMMIT (dd2fcc6, the last commit before
        6f5e386). Never re-targeted at a moving HEAD -- see class docstring.
        """
        with tempfile.TemporaryDirectory(prefix="a10-attack-hist6b-") as histtmp:
            historical = ScratchControlPlane(Path(histtmp), commit=INV6_PRE_FIX_COMMIT)
            historical.write_ownership(
                {
                    "attacker": {"owned_prefixes": ["workstreams/po03/control/units/attacker/"]},
                    "legit-reviewer": {"owned_prefixes": []},
                }
            )
            dispatch = historical.create_unit("inv6b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
            lease = historical.lease("inv6b-u1", "attacker")

            decoy_content = b'{"not_owned_by_attacker": true, "lives_outside_repo_root": true}'
            # Sibling of historical.root ("repo/"), i.e. genuinely outside the
            # scratch repository / allowlist / owner subtree.
            historical.write_file_outside(
                "workstreams/po03/control/units/attacker/escaped.json", decoy_content
            )

            traversal_uri = "../workstreams/po03/control/units/attacker/escaped.json"
            doc = historical.build_result_doc(
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
            outcome = historical.ingest(doc, tag="leadingdotslash")
            self.assertEqual(
                outcome.returncode,
                0,
                f"historical reproduction at {INV6_PRE_FIX_COMMIT} must still hold "
                f"(traversal outside repo root passes ingestion); got rejection: "
                f"{outcome.stdout} {outcome.stderr}",
            )
            # Prove the decoy file genuinely lives outside the repo root, so this
            # is not an accidental same-directory coincidence.
            decoy_path = historical.base / "workstreams/po03/control/units/attacker/escaped.json"
            self.assertTrue(decoy_path.exists())
            self.assertFalse(str(decoy_path).startswith(str(historical.root)))

    def test_c_string_level_divergence_absolute_path_pinned_historical(self):
        """Pinned-historical companion (code-level, no subprocess needed) of
        test_b, at the same immutable pre-fix commit: an absolute content_uri
        that happens to start with an allowed prefix once its leading '/' is
        lstripped was judged in-allowlist and in-ownership by the validator,
        while pathlib's `/` operator treats an absolute right operand as a
        full path override, discarding artifact_root entirely."""
        with tempfile.TemporaryDirectory(prefix="a10-attack-hist6c-") as histtmp:
            historical = ScratchControlPlane(Path(histtmp), commit=INV6_PRE_FIX_COMMIT)
            historical.write_ownership(
                {
                    "attacker": {"owned_prefixes": ["workstreams/po03/control/units/attacker/"]},
                    "legit-reviewer": {"owned_prefixes": []},
                }
            )
            import importlib.util

            spec = importlib.util.spec_from_file_location("scratch_cp_historical", historical.script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # nosec - executing our own scratch copy only

            absolute_uri = "/workstreams/po03/control/units/attacker/evil.json"
            self.assertTrue(
                module.path_in_allowlist(absolute_uri),
                f"historical reproduction at {INV6_PRE_FIX_COMMIT} must still hold: "
                "the absolute path is judged in-allowlist by the string check",
            )
            self.assertEqual(
                module.check_ownership("attacker", [absolute_uri]),
                [],
                "the absolute path is judged fully owned by the string check",
            )
            joined = historical.root / absolute_uri
            self.assertEqual(
                joined,
                Path(absolute_uri),
                "pathlib's `/` operator discards artifact_root entirely for an absolute operand",
            )
            self.assertFalse(str(joined).startswith(str(historical.root)))

    def test_d_corrected_state_rejects_all_four_coordinator_cited_escapes(self):
        """Live invariant against CURRENT code (self.scp defaults to HEAD):
        confirms the four escapes the coordinator explicitly named as
        now-rejected. This is intentionally NOT pinned -- it is expected to
        keep passing, and it going red on some future HEAD would itself be
        exactly the live regression the coordinator asked this reviewer to
        watch for.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location("scratch_cp_current", self.scp.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # nosec - executing our own scratch copy only

        for escape in (
            "./../packs/x.json",
            "workstreams/po03/engine/../../../etc/passwd",
            "/etc/passwd",
            "workstreams/po03/../po01/x",
        ):
            with self.subTest(escape=escape):
                self.assertFalse(
                    module.path_in_allowlist(escape), f"{escape!r} must not be judged in-allowlist"
                )
        violations = module.check_ownership(
            "attacker",
            ["workstreams/po03/engine/../../../etc/passwd", "/etc/passwd"],
        )
        self.assertEqual(
            len(violations), 2, f"both traversal and absolute cases must be flagged; got {violations}"
        )

    def test_e_end_to_end_traversal_still_rejected_at_ingestion_current_code(self):
        """End-to-end confirmation against current code, not just the
        unit-level normaliser: the original test_b attack no longer reaches
        ingestion. Live invariant, not pinned; see test_d docstring."""
        dispatch = self.scp.create_unit("inv6d-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
        lease = self.scp.lease("inv6d-u1", "attacker")
        decoy_content = b'{"not_owned_by_attacker": true}'
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
                    "logical_name": "inv6d-escaped",
                    "content_uri": traversal_uri,
                    "sha256": sha256_bytes(decoy_content),
                    "bytes": len(decoy_content),
                }
            ],
        )
        outcome = self.scp.ingest(doc, tag="leadingdotslash-current")
        self.assertNotEqual(
            outcome.returncode,
            0,
            f"corrected state requires this to be rejected now; got: {outcome.stdout} {outcome.stderr}",
        )

    def test_f_residual_divergence_exact_file_owned_prefix_permits_sibling_suffix_BREAK(self):
        """LIVE, currently-unremediated residual finding (new in this v2
        audit; not present in the a10-u03 v1 findings.json). `check_ownership`
        still confines an owner using `normalised.startswith(prefixes)`, a
        plain STRING prefix test with no path-segment boundary. That is safe
        for every *directory-style* owned_prefix (all end in '/', so a
        sibling directory's name can never share the string prefix), but the
        real, current production path-ownership.json also grants several
        cohorts (po03-worker-a2, a3, a4, a8 as of this audit) ownership of an
        EXACT FILE with no trailing separator -- e.g. po03-worker-a2 owns the
        literal string 'workstreams/po03/evidence/recovery-fault-matrix.json'.
        For any such entry, `check_ownership` also accepts any path that
        merely starts with that string, e.g. the same file name with an
        arbitrary suffix appended, with no real relationship to the actual
        named file. This is the same "string prefix diverges from the actual
        object identity" root cause as the fixed traversal bug, one level up
        (file identity instead of path traversal), and it is still present
        in current code. Pinned to AUDIT_SNAPSHOT_COMMIT because no
        remediation unit has been dispatched for it yet -- report and
        dispatch one, then convert this to an expected-failure guard.
        """
        with tempfile.TemporaryDirectory(prefix="a10-attack-residual6-") as histtmp:
            snap = ScratchControlPlane(Path(histtmp), commit=AUDIT_SNAPSHOT_COMMIT)
            owned_file = "workstreams/po03/control/units/attacker/exact-file.json"
            snap.write_ownership({"attacker": {"owned_prefixes": [owned_file]}})
            dispatch = snap.create_unit("inv6residual-u1", "attacker", [owned_file])
            lease = snap.lease("inv6residual-u1", "attacker")
            content = b'{"sibling": "file, never named in owned_prefixes"}'
            sibling_path = owned_file + "-EVIL-SIBLING-NOT-THE-REAL-FILE"
            snap.write_file_at(sibling_path, content)
            doc = snap.build_result_doc(
                dispatch,
                fence_token=lease["fence_token"],
                artifacts=[
                    {
                        "artifact_id": "a1",
                        "logical_name": "evil-sibling",
                        "content_uri": sibling_path,
                        "sha256": sha256_bytes(content),
                        "bytes": len(content),
                    }
                ],
            )
            outcome = snap.ingest(doc, tag="residual")
            self.assertEqual(
                outcome.returncode,
                0,
                "expected the BREAK (a sibling file passes ownership on a bare "
                f"string-prefix match of an exact-file owned_prefix, at pin "
                f"{AUDIT_SNAPSHOT_COMMIT}); got rejection: {outcome.stdout} {outcome.stderr}",
            )
            self.assertNotEqual(
                sibling_path, owned_file, "sanity: the sibling is a genuinely different path string"
            )


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

    def test_b_alias_reviewer_id_pinned_historical_BOUNDARY(self):
        """Pinned-historical: documents the boundary exactly as it stood at
        AUDIT_SNAPSHOT_COMMIT -- the self-acceptance guard is a byte-equality
        check against dispatch['owner'], with no mechanism binding the
        --reviewer argument to any authenticated identity, so the *same*
        actor can self-review by passing any string other than the exact
        owner id. Remediation dispatched as a11-u15 ("identity binding or a
        recorded boundary plus a tested compensating control"), but a11-u15's
        own acceptance contract explicitly permits resolving this as a
        documented NOT_SUPPORTED plus a compensating control rather than a
        hard rejection -- unlike INV-2/3/8/9, this reviewer cannot write one
        fixed-behaviour assertion guaranteed to match whichever of the two
        acceptable resolutions a11 chooses (a compensating control might not
        even change `review`'s exit code for this exact CLI shape). Pinning
        preserves the finding without guessing the remediation's shape.
        """
        with tempfile.TemporaryDirectory(prefix="a10-attack-hist7b-") as histtmp:
            historical = ScratchControlPlane(Path(histtmp), commit=AUDIT_SNAPSHOT_COMMIT)
            historical.write_ownership(
                {
                    "attacker": {"owned_prefixes": ["workstreams/po03/control/units/attacker/"]},
                    "legit-reviewer": {"owned_prefixes": []},
                }
            )
            dispatch = historical.create_unit("inv7b-u1", "attacker", ["workstreams/po03/control/units/attacker/"])
            lease = historical.lease("inv7b-u1", "attacker")
            content = b'{"self": "accept via alias"}'
            historical.write_file_at("workstreams/po03/control/units/attacker/inv7b.json", content)
            doc = historical.build_result_doc(
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
            historical.ingest(doc, tag="aliasaccept")
            historical.complete("inv7b-u1")
            outcome = historical.review("inv7b-u1", "ACCEPTED", reviewer="attacker-alias-not-byte-equal")
            self.assertEqual(
                outcome.returncode,
                0,
                f"historical reproduction at {AUDIT_SNAPSHOT_COMMIT} must still hold: "
                "any non-exact-match reviewer string is accepted with no identity check",
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

    @unittest.expectedFailure
    def test_defect_cascade_rehashed_tamper_must_not_pass_verification(self):
        """Desired invariant, not yet held. Remediation dispatched as
        a11-u10 ("anchored verify_chain plus recurrence tests plus the
        corrected coordinator test"). Currently BROKEN: verify_chain only
        checks internal self-consistency (each row's own hash, and that it
        chains to the row before it), with no external anchor outside the
        file itself, so an actor with write access to the ledger file can
        rewrite a row's payload and cascade-recompute every subsequent row's
        row_sha256/prev_sha256, producing a fully self-consistent chain that
        verify_chain/cmd_verify reports as valid despite the tamper. Because
        this is git-tracked content, the real deployment argues the tamper
        is *evident* via git diff -- but nothing in the code itself detects
        it, which is exactly what this unit was asked to attack, and exactly
        what a11-u10's own acceptance contract also names as a second,
        related defect: the coordinator's test
        test_truncation_is_detected_by_projection_gap asserts verify_chain
        returns NO errors after truncation while claiming detection in its
        name -- a false green baked into the gate itself. That second defect
        lives in the coordinator/a11's own owned test file, not this
        reviewer's paths, so only the cascade-rehash form is re-asserted
        here.

        The row this attack tampers is built, not searched for: its index is
        captured as the ledger length immediately before the `review` call
        that appends it, and its event is asserted to be REJECTED as a
        sanity check, rather than located after the fact with a `next(...)`
        scan that raises StopIteration the moment the fixture's shape
        changes (which is exactly what happened when the DEF-19 schema
        regression left this test's earlier ingest/complete/review calls
        silently failing and the REJECTED row never appearing at all).
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
        ingest_outcome = self.scp.ingest(doc, tag="pretamper")
        self.assertEqual(ingest_outcome.returncode, 0, "sanity: ingest must succeed to set up the attack")
        complete_outcome = self.scp.complete("inv8b-u1")
        self.assertEqual(complete_outcome.returncode, 0, "sanity: complete must succeed to set up the attack")

        # Build (do not search for) the REJECTED row this attack tampers: it
        # is deterministically the very next ledger row appended by this
        # `review` call, so its index is captured directly.
        pre_review_row_count = len(self.scp.ledger_rows())
        review_outcome = self.scp.review(
            "inv8b-u1", "REJECTED", reviewer="legit-reviewer", receipt="receipt://legit"
        )
        self.assertEqual(review_outcome.returncode, 0, "sanity: the REJECTED review itself must succeed")

        rows = self.scp.ledger_rows()
        target_index = pre_review_row_count
        self.assertEqual(
            rows[target_index]["event"],
            "REJECTED",
            "sanity: the row this attack tampers must be the REJECTED row just built",
        )

        pre_verify = self.scp.verify()
        self.assertEqual(pre_verify.returncode, 0, "sanity: untampered chain verifies clean")

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
        self.assertNotEqual(
            outcome.returncode,
            0,
            "desired: a cascade-rehashed tamper must not verify as clean",
        )


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

    @unittest.expectedFailure
    def test_defect_fabricated_result_commit_id_must_not_reach_completed(self):
        """Desired invariant, not yet held. Remediation dispatched as
        a11-u04 ("commit-resolution verification plus recurrence test"; a2
        measured 10 of 10 invented locators accepted before the fix).
        Currently BROKEN: `ingest_result` never checks that `result_commit_id`
        refers to a real git commit. It only re-hashes whatever file
        currently sits on disk at the claimed path. This scratch repo has no
        `.git` at all, so *no* result_commit_id here could possibly be real,
        yet a syntactically well-formed, entirely fabricated commit id is
        accepted at face value and the unit reaches COMPLETED -- the exact
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
        self.assertNotEqual(
            ingest_outcome.returncode,
            0,
            "desired: ingest_result must resolve result_commit_id against real git history",
        )


if __name__ == "__main__":
    unittest.main()
