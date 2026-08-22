"""Black-box recurrence tests for the WA-002 compiler CLI."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


UNIT = Path(__file__).resolve().parents[1]
COMPILER = UNIT / "current_source_compiler.py"
FIXTURES = UNIT / "fixtures"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class CompilerCliTests(unittest.TestCase):
    maxDiff = None

    def invoke(
        self, repository: Path, output: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-I",
            str(COMPILER),
            str(repository / "pointer.json"),
            "--repository",
            str(repository),
        ]
        if output is not None:
            command.extend(["--output", str(output)])
        return subprocess.run(
            command,
            check=False,
            cwd=UNIT,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def copy_fixture(self, name: str, destination: Path) -> Path:
        repository = destination / name
        shutil.copytree(FIXTURES / name, repository)
        return repository

    def rewrite_json(self, path: Path, mutate) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_bytes(_json_bytes(value))

    def update_candidate_hash(
        self, repository: Path, source_relative: str, candidate_index: int = 0
    ) -> None:
        source_sha = hashlib.sha256(
            (repository / source_relative).read_bytes()
        ).hexdigest()
        self.rewrite_json(
            repository / "pointer.json",
            lambda value: value["selections"][0]["candidates"][candidate_index].update(
                sha256=source_sha
            ),
        )

    def rejection(self, process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual(2, process.returncode, process)
        self.assertEqual("", process.stdout)
        return json.loads(process.stderr)

    def test_current_source_is_resolved(self):
        process = self.invoke(FIXTURES / "current")
        self.assertEqual(0, process.returncode, process.stderr)
        compiled = json.loads(process.stdout)
        self.assertEqual(
            ["source-current-v2"],
            [item["source_id"] for item in compiled["resolved_sources"]],
        )
        self.assertEqual([], compiled["superseded_sources"])
        self.assertRegex(compiled["resolution_sha256"], r"^[0-9a-f]{64}$")

    def test_superseded_source_is_classified_but_not_selected(self):
        process = self.invoke(FIXTURES / "superseded")
        self.assertEqual(0, process.returncode, process.stderr)
        compiled = json.loads(process.stdout)
        self.assertEqual(
            ["source-current-v2"],
            [item["source_id"] for item in compiled["resolved_sources"]],
        )
        self.assertEqual(
            ["source-legacy-v1"],
            [item["source_id"] for item in compiled["superseded_sources"]],
        )
        self.assertEqual(
            "source-current-v2",
            compiled["superseded_sources"][0]["superseded_by"],
        )

    def test_ambiguous_current_sources_fail_closed_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "compilation.json"
            process = self.invoke(FIXTURES / "ambiguous", output)
            rejection = self.rejection(process)
            self.assertEqual(
                "AMBIGUOUS_CURRENT_SOURCE", rejection["error"]["code"]
            )
            self.assertFalse(output.exists())

    def test_rejection_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "compilation.json"
            output.write_text("retained\n", encoding="utf-8")
            process = self.invoke(FIXTURES / "ambiguous", output)
            self.rejection(process)
            self.assertEqual("retained\n", output.read_text(encoding="utf-8"))

    def test_source_byte_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))
            source = repository / "sources/current-instruction.json"
            source.write_bytes(source.read_bytes() + b" ")
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("HASH_MISMATCH", rejection["error"]["code"])

    def test_source_declaration_cannot_disagree_with_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))
            source_relative = "sources/current-instruction.json"
            self.rewrite_json(
                repository / source_relative,
                lambda value: value.update(source_id="source-substitution"),
            )
            self.update_candidate_hash(repository, source_relative)
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual(
                "DECLARATION_MISMATCH", rejection["error"]["code"]
            )

    def test_missing_current_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("superseded", Path(temporary))
            source_relative = "sources/current-instruction.json"
            self.rewrite_json(
                repository / source_relative,
                lambda value: value.update(standing="SUPERSEDED"),
            )
            pointer = repository / "pointer.json"

            def mutate(value):
                candidate = value["selections"][0]["candidates"][1]
                candidate["standing"] = "SUPERSEDED"
                candidate["superseded_by"] = "source-legacy-v1"

            self.rewrite_json(pointer, mutate)
            self.update_candidate_hash(repository, source_relative, candidate_index=1)
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("NO_CURRENT_SOURCE", rejection["error"]["code"])

    def test_broken_supersession_edge_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("superseded", Path(temporary))
            self.rewrite_json(
                repository / "pointer.json",
                lambda value: value["selections"][0]["candidates"][0].update(
                    superseded_by="unselected-source"
                ),
            )
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("BROKEN_SUPERSESSION", rejection["error"]["code"])

    def test_duplicate_logical_selection_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))

            def duplicate(value):
                value["selections"].append(value["selections"][0])

            self.rewrite_json(repository / "pointer.json", duplicate)
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual(
                "AMBIGUOUS_LOGICAL_SOURCE", rejection["error"]["code"]
            )

    def test_non_current_pointer_is_not_a_launch_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))
            self.rewrite_json(
                repository / "pointer.json",
                lambda value: value.update(status="SUPERSEDED"),
            )
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("POINTER_NOT_CURRENT", rejection["error"]["code"])

    def test_repository_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))
            self.rewrite_json(
                repository / "pointer.json",
                lambda value: value["selections"][0]["candidates"][0].update(
                    path="../outside.json"
                ),
            )
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("PATH_ESCAPE", rejection["error"]["code"])

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = self.copy_fixture("current", Path(temporary))
            pointer = repository / "pointer.json"
            text = pointer.read_text(encoding="utf-8")
            pointer.write_text(
                text.replace(
                    '"status": "CURRENT"',
                    '"status": "CURRENT",\n  "status": "CURRENT"',
                ),
                encoding="utf-8",
            )
            rejection = self.rejection(self.invoke(repository))
            self.assertEqual("DUPLICATE_JSON_KEY", rejection["error"]["code"])

    def test_compilation_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.json"
            second = Path(temporary) / "second.json"
            first_process = self.invoke(FIXTURES / "superseded", first)
            second_process = self.invoke(FIXTURES / "superseded", second)
            self.assertEqual(0, first_process.returncode, first_process.stderr)
            self.assertEqual(0, second_process.returncode, second_process.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
