"""Tests for the triage and routing of whole-tree gate findings (a3-u02, a3-u04).

The integrated tree fails gates that passed on every branch that produced it,
because each cohort's gate ran over a tree holding only that cohort's files. So
the gate output stops being a pass/fail signal and becomes a work list, and a
work list has its own correctness conditions: every finding needs a verdict,
every verdict needs an owner who can act on it, and no finding may quietly
vanish between the prober and the list.

Those are the conditions asserted here. What is deliberately not asserted is
that any particular finding still exists: these are routed so they get fixed,
and a test that broke when they were fixed would be an argument for leaving
them alone.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_DIR = REPO_ROOT / "workstreams" / "po03" / "runtime"
ROUTER_PATH = RUNTIME_DIR / "route_findings.py"
ROUTED_PATH = RUNTIME_DIR / "routed-findings.json"
TRIAGE_PATH = RUNTIME_DIR / "finding-triage.json"
OWNERSHIP_PATH = REPO_ROOT / "workstreams" / "po03" / "control" / "path-ownership.json"

OWNED_PREFIXES = (
    "workstreams/po03/runtime/",
    "workstreams/po03/control/units/a3/",
    "workstreams/po03/tests/test_a3_",
    ".github/workflows/po03-path-scope.yml",
    ".github/workflows/po03-clean-clone.yml",
    "receipts/po03/2026-08-22/ci-clean-clone.json",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


router = load_module(ROUTER_PATH, "po03_route_findings")
TRIAGE = json.loads(TRIAGE_PATH.read_text(encoding="utf-8"))


class TriageDocumentIsComplete(unittest.TestCase):
    def test_every_verdict_is_one_of_the_three(self) -> None:
        allowed = {"GENUINE", "FALSE_POSITIVE", "UNTRIAGED"}
        entries = list(TRIAGE["per_finding"]) + list(TRIAGE["per_class"].values())
        entries += list(TRIAGE["role_verdicts"].values())
        for entry in entries:
            self.assertIn(entry["verdict"], allowed, entry)

    def test_every_verdict_carries_a_justification_and_a_fix(self) -> None:
        """A verdict without a reason is an opinion, and cannot be routed."""
        entries = list(TRIAGE["per_finding"]) + list(TRIAGE["per_class"].values())
        entries += list(TRIAGE["role_verdicts"].values())
        for entry in entries:
            self.assertTrue(entry["justification"].strip(), entry)
            self.assertTrue(entry["minimal_fix"].strip(), entry)

    def test_a_genuine_verdict_names_a_fix_rather_than_deferring(self) -> None:
        for entry in TRIAGE["per_finding"]:
            if entry["verdict"] != "GENUINE":
                continue
            self.assertNotEqual(entry["minimal_fix"], "NOT_YET", entry)
            self.assertNotIn("none required", entry["minimal_fix"], entry)

    def test_the_hermeticity_accounting_adds_up(self) -> None:
        """Every original finding is accounted for, none dropped unexplained."""
        measured = TRIAGE["measured_at"]
        self.assertEqual(
            measured["hermeticity_reportable_after"]
            + measured["hermeticity_exempt_by_role_after"]
            + measured["hermeticity_advisory_after"],
            measured["hermeticity_findings_before_precision_work"],
        )

    def test_the_ci_surface_population_is_fully_triaged(self) -> None:
        population = TRIAGE["ci_surface_population"]
        totals = population["totals"]
        genuine = sum(
            entry["observed_count_coordinator"]
            for entry in population["classes"]
            if entry["verdict"] == "GENUINE"
        )
        false_positive = sum(
            entry["observed_count_coordinator"]
            for entry in population["classes"]
            if entry["verdict"] == "FALSE_POSITIVE"
        )
        self.assertEqual(genuine, totals["genuine"])
        self.assertEqual(false_positive, totals["false_positive"])
        self.assertEqual(genuine + false_positive, totals["coordinator_reported"])

    def test_the_counts_are_pinned_to_a_commit_rather_than_to_live_state(self) -> None:
        """Anti-coupling. The counts are observations, not invariants.

        Nothing recomputes them and compares. They are recorded at a pin so a
        reader can reproduce them, and they are expected to change as the routed
        findings land -- which is the point of routing them.
        """
        pin = TRIAGE["observation_pin"]
        self.assertRegex(pin["commit"], r"^[0-9a-f]{12}$")
        known = subprocess.run(
            ["git", "cat-file", "-e", f"{pin['commit']}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(known.returncode, 0, known.stderr)

    def test_the_sys_path_verdict_is_argued_and_states_its_own_exposure(self) -> None:
        """The judgement the coordinator asked for, with its failure mode named.

        Getting this wrong in either direction is costly, so the verdict has to
        carry the case against itself. A conclusion with no stated way of being
        wrong is not a judgement.
        """
        verdict = TRIAGE["sys_path_verdict"]
        self.assertEqual(verdict["verdict"].split(".")[0], "ACCEPTED_PATTERN")
        self.assertGreaterEqual(len(verdict["reasoning"]), 3)
        self.assertTrue(verdict["how_this_could_be_wrong"].strip())
        self.assertTrue(verdict["what_is_not_dismissed"].strip())


class TheRoutedListIsReadableWithoutRunningTheTool(unittest.TestCase):
    """The coordinator asked for a list, and a tool is not a list.

    A routed work list that only exists when someone runs a script cannot be read
    in review, cannot be quoted in a dispatch, and puts the burden of reproducing
    my analysis on the person I am reporting to. So the list is committed.

    What is asserted here is the shape a reader needs and nothing about the
    contents. Asserting that a fresh run still produces this file would be exactly
    the recomputation-against-a-committed-record the anti-coupling rule forbids,
    and it would also be wrong on the merits: these findings are routed so that
    they get fixed, so the file is expected to go stale.
    """

    def setUp(self) -> None:
        self.document = json.loads(ROUTED_PATH.read_text(encoding="utf-8"))

    def test_the_document_says_it_is_an_observation_rather_than_an_invariant(self) -> None:
        self.assertEqual(self.document["schema"], "po03-routed-findings-v1")
        self.assertTrue(self.document["document_status"].startswith("OBSERVATION_AT_A_PIN"))

    def test_it_names_the_tree_it_was_generated_from(self) -> None:
        """Without this an owner cannot tell if a line number still means anything."""
        self.assertRegex(self.document["generated_from_tree_at"], r"^([0-9a-f]{12}|NOT_OBSERVABLE)$")

    def test_every_genuine_entry_carries_the_five_fields_a_router_needs(self) -> None:
        genuine = [r for r in self.document["findings"] if r["triage"] == "GENUINE"]
        self.assertTrue(genuine, "a routed list with nothing routed proves nothing")
        for record in genuine:
            for field in ("owner", "file", "line", "finding_class", "minimal_fix"):
                self.assertTrue(str(record[field]).strip(), f"{field} empty in {record}")
            self.assertNotEqual(record["minimal_fix"], "NOT_YET", record)

    def test_it_routes_nothing_to_me(self) -> None:
        self.assertEqual(self.document["mine_to_fix"], [])


class RoutingUsesTheAuthoritativeRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.routed = router.route(REPO_ROOT)

    def test_owners_come_from_path_ownership_and_not_from_a_local_table(self) -> None:
        """A routing table in the tool would drift from the record that governs.

        Asserted by construction rather than by inspection: every owner the
        router emits must be a name that appears in path-ownership.json.
        """
        declared = set(json.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))["owners"])
        emitted = {record["owner"] for record in self.routed["findings"]}
        self.assertTrue(emitted)
        self.assertEqual(emitted - declared, set())
        self.assertIn("path-ownership.json", self.routed["routing_authority"])

    def test_the_longest_matching_prefix_wins(self) -> None:
        """String-prefix matching let a shorter grant swallow a longer one.

        This is the same hazard that put a typed grants block into
        path-ownership.json. Until that block is authoritative, ordering by
        length is what keeps a nested grant from being routed to the parent.
        """
        pairs = [("workstreams/po03/", "outer"), ("workstreams/po03/runtime/", "inner")]
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        self.assertEqual(
            router.resolve_owner("workstreams/po03/runtime/hermeticity.py", pairs), "inner"
        )
        self.assertEqual(router.resolve_owner("workstreams/po03/engine/x.py", pairs), "outer")

    def test_an_unrecognised_path_is_named_rather_than_guessed(self) -> None:
        self.assertEqual(router.resolve_owner("packs/x.json", []), "UNOWNED")

    def test_every_finding_reaches_an_owner(self) -> None:
        unowned = sorted(
            {
                record["file"]
                for record in self.routed["findings"]
                if record["owner"] == "UNOWNED"
            }
        )
        self.assertEqual(unowned, [], f"findings no owner claims: {unowned}")

    def test_no_finding_escapes_triage(self) -> None:
        untriaged = [
            f"{record['finding_class']} {record['file']}:{record['line']}"
            for record in self.routed["findings"]
            if record["triage"] == "UNTRIAGED"
        ]
        self.assertEqual(untriaged, [], f"findings with no verdict: {untriaged}")

    def test_the_disposition_distinguishes_two_findings_of_one_class_in_one_file(self) -> None:
        """The bug the first version of this router had.

        ``boundary_run.py`` carries an ABS_PATH_LITERAL that is reported and
        another that a role exempts. Keyed on class and file alone, the exempted
        one borrowed the reported one's GENUINE verdict and would have been
        routed to a4 as work that does not exist.
        """
        reported = router.triage_for(
            {
                "rule": "ABS_PATH_LITERAL",
                "path": "workstreams/po03/packverify/boundary_run.py",
                "disposition": "REPORTED",
            },
            TRIAGE,
        )
        exempt = router.triage_for(
            {
                "rule": "ABS_PATH_LITERAL",
                "path": "workstreams/po03/packverify/boundary_run.py",
                "disposition": "EXEMPT_BY_ROLE",
                "exempt_role": "FSTRING_FRAGMENT",
            },
            TRIAGE,
        )
        self.assertEqual(reported["verdict"], "GENUINE")
        self.assertEqual(exempt["verdict"], "FALSE_POSITIVE")

    def test_i_route_rather_than_fix_another_cohorts_file(self) -> None:
        """The constraint, asserted rather than promised.

        Every genuine finding outside my owned prefixes has an owner who is not
        me, and my own list is empty. If it were not empty the correct response
        would be to fix mine, not to route it.
        """
        self.assertEqual(self.routed["mine_to_fix"], [])
        for record in self.routed["findings"]:
            if record["triage"] != "GENUINE":
                continue
            mine = record["file"].startswith(OWNED_PREFIXES)
            self.assertFalse(mine, f"a genuine finding in my own file: {record}")

    def test_the_routed_list_names_everything_needed_to_act(self) -> None:
        for record in self.routed["findings"]:
            for field in ("owner", "file", "line", "finding_class", "triage", "minimal_fix"):
                self.assertIn(field, record)

    def test_the_command_prints_a_routable_list(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ROUTER_PATH), "--only", "GENUINE"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("genuine by owner", result.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
