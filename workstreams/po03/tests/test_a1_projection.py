"""a1-u05 — the registry is a pure projection, so deleting it loses no state.

Hypothesis (frozen in ``control/dispatch/a1-u05.json``): the work-unit registry
is a pure projection of the ledger, so deleting it loses no state.

Acceptance, satisfied literally: deleting the registry and rebuilding it from
the ledger alone yields byte-identical content across at least 50 randomised
event histories.  Falsified if any rebuild differs by a single byte.

Byte-identical is compared on raw bytes, not on parsed objects, because a
projection that reordered keys or changed spacing would still parse equal while
breaking every hash that pins it.  Two negative controls plant the two ways
purity actually breaks in practice — a clock in the output and a read of the
file being rebuilt — and prove the harness catches both.
"""

from __future__ import annotations

import random
import unittest

from test_a1_support import PO03_ROOT, ScratchCase, load_isolated_module

from engine.canonical import canonical, utc_now
from engine.ledger import ALL_EVENT_KINDS, OBZIO_EVENT_KINDS, HashChainedLedger
from engine.projection import Registry, project, project_and_render, render

HISTORY_COUNT = 60
EVENTS = tuple(sorted(ALL_EVENT_KINDS))


def build_history(ledger: HashChainedLedger, rng: random.Random, *, kinds=EVENTS) -> None:
    """Write a randomised but well-formed history covering every code path."""
    units = [f"unit-{index:02d}" for index in range(1, rng.randrange(2, 6))]
    for step in range(rng.randrange(4, 40)):
        unit_id = rng.choice(units)
        event = rng.choice(kinds)
        payload: dict[str, object] = {"step": step}
        if event == "LEASED":
            payload |= {
                "lease_id": f"lease-{unit_id}-{step}",
                "worker_id": f"worker-{rng.randrange(3)}",
                "expires_at": f"2026-08-22T09:{step % 60:02d}:00Z",
                "ttl_seconds": 600,
            }
        elif event == "HEARTBEAT":
            payload |= {"expires_at": f"2026-08-22T10:{step % 60:02d}:00Z"}
        elif event == "CHECKPOINTED":
            payload |= {"checkpoint_seq": rng.randrange(1, 12)}
        elif event == "STEP_COMMITTED":
            payload |= {"step_id": f"step-{rng.randrange(1, 9):02d}"}
        elif event in ("RESULT_COMMITTED", "PARENT_INGESTED", "COMPLETED"):
            payload |= {
                "result_commit_id": f"commit-{rng.randrange(10**6):06d}",
                "result_locator": f"git:branch@commit:{unit_id}",
                "artifact_count": rng.randrange(1, 6),
                "total_bytes": rng.randrange(10, 10_000),
            }
        elif event in ("ACCEPTED", "REJECTED"):
            payload |= {"reviewer_id": f"reviewer-{rng.randrange(2)}"}
        ledger.append(
            unit_id,
            event,
            actor=rng.choice(("coordinator", "po03-worker-a1", "reviewer-0")),
            provider_state=rng.choice((None, "QUEUED", "RUNNING", "COMPLETED", "FAILED")),
            fence_token=rng.choice((None, 1, 2, 3)),
            payload=payload,
            ts=f"2026-08-22T0{rng.randrange(6, 10)}:{step % 60:02d}:{rng.randrange(60):02d}Z",
        )


class PurityTests(ScratchCase):
    def test_project_is_a_function_of_rows_only(self):
        rng = random.Random(11)
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(ledger, rng)
        rows = ledger.rows()
        self.assertEqual(canonical(project(rows)), canonical(project(rows)))
        self.assertEqual(canonical(project(rows)), canonical(project(list(rows))))

    def test_render_is_byte_stable(self):
        rng = random.Random(12)
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(ledger, rng)
        units = project(ledger.rows())
        self.assertEqual(render(units).encode("utf-8"), render(units).encode("utf-8"))

    def test_projection_does_not_read_the_registry_it_writes(self):
        rng = random.Random(13)
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(ledger, rng)
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        registry.materialize()
        with_file = registry.bytes_on_disk()
        registry.delete()
        self.assertEqual(b"", registry.bytes_on_disk())
        registry.materialize()
        self.assertEqual(with_file, registry.bytes_on_disk())

    def test_registry_is_faithful_only_when_it_matches_the_ledger(self):
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl")
        ledger.append("u1", "CREATED", actor="coordinator")
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        registry.materialize()
        self.assertTrue(registry.is_faithful())
        registry.path.write_text("tampered\n", encoding="utf-8")
        self.assertFalse(registry.is_faithful())
        registry.rebuild()
        self.assertTrue(registry.is_faithful())


