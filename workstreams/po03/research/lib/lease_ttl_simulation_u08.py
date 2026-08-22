"""a5-u08: does lease-TTL tuning have a measurable optimum for a fleet
workload, rather than being an arbitrary constant?

A discrete-event simulation generates, ONCE per worker with a single seeded
RNG stream, a fixed timeline of heartbeat-intended times and (probabilistic)
crash times for a sequence of "epochs" (tasks). That timeline is entirely
independent of any TTL value. The SAME fixed timelines are then replayed
against each candidate TTL in the sweep, so every TTL is evaluated against
identical underlying randomness -- a controlled comparison, not independent
noisy samples.

For each epoch and TTL we classify exactly one outcome:

* ``true_recovery``  -- the worker actually crashed and the TTL-based lease
  expiry correctly detected it; ``recovery_time`` is how long detection took
  after the real crash.
* ``false_eviction``  -- the worker never crashed, but heartbeat jitter (or
  an occasional larger stall, modelling a GC pause / scheduler hiccup)
  produced a gap exceeding the TTL, so a live worker's lease is wrongly
  reclaimed.
* ``none``  -- the epoch completed with no crash and no premature eviction.

A sentinel checkpoint at the epoch's natural end guarantees every epoch
resolves to exactly one of the three outcomes (no epoch is left unclassified
by falling off the end of its heartbeat list).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimConfig:
    heartbeat_interval: float = 10.0
    jitter_std: float = 1.5
    stall_prob: float = 0.03
    stall_range: tuple[float, float] = (20.0, 60.0)
    crash_prob: float = 0.06
    task_duration_mean: float = 200.0
    task_duration_stddev: float = 60.0
    min_duration: float = 30.0
    num_workers: int = 40
    epochs_per_worker: int = 50


@dataclass
class Epoch:
    start: float
    duration: float
    heartbeats: list[float]  # last element is always a sentinel == start + duration
    crash_time: Optional[float]


def generate_epoch(rng: random.Random, start: float, cfg: SimConfig) -> Epoch:
    duration = max(cfg.min_duration, rng.gauss(cfg.task_duration_mean, cfg.task_duration_stddev))
    heartbeats: list[float] = []
    cursor = start
    while cursor < start + duration:
        gap = cfg.heartbeat_interval
        if rng.random() < cfg.stall_prob:
            gap += rng.uniform(*cfg.stall_range)
        else:
            gap += max(0.0, rng.gauss(0.0, cfg.jitter_std))
        cursor += gap
        if cursor < start + duration:
            heartbeats.append(cursor)
    heartbeats.append(start + duration)  # sentinel: >= any possible crash_time below

    crash_time = None
    if rng.random() < cfg.crash_prob:
        crash_time = rng.uniform(start, start + duration)
    return Epoch(start=start, duration=duration, heartbeats=heartbeats, crash_time=crash_time)


def generate_worker_timeline(rng: random.Random, cfg: SimConfig) -> list[Epoch]:
    epochs = []
    cursor = 0.0
    for _ in range(cfg.epochs_per_worker):
        epoch = generate_epoch(rng, cursor, cfg)
        epochs.append(epoch)
        cursor = epoch.start + epoch.duration
    return epochs


def generate_fleet_timeline(seed: int, cfg: SimConfig) -> list[list[Epoch]]:
    """One fixed, TTL-independent timeline per worker, generated from a
    single seeded RNG stream shared across all workers in a fixed order so
    the whole fleet timeline is exactly reproducible from ``seed`` alone."""
    rng = random.Random(seed)
    return [generate_worker_timeline(rng, cfg) for _ in range(cfg.num_workers)]


def evaluate_epoch(epoch: Epoch, ttl: float) -> tuple[str, Optional[float]]:
    last_hb = epoch.start
    for h in epoch.heartbeats:
        deadline = last_hb + ttl
        if deadline < h:
            if epoch.crash_time is not None and epoch.crash_time <= deadline:
                return "true_recovery", deadline - epoch.crash_time
            return "false_eviction", None
        if epoch.crash_time is not None and epoch.crash_time <= h:
            return "true_recovery", deadline - epoch.crash_time
        last_hb = h
    return "none", None  # unreachable when crash_time is not None; see module docstring


def evaluate_fleet(fleet_timeline: list[list[Epoch]], ttl: float) -> dict:
    false_evictions = 0
    true_recoveries = 0
    healthy_epochs = 0
    crashed_epochs = 0
    total_epochs = 0
    recovery_times: list[float] = []

    for worker_epochs in fleet_timeline:
        for epoch in worker_epochs:
            total_epochs += 1
            if epoch.crash_time is None:
                healthy_epochs += 1
            else:
                crashed_epochs += 1
            outcome, recovery_time = evaluate_epoch(epoch, ttl)
            if outcome == "false_eviction":
                false_evictions += 1
            elif outcome == "true_recovery":
                true_recoveries += 1
                recovery_times.append(recovery_time)

    mean_recovery_time = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0
    return {
        "ttl": ttl,
        "total_epochs": total_epochs,
        "healthy_epochs": healthy_epochs,
        "crashed_epochs": crashed_epochs,
        "false_evictions": false_evictions,
        "true_recoveries": true_recoveries,
        # Denominator is total_epochs, not healthy_epochs: at a small enough
        # TTL, a worker can be evicted for exceeding the gap BEFORE its own
        # (later) scheduled crash time takes effect, so a false eviction can
        # occur even in an epoch that would eventually have crashed anyway.
        # That eviction was still premature relative to the actual cause, so
        # it still counts as false.
        "false_eviction_rate": false_evictions / total_epochs if total_epochs else 0.0,
        "true_recovery_rate": true_recoveries / crashed_epochs if crashed_epochs else 0.0,
        "mean_recovery_time": mean_recovery_time,
    }


def cost(measurement: dict, false_eviction_cost_ticks: float) -> float:
    """A single scalar trading off detection latency against false-eviction
    churn, in TTL-tick-equivalent units: expected recovery time plus the
    false-eviction rate weighted by how many ticks-worth of wasted work a
    single false eviction costs."""
    return measurement["mean_recovery_time"] + false_eviction_cost_ticks * measurement["false_eviction_rate"]
