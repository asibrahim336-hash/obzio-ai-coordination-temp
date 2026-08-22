"""A logical clock.

The review path must be able to prove that criteria were sealed before any
candidate arrived. Wall-clock time cannot carry that proof in a test: two
events inside one process can share a timestamp, and a coarse clock can even
report them out of order. A strictly monotonic counter makes "before" a fact
about the recorded order rather than a fact about the host's timer resolution.
"""

from __future__ import annotations


class LogicalClock:
    """A strictly monotonic tick source, starting at 1."""

    __slots__ = ("_tick",)

    def __init__(self) -> None:
        self._tick = 0

    def tick(self) -> int:
        self._tick += 1
        return self._tick

    @property
    def now(self) -> int:
        """The last tick issued; 0 before the first tick."""
        return self._tick

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"LogicalClock(now={self._tick})"
