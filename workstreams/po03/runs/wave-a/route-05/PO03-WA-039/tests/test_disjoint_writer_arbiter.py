"""Falsification tests for the PO03-WA-039 disjoint writer arbiter.

The concurrency tests use real threads released simultaneously by a
``threading.Barrier``, and are repeated so a single lucky interleaving
cannot produce a green result.  A control test shows that the same fixture
under ordinary file writes loses data silently, which is the behaviour the
arbiter exists to prevent.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SLOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SLOT / "src" / "disjoint_writer_arbiter.py"
SPEC = importlib.util.spec_from_file_location("disjoint_writer_arbiter", MODULE_PATH)
G = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


ROUTE_04 = "workstreams/po03/runs/wave-a/route-04"
ROUTE_05 = "workstreams/po03/runs/wave-a/route-05"


class ClaimOverlapTests(unittest.TestCase):
    def test_sibling_routes_are_disjoint(self):
        overlaps = G.detect_claim_overlaps(
            [G.Claim("route-04", ROUTE_04), G.Claim("route-05", ROUTE_05)]
        )
        self.assertEqual([], overlaps)

    def test_identical_claims_are_flagged(self):
        overlaps = G.detect_claim_overlaps(
            [G.Claim("route-05a", ROUTE_05), G.Claim("route-05b", ROUTE_05)]
        )
        self.assertEqual(1, len(overlaps))
        self.assertEqual(G.OVERLAP_IDENTICAL, overlaps[0].kind)

    def test_nested_claims_are_flagged(self):
        overlaps = G.detect_claim_overlaps(
            [G.Claim("route", ROUTE_05), G.Claim("task", ROUTE_05 + "/PO03-WA-039")]
        )
        self.assertEqual(1, len(overlaps))
        self.assertEqual(G.OVERLAP_NESTED, overlaps[0].kind)

    def test_lexical_prefix_without_component_boundary_is_disjoint(self):
        """`route-05` and `route-050` share a string prefix but not a subtree."""
        overlaps = G.detect_claim_overlaps(
            [G.Claim("a", "runs/route-05"), G.Claim("b", "runs/route-050")]
        )
        self.assertEqual([], overlaps)

    def test_double_star_and_trailing_slash_spellings_are_equivalent(self):
        overlaps = G.detect_claim_overlaps(
            [G.Claim("a", ROUTE_05 + "/**"), G.Claim("b", ROUTE_05 + "/")]
        )
        self.assertEqual(G.OVERLAP_IDENTICAL, overlaps[0].kind)

    def test_all_eight_wave_a_route_claims_are_disjoint(self):
        claims = [
            G.Claim(f"route-0{n}", f"workstreams/po03/runs/wave-a/route-0{n}/**") for n in range(1, 9)
        ]
        report = G.build_report(claims)
        self.assertTrue(report["disjoint"], report)
        self.assertEqual(0, report["overlap_count"])

    def test_absolute_claim_is_refused(self):
        with self.assertRaises(G.ArbiterError):
            G.normalise_prefix("/workspace/workstreams")

    def test_escaping_claim_is_refused(self):
        with self.assertRaises(G.ArbiterError):
            G.normalise_prefix("../outside")

    def test_arbiter_refuses_to_start_with_overlapping_claims(self):
        with tempfile.TemporaryDirectory(prefix="po03-wa-039-") as tmp:
            with self.assertRaises(G.ArbiterError):
                G.ArbitratedWriter(Path(tmp), [G.Claim("a", ROUTE_05), G.Claim("b", ROUTE_05)])


class ArbiterFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="po03-wa-039-")
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def arbiter(self, claims, allow_overlapping=False):
        return G.ArbitratedWriter(self.root, claims, allow_overlapping_claims=allow_overlapping)


class ClaimEnforcementTests(ArbiterFixture):
    def test_write_inside_claim_succeeds(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        outcome = arbiter.write("route-05", ROUTE_05 + "/PO03-WA-039/result.json", b"payload")
        self.assertTrue(outcome.succeeded(), outcome.detail)
        self.assertEqual(b"payload", (self.root / ROUTE_05 / "PO03-WA-039" / "result.json").read_bytes())

    def test_write_outside_claim_is_rejected_and_creates_nothing(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        outcome = arbiter.write("route-05", ROUTE_04 + "/PO03-WA-025/result.json", b"payload")
        self.assertEqual(G.OUTCOME_OUT_OF_CLAIM, outcome.outcome)
        self.assertFalse((self.root / ROUTE_04).exists())

    def test_traversal_out_of_claim_is_rejected(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        outcome = arbiter.write("route-05", ROUTE_05 + "/../route-04/stolen.json", b"x")
        self.assertEqual(G.OUTCOME_OUT_OF_CLAIM, outcome.outcome)

    def test_unknown_writer_is_rejected(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        outcome = arbiter.write("route-99", ROUTE_05 + "/x.json", b"x")
        self.assertEqual(G.OUTCOME_UNCLAIMED_WRITER, outcome.outcome)

    def test_second_write_to_the_same_path_is_a_collision_not_an_overwrite(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        first = arbiter.write("route-05", ROUTE_05 + "/x.json", b"first")
        second = arbiter.write("route-05", ROUTE_05 + "/x.json", b"second")
        self.assertTrue(first.succeeded())
        self.assertEqual(G.OUTCOME_COLLISION, second.outcome)
        self.assertEqual(b"first", (self.root / ROUTE_05 / "x.json").read_bytes())

    def test_no_staging_files_are_left_behind(self):
        arbiter = self.arbiter([G.Claim("route-05", ROUTE_05)])
        arbiter.write("route-05", ROUTE_05 + "/x.json", b"first")
        arbiter.write("route-05", ROUTE_05 + "/x.json", b"second")
        leftovers = [p.name for p in (self.root / ROUTE_05).iterdir() if p.name.startswith(".po03-stage-")]
        self.assertEqual([], leftovers)


class ConcurrencyTests(ArbiterFixture):
    REPEATS = 25

    def _race(self, arbiter, writers, target_for, payload_for):
        barrier = threading.Barrier(len(writers))

        def run(writer_id):
            barrier.wait()
            return arbiter.write(writer_id, target_for(writer_id), payload_for(writer_id))

        with ThreadPoolExecutor(max_workers=len(writers)) as pool:
            return list(pool.map(run, writers))

    def test_disjoint_concurrent_writers_all_succeed(self):
        writers = [f"route-0{n}" for n in range(1, 9)]
        claims = [G.Claim(w, f"workstreams/po03/runs/wave-a/{w}") for w in writers]
        arbiter = self.arbiter(claims)
        outcomes = self._race(
            arbiter,
            writers,
            lambda w: f"workstreams/po03/runs/wave-a/{w}/result.json",
            lambda w: w.encode(),
        )
        self.assertTrue(all(o.succeeded() for o in outcomes), [o.detail for o in outcomes])
        for writer in writers:
            path = self.root / "workstreams/po03/runs/wave-a" / writer / "result.json"
            self.assertEqual(writer.encode(), path.read_bytes())

    def test_colliding_concurrent_writers_produce_exactly_one_success(self):
        for attempt in range(self.REPEATS):
            with tempfile.TemporaryDirectory(prefix="po03-wa-039-race-") as tmp:
                writers = [f"w{i}" for i in range(8)]
                claims = [G.Claim(w, "shared") for w in writers]
                arbiter = G.ArbitratedWriter(Path(tmp), claims, allow_overlapping_claims=True)
                outcomes = self._race(
                    arbiter, writers, lambda w: "shared/contested.json", lambda w: w.encode()
                )
                succeeded = [o for o in outcomes if o.succeeded()]
                collided = [o for o in outcomes if o.outcome == G.OUTCOME_COLLISION]
                self.assertEqual(1, len(succeeded), f"attempt {attempt}: {outcomes}")
                self.assertEqual(len(writers) - 1, len(collided), f"attempt {attempt}: {outcomes}")
                winner = succeeded[0].writer_id.encode()
                self.assertEqual(winner, (Path(tmp) / "shared" / "contested.json").read_bytes())

    def test_unguarded_concurrent_writes_lose_data_silently(self):
        """Control case: plain writes give no signal that a collision occurred."""
        target = self.root / "unguarded.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        writers = [f"w{i}" for i in range(8)]
        barrier = threading.Barrier(len(writers))

        def run(writer_id):
            barrier.wait()
            target.write_bytes(writer_id.encode())
            return writer_id

        with ThreadPoolExecutor(max_workers=len(writers)) as pool:
            reported = list(pool.map(run, writers))

        self.assertEqual(len(writers), len(reported))  # every writer believes it succeeded
        self.assertIn(target.read_bytes().decode(), writers)  # only one survived

    def test_journal_accounts_for_every_attempt(self):
        writers = [f"w{i}" for i in range(6)]
        arbiter = self.arbiter([G.Claim(w, "shared") for w in writers], allow_overlapping=True)
        self._race(arbiter, writers, lambda w: "shared/one.json", lambda w: w.encode())
        journal = arbiter.journal
        self.assertEqual(len(writers), len(journal))
        self.assertEqual(1, sum(1 for o in journal if o.succeeded()))


class CommandLineTests(unittest.TestCase):
    def _run(self, *claims: str):
        args = []
        for claim in claims:
            args.extend(["--claim", claim])
        return subprocess.run(
            [sys.executable, str(MODULE_PATH), *args, "--json"], capture_output=True, text=True, check=False
        )

    def test_disjoint_claims_exit_zero(self):
        proc = self._run(f"route-04={ROUTE_04}", f"route-05={ROUTE_05}")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["disjoint"])

    def test_nested_claims_exit_one(self):
        proc = self._run(f"route-05={ROUTE_05}", f"task={ROUTE_05}/PO03-WA-039")
        self.assertEqual(1, proc.returncode)
        self.assertEqual(1, json.loads(proc.stdout)["overlap_count"])

    def test_malformed_claim_exits_two(self):
        self.assertEqual(2, self._run("no-equals-sign").returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
