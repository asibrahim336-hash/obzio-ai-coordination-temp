"""The result emitter must never count non-portable bytes as durable artifacts.

Interpreter bytecode is machine and interpreter specific.  Counting it would put
non-reproducible bytes inside the hash coverage that clean-clone reproduction is
supposed to guarantee, and it inflates byte totals with derived output.
"""

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


TOOLS = Path(__file__).parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("emit_result", TOOLS / "emit_result.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

TASK_ID = "po03-emit-test-001"
SLOT = f"workstreams/po03/attempts/{TASK_ID}"


class NonPortableClassificationTests(unittest.TestCase):
    def test_bytecode_is_non_portable(self):
        self.assertTrue(MODULE.is_non_portable(f"{SLOT}/__pycache__/thing.cpython-312.pyc"))
        self.assertTrue(MODULE.is_non_portable(f"{SLOT}/thing.pyc"))
        self.assertTrue(MODULE.is_non_portable(f"{SLOT}/thing.pyo"))

    def test_native_objects_are_non_portable(self):
        for suffix in (".so", ".dylib", ".dll"):
            self.assertTrue(MODULE.is_non_portable(f"{SLOT}/native{suffix}"))

    def test_tool_caches_are_non_portable(self):
        self.assertTrue(MODULE.is_non_portable(f"{SLOT}/.pytest_cache/v/cache/lastfailed"))
        self.assertTrue(MODULE.is_non_portable(f"{SLOT}/.mypy_cache/3.12/x.json"))

    def test_source_and_evidence_are_portable(self):
        self.assertFalse(MODULE.is_non_portable(f"{SLOT}/component.py"))
        self.assertFalse(MODULE.is_non_portable(f"{SLOT}/test_component.py"))
        self.assertFalse(MODULE.is_non_portable(f"{SLOT}/evidence.json"))
        self.assertFalse(MODULE.is_non_portable(f"{SLOT}/test_output.txt"))


class EmitterExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repository"
        (self.repo / "workstreams/po03/tools").mkdir(parents=True)
        (self.repo / "workstreams/po03/tools/validate_contracts.py").write_bytes(
            (TOOLS / "validate_contracts.py").read_bytes()
        )
        capsule_dir = self.repo / "workstreams/po03/control/tasks" / TASK_ID
        capsule_dir.mkdir(parents=True)
        capsule = {
            "task_id": TASK_ID,
            "falsifiable_hypothesis": "bytecode is excluded from counted artifacts",
            "ownership": {"result_slot": SLOT},
            "source_hashes": {"acceptance_contract_sha256": "a" * 64},
            "transaction": {
                "idempotency_key": f"COM:{TASK_ID}:attempt-1",
                "lease_id": f"lease-{TASK_ID}-1",
                "fence_token": 1,
                "attempt_number": 1,
            },
        }
        (capsule_dir / "input.json").write_text(json.dumps(capsule, indent=2), encoding="utf-8")

        slot = self.repo / SLOT
        (slot / "__pycache__").mkdir(parents=True)
        (slot / "component.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (slot / "test_component.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
        (slot / "test_output.txt").write_text("Ran 1 test\nOK\n", encoding="utf-8")
        (slot / "__pycache__" / "component.cpython-312.pyc").write_bytes(b"\x00bytecode-bytes\x00")

        self._git("init", "--quiet")
        self._git("config", "user.email", "po03@obzio.invalid")
        self._git("config", "user.name", "PO-03 Test")
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "po03: emitter fixture")
        self.commit = self._git("rev-parse", "HEAD")

    def _git(self, *arguments):
        return subprocess.run(
            ("git", *arguments), cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def _emit(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = MODULE.main(
                [
                    "--repo-root", str(self.repo),
                    "--task-id", TASK_ID,
                    "--artifact-commit", self.commit,
                    "--result-branch", "po03/emit-test",
                    "--worker-id", f"{TASK_ID}-producer",
                    "--provider-run-id", "NOT_SUPPORTED",
                    "--exact-model", "gpt-5.6-sol-xhigh",
                    "--verdict", "PASS",
                    "--evidence", "ran the component and its test",
                ]
            )
        return code, json.loads(buffer.getvalue())

    def test_bytecode_is_excluded_from_counted_artifacts(self):
        code, summary = self._emit()
        self.assertEqual(0, code)
        manifest = json.loads((self.repo / SLOT / "manifest.json").read_text(encoding="utf-8"))
        names = [artifact["logical_name"] for artifact in manifest["artifacts"]]
        self.assertNotIn("__pycache__/component.cpython-312.pyc", names)
        self.assertEqual(
            ["component.py", "test_component.py", "test_output.txt"], sorted(names)
        )
        self.assertEqual(3, summary["artifact_count"])

    def test_exclusion_is_recorded_rather_than_silent(self):
        _, summary = self._emit()
        self.assertEqual(
            [f"{SLOT}/__pycache__/component.cpython-312.pyc"],
            summary["excluded_non_portable_paths"],
        )
        manifest = json.loads((self.repo / SLOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [f"{SLOT}/__pycache__/component.cpython-312.pyc"],
            manifest["excluded_non_portable_paths"],
        )

    def test_byte_total_excludes_bytecode(self):
        _, summary = self._emit()
        manifest = json.loads((self.repo / SLOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            sum(artifact["bytes"] for artifact in manifest["artifacts"]), summary["total_bytes"]
        )

    def test_emitted_result_satisfies_the_seeded_contract(self):
        self._emit()
        result = json.loads((self.repo / SLOT / "result.json").read_text(encoding="utf-8"))
        spec = importlib.util.spec_from_file_location(
            "po03_validator_check", self.repo / "workstreams/po03/tools/validate_contracts.py"
        )
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        self.assertEqual([], validator.validate_result(result))

    def test_producer_cannot_emit_completion_or_self_acceptance(self):
        self._emit()
        result = json.loads((self.repo / SLOT / "result.json").read_text(encoding="utf-8"))
        self.assertEqual("RESULT_COMMITTED", result["obzio_state"])
        self.assertIsNone(result["completion_actor"])
        self.assertEqual("NOT_TESTED", result["independent_acceptance"]["state"])
        self.assertIsNone(result["result_transaction"]["parent_ingested_at"])

    def test_emitting_leaves_no_bytecode_in_a_shared_path(self):
        """A producer owns only its slot, so this tool must not write elsewhere."""
        tools = self.repo / "workstreams/po03/tools"
        self._emit()
        self.assertEqual([], sorted(tools.rglob("__pycache__")))
        self.assertEqual([], sorted(tools.rglob("*.pyc")))

    def test_a_slot_holding_only_bytecode_is_refused(self):
        for name in ("component.py", "test_component.py", "test_output.txt"):
            (self.repo / SLOT / name).unlink()
        self._git("add", "-A")
        self._git("commit", "--quiet", "-m", "po03: bytecode only")
        self.commit = self._git("rev-parse", "HEAD")
        with self.assertRaises(SystemExit):
            self._emit()


if __name__ == "__main__":
    unittest.main()