class RebuildTests(ScratchCase):
    def test_delete_and_rebuild_is_byte_identical_across_randomised_histories(self):
        mismatches: list[dict[str, object]] = []
        for index in range(HISTORY_COUNT):
            rng = random.Random(1000 + index)
            ledger = HashChainedLedger(self.scratch / f"ledger-{index:03d}.jsonl", verify_on_append=False)
            build_history(ledger, rng)
            registry = Registry(ledger, self.scratch / f"registry-{index:03d}.jsonl")
            registry.materialize()
            original_bytes = registry.bytes_on_disk()
            original_units = registry.units()

            registry.delete()
            self.assertFalse(registry.path.exists())
            registry.materialize()

            if registry.bytes_on_disk() != original_bytes:
                mismatches.append({"history": index, "rows": len(ledger.rows())})
            self.assertEqual(canonical(original_units), canonical(registry.units()))
        self.assertGreaterEqual(HISTORY_COUNT, 50)
        self.assertEqual([], mismatches, "a rebuild differed from the original bytes")

    def test_rebuild_after_appending_extends_rather_than_diverges(self):
        rng = random.Random(77)
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(ledger, rng)
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        before = registry.materialize()
        ledger.append("unit-new", "CREATED", actor="coordinator")
        after = registry.rebuild()
        self.assertNotEqual(before, after)
        self.assertIn("unit-new", registry.units())

    def test_a_fresh_process_view_matches_the_materialised_bytes(self):
        rng = random.Random(78)
        path = self.scratch / "ledger.jsonl"
        ledger = HashChainedLedger(path, verify_on_append=False)
        build_history(ledger, rng)
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        registry.materialize()
        # A different object over the same file, as a restarted parent would use.
        reopened = Registry(HashChainedLedger(path), self.scratch / "registry-2.jsonl")
        reopened.materialize()
        self.assertEqual(registry.bytes_on_disk(), reopened.bytes_on_disk())


class ImpureProjectionNegativeControlTests(ScratchCase):
    """Plant the two realistic ways purity breaks and prove detection."""

    def setUp(self) -> None:
        super().setUp()
        self.ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(self.ledger, random.Random(4321))

    def test_a_clock_in_the_projection_breaks_byte_identity(self):
        def impure_renderer(rows):
            units = project(rows)
            for unit in units.values():
                unit["rebuilt_at"] = utc_now()
                unit["nonce"] = random.random()
            return render(units)

        registry = Registry(self.ledger, self.scratch / "registry.jsonl", renderer=impure_renderer)
        registry.materialize()
        original = registry.bytes_on_disk()
        registry.rebuild()
        self.assertNotEqual(
            original,
            registry.bytes_on_disk(),
            "the byte-identity assertion must be able to fail",
        )

    def test_a_projection_that_reads_the_registry_loses_state_on_deletion(self):
        target = self.scratch / "registry.jsonl"

        def stateful_renderer(rows):
            # The bug this forbids: treating the derived file as an input, so
            # deleting it silently drops everything it held.
            previous = target.read_text(encoding="utf-8") if target.exists() else ""
            units = project(rows)
            return previous + render(units) if previous else render(units)

        registry = Registry(self.ledger, target, renderer=stateful_renderer)
        registry.materialize()
        registry.materialize()
        grown = registry.bytes_on_disk()
        registry.rebuild()
        self.assertNotEqual(grown, registry.bytes_on_disk(), "the impure renderer must be detectable")

        # The pure renderer over the same ledger is faithful, so the failure
        # above is caused by the planted impurity and nothing else.
        pure = Registry(self.ledger, self.scratch / "pure.jsonl")
        pure.materialize()
        self.assertTrue(pure.is_faithful())
        self.assertEqual(pure.bytes_on_disk(), pure.rebuild() and pure.bytes_on_disk())


