"""a5-u07: a two-phase "lease" actor that calls the REAL, unmodified,
sandboxed ``control_plane.py`` functions in exactly the sequence
``cmd_lease`` uses them, split into two yield points so a DST scheduler can
interleave it with other concurrent actors racing to lease the same unit.

``cmd_lease`` (workstreams/po03/tools/control_plane.py) does, in order:

    units = project_units()               # phase 1: read current fence_token
    fence = units[unit_id]["fence_token"] + 1
    row = append_event(unit_id, "LEASED", ..., fence_token=fence, ...)  # phase 2: append

This module calls those exact two real functions, in that exact order, on a
worker-owned sandboxed module instance (see ``sandboxed_control_plane.py``).
It does not reimplement or approximate control_plane's logic -- it drives
the real logic through a controlled interleaving window that a single
sequential invocation could never expose, because ``project_units`` and
``append_event`` are two separate calls with no lock held across them.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any, Iterator


def seed_created_unit(module: ModuleType, unit_id: str) -> None:
    module.append_event(unit_id, "CREATED", actor="coordinator", provider_state="UNKNOWN", payload={})


def lease_race_actor(module: ModuleType, unit_id: str, worker_id: str, out: dict[str, Any]) -> Iterator[str]:
    """Two-step generator mirroring cmd_lease's real read-then-append
    pattern. ``out`` is a per-actor dict the caller pre-creates; this
    generator fills it in as it progresses so results survive even if a
    scheduler interleaves many of these against the same shared ledger."""
    units = module.project_units()
    computed_fence = units[unit_id]["fence_token"] + 1
    out["phase"] = "read_done"
    out["computed_fence"] = computed_fence
    yield "read_fence"

    row = module.append_event(
        unit_id,
        "LEASED",
        actor="coordinator",
        provider_state="RUNNING",
        fence_token=computed_fence,
        payload={
            "lease_id": f"lease-{unit_id}-{computed_fence}-{worker_id}",
            "worker_id": worker_id,
            "expires_at": "2026-08-22T08:00:00Z",
            "ttl_seconds": 900,
        },
    )
    out["phase"] = "append_done"
    out["row_sha256"] = row["row_sha256"]
    out["appended_fence_token"] = row["fence_token"]
    yield "append_leased"


def leased_rows_for_unit(module: ModuleType, unit_id: str) -> list[dict[str, Any]]:
    return [row for row in module.ledger_rows() if row["unit_id"] == unit_id and row["event"] == "LEASED"]


def fence_collision_detected(module: ModuleType, unit_id: str) -> bool:
    """True if two or more LEASED rows for the unit share a fence_token --
    a violation of the safety property control_plane.py's own docstring
    claims: 'A stale worker (lower fence token) cannot commit after
    ownership transfers,' which presumes fence tokens granted by LEASED
    events are unique per lease grant."""
    tokens = [row["fence_token"] for row in leased_rows_for_unit(module, unit_id)]
    return len(tokens) != len(set(tokens))
