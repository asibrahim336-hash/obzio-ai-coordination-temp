"""A tiny deterministic-simulation-testing (DST) scheduler for a5-u07.

Models a fleet of concurrent "actors" as ordinary Python generators, each
yielding a token after every internal step. A schedule is a sequence of
actor indices telling the runner which actor's *next* step to advance. Two
exploration strategies are provided over exactly the same actor generators:

* ``exhaustive_interleavings`` -- enumerates every schedule that preserves
  each actor's own step order (the standard "riffle merge" of k sequences),
  and reports the exact count via the multinomial coefficient, so the
  explored space is always quantified in closed form, not estimated.
* ``sequential_orderings`` -- the strategy classical single-fault sequential
  injection actually uses: run one actor's *entire* sequence to completion,
  then the next actor's entire sequence, and so on. This explores only the
  k! fully-serial arrangements, a small, provably non-overlapping subset of
  the full interleaving space: no two actors' steps are ever adjacent to a
  shared, uncommitted intermediate state under this strategy, by
  construction, regardless of what the actors do.
* ``seeded_random_interleavings`` -- for spaces too large to enumerate
  exhaustively, draws ``count`` valid interleavings using a stochastic merge
  driven by a seeded ``random.Random``, so a run is exactly replayable from
  its recorded seed.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")
ActorFactory = Callable[[], Iterator[T]]


def multinomial_space_size(step_counts: list[int]) -> int:
    """Exact count of distinct order-preserving interleavings of k sequences
    of the given lengths: (sum n_i)! / prod(n_i!)."""
    total = sum(step_counts)
    denom = 1
    for n in step_counts:
        denom *= math.factorial(n)
    return math.factorial(total) // denom


def exhaustive_interleavings(step_counts: list[int]) -> list[tuple[int, ...]]:
    """All order-preserving interleavings of k sequences of the given
    lengths, as tuples of actor indices. Length of the result always equals
    ``multinomial_space_size(step_counts)`` exactly."""
    k = len(step_counts)

    def helper(remaining: list[int]) -> list[tuple[int, ...]]:
        if all(r == 0 for r in remaining):
            return [()]
        out: list[tuple[int, ...]] = []
        for i in range(k):
            if remaining[i] > 0:
                nxt = list(remaining)
                nxt[i] -= 1
                for tail in helper(nxt):
                    out.append((i,) + tail)
        return out

    return helper(list(step_counts))


def sequential_orderings(step_counts: list[int]) -> list[tuple[int, ...]]:
    """Every fully-serial arrangement of k actors: one actor's whole
    sequence, then the next actor's whole sequence. There are exactly k!
    of these, all of which are also members of the full interleaving
    space, but none of which ever interleaves a partial step of one actor
    with a partial step of another."""
    import itertools

    k = len(step_counts)
    orderings = []
    for perm in itertools.permutations(range(k)):
        schedule: tuple[int, ...] = ()
        for actor in perm:
            schedule += (actor,) * step_counts[actor]
        orderings.append(schedule)
    return orderings


def seeded_random_interleavings(step_counts: list[int], seed: int, count: int) -> list[tuple[int, ...]]:
    """``count`` order-preserving interleavings drawn by a stochastic merge
    driven by ``random.Random(seed)``. Deterministic and replayable: the
    same seed and count always reproduce the identical list."""
    rng = random.Random(seed)
    k = len(step_counts)
    schedules = []
    for _ in range(count):
        remaining = list(step_counts)
        schedule: list[int] = []
        while any(r > 0 for r in remaining):
            choices = [i for i in range(k) if remaining[i] > 0]
            pick = rng.choice(choices)
            remaining[pick] -= 1
            schedule.append(pick)
        schedules.append(tuple(schedule))
    return schedules


def run_schedule(actor_factories: list[ActorFactory], schedule: tuple[int, ...]) -> list[tuple[int, T]]:
    """Drive fresh generators from ``actor_factories`` according to
    ``schedule`` (a sequence of actor indices), returning every yielded
    value tagged with its actor index, in the order actually executed."""
    gens = [factory() for factory in actor_factories]
    trace: list[tuple[int, T]] = []
    for actor_idx in schedule:
        value = next(gens[actor_idx])
        trace.append((actor_idx, value))
    return trace
