"""Load the real, unmodified coordinator control plane into a private sandbox.

``workstreams/po03/tools/control_plane.py`` is coordinator-owned; this worker
may read and execute it as a library but must never write to the shared
paths it defaults to (``workstreams/po03/control/events/ledger.jsonl`` and
friends), since those belong to the coordinator, not to ``po03-worker-a5``.

This loader imports a fresh copy of the real module by source path (so its
logic is byte-identical to the live mechanism) and then redirects only its
mutable path constants into a sandbox directory that must live under this
worker's own ``workstreams/po03/research/`` subtree. Every function in the
module reads those constants from its own globals at call time, so the
redirection is complete: no test run through this loader can touch shared
coordinator state.
"""

from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path
from types import ModuleType

PO03_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_ROOT = PO03_ROOT / "research"
CONTROL_PLANE_SOURCE = PO03_ROOT / "tools" / "control_plane.py"

_counter = itertools.count()


def load_sandboxed_control_plane(sandbox_root: Path) -> ModuleType:
    sandbox_root = sandbox_root.resolve()
    research_root = RESEARCH_ROOT.resolve()
    if sandbox_root != research_root and research_root not in sandbox_root.parents:
        raise ValueError(
            f"sandbox_root {sandbox_root} must live under this worker's own "
            f"{research_root}; refusing to load the control plane against a "
            "path outside po03-worker-a5's ownership"
        )
    module_name = f"po03_control_plane_sandbox_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(module_name, CONTROL_PLANE_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    sandbox_root.mkdir(parents=True, exist_ok=True)
    module.LEDGER_PATH = sandbox_root / "events" / "ledger.jsonl"
    module.REGISTRY_PATH = sandbox_root / "work-unit-registry.jsonl"
    module.RECOVERY_PATH = sandbox_root / "recovery-state.json"
    module.DISPATCH_DIR = sandbox_root / "dispatch"
    module.PATH_OWNERSHIP_PATH = sandbox_root / "path-ownership.json"
    return module