class ControlPlaneAgreementTests(ScratchCase):
    """The coordinator and this projection must read a ledger the same way.

    Divergence here would be invisible in normal operation and catastrophic
    during recovery: two processes would rebuild two different fleets from one
    immutable history.
    """

    SHARED_FIELDS = (
        "obzio_state",
        "provider_state",
        "fence_token",
        "checkpoint_seq",
        "result_commit_id",
        "result_locator",
        "artifact_count",
        "total_bytes",
        "attempts",
        "retries",
        "acceptance",
        "reviewer_id",
        "lease",
        "first_seen_ts",
        "last_event_ts",
        "last_event_seq",
    )

    def setUp(self) -> None:
        super().setUp()
        self.plane = load_isolated_module(PO03_ROOT / "tools" / "control_plane.py", "a1_projection_plane")

    def _compare(self, index: int, kinds) -> tuple[list[dict[str, object]], HashChainedLedger]:
        path = self.scratch / f"ledger-{index:03d}.jsonl"
        ledger = HashChainedLedger(path, verify_on_append=False)
        build_history(ledger, random.Random(5000 + index), kinds=kinds)
        self.plane.LEDGER_PATH = path
        mine = project(ledger.rows())
        theirs = self.plane.project_units()
        problems: list[dict[str, object]] = []
        if set(mine) != set(theirs):
            problems.append({"history": index, "field": "<unit set>", "engine": sorted(mine), "plane": sorted(theirs)})
            return problems, ledger
        for unit_id in sorted(mine):
            for field in self.SHARED_FIELDS:
                if canonical(mine[unit_id][field]) != canonical(theirs[unit_id][field]):
                    problems.append(
                        {
                            "history": index,
                            "unit_id": unit_id,
                            "field": field,
                            "engine": mine[unit_id][field],
                            "plane": theirs[unit_id][field],
                        }
                    )
        return problems, ledger

    def test_projections_agree_on_obzio_event_histories(self):
        problems: list[dict[str, object]] = []
        for index in range(HISTORY_COUNT):
            found, _ = self._compare(index, tuple(sorted(OBZIO_EVENT_KINDS)))
            problems.extend(found)
        self.assertEqual([], problems[:10], f"{len(problems)} disagreements; first ten shown")

    def test_additive_engine_events_never_move_custody_state_for_either_reader(self):
        problems: list[dict[str, object]] = []
        for index in range(HISTORY_COUNT, HISTORY_COUNT + 30):
            found, _ = self._compare(index, EVENTS)
            problems.extend(found)
        custody = [p for p in problems if p["field"] != "lease"]
        self.assertEqual(
            [],
            custody[:10],
            "an additive engine event changed a custody field for one reader but not the other",
        )

    def test_the_only_divergence_is_heartbeat_lease_renewal(self):
        """A real defect in the coordinator's reader, isolated and named.

        ``control_plane.project_units`` has no ``HEARTBEAT`` case, so it keeps
        the expiry recorded at grant time.  The engine applies the renewal.
        That matters because ``control_plane.scan_recovery`` decides a lease has
        expired from this field, so a live worker that is renewing on schedule
        would be reported as needing recovery.

        The engine keeps the renewing semantics, since a1-u04 depends on them.
        ``control_plane.py`` is coordinator-owned and is not edited here; the
        finding is handed over in
        ``control/units/a1/a1-findings-out-of-scope.json`` with an
        integration-ready description instead.
        """
        divergences: list[dict[str, object]] = []
        for index in range(HISTORY_COUNT + 30, HISTORY_COUNT + 70):
            found, ledger = self._compare(index, EVENTS)
            for problem in found:
                problem["heartbeats_present"] = any(
                    row["event"] == "HEARTBEAT" and row["unit_id"] == problem.get("unit_id")
                    for row in ledger.rows()
                )
            divergences.extend(found)

        self.assertNotEqual([], divergences, "the fixture must actually produce the divergence")
        for problem in divergences:
            self.assertEqual("lease", problem["field"], f"unexpected divergence: {problem}")
            self.assertTrue(problem["heartbeats_present"], f"divergence without a heartbeat: {problem}")
            engine_lease = problem["engine"]
            plane_lease = problem["plane"]
            self.assertEqual(engine_lease["lease_id"], plane_lease["lease_id"])
            self.assertEqual(engine_lease["worker_id"], plane_lease["worker_id"])
            self.assertEqual(engine_lease["granted_at"], plane_lease["granted_at"])
            self.assertNotEqual(
                engine_lease["expires_at"],
                plane_lease["expires_at"],
                "the divergence must be confined to the renewed expiry",
            )


class StateRecoveryTests(ScratchCase):
    def test_losing_the_registry_loses_no_unit_state(self):
        rng = random.Random(999)
        ledger = HashChainedLedger(self.scratch / "ledger.jsonl", verify_on_append=False)
        build_history(ledger, rng)
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        registry.materialize()
        before = {unit_id: dict(unit) for unit_id, unit in registry.units().items()}

        registry.delete()
        recovered = Registry(HashChainedLedger(self.scratch / "ledger.jsonl"), self.scratch / "registry.jsonl")
        recovered.materialize()
        self.assertEqual(canonical(before), canonical(recovered.units()))
        self.assertTrue(recovered.is_faithful())

    def test_projection_of_an_empty_ledger_is_empty_not_absent(self):
        ledger = HashChainedLedger(self.scratch / "empty.jsonl")
        registry = Registry(ledger, self.scratch / "registry.jsonl")
        registry.materialize()
        self.assertEqual(b"", registry.bytes_on_disk())
        self.assertEqual({}, registry.units())
        self.assertEqual("", project_and_render([]))


if __name__ == "__main__":
    unittest.main()
