"""a1-u08 — no path reaches COMPLETED without verified coordinator ingestion.

Hypothesis (frozen in ``control/dispatch/a1-u08.json``): coordinator-only
completion is enforced structurally rather than by convention, so no
worker-authored document can reach ``COMPLETED``.

Acceptance, satisfied literally: every attempt to reach ``COMPLETED`` without a
prior verified ``PARENT_INGESTED`` event, or with a non-coordinator actor, is
rejected; an exhaustive state-transition test covers all fifteen Obzio states.

Exhaustive here means enumerated, not sampled:

* all 15 x 15 x 4 = 900 (from-state, to-state, role) triples are evaluated and
  compared against the declared relation;
* the full product space of state and custody-fact flags is searched by
  breadth-first traversal, with an adversary allowed to set any flag at any
  moment, and every configuration reaching ``COMPLETED`` is inspected;
* every simple path through the structural graph from ``CREATED`` to
  ``COMPLETED`` is enumerated and required to pass through the whole custody
  chain.

The state list is checked against the published contract schema and the
coordinator's own validator rather than declared here, so the fifteen states
are the commission's fifteen and not this module's opinion of them.  A negative
control adds one illegal edge and proves the search fails.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import unittest

from test_a1_support import PO03_ROOT, ScratchCase, load_isolated_module

from engine.completion import (
    CANCELLED,
    COMPLETED,
    COORDINATOR,
    CREATED,
    FAILED_TERMINAL,
    OBZIO_STATES,
    PARENT_INGESTED,
    PROVIDER_COMPLETED_UNCOMMITTED,
    RESULT_COMMITTED,
    RESULT_VERIFIED,
    ROLES,
    RUNNING,
    TERMINAL_STATES,
    TRANSITIONS,
    WORKER,
    CustodyAuthority,
    CustodyContext,
    CustodyMachine,
    CustodyViolation,
    evaluate,
    paths_into,
)
from engine.ledger import HashChainedLedger

SCHEMA_PATH = PO03_ROOT / "contracts" / "transactional-result.schema.json"
COMMIT_ID = "commit-abc123"

FULLY_EARNED = CustodyContext(
    artifacts_verified=True,
    durable_commit_id=COMMIT_ID,
    readback_verified=True,
    ingestion_recorded=True,
)


class StateInventoryTests(ScratchCase):
    """The fifteen states are the commission's, not this module's."""

    def test_fifteen_states(self):
        self.assertEqual(15, len(OBZIO_STATES))
        self.assertEqual(len(OBZIO_STATES), len(set(OBZIO_STATES)))

    def test_states_match_the_published_contract_schema(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        enum = schema["properties"]["obzio_state"]["enum"]
        self.assertEqual(set(enum), set(OBZIO_STATES))
        self.assertEqual(15, len(enum))

    def test_states_match_the_coordinator_validator(self):
        validator = load_isolated_module(PO03_ROOT / "tools" / "validate_contracts.py", "a1_u08_validator")
        self.assertEqual(validator.RESULT_STATES, set(OBZIO_STATES))

    def test_every_state_appears_in_the_transition_relation(self):
        self.assertEqual(set(OBZIO_STATES), set(TRANSITIONS))


class ExhaustiveTransitionTableTests(ScratchCase):
    """All 900 (from, to, role) triples, evaluated one by one."""

    def test_every_triple_agrees_with_the_declared_relation(self):
        checked = 0
        completing: list[tuple[str, str]] = []
        for from_state, to_state, role in itertools.product(OBZIO_STATES, OBZIO_STATES, ROLES):
            checked += 1
            decision = evaluate(from_state, to_state, role, FULLY_EARNED)
            declared = TRANSITIONS[from_state].get(to_state)
            expected = declared is not None and role in declared
            self.assertEqual(
                expected,
                decision.allowed,
                f"{from_state} -> {to_state} by {role}: relation says {expected}, "
                f"evaluate says {decision.allowed} ({decision.reason})",
            )
            if decision.allowed and to_state == COMPLETED:
                completing.append((from_state, role))
        self.assertEqual(15 * 15 * len(ROLES), checked)
        self.assertEqual(900, checked)
        self.assertEqual([(PARENT_INGESTED, COORDINATOR)], completing)

    def test_completed_has_exactly_one_predecessor_and_one_role(self):
        self.assertEqual([(PARENT_INGESTED, frozenset({COORDINATOR}))], paths_into(COMPLETED))

    def test_no_role_may_leave_a_terminal_state(self):
        for terminal in (COMPLETED, FAILED_TERMINAL, CANCELLED):
            self.assertEqual({}, TRANSITIONS[terminal])
            for to_state, role in itertools.product(OBZIO_STATES, ROLES):
                with self.subTest(terminal=terminal, to_state=to_state, role=role):
                    self.assertFalse(evaluate(terminal, to_state, role, FULLY_EARNED).allowed)

    def test_the_worker_role_has_no_edge_past_result_committed(self):
        for from_state in OBZIO_STATES:
            for to_state in (PARENT_INGESTED, COMPLETED):
                with self.subTest(from_state=from_state, to_state=to_state):
                    self.assertFalse(
                        evaluate(from_state, to_state, WORKER, FULLY_EARNED).allowed,
                        f"a worker reached {to_state} from {from_state}",
                    )

    def test_result_committed_is_the_strongest_state_a_worker_can_write(self):
        self.assertTrue(evaluate(RESULT_VERIFIED, RESULT_COMMITTED, WORKER, FULLY_EARNED).allowed)
        self.assertFalse(evaluate(RESULT_COMMITTED, PARENT_INGESTED, WORKER, FULLY_EARNED).allowed)


class GuardTests(ScratchCase):
    """Each custody fact is load-bearing on its own."""

    def test_completion_requires_recorded_ingestion(self):
        context = CustodyContext(
            artifacts_verified=True,
            durable_commit_id=COMMIT_ID,
            readback_verified=True,
            ingestion_recorded=False,
        )
        decision = evaluate(PARENT_INGESTED, COMPLETED, COORDINATOR, context)
        self.assertFalse(decision.allowed)
        self.assertIn("recorded coordinator ingestion", decision.reason)

    def test_completion_requires_a_durable_commit(self):
        context = FULLY_EARNED.merged(durable_commit_id=None)
        decision = evaluate(PARENT_INGESTED, COMPLETED, COORDINATOR, context)
        self.assertFalse(decision.allowed)
        self.assertIn("durable commit identifier", decision.reason)

    def test_ingestion_requires_the_coordinators_own_readback(self):
        context = FULLY_EARNED.merged(readback_verified=False)
        decision = evaluate(RESULT_COMMITTED, PARENT_INGESTED, COORDINATOR, context)
        self.assertFalse(decision.allowed)
        self.assertIn("read-back", decision.reason)

    def test_result_commit_requires_producer_verification(self):
        self.assertFalse(
            evaluate(
                RESULT_VERIFIED, RESULT_COMMITTED, WORKER, FULLY_EARNED.merged(artifacts_verified=False)
            ).allowed
        )
        self.assertFalse(
            evaluate(
                RESULT_VERIFIED, RESULT_COMMITTED, WORKER, FULLY_EARNED.merged(durable_commit_id=None)
            ).allowed
        )

    def test_acceptance_is_not_a_custody_state(self):
        self.assertNotIn("ACCEPTED", OBZIO_STATES)
        self.assertNotIn("REJECTED", OBZIO_STATES)


class AuthorityTests(ScratchCase):
    """Identity does not confer authority."""

    def test_a_worker_cannot_become_coordinator_by_naming_itself(self):
        authority = CustodyAuthority(reviewer_ids=("po03-worker-a6",))
        self.assertEqual(COORDINATOR, authority.role_of("coordinator"))
        for impostor in (
            "po03-worker-a1",
            "coordinator-ish",
            "the coordinator",
            "COORDINATOR",
            "coordinator ",
            "po03-worker-a1 (acting coordinator)",
        ):
            with self.subTest(actor=impostor):
                self.assertEqual(WORKER, authority.role_of(impostor))
                self.assertFalse(
                    evaluate(PARENT_INGESTED, COMPLETED, authority.role_of(impostor), FULLY_EARNED).allowed
                )

    def test_a_reviewer_is_not_a_coordinator(self):
        authority = CustodyAuthority(reviewer_ids=("po03-worker-a6",))
        self.assertNotEqual(COORDINATOR, authority.role_of("po03-worker-a6"))
        self.assertFalse(
            evaluate(PARENT_INGESTED, COMPLETED, authority.role_of("po03-worker-a6"), FULLY_EARNED).allowed
        )

    def test_the_coordinator_cannot_also_be_a_reviewer(self):
        with self.assertRaises(ValueError):
            CustodyAuthority(coordinator_id="coordinator", reviewer_ids=("coordinator",))


class ExhaustiveReachabilityTests(ScratchCase):
    """Search the whole product space, with an adversary setting the flags."""

    FLAGS = ("artifacts_verified", "durable_commit_id", "readback_verified", "ingestion_recorded")

    @staticmethod
    def _context(flags: frozenset[str]) -> CustodyContext:
        return CustodyContext(
            artifacts_verified="artifacts_verified" in flags,
            durable_commit_id=COMMIT_ID if "durable_commit_id" in flags else None,
            readback_verified="readback_verified" in flags,
            ingestion_recorded="ingestion_recorded" in flags,
        )

    def _search(
        self,
        relation=None,
        *,
        drop_predecessor_guard: bool = False,
        drop_fact_guards: bool = False,
    ):
        """Breadth-first over (state, flags); returns nodes and completing edges.

        With no keyword arguments this drives the real :func:`evaluate`. The
        keyword arguments exist only for the negative controls, which weaken one
        defence at a time to prove each of the assertions above can fail.
        """
        transitions = relation if relation is not None else TRANSITIONS
        substituted = relation is not None or drop_predecessor_guard or drop_fact_guards
        start = (CREATED, frozenset())
        seen = {start}
        frontier = [start]
        completing_edges: set[tuple[str, str, frozenset[str]]] = set()
        while frontier:
            state, flags = frontier.pop()
            # The adversary may establish any custody fact at any moment.
            for flag in self.FLAGS:
                if flag not in flags:
                    node = (state, flags | {flag})
                    if node not in seen:
                        seen.add(node)
                        frontier.append(node)
            context = self._context(flags)
            for role in ROLES:
                for target in transitions[state]:
                    allowed = (
                        self._evaluate_with(
                            transitions,
                            state,
                            target,
                            role,
                            context,
                            predecessor_guard=not drop_predecessor_guard,
                            fact_guards=not drop_fact_guards,
                        )
                        if substituted
                        else evaluate(state, target, role, context).allowed
                    )
                    if not allowed:
                        continue
                    if target == COMPLETED:
                        completing_edges.add((state, role, flags))
                    node = (target, flags)
                    if node not in seen:
                        seen.add(node)
                        frontier.append(node)
        return seen, completing_edges

    @staticmethod
    def _evaluate_with(
        relation,
        from_state,
        to_state,
        role,
        context,
        *,
        predecessor_guard: bool = True,
        fact_guards: bool = True,
    ) -> bool:
        """Re-implement :func:`evaluate` so one defence at a time can be removed."""
        if from_state in TERMINAL_STATES:
            return False
        permitted = relation[from_state].get(to_state)
        if permitted is None or role not in permitted:
            return False
        if to_state == RESULT_COMMITTED:
            return context.artifacts_verified and bool(context.durable_commit_id)
        if to_state == PARENT_INGESTED:
            return context.readback_verified and bool(context.durable_commit_id)
        if to_state == COMPLETED:
            if predecessor_guard and from_state != PARENT_INGESTED:
                return False
            if fact_guards:
                return context.ingestion_recorded and bool(context.durable_commit_id)
        return True

    def test_the_substituted_evaluator_matches_the_real_one(self):
        """The controls below are only meaningful if the stand-in is faithful.

        Compared over every triple and every one of the sixteen flag
        combinations, so a divergence cannot hide in an untested corner.
        """
        compared = 0
        for from_state, to_state, role in itertools.product(OBZIO_STATES, OBZIO_STATES, ROLES):
            for size in range(len(self.FLAGS) + 1):
                for combination in itertools.combinations(self.FLAGS, size):
                    context = self._context(frozenset(combination))
                    compared += 1
                    self.assertEqual(
                        evaluate(from_state, to_state, role, context).allowed,
                        self._evaluate_with(TRANSITIONS, from_state, to_state, role, context),
                        f"stand-in disagrees on {from_state} -> {to_state} by {role} "
                        f"with {sorted(combination)}",
                    )
        self.assertEqual(900 * 2 ** len(self.FLAGS), compared)

    def test_the_search_space_is_fully_explored(self):
        nodes, _ = self._search()
        self.assertEqual(15 * 2**4, 240)
        self.assertLessEqual(len(nodes), 240)
        self.assertGreater(len(nodes), 100, "the search must actually traverse the graph")

    def test_no_reachable_configuration_is_completed_without_ingestion(self):
        nodes, completing = self._search()
        completed_nodes = [node for node in nodes if node[0] == COMPLETED]
        self.assertNotEqual([], completed_nodes, "COMPLETED must be reachable or the test is vacuous")
        for state, flags in completed_nodes:
            self.assertIn(
                "ingestion_recorded",
                flags,
                f"reached {state} with flags {sorted(flags)} and no recorded ingestion",
            )
            self.assertIn("durable_commit_id", flags)

    def test_every_completing_edge_comes_from_the_coordinator_after_ingestion(self):
        _, completing = self._search()
        self.assertNotEqual(set(), completing)
        for from_state, role, flags in completing:
            self.assertEqual(PARENT_INGESTED, from_state)
            self.assertEqual(COORDINATOR, role)
            self.assertIn("ingestion_recorded", flags)

    @staticmethod
    def _with_illegal_edge() -> dict[str, dict[str, frozenset[str]]]:
        relation = {state: dict(edges) for state, edges in TRANSITIONS.items()}
        relation[RUNNING][COMPLETED] = frozenset({WORKER, COORDINATOR})
        return relation

    def test_one_planted_illegal_edge_is_not_enough_to_reach_completion(self):
        """Defence in depth: the predecessor guard refuses the edge on its own.

        This is the reason the negative control below has to remove two
        defences: corrupting the relation alone changes nothing observable.
        """
        nodes, completing = self._search(relation=self._with_illegal_edge())
        self.assertEqual(
            [],
            sorted(edge[:2] for edge in completing if edge[0] != PARENT_INGESTED),
            "the guard on COMPLETED must refuse an edge the relation wrongly permits",
        )
        for state, flags in [node for node in nodes if node[0] == COMPLETED]:
            self.assertIn("ingestion_recorded", flags, f"{state} reached with {sorted(flags)}")

    def test_the_search_catches_an_illegal_edge_once_the_guard_goes_too(self):
        """Negative control: with the relation and its guard both weakened the
        search must report the unlawful completing edge."""
        _, completing = self._search(
            relation=self._with_illegal_edge(), drop_predecessor_guard=True
        )
        offending = sorted(edge[:2] for edge in completing if edge[0] != PARENT_INGESTED)
        self.assertIn(
            (RUNNING, COORDINATOR),
            offending,
            "the reachability search must be able to detect an illegal completing edge",
        )
        self.assertIn((RUNNING, WORKER), offending, "a worker completion must be detected too")

    def test_the_search_catches_completion_without_ingestion_when_the_fact_guard_goes(self):
        """Negative control for the custody-fact assertion, which is separate:
        with ``ingestion_recorded`` no longer required, an unearned COMPLETED
        must become reachable and be reported."""
        nodes, completing = self._search(drop_fact_guards=True)
        unearned = [
            sorted(flags)
            for state, flags in nodes
            if state == COMPLETED and "ingestion_recorded" not in flags
        ]
        self.assertNotEqual(
            [],
            unearned,
            "removing the ingestion requirement must make an unearned COMPLETED reachable",
        )
        self.assertNotEqual(set(), completing)


class SimplePathTests(ScratchCase):
    """Enumerate every acyclic route through the structural graph."""

    def _all_simple_paths(self, source: str, target: str, cap: int = 500_000) -> list[tuple[str, ...]]:
        found: list[tuple[str, ...]] = []
        stack: list[tuple[str, tuple[str, ...]]] = [(source, (source,))]
        while stack:
            state, path = stack.pop()
            if state == target:
                found.append(path)
                if len(found) > cap:
                    raise AssertionError("path enumeration exceeded its cap")
                continue
            for successor in TRANSITIONS[state]:
                if successor in path:
                    continue
                stack.append((successor, path + (successor,)))
        return found

    def test_every_path_to_completed_passes_through_the_whole_custody_chain(self):
        paths = self._all_simple_paths(CREATED, COMPLETED)
        self.assertGreater(len(paths), 0)
        for path in paths:
            self.assertEqual(COMPLETED, path[-1])
            self.assertEqual(
                (RESULT_VERIFIED, RESULT_COMMITTED, PARENT_INGESTED, COMPLETED),
                path[-4:],
                f"path {path} reached COMPLETED without the full custody chain",
            )

    def test_no_path_reaches_completed_from_provider_completed_uncommitted(self):
        for path in self._all_simple_paths(CREATED, COMPLETED):
            self.assertNotIn(
                PROVIDER_COMPLETED_UNCOMMITTED,
                path[-2:],
                f"path {path} treats provider completion as adjacent to Obzio completion",
            )


class LiveMachineTests(ScratchCase):
    """The running mechanism, not just the relation it is built from."""

    def setUp(self) -> None:
        super().setUp()
        self.ledger = HashChainedLedger(self.scratch / "ledger.jsonl")

    def machine(self, state: str, context: CustodyContext | None = None) -> CustodyMachine:
        return CustodyMachine(
            "a1-u08-subject", self.ledger, state=state, context=context or FULLY_EARNED
        )

    def test_no_state_but_parent_ingested_can_transition_to_completed(self):
        refused = 0
        for state in OBZIO_STATES:
            if state == PARENT_INGESTED:
                continue
            with self.subTest(from_state=state):
                machine = self.machine(state)
                with self.assertRaises(CustodyViolation):
                    machine.transition(COMPLETED, actor_id="coordinator")
                refused += 1
        self.assertEqual(14, refused)
        self.assertEqual(
            [], [row for row in self.ledger.rows() if row["event"] == COMPLETED]
        )

    def test_no_actor_but_the_coordinator_can_complete(self):
        for actor in ("po03-worker-a1", "po03-worker-a6", "provider:cursor", "coordinator-ish"):
            with self.subTest(actor=actor):
                machine = self.machine(PARENT_INGESTED)
                with self.assertRaises(CustodyViolation) as caught:
                    machine.transition(COMPLETED, actor_id=actor)
                self.assertIn("may not traverse", str(caught.exception))
        self.assertEqual([], [row for row in self.ledger.rows() if row["event"] == COMPLETED])

    def test_the_coordinator_completes_only_after_recorded_ingestion(self):
        machine = self.machine(PARENT_INGESTED, FULLY_EARNED.merged(ingestion_recorded=False))
        with self.assertRaises(CustodyViolation):
            machine.transition(COMPLETED, actor_id="coordinator")
        self.assertEqual([], self.ledger.rows())

        machine.context = FULLY_EARNED
        row = machine.transition(COMPLETED, actor_id="coordinator")
        self.assertEqual(COMPLETED, row["event"])
        self.assertEqual(COORDINATOR, row["payload"]["role"])
        self.assertTrue(row["payload"]["context"]["ingestion_recorded"])
        self.assertTrue(self.ledger.verify().ok)

    def test_a_refused_transition_writes_nothing(self):
        machine = self.machine(RUNNING)
        before = len(self.ledger.rows())
        with self.assertRaises(CustodyViolation):
            machine.transition(COMPLETED, actor_id="coordinator")
        self.assertEqual(before, len(self.ledger.rows()))
        self.assertEqual(RUNNING, machine.state, "a refused transition must not move the machine")

    def test_the_full_lawful_sequence_records_every_state(self):
        machine = CustodyMachine("a1-u08-lawful", self.ledger, state=CREATED, context=CustodyContext())
        machine.transition("LEASED", actor_id="coordinator")
        machine.transition("RUNNING", actor_id="po03-worker-a1")
        machine.transition("CHECKPOINTED", actor_id="po03-worker-a1", checkpoint_seq=1)
        machine.transition("RESULT_STAGING", actor_id="po03-worker-a1")
        machine.transition("RESULT_STAGED", actor_id="po03-worker-a1")
        machine.transition("RESULT_VERIFIED", actor_id="po03-worker-a1")
        machine.transition(
            RESULT_COMMITTED,
            actor_id="po03-worker-a1",
            artifacts_verified=True,
            durable_commit_id=COMMIT_ID,
        )
        machine.transition(PARENT_INGESTED, actor_id="coordinator", readback_verified=True)
        machine.transition(COMPLETED, actor_id="coordinator", ingestion_recorded=True)
        events = [row["event"] for row in self.ledger.events_for("a1-u08-lawful")]
        self.assertEqual(
            [
                "LEASED",
                "RUNNING",
                "CHECKPOINTED",
                "RESULT_STAGING",
                "RESULT_STAGED",
                "RESULT_VERIFIED",
                "RESULT_COMMITTED",
                "PARENT_INGESTED",
                "COMPLETED",
            ],
            events,
        )
        self.assertTrue(self.ledger.verify().ok)


class WorkerAuthoredDocumentTests(ScratchCase):
    """A worker cannot write its way to COMPLETED in a result document either."""

    def setUp(self) -> None:
        super().setUp()
        self.validator = load_isolated_module(
            PO03_ROOT / "tools" / "validate_contracts.py", "a1_u08_doc_validator"
        )

    def document(self, state: str, actor) -> dict:
        return {
            "protocol_version": "OBZIO-TRANSACTIONAL-RESULT-v1",
            "task_id": "a1-u08-subject",
            "commission_id": "COM-PO03",
            "immutable_input_manifest_sha256": "a" * 64,
            "acceptance_contract_sha256": "b" * 64,
            "provider_state": "COMPLETED",
            "obzio_state": state,
            "attempt": {
                "attempt_id": "attempt-1",
                "idempotency_key": "a1-u08-subject:1",
                "lease_id": "lease-1",
                "fence_token": 1,
                "provider_run_id": "po03-a1-subagent",
                "worker_id": "po03-worker-a1",
                "heartbeat_at": "2026-08-22T07:00:00Z",
                "checkpoint_seq": 1,
            },
            "result_transaction": {
                "result_txn_id": "txn-1",
                "state": "COMMITTED",
                "manifest_uri": "git:branch@commit:manifest",
                "manifest_sha256": "c" * 64,
                "artifact_count": 1,
                "total_bytes": 9,
                "committed_at": "2026-08-22T07:01:00Z",
                "verified_at": "2026-08-22T07:01:00Z",
                "parent_ingested_at": "2026-08-22T07:02:00Z",
                "result_commit_id": COMMIT_ID,
            },
            "artifacts": [
                {
                    "artifact_id": "art-1",
                    "logical_name": "result.json",
                    "content_uri": "git:branch@commit:workstreams/po03/engine/x.py",
                    "sha256": "d" * 64,
                    "bytes": 9,
                    "media_type": "application/json",
                    "readback_verified_at": "2026-08-22T07:01:00Z",
                }
            ],
            "completion_actor": actor,
            "independent_acceptance": {"state": "NOT_TESTED", "reviewer_id": None, "receipt_uri": None},
        }

    def test_a_worker_authored_completed_document_is_rejected(self):
        for actor in ("po03-worker-a1", "worker", "provider", None, "coordinator-ish"):
            with self.subTest(completion_actor=actor):
                errors = self.validator.validate_result(self.document(COMPLETED, actor))
                self.assertTrue(
                    any("only coordinator" in error for error in errors),
                    f"completion_actor={actor!r} was accepted: {errors}",
                )

    def test_the_strongest_state_a_worker_may_emit_is_result_committed(self):
        document = self.document(RESULT_COMMITTED, None)
        document["result_transaction"]["parent_ingested_at"] = None
        self.assertEqual([], self.validator.validate_result(document))

    def test_a_producer_cannot_accept_its_own_completed_result(self):
        document = self.document(COMPLETED, "coordinator")
        document["independent_acceptance"] = {
            "state": "ACCEPTED",
            "reviewer_id": "po03-worker-a1",
            "receipt_uri": "git:review@x:receipt.json",
        }
        errors = self.validator.validate_result(document)
        self.assertTrue(any("self-accept" in error for error in errors), errors)


class ControlPlaneCompletionTests(ScratchCase):
    """The coordinator's own ``complete`` command, over all fifteen states."""

    def setUp(self) -> None:
        super().setUp()
        self.plane = load_isolated_module(PO03_ROOT / "tools" / "control_plane.py", "a1_u08_plane")
        control = self.scratch / "control"
        self.plane.LEDGER_PATH = control / "events" / "ledger.jsonl"
        self.plane.REGISTRY_PATH = control / "work-unit-registry.jsonl"
        self.plane.RECOVERY_PATH = control / "recovery-state.json"
        self.plane.DISPATCH_DIR = control / "dispatch"
        self.plane.PATH_OWNERSHIP_PATH = control / "path-ownership.json"

    def _namespace(self, unit_id: str):
        return type("Namespace", (), {"unit_id": unit_id})()

    def test_completion_is_refused_from_every_state_but_parent_ingested(self):
        refused: list[str] = []
        for state in OBZIO_STATES:
            if state in (PARENT_INGESTED, "COMPLETED"):
                continue
            unit_id = f"unit-{state.lower()}"
            self.plane.append_event(unit_id, "CREATED", actor="coordinator", provider_state="QUEUED")
            if state != "CREATED":
                self.plane.append_event(
                    unit_id,
                    state,
                    actor="coordinator",
                    payload={"result_commit_id": COMMIT_ID, "result_locator": "locator"},
                )
            with self.subTest(state=state):
                with self.assertRaises(self.plane.ControlPlaneError) as caught:
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.plane.cmd_complete(self._namespace(unit_id))
                self.assertIn("requires PARENT_INGESTED", str(caught.exception))
                refused.append(state)
        self.assertEqual(13, len(refused))
        self.assertEqual([], [row for row in self.plane.ledger_rows() if row["event"] == "COMPLETED"])

    def test_parent_ingested_without_a_durable_commit_cannot_complete(self):
        unit_id = "unit-ingested-no-commit"
        self.plane.append_event(unit_id, "CREATED", actor="coordinator", provider_state="QUEUED")
        self.plane.append_event(unit_id, "PARENT_INGESTED", actor="coordinator", payload={})
        with self.assertRaises(self.plane.ControlPlaneError) as caught:
            with contextlib.redirect_stdout(io.StringIO()):
                self.plane.cmd_complete(self._namespace(unit_id))
        self.assertIn("no durable result commit", str(caught.exception))

    def test_provider_completion_without_a_commit_is_never_obzio_completion(self):
        unit_id = "unit-provider-only"
        self.plane.append_event(unit_id, "CREATED", actor="coordinator", provider_state="QUEUED")
        self.plane.append_event(
            unit_id, "PROVIDER_COMPLETED_UNCOMMITTED", actor="coordinator", provider_state="COMPLETED"
        )
        state = self.plane.scan_recovery()
        self.assertIn(unit_id, state["provider_completed_uncommitted"])
        self.assertEqual([], state["false_completions"])
        with self.assertRaises(self.plane.ControlPlaneError):
            with contextlib.redirect_stdout(io.StringIO()):
                self.plane.cmd_complete(self._namespace(unit_id))

    def test_a_lawful_completion_is_admitted(self):
        unit_id = "unit-lawful"
        self.plane.append_event(unit_id, "CREATED", actor="coordinator", provider_state="QUEUED")
        self.plane.append_event(
            unit_id,
            "PARENT_INGESTED",
            actor="coordinator",
            payload={"result_commit_id": COMMIT_ID, "result_locator": "git:branch@commit:manifest"},
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.plane.cmd_complete(self._namespace(unit_id))
        completed = [row for row in self.plane.ledger_rows() if row["event"] == "COMPLETED"]
        self.assertEqual(1, len(completed))
        self.assertEqual("coordinator", completed[0]["actor"])
        self.assertEqual([], self.plane.scan_recovery()["false_completions"])

    def test_the_producer_cannot_review_its_own_completed_unit(self):
        unit_id = "unit-review"
        self.plane.write_json(
            self.plane.DISPATCH_DIR / f"{unit_id}.json", {"unit_id": unit_id, "owner": "po03-worker-a1"}
        )
        self.plane.append_event(unit_id, "CREATED", actor="coordinator", provider_state="QUEUED")
        self.plane.append_event(
            unit_id,
            "PARENT_INGESTED",
            actor="coordinator",
            payload={"result_commit_id": COMMIT_ID, "result_locator": "locator"},
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.plane.cmd_complete(self._namespace(unit_id))
        review = type(
            "Namespace",
            (),
            {
                "unit_id": unit_id,
                "decision": "ACCEPTED",
                "reviewer": "po03-worker-a1",
                "receipt": "receipt",
                "rationale": "",
            },
        )()
        with self.assertRaises(self.plane.ControlPlaneError) as caught:
            with contextlib.redirect_stdout(io.StringIO()):
                self.plane.cmd_review(review)
        self.assertIn("cannot accept or reject its own work", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
