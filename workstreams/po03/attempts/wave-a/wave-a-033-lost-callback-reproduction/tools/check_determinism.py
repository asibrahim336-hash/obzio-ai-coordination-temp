#!/usr/bin/env python3
"""Compare two reproduction runs and report whether the faults are deterministic.

Wall times, temporary sandbox paths and event hashes vary between runs by
construction, so they are excluded. Everything that carries a claim - verdicts,
error messages, recovery classifications and counters - must match exactly.

Usage:
    python3 tools/check_determinism.py run-a.json run-b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

VOLATILE_KEYS = frozenset(
    {
        "sandbox_root",
        "wall_seconds",
        "total_wall_seconds",
        "lease_expiry_wait_seconds",
        "recorded_at",
    }
)
# Capsule and event digests hash a creation timestamp and the sandbox's own
# commit SHA, so they differ between runs by construction. Excluding them keeps
# the comparison focused on fault behaviour; the digests are still asserted for
# internal consistency by the factory's own chain verification, which the
# scenarios record as ``chain_errors``.
VOLATILE_FIELDS = frozenset(
    {
        "latest_event_sha256",
        "sandbox_root",
        "input_sha256",
        "created_event_sha256",
    }
)


def _strip(value: Any) -> Any:
    """Drop run-varying fields from a nested observation."""
    if isinstance(value, dict):
        return {
            key: _strip(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_FIELDS and key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def claim_shape(document: dict[str, Any]) -> dict[str, str]:
    """Reduce one run to the set of claims it asserts."""
    shape: dict[str, str] = {}
    for scenario in document["scenarios"]:
        scenario_id = scenario["scenario_id"]
        for key, value in scenario.items():
            if key in VOLATILE_KEYS:
                continue
            shape[f"{scenario_id}.{key}"] = json.dumps(_strip(value), sort_keys=True)
    return shape


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first")
    parser.add_argument("second")
    arguments = parser.parse_args()

    with open(arguments.first, encoding="utf-8") as handle:
        first = claim_shape(json.load(handle))
    with open(arguments.second, encoding="utf-8") as handle:
        second = claim_shape(json.load(handle))

    differing = [key for key in sorted(set(first) | set(second)) if first.get(key) != second.get(key)]
    print(f"compared_claims={len(set(first) | set(second))}")
    print(f"differing_claims={len(differing)}")
    for key in differing:
        print(f"  DIFF {key}\n    a={first.get(key)}\n    b={second.get(key)}")
    print("DETERMINISTIC" if not differing else "NONDETERMINISTIC")
    return 0 if not differing else 1


if __name__ == "__main__":
    sys.exit(main())
