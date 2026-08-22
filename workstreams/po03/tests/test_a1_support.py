"""Shared fixtures for the cohort a1 custody-engine tests.

This module holds no test cases.  It exists because every a1 test needs the
same two things and neither may be improvised per file:

* the engine package on ``sys.path`` without installing anything;
* a scratch directory that is *not* under ``/tmp``.  The commission forbids a
  result that depends on ``/tmp`` state, so scratch space lives inside the
  repository under the cohort's own owned subtree and is removed again in
  ``tearDown``.  Nothing committed ever depends on it.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from types import ModuleType

PO03_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PO03_ROOT.parents[1]
ENGINE_ROOT = PO03_ROOT / "engine"
SCRATCH_ROOT = ENGINE_ROOT / "_scratch"

if str(PO03_ROOT) not in sys.path:
    sys.path.insert(0, str(PO03_ROOT))


def load_isolated_module(path: Path, name: str) -> ModuleType:
    """Load a coordinator-owned tool as a private module instance.

    The control plane keeps its state paths in module globals.  Loading a fresh
    private instance and repointing those globals at scratch space is the only
    way a subordinate can test the coordinator's real code without writing a
    single byte into the coordinator's tree, which it does not own.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScratchCase(unittest.TestCase):
    """Base case providing ``self.scratch``, a repo-local disposable directory."""

    def setUp(self) -> None:
        super().setUp()
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.scratch = SCRATCH_ROOT / f"{self.__class__.__name__}-{uuid.uuid4().hex[:12]}"
        self.scratch.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)
        super().tearDown()

    def assertNotUnderTmp(self, path: Path) -> None:
        resolved = Path(path).resolve()
        self.assertFalse(
            str(resolved).startswith("/tmp/"),
            f"{resolved} is under /tmp; no result or test state may depend on it",
        )


if __name__ == "__main__":  # pragma: no cover
    print(f"support module; engine root {ENGINE_ROOT}")
