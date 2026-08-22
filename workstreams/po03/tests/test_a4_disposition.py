import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from workstreams.po03.packverify.disposition import compile_disposition


SCRATCH = ROOT / "workstreams/po03/control/units/a4/test-scratch"


def write(root: Path, relative: str, content: str = "fixture\n"):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class DispositionFixtureTests(unittest.TestCase):
    def test_pointer_resolution_and_superseded_surface_are_deterministic(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            root = Path(temporary)
            route = [
                "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
                "state/founder.md",
                "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json",
                "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
                "instructions/functions/current.md",
                "state/operator-system/AUTHORITY_ENVELOPE_REGISTER.jsonl",
                "operations/INSTRUCTION_ESTATE_DISPOSITION_20260819_v001.md",
                "templates/NEXT_OPERATOR_PREFLIGHT_CURRENT.md",
            ]
            write(
                root,
                "operations/README.md",
                "\n".join(
                    f"{index}. `{path}`" for index, path in enumerate(route, 1)
                )
                + "\n",
            )
            for path in route:
                if path.endswith(".json"):
                    continue
                write(root, path)

            identity = {
                "strategy_snapshot_id": "snapshot",
                "function_id": "function",
                "appointment_id": "appointment",
                "commission_id": "commission",
                "authority_envelope_id": "authority",
                "runtime_binding_id": "runtime",
            }
            stack = {
                **identity,
                "resolve_in_order": ["state/founder.md"],
                "immutable_execution_evidence": [
                    "dispatch/CURRENT_LAUNCH.md"
                ],
                "supersession_rule": "unselected files remain evidence",
            }
            write(
                root,
                "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
                json.dumps(stack),
            )
            write(
                root,
                "state/operator-system/ACTIVE_OPERATOR_SYSTEM_POINTER_CURRENT.json",
                json.dumps(
                    {
                        **identity,
                        "instruction_stack": (
                            "state/operator-system/ACTIVE_INSTRUCTION_STACK.json"
                        ),
                    }
                ),
            )
            current_paths = {
                "selected_pointer": "state/CURRENT_POINTER.json",
                "selected_payload": "dispatch/CURRENT_LAUNCH.md",
                "selected_manifest": "dispatch/CURRENT_MANIFEST.json",
                "canonical_command": "dispatch/CURRENT_COMMAND.md",
            }
            active_control = {
                key: {"path": path} for key, path in current_paths.items()
            }
            active_control["superseded_pointer"] = {
                "path": "state/ACTIVE_CONTROL_POINTER_20260819_01.json"
            }
            write(
                root,
                "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
                json.dumps(active_control),
            )
            for path in current_paths.values():
                write(root, path)
            write(root, "state/ACTIVE_CONTROL_POINTER_20260819_01.json", "{}")
            write(root, "dispatch/OLD_V009_LAUNCH.md")

            first = compile_disposition(root)
            second = compile_disposition(root)
            self.assertEqual(first, second)
            by_path = {
                item["path"]: item for item in first["surface_dispositions"]
            }
            self.assertEqual(
                by_path["dispatch/CURRENT_LAUNCH.md"]["disposition"],
                "RETAIN_CURRENT",
            )
            self.assertEqual(
                by_path["dispatch/OLD_V009_LAUNCH.md"]["disposition"],
                "SUPERSEDED_UNSENT_RETAIN_EVIDENCE",
            )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
