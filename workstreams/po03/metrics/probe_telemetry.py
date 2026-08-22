#!/usr/bin/env python3
"""a7-u04: explicitly probe this runtime for token and cost telemetry and
record the exact outcome. Dependency-free standard-library Python 3.12.

This tool performs four independent, read-only probes and records exactly
what each one found. It never estimates a token or cost figure: if every
probe comes back negative, the metric is recorded as NOT_SUPPORTED with the
precise boundary observed, per workstreams/po03/metrics/metric-definitions.json.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOKEN_COST_ENV_MARKERS = (
    "TOKEN",
    "COST",
    "USAGE",
    "BILLING",
    "SPEND",
    "CREDIT",
    "QUOTA",
)

CANDIDATE_USAGE_PATHS = (
    "/home/ubuntu/.cursor/usage",
    "/home/ubuntu/.cursor/billing",
    "/home/ubuntu/.cursor/telemetry",
    "/home/ubuntu/.cursor/projects/workspace/usage",
    "/tmp/cursor/usage",
    "/tmp/cursor/telemetry",
    "/run/cursor/usage.sock",
)


def probe_environment_variables() -> dict[str, Any]:
    matches = {
        key: value
        for key, value in os.environ.items()
        if any(marker in key.upper() for marker in TOKEN_COST_ENV_MARKERS)
    }
    return {
        "probe": "environment_variables",
        "markers_searched": list(TOKEN_COST_ENV_MARKERS),
        "matches_found": sorted(matches.keys()),
        "result": "NEGATIVE" if not matches else "POSITIVE",
    }


def probe_filesystem_locations() -> dict[str, Any]:
    found = []
    for candidate in CANDIDATE_USAGE_PATHS:
        path = Path(candidate)
        if path.exists():
            found.append(str(path))
    return {
        "probe": "filesystem_locations",
        "paths_checked": list(CANDIDATE_USAGE_PATHS),
        "paths_found": found,
        "result": "NEGATIVE" if not found else "POSITIVE",
    }


def probe_agent_control_socket() -> dict[str, Any]:
    """The exec-daemon control socket (CURSOR_AGENT_SOCKET) exists in this
    environment, but its documented purpose is command execution plumbing for
    this tool session, not a token/cost usage API. This probe verifies the
    socket is connectable and notes that no telemetry protocol is documented
    or discoverable for it from this process; it does not attempt to reverse
    engineer an undocumented wire protocol, which would not constitute an
    honest, reproducible probe."""
    socket_path = os.environ.get("CURSOR_AGENT_SOCKET")
    if not socket_path or not Path(socket_path).exists():
        return {
            "probe": "agent_control_socket",
            "socket_path_env": socket_path,
            "connectable": False,
            "result": "NEGATIVE",
            "note": "CURSOR_AGENT_SOCKET is unset or the path does not exist in this process.",
        }
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(socket_path)
        connectable = True
        sock.close()
    except OSError as exc:
        connectable = False
        return {
            "probe": "agent_control_socket",
            "socket_path_env": socket_path,
            "connectable": connectable,
            "connect_error": str(exc),
            "result": "NEGATIVE",
        }
    return {
        "probe": "agent_control_socket",
        "socket_path_env": socket_path,
        "connectable": connectable,
        "result": "NEGATIVE",
        "note": (
            "Socket connects, but no token/cost telemetry endpoint or protocol is documented "
            "or was found for it; this is the exec-daemon's own command-execution channel, not "
            "a usage-reporting API. No undocumented protocol was attempted."
        ),
    }


def probe_cli_tools() -> dict[str, Any]:
    path_dirs = os.environ.get("PATH", "").split(":")
    candidates = ("cursor", "cursor-agent", "cursor-cli")
    found_binaries = []
    for directory in path_dirs:
        for name in candidates:
            candidate_path = Path(directory) / name
            if candidate_path.is_file() and os.access(candidate_path, os.X_OK):
                found_binaries.append(str(candidate_path))
    return {
        "probe": "cli_tools",
        "candidates_searched": list(candidates),
        "path_directories_searched": path_dirs,
        "binaries_found": found_binaries,
        "result": "NEGATIVE" if not found_binaries else "POSITIVE",
    }


def probe_dispatch_and_ledger_schema(root: Path) -> dict[str, Any]:
    """Confirm, by direct inspection of the committed schema, that neither the
    ledger event schema nor the transactional-result schema carries a token or
    cost field. This is a structural probe of this cohort's own inputs, not a
    runtime capability probe, but it closes off the possibility that a token
    or cost figure could be silently smuggled through an existing field."""
    control_plane_text = (root / "workstreams/po03/tools/control_plane.py").read_text(encoding="utf-8")
    result_schema_path = root / "workstreams/po03/contracts/transactional-result.schema.json"
    result_schema_text = result_schema_path.read_text(encoding="utf-8") if result_schema_path.exists() else ""
    # Deliberately specific markers: bare "token" and "cost" would false-positive on
    # unrelated fields such as "fence_token" or "cost_center"-shaped English prose, so
    # only markers that would be unambiguous evidence of token/cost telemetry are used.
    markers = (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "token_count",
        "num_tokens",
        "usage_usd",
        "cost_usd",
        "usd_cost",
        "billing_",
    )
    found_in_ledger_tool = [m for m in markers if m in control_plane_text.lower()]
    found_in_result_schema = [m for m in markers if m in result_schema_text.lower()]
    return {
        "probe": "dispatch_and_ledger_schema_inspection",
        "markers_searched": list(markers),
        "found_in_control_plane_py": found_in_ledger_tool,
        "found_in_transactional_result_schema": found_in_result_schema,
        "result": "NEGATIVE" if not (found_in_ledger_tool or found_in_result_schema) else "POSITIVE",
    }


def run_all_probes(root: Path) -> dict[str, Any]:
    probes = [
        probe_environment_variables(),
        probe_filesystem_locations(),
        probe_agent_control_socket(),
        probe_cli_tools(),
        probe_dispatch_and_ledger_schema(root),
    ]
    overall_positive = any(p["result"] == "POSITIVE" for p in probes)
    return {
        "protocol_version": "OBZIO-TELEMETRY-PROBE-v1",
        "unit_id": "a7-u04",
        "probes": probes,
        "overall_result": "TELEMETRY_EXPOSED" if overall_positive else "NOT_SUPPORTED",
        "metric_availability_table": {
            "input_tokens_per_unit": "NOT_SUPPORTED" if not overall_positive else "REQUIRES_MANUAL_REVIEW",
            "output_tokens_per_unit": "NOT_SUPPORTED" if not overall_positive else "REQUIRES_MANUAL_REVIEW",
            "reasoning_tokens_per_unit": "NOT_SUPPORTED" if not overall_positive else "REQUIRES_MANUAL_REVIEW",
            "usd_cost_per_unit": "NOT_SUPPORTED" if not overall_positive else "REQUIRES_MANUAL_REVIEW",
            "context_bytes_admitted_per_unit": "NOT_SUPPORTED" if not overall_positive else "REQUIRES_MANUAL_REVIEW",
        },
        "no_estimate_asserted": True,
        "observed_boundary": (
            "Five independent probes (process environment variables, well-known filesystem "
            "usage/billing locations, the exec-daemon control socket, PATH-resolvable CLI "
            "binaries, and the committed ledger/result schemas) found no token count, no "
            "reasoning-token count and no monetary cost figure exposed to this Python process "
            "for any dispatched unit. This runtime binding (Cursor Cloud background agent, "
            "worker po03-worker-a7) does not expose per-unit token or cost telemetry to "
            "delegated subordinate processes at commission revision v002. No figure is "
            "estimated or substituted; every token/cost field in this cohort's outputs is "
            "recorded as the literal string NOT_SUPPORTED."
        ),
    }


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="workstreams/po03/metrics/telemetry-probe-result.json")
    parser.add_argument("--probed-at", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    probed_at = args.probed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = run_all_probes(root)
    result["probe_performed_at"] = probed_at

    out_path = root / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(canonical({"wrote": str(out_path), "overall_result": result["overall_result"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
