#!/usr/bin/env python3
"""Deterministic queue/verification simulation of the PO-03 produce-then-verify factory.

The model answers one preregistered question: what happens to safety and to
throughput when producer concurrency rises without a proportional rise in
verification capacity. It is calibrated from sanitized repository-native
evidence and uses common random numbers so that differences between
configurations are structural rather than sampling noise.

Standard library only. See preregistration.json for the frozen model spec,
parameters, thresholds and falsifiers.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import statistics
from dataclasses import dataclass, field, replace
from hashlib import blake2b
from pathlib import Path
from typing import Any, Iterable

SIM_VERSION = "OBZIO-WA-018-QUEUE-VERIFICATION-SIM-v1"

BLOCKING_GATE = "BLOCKING_GATE"
DEADLINE_BYPASS = "DEADLINE_BYPASS"
SAMPLED_VERIFICATION = "SAMPLED_VERIFICATION"
TRUNCATED_VERIFICATION = "TRUNCATED_VERIFICATION"
POLICIES = (
    BLOCKING_GATE,
    DEADLINE_BYPASS,
    SAMPLED_VERIFICATION,
    TRUNCATED_VERIFICATION,
)

REWORK_INDEX_BASE = 1_000_000

# The preregistration names these metrics; their exact split is fixed here,
# before any configuration is executed, and both channels are always reported so
# no conclusion depends on which side of the split a reader prefers.
MEASUREMENT_DEFINITIONS = {
    "false_green_count": (
        "Latently defective results promoted with strictly less than nominal "
        "verification work applied. This is the capacity-attributable safety "
        "failure: it can only occur when verification was skipped or shortened."
    ),
    "escaped_defect_count": (
        "All latently defective results promoted without detection, including "
        "misses by complete verification. This is the wider safety failure and "
        "has an irreducible floor set by detect_power_full."
    ),
    "verification_wait_seconds": (
        "Time from a result being staged to its promotion decision, so it is "
        "defined identically for verified, truncated and bypassed results."
    ),
    "verified_throughput_per_hour": (
        "Promotions that received complete nominal verification work, per hour "
        "of makespan. Nominal throughput counts every promotion regardless of "
        "verification."
    ),
    "mean_time_to_detect_seconds": (
        "Dispatch to detection for defects caught by verification, and dispatch "
        "to downstream discovery for escapes that are later discovered."
    ),
}


def u01(seed: int, index: int, stream: str) -> float:
    """Draw one uniform on [0,1) addressed by (seed, unit index, stream name).

    Addressed rather than sequential draws are what make the common-random-number
    scheme hold: unit 7's produce duration is identical at every concurrency,
    verifier count and policy.
    """
    digest = blake2b(
        f"{seed}|{index}|{stream}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / 2.0**64


def _pick(population: list[int], value: float) -> int:
    return population[min(len(population) - 1, int(value * len(population)))]


def detection_power(
    work_applied: float, nominal_work: float, detect_power_full: float, k: float
) -> float:
    """Saturating concave detection power in verification work applied.

    power(0) is exactly 0 and power(nominal) is exactly detect_power_full.
    """
    if nominal_work <= 0 or work_applied <= 0:
        return 0.0
    if work_applied >= nominal_work:
        return detect_power_full
    fraction = work_applied / nominal_work
    return detect_power_full * (1.0 - math.exp(-k * fraction)) / (1.0 - math.exp(-k))


@dataclass
class Config:
    concurrency: int
    verifiers: int
    policy: str = BLOCKING_GATE
    units: int = 64
    seed: int = 20260822
    produce_population: tuple[int, ...] = (
        538, 655, 674, 693, 694, 727, 744, 1040, 1211, 2141, 2737, 3689,
    )
    verify_population: tuple[int, ...] = (
        157, 231, 237, 254, 295, 323, 329, 411, 416, 516, 546, 738,
    )
    verify_scale: float = 1.0
    latent_defect_probability: float = 0.071429
    detect_power_full: float = 0.9
    detection_k: float = 3.0
    bypass_deadline_seconds: int = 1800
    queue_cap: int = 8
    downstream_discovery_probability: float = 0.5
    discovery_delay_seconds: int = 3600
    rework_seconds: int = 1295

    def as_dict(self) -> dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "verifiers": self.verifiers,
            "policy": self.policy,
            "units": self.units,
            "seed": self.seed,
            "verify_scale": self.verify_scale,
            "latent_defect_probability": self.latent_defect_probability,
            "detect_power_full": self.detect_power_full,
            "detection_k": self.detection_k,
            "bypass_deadline_seconds": self.bypass_deadline_seconds,
            "queue_cap": self.queue_cap,
            "downstream_discovery_probability": self.downstream_discovery_probability,
            "discovery_delay_seconds": self.discovery_delay_seconds,
            "rework_seconds": self.rework_seconds,
        }


@dataclass
class Unit:
    index: int
    produce_seconds: int
    nominal_verify_seconds: int
    latent_defect: bool
    detect_draw: float
    discovery_draw: float
    is_rework: bool = False
    dispatched_at: int = -1
    staged_at: int = -1
    promoted_at: int = -1
    work_applied: float = 0.0
    detected: bool = False
    detected_at: int = -1
    escaped: bool = False


@dataclass
class _State:
    clock: int = 0
    events: list[tuple[int, int, str, int]] = field(default_factory=list)
    counter: int = 0
    staged: list[int] = field(default_factory=list)
    busy_producers: int = 0
    busy_verifiers: int = 0
    pending_dispatch: list[int] = field(default_factory=list)


class Simulation:
    """One deterministic run of the produce-then-verify pipeline."""

    def __init__(self, config: Config) -> None:
        if config.concurrency < 1 or config.verifiers < 1:
            raise ValueError("concurrency and verifiers must both be at least 1")
        if config.units < 1:
            raise ValueError("units must be at least 1")
        if not 0.0 <= config.latent_defect_probability <= 1.0:
            raise ValueError("latent_defect_probability must be a probability")
        if not 0.0 <= config.detect_power_full <= 1.0:
            raise ValueError("detect_power_full must be a probability")
        if config.policy not in POLICIES:
            raise ValueError(f"unknown policy: {config.policy}")
        self.cfg = config
        self.units: dict[int, Unit] = {}
        self.state = _State()
        self.rework_created = 0
        self._unverified_promotions = 0

    # ---- unit construction -------------------------------------------------

    def _make_unit(self, index: int, is_rework: bool) -> Unit:
        cfg = self.cfg
        verify_nominal = max(
            1,
            int(
                round(
                    _pick(list(cfg.verify_population), u01(cfg.seed, index, "verify"))
                    * cfg.verify_scale
                )
            ),
        )
        if is_rework:
            produce = cfg.rework_seconds
            latent = False
        else:
            produce = _pick(list(cfg.produce_population), u01(cfg.seed, index, "produce"))
            latent = u01(cfg.seed, index, "defect") < cfg.latent_defect_probability
        return Unit(
            index=index,
            produce_seconds=produce,
            nominal_verify_seconds=verify_nominal,
            latent_defect=latent,
            detect_draw=u01(cfg.seed, index, "detect"),
            discovery_draw=u01(cfg.seed, index, "discovery"),
            is_rework=is_rework,
        )

    # ---- event plumbing ----------------------------------------------------

    def _push(self, at: int, kind: str, index: int) -> None:
        self.state.counter += 1
        heapq.heappush(self.state.events, (at, self.state.counter, kind, index))

    # ---- pipeline stages ---------------------------------------------------

    def _dispatch(self) -> None:
        st = self.state
        while st.pending_dispatch and st.busy_producers < self.cfg.concurrency:
            index = st.pending_dispatch.pop(0)
            unit = self.units[index]
            unit.dispatched_at = st.clock
            st.busy_producers += 1
            self._push(st.clock + unit.produce_seconds, "produce_done", index)

    def _stage(self, index: int) -> None:
        st = self.state
        unit = self.units[index]
        unit.staged_at = st.clock
        st.busy_producers -= 1
        st.staged.append(index)
        if self.cfg.policy == DEADLINE_BYPASS:
            self._push(
                st.clock + self.cfg.bypass_deadline_seconds, "deadline", index
            )

    def _promote(self, index: int, work_applied: float) -> None:
        st = self.state
        unit = self.units[index]
        unit.promoted_at = st.clock
        unit.work_applied = work_applied
        if work_applied <= 0.0:
            self._unverified_promotions += 1
        power = detection_power(
            work_applied,
            float(unit.nominal_verify_seconds),
            self.cfg.detect_power_full,
            self.cfg.detection_k,
        )
        if unit.latent_defect and unit.detect_draw < power:
            unit.detected = True
            unit.detected_at = st.clock
            return
        if unit.latent_defect:
            unit.escaped = True
            if unit.discovery_draw < self.cfg.downstream_discovery_probability:
                self._push(
                    st.clock + self.cfg.discovery_delay_seconds, "discovery", index
                )

    def _assign_verifiers(self) -> None:
        st = self.state
        while st.staged and st.busy_verifiers < self.cfg.verifiers:
            index = st.staged.pop(0)
            unit = self.units[index]
            nominal = float(unit.nominal_verify_seconds)
            if self.cfg.policy == TRUNCATED_VERIFICATION:
                queue_len = len(st.staged) + 1
                fraction = min(1.0, self.cfg.verifiers / float(queue_len))
            else:
                fraction = 1.0
            work = nominal * fraction
            service = max(1, int(round(work)))
            st.busy_verifiers += 1
            self._push(st.clock + service, "verify_done", index)
            unit.work_applied = work

    def _shed_over_cap(self) -> None:
        if self.cfg.policy != SAMPLED_VERIFICATION:
            return
        st = self.state
        while len(st.staged) > self.cfg.queue_cap:
            index = st.staged.pop(0)
            self._promote(index, 0.0)

    def _settle(self) -> None:
        self._shed_over_cap()
        self._assign_verifiers()
        self._dispatch()

    # ---- driver -----------------------------------------------------------

    def run(self) -> dict[str, Any]:
        st = self.state
        for index in range(self.cfg.units):
            self.units[index] = self._make_unit(index, is_rework=False)
            st.pending_dispatch.append(index)
        self._settle()
        while st.events:
            at, _, kind, index = heapq.heappop(st.events)
            st.clock = at
            if kind == "produce_done":
                self._stage(index)
            elif kind == "verify_done":
                st.busy_verifiers -= 1
                unit = self.units[index]
                self._promote(index, unit.work_applied)
            elif kind == "deadline":
                if index in st.staged:
                    st.staged.remove(index)
                    self._promote(index, 0.0)
            elif kind == "discovery":
                self._inject_rework()
            else:  # pragma: no cover - defensive
                raise AssertionError(f"unknown event kind: {kind}")
            self._settle()
        return self._metrics()

    def _inject_rework(self) -> None:
        index = REWORK_INDEX_BASE + self.rework_created
        self.rework_created += 1
        self.units[index] = self._make_unit(index, is_rework=True)
        self.state.pending_dispatch.append(index)

    # ---- measurement ------------------------------------------------------

    def _metrics(self) -> dict[str, Any]:
        units = list(self.units.values())
        promoted = [unit for unit in units if unit.promoted_at >= 0]
        if len(promoted) != len(units):
            raise AssertionError("simulation ended with unpromoted units")
        makespan = max(unit.promoted_at for unit in promoted)
        waits = [unit.promoted_at - unit.staged_at for unit in promoted]
        full = [
            unit
            for unit in promoted
            if unit.work_applied >= float(unit.nominal_verify_seconds)
        ]
        unverified = [unit for unit in promoted if unit.work_applied <= 0.0]
        partial = len(promoted) - len(full) - len(unverified)
        escapes = [unit for unit in promoted if unit.escaped]
        false_greens = [unit for unit in escapes if unit.work_applied < float(unit.nominal_verify_seconds)]
        detected = [unit for unit in promoted if unit.detected]
        latent = [unit for unit in units if unit.latent_defect]

        detect_latencies = [
            unit.detected_at - unit.dispatched_at for unit in detected
        ]
        discovered = [
            unit
            for unit in escapes
            if unit.discovery_draw < self.cfg.downstream_discovery_probability
        ]
        detect_latencies += [
            unit.promoted_at + self.cfg.discovery_delay_seconds - unit.dispatched_at
            for unit in discovered
        ]

        work_fraction = statistics.fmean(
            [
                min(1.0, unit.work_applied / float(unit.nominal_verify_seconds))
                for unit in promoted
            ]
        )
        hours = makespan / 3600.0
        metrics = {
            "config": self.cfg.as_dict(),
            "makespan_seconds": makespan,
            "promoted_count": len(promoted),
            "wave_units": self.cfg.units,
            "fully_verified_count": len(full),
            "partially_verified_count": partial,
            "unverified_promotion_count": len(unverified),
            "latent_defect_count": len(latent),
            "detected_defect_count": len(detected),
            "false_green_count": len(false_greens),
            "escaped_defect_count": len(escapes),
            "undetected_escape_count": len(escapes) - len(discovered),
            "nominal_throughput_per_hour": round(len(promoted) / hours, 6) if hours else 0.0,
            "verified_throughput_per_hour": round(len(full) / hours, 6) if hours else 0.0,
            "mean_verification_wait_seconds": round(statistics.fmean(waits), 3),
            "p95_verification_wait_seconds": _p95(waits),
            "peak_staged_backlog": self._peak_backlog(),
            "mean_time_to_detect_seconds": (
                round(statistics.fmean(detect_latencies), 3) if detect_latencies else None
            ),
            "recovery_rework_units": self.rework_created,
            "recovery_rework_seconds": self.rework_created * self.cfg.rework_seconds,
            "verification_work_applied_fraction": round(work_fraction, 6),
        }
        _assert_conservation(metrics)
        return metrics

    def _peak_backlog(self) -> int:
        """Recover the peak staged backlog from the completed unit timeline."""
        stamps: list[tuple[int, int]] = []
        for unit in self.units.values():
            if unit.staged_at < 0:
                continue
            stamps.append((unit.staged_at, 1))
            stamps.append((unit.promoted_at, -1))
        stamps.sort()
        peak = 0
        current = 0
        for _, delta in stamps:
            current += delta
            peak = max(peak, current)
        return peak


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[rank]


def _assert_conservation(metrics: dict[str, Any]) -> None:
    """Falsifier F-018-8: a violated conservation law invalidates the run."""
    expected = metrics["wave_units"] + metrics["recovery_rework_units"]
    if metrics["promoted_count"] != expected:
        raise AssertionError(
            f"conservation violated: promoted {metrics['promoted_count']} != {expected}"
        )
    parts = (
        metrics["fully_verified_count"]
        + metrics["partially_verified_count"]
        + metrics["unverified_promotion_count"]
    )
    if parts != metrics["promoted_count"]:
        raise AssertionError("verification-class partition does not cover promotions")
    if metrics["false_green_count"] > metrics["escaped_defect_count"]:
        raise AssertionError("false greens exceed escaped defects")
    if metrics["detected_defect_count"] + metrics["escaped_defect_count"] != metrics[
        "latent_defect_count"
    ]:
        raise AssertionError("detected plus escaped does not equal latent defects")


def run_single(config: Config) -> dict[str, Any]:
    return Simulation(config).run()


def run_ensemble(base: Config, seeds: Iterable[int]) -> dict[str, Any]:
    """Run one configuration across a seed ensemble and aggregate."""
    runs = [run_single(replace(base, seed=seed)) for seed in seeds]
    return _aggregate(base, runs)


def _mean(runs: list[dict[str, Any]], key: str) -> float | None:
    values = [run[key] for run in runs if run[key] is not None]
    if not values:
        return None
    return round(statistics.fmean(values), 3)


def _aggregate(base: Config, runs: list[dict[str, Any]]) -> dict[str, Any]:
    total_false_green = sum(run["false_green_count"] for run in runs)
    seeds_with_false_green = sum(1 for run in runs if run["false_green_count"] > 0)
    return {
        "config": {
            key: value
            for key, value in base.as_dict().items()
            if key != "seed"
        },
        "seeds": len(runs),
        "false_green_total": total_false_green,
        "false_green_seeds": seeds_with_false_green,
        "false_green_seed_fraction": round(seeds_with_false_green / len(runs), 6),
        "escaped_defect_total": sum(run["escaped_defect_count"] for run in runs),
        "detected_defect_total": sum(run["detected_defect_count"] for run in runs),
        "latent_defect_total": sum(run["latent_defect_count"] for run in runs),
        "unverified_promotion_total": sum(
            run["unverified_promotion_count"] for run in runs
        ),
        "partially_verified_total": sum(
            run["partially_verified_count"] for run in runs
        ),
        "mean_makespan_seconds": _mean(runs, "makespan_seconds"),
        "mean_nominal_throughput_per_hour": _mean(runs, "nominal_throughput_per_hour"),
        "mean_verified_throughput_per_hour": _mean(
            runs, "verified_throughput_per_hour"
        ),
        "mean_verification_wait_seconds": _mean(runs, "mean_verification_wait_seconds"),
        "mean_p95_verification_wait_seconds": _mean(
            runs, "p95_verification_wait_seconds"
        ),
        "mean_peak_staged_backlog": _mean(runs, "peak_staged_backlog"),
        "mean_time_to_detect_seconds": _mean(runs, "mean_time_to_detect_seconds"),
        "mean_recovery_rework_units": _mean(runs, "recovery_rework_units"),
        "recovery_rework_units_total": sum(run["recovery_rework_units"] for run in runs),
        "mean_verification_work_applied_fraction": _mean(
            runs, "verification_work_applied_fraction"
        ),
    }


def seed_list(base: int, count: int) -> list[int]:
    return [base + index for index in range(count)]


def _cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--verifiers", type=int, default=1)
    parser.add_argument("--policy", default=BLOCKING_GATE, choices=POLICIES)
    parser.add_argument("--units", type=int, default=64)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--seed-base", type=int, default=20260822)
    parser.add_argument("--latent-defect-probability", type=float, default=0.071429)
    parser.add_argument("--detect-power-full", type=float, default=0.9)
    parser.add_argument("--detection-k", type=float, default=3.0)
    parser.add_argument("--bypass-deadline-seconds", type=int, default=1800)
    parser.add_argument("--queue-cap", type=int, default=8)
    parser.add_argument("--verify-scale", type=float, default=1.0)
    parser.add_argument("--out", default="-")
    return parser.parse_args()


def main() -> int:
    args = _cli()
    base = Config(
        concurrency=args.concurrency,
        verifiers=args.verifiers,
        policy=args.policy,
        units=args.units,
        seed=args.seed_base,
        latent_defect_probability=args.latent_defect_probability,
        detect_power_full=args.detect_power_full,
        detection_k=args.detection_k,
        bypass_deadline_seconds=args.bypass_deadline_seconds,
        queue_cap=args.queue_cap,
        verify_scale=args.verify_scale,
    )
    if args.seeds <= 1:
        payload: dict[str, Any] = {
            "sim_version": SIM_VERSION,
            "run": run_single(base),
        }
    else:
        payload = {
            "sim_version": SIM_VERSION,
            "ensemble": run_ensemble(base, seed_list(args.seed_base, args.seeds)),
        }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        print(text, end="")
    else:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
