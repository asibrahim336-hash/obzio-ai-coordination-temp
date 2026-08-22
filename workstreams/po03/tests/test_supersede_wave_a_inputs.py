import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = (
    REPO_ROOT / "workstreams" / "po03" / "tools" / "supersede_wave_a_inputs.py"
)
TOOL_SPEC = importlib.util.spec_from_file_location(
    "supersede_wave_a_inputs", TOOL_PATH
)
TOOL = importlib.util.module_from_spec(TOOL_SPEC)
assert TOOL_SPEC.loader is not None
sys.modules[TOOL_SPEC.name] = TOOL
TOOL_SPEC.loader.exec_module(TOOL)

PREPARE_PATH = REPO_ROOT / "workstreams" / "po03" / "tools" / "prepare_wave_a.py"
PREPARE_SPEC = importlib.util.spec_from_file_location("prepare_wave_a", PREPARE_PATH)
PREPARE = importlib.util.module_from_spec(PREPARE_SPEC)
assert PREPARE_SPEC.loader is not None
sys.modules[PREPARE_SPEC.name] = PREPARE
PREPARE_SPEC.loader.exec_module(PREPARE)


H = "a" * 64
CREATED_AT = "2026-08-22T07:13:11Z"
LEASE_EXPIRES_AT = "2026-08-22T13:13:11Z"


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def jsonl_bytes(rows):
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SyntheticControl:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".po03-provenance-supersession-", dir=REPO_ROOT
        )
        self.repo = Path(self.temporary.name)
        self.root = self.repo / "workstreams" / "po03"
        self.git("init", "-q")
        (self.repo / "marker.txt").write_text("protocol\n", encoding="utf-8")
        self.git("add", "marker.txt")
        self.git("commit", "-q", "-m", "protocol")
        self.ancestor = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "marker.txt").write_text("commission\n", encoding="utf-8")
        self.git("add", "marker.txt")
        self.git("commit", "-q", "-m", "commission")
        self.commission = self.git("rev-parse", "HEAD").stdout.strip()
        self._write_control()

    def cleanup(self):
        self.temporary.cleanup()

    def git(self, *args):
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
        )
        return subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "-c",
                "user.name=PO03 Test",
                "-c",
                "user.email=po03-test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _a01(self, number):
        task_id = f"PO03-WA-{number:03d}"
        slug = f"wa-{number:03d}"
        cohort = (number - 1) // 8 + 1
        return {
            "protocol_version": "OBZIO-IMMUTABLE-TASK-INPUT-v1",
            "task_id": task_id,
            "hypothesis_id": f"H-{task_id}",
            "commission_id": TOOL.COMMISSION_ID,
            "wave_id": "PO03-WAVE-A",
            "controller_run_id": TOOL.CONTROLLER_RUN_ID,
            "created_at": CREATED_AT,
            "portfolio": {
                "path": "workstreams/po03/control/wave-a-portfolio.json",
                "sha256": H,
                "dispatch_order": number,
                "cohort": cohort,
            },
            "source_base": {
                "repository": "example.invalid/po03-fixture",
                "commission_commit": self.commission,
                "minimum_protocol_ancestor": TOOL.INVALID_PROTOCOL_ANCESTOR,
            },
            "acceptance_contract": {
                "path": (
                    "workstreams/po03/control/acceptance/"
                    "wave-a-material-v1.json"
                ),
                "sha256": H,
            },
            "assignment": {
                "group": "engineering",
                "standing_function": "current-plan-engineering",
                "title": f"Synthetic task {number}",
                "falsifiable_hypothesis": "The synthetic invariant holds.",
                "required_executable_output": "A tested synthetic result.",
                "first_substantive_return_seed": False,
                "minimum_current_method_hypotheses": 0,
                "minimum_sanitized_reproductions": 0,
                "mechanism_change_or_rejection_required": False,
            },
            "configuration": {
                "subagent_type": "best-of-n-runner",
                "execution_environment": "isolated-git-worktree",
                "model_slug": "gpt-5.6-sol-xhigh",
                "reasoning": "xhigh",
                "auto_model_selection": False,
                "material_work": True,
                "context_policy": "bounded-hashed-source-capsule",
            },
            "ownership": {
                "allowed_write_globs": [
                    f"workstreams/po03/wave-a/units/{slug}/**"
                ],
                "result_slot": f"workstreams/po03/wave-a/units/{slug}/result/",
                "remote_branch_prefix": f"cursor/po03-{slug}-fixture-",
                "read_only_globs": ["workstreams/po03/control/**"],
                "prohibited_globs": ["workstreams/po01/**"],
            },
            "attempt": {
                "attempt_id": f"{task_id}-A01",
                "idempotency_key": f"po03:100bc20:{slug}:a01",
                "lease_id": f"lease-po03-{slug}-a01",
                "fence_token": 1,
                "lease_expires_at": LEASE_EXPIRES_AT,
                "checkpoint_seq": 0,
            },
            "producer_return_contract": {
                "only_permitted_terminal_report": "READY_TO_COMMIT",
                "required_fields": ["task_id"],
            },
            "preregistered_metrics": ["test_count"],
            "decision_changed": [],
        }

    def _write_control(self):
        for relative in (
            "control/inputs/wave-a",
            "control/results/wave-a",
            "control/events",
            "control/reviews/wave-a",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

        portfolio = {
            "schema_version": "1.0",
            "wave_id": "PO03-WAVE-A",
            "count": 64,
            "tasks": [
                {"number": number, "task_id": f"PO03-WA-{number:03d}"}
                for number in range(1, 65)
            ],
            "decision_changed": [],
        }
        self._write(TOOL.PORTFOLIO_REL, json_bytes(portfolio))

        registry = []
        outbox = []
        events = []
        owners = []
        active_leases = []
        pending_outbox = []
        for number in range(1, 65):
            task_id = f"PO03-WA-{number:03d}"
            slug = f"wa-{number:03d}"
            a01 = self._a01(number)
            a01_data = json_bytes(a01)
            a01_sha = sha(a01_data)
            self._write(TOOL._a01_rel(number), a01_data)
            registry.append(TOOL._a01_registry(a01, a01_sha))
            result = TOOL._set_acceptance_hash(
                TOOL._reserved_result(
                    number,
                    a01_sha,
                    f"{task_id}-A01",
                    a01["attempt"]["idempotency_key"],
                    a01["attempt"]["lease_id"],
                    1,
                    "a01",
                ),
                a01,
            )
            self._write(TOOL._result_rel(number), json_bytes(result))
            outbox_id = f"outbox-po03-{slug}-dispatch-a01"
            outbox.append(
                {
                    "outbox_id": outbox_id,
                    "task_id": task_id,
                    "operation": "DISPATCH_MATERIAL",
                    "idempotency_key": a01["attempt"]["idempotency_key"],
                    "fence_token": 1,
                    "payload_uri": TOOL._uri(TOOL._a01_rel(number)),
                    "payload_sha256": a01_sha,
                    "state": "PENDING",
                    "attempts": 0,
                    "created_at": CREATED_AT,
                    "last_attempt_at": None,
                    "delivered_at": None,
                    "cohort": a01["portfolio"]["cohort"],
                }
            )
            for to_state in ("CREATED", "LEASED"):
                seq = len(events) + 1
                events.append(
                    {
                        "event_id": f"evt-fixture-{seq:04d}",
                        "event_seq": seq,
                        "task_id": task_id,
                        "from_state": None if to_state == "CREATED" else "CREATED",
                        "to_state": to_state,
                        "actor": f"controller:{TOOL.CONTROLLER_RUN_ID}",
                        "at": CREATED_AT,
                        "fence_token": 1,
                    }
                )
            owners.append(
                {
                    "task_id": task_id,
                    "lease_id": a01["attempt"]["lease_id"],
                    "fence_token": 1,
                    "owned_globs": a01["ownership"]["allowed_write_globs"],
                    "write_mode": "BEST_OF_N_ISOLATED_WORKTREE_ONLY",
                }
            )
            active_leases.append(
                {
                    "task_id": task_id,
                    "lease_id": a01["attempt"]["lease_id"],
                    "fence_token": 1,
                    "expires_at": LEASE_EXPIRES_AT,
                    "state": "LEASED",
                    "cohort": a01["portfolio"]["cohort"],
                }
            )
            pending_outbox.append(outbox_id)

        self._write(TOOL.REGISTRY_REL, jsonl_bytes(registry))
        self._write(TOOL.OUTBOX_REL, jsonl_bytes(outbox))
        self._write(TOOL.EVENTS_REL, jsonl_bytes(events))
        self._write(
            TOOL.OWNERSHIP_REL,
            json_bytes(
                {
                    "schema_version": "1.0",
                    "subordinate_owners": owners,
                    "decision_changed": [],
                }
            ),
        )
        self._write(
            TOOL.RECOVERY_REL,
            json_bytes(
                {
                    "schema_version": "1.0",
                    "last_event_seq": len(events),
                    "scanned_at": CREATED_AT,
                    "active_leases": active_leases,
                    "pending_outbox": pending_outbox,
                    "stale_attempts_blocked": [],
                    "wave_a": {"registered": 64},
                    "decision_changed": [],
                }
            ),
        )

    def plan(self, selected):
        return TOOL.build_plan(
            self.root,
            set(selected),
            protocol_ancestor=self.ancestor,
            commission_commit=self.commission,
        )

    def snapshot(self):
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def a01_snapshot(self):
        return {
            number: (self.root / TOOL._a01_rel(number)).read_bytes()
            for number in range(1, 65)
        }

    def load_json(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def load_jsonl(self, relative):
        return [
            json.loads(line)
            for line in (self.root / relative)
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]


class ProvenanceSupersessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SyntheticControl()

    def tearDown(self):
        self.fixture.cleanup()

    def test_generator_constant_and_git_validation_use_real_commits(self):
        self.assertEqual(
            "100bc2079cedc193af3524234ab833cc9f9f4669",
            PREPARE.PROTOCOL_ANCESTOR,
        )
        PREPARE.validate_git_provenance(
            self.fixture.root,
            self.fixture.ancestor,
            self.fixture.commission,
        )

    def test_happy_path_updates_every_projection_and_preserves_cardinality(self):
        a01_before = self.fixture.a01_snapshot()
        plan = self.fixture.plan({5, 6})
        self.assertEqual((5, 6), plan.new_successors)
        TOOL.apply_plan(plan)

        a02 = self.fixture.load_json(TOOL._a02_rel(5))
        self.assertEqual("PO03-WA-005-A02", a02["attempt"]["attempt_id"])
        self.assertEqual(2, a02["attempt"]["fence_token"])
        self.assertEqual(self.fixture.ancestor, a02["source_base"]["minimum_protocol_ancestor"])
        self.assertEqual(
            sha(a01_before[5]), a02["supersedes"]["immutable_input"]["sha256"]
        )
        registry = self.fixture.load_jsonl(TOOL.REGISTRY_REL)
        material = [row for row in registry if row["task_id"].startswith("PO03-WA-")]
        self.assertEqual(64, len(material))
        task_row = next(row for row in material if row["task_id"] == "PO03-WA-005")
        self.assertEqual("PO03-WA-005-A02", task_row["attempt_id"])
        result = self.fixture.load_json(TOOL._result_rel(5))
        self.assertEqual("PO03-WA-005-A02", result["attempt"]["attempt_id"])
        outbox = [
            row
            for row in self.fixture.load_jsonl(TOOL.OUTBOX_REL)
            if row["task_id"] == "PO03-WA-005"
        ]
        self.assertEqual(["FENCED", "PENDING"], [row["state"] for row in outbox])
        events = [
            row
            for row in self.fixture.load_jsonl(TOOL.EVENTS_REL)
            if row.get("event_type") in TOOL.EVENT_KINDS
            and row["task_id"] == "PO03-WA-005"
        ]
        self.assertEqual(list(TOOL.EVENT_KINDS), [row["event_type"] for row in events])
        recovery = self.fixture.load_json(TOOL.RECOVERY_REL)
        self.assertIn(
            "outbox-po03-wa-005-dispatch-a02", recovery["pending_outbox"]
        )
        self.assertEqual(
            2,
            next(
                row["fence_token"]
                for row in recovery["active_leases"]
                if row["task_id"] == "PO03-WA-005"
            ),
        )
        self.assertEqual([], self.fixture.load_json(TOOL._review_rel(5))["decision_changed"])
        self.assertEqual(a01_before, self.fixture.a01_snapshot())

    def test_default_cli_dry_run_writes_nothing(self):
        before = self.fixture.snapshot()
        with (
            mock.patch.object(TOOL, "CORRECTED_PROTOCOL_ANCESTOR", self.fixture.ancestor),
            mock.patch.object(TOOL, "COMMISSION_COMMIT", self.fixture.commission),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                0,
                TOOL.main(["--root", str(self.fixture.root), "--tasks", "5"]),
            )
        self.assertEqual("DRY_RUN", json.loads(output.getvalue())["mode"])
        self.assertEqual(before, self.fixture.snapshot())

    def test_apply_rerun_is_byte_and_state_idempotent(self):
        TOOL.apply_plan(self.fixture.plan({5}))
        after_first = self.fixture.snapshot()
        rerun = self.fixture.plan({5})
        self.assertEqual((), rerun.new_successors)
        self.assertEqual((5,), rerun.existing_successors)
        self.assertEqual((), rerun.mutations)
        TOOL.apply_plan(rerun)
        self.assertEqual(after_first, self.fixture.snapshot())

    def test_all_64_a01_inputs_are_byte_identical_after_apply(self):
        before = self.fixture.a01_snapshot()
        TOOL.apply_plan(self.fixture.plan({5, 6, 7, 8}))
        self.assertEqual(before, self.fixture.a01_snapshot())

    def test_protected_selection_is_refused_without_writes(self):
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(TOOL.MigrationError, "protected"):
            self.fixture.plan({1})
        self.assertEqual(before, self.fixture.snapshot())

    def test_delivered_unprotected_attempt_is_refused(self):
        rows = self.fixture.load_jsonl(TOOL.OUTBOX_REL)
        row = next(row for row in rows if row["task_id"] == "PO03-WA-005")
        row.update(state="DELIVERED", attempts=1, delivered_at="2026-08-22T07:14:00Z")
        (self.fixture.root / TOOL.OUTBOX_REL).write_bytes(jsonl_bytes(rows))
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(TOOL.MigrationError, "delivered"):
            self.fixture.plan({5})
        self.assertEqual(before, self.fixture.snapshot())

    def test_divergent_preexisting_successor_is_refused(self):
        plan = self.fixture.plan({5})
        mutation_map = {mutation.relative: mutation.after for mutation in plan.mutations}
        (self.fixture.root / TOOL._a02_rel(5)).write_bytes(b'{"divergent":true}\n')
        (self.fixture.root / TOOL._review_rel(5)).write_bytes(
            mutation_map[TOOL._review_rel(5)]
        )
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(TOOL.MigrationError, "divergent A02"):
            self.fixture.plan({5})
        self.assertEqual(before, self.fixture.snapshot())

    def test_bad_full_sha_is_refused_by_generator_and_migration(self):
        bad = "f" * 40
        with self.assertRaises(ValueError):
            PREPARE.validate_git_provenance(
                self.fixture.root, bad, self.fixture.commission
            )
        with self.assertRaisesRegex(TOOL.MigrationError, "resolvable commit"):
            TOOL.build_plan(
                self.fixture.root,
                {5},
                protocol_ancestor=bad,
                commission_commit=self.fixture.commission,
            )

    def test_non_ancestor_commit_is_refused(self):
        tree = self.fixture.git("rev-parse", f"{self.fixture.ancestor}^{{tree}}").stdout.strip()
        unrelated = self.fixture.git("commit-tree", tree, "-m", "unrelated").stdout.strip()
        with self.assertRaisesRegex(TOOL.MigrationError, "not an ancestor"):
            TOOL.build_plan(
                self.fixture.root,
                {5},
                protocol_ancestor=unrelated,
                commission_commit=self.fixture.commission,
            )

    def test_late_staged_validation_failure_leaves_no_partial_writes(self):
        plan = self.fixture.plan({5})
        before = self.fixture.snapshot()
        with mock.patch.object(
            TOOL,
            "_validate_staged_payloads",
            side_effect=TOOL.MigrationError("injected late validation failure"),
        ):
            with self.assertRaisesRegex(TOOL.MigrationError, "late validation"):
                TOOL.apply_plan(plan)
        self.assertEqual(before, self.fixture.snapshot())

    def test_replace_failure_rolls_back_all_targets(self):
        plan = self.fixture.plan({5})
        before = self.fixture.snapshot()
        real_replace = TOOL.os.replace
        calls = {"forward": 0, "failed": False}

        def fail_once(source, destination):
            if "po03-rollback" not in str(source):
                calls["forward"] += 1
                if calls["forward"] == 3 and not calls["failed"]:
                    calls["failed"] = True
                    raise OSError("injected replace failure")
            return real_replace(source, destination)

        with mock.patch.object(TOOL.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(TOOL.MigrationError, "rolled back"):
                TOOL.apply_plan(plan)
        self.assertEqual(before, self.fixture.snapshot())

    def test_path_escape_via_a01_symlink_is_refused(self):
        target = self.fixture.repo / "escaped-a01.json"
        target.write_bytes((self.fixture.root / TOOL._a01_rel(5)).read_bytes())
        source = self.fixture.root / TOOL._a01_rel(5)
        source.unlink()
        source.symlink_to(target)
        with self.assertRaisesRegex(TOOL.MigrationError, "path escape"):
            self.fixture.plan({5})

    def test_only_explicitly_selected_tasks_receive_successors(self):
        TOOL.apply_plan(self.fixture.plan({5, 7}))
        names = {
            path.name
            for path in (self.fixture.root / "control/inputs/wave-a").glob("*-a02.json")
        }
        self.assertEqual({"wa-005-a02.json", "wa-007-a02.json"}, names)
        self.assertFalse((self.fixture.root / TOOL._a02_rel(6)).exists())


if __name__ == "__main__":
    unittest.main()
