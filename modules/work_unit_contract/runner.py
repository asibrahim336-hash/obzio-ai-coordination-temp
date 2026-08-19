"""A cold runner.

Reconstructs execution state from the ledger alone. It is given no conversation,
no chat history and no in-memory state from any previous process. This is the
whole point: if a runner needs the transcript, the work was never portable.

External effects are recorded through record_effect(), which is keyed. An effect
whose key is already in the ledger is NOT performed again - so a kill between
"effect performed" and "effect recorded" cannot produce a double side effect,
because the record is written first and the effect is derived from the record.
"""
from typing import Any, Callable, Dict, List
from contract import WorkUnit
from ledger import Ledger


class ForcedInterruption(Exception):
    """Injected process kill."""


class Runner:
    def __init__(self, unit: WorkUnit, ledger: Ledger, effects_sink: List[str]):
        self.unit = unit
        self.ledger = ledger
        self.sink = effects_sink   # stands in for the outside world

    def start(self) -> None:
        self.ledger.append(
            "run_started",
            {"unit_id": self.unit.unit_id, "contract_sha256": self.unit.seal()},
            idempotency_key=f"start:{self.unit.unit_id}",
        )

    def _perform(self, key: str, effect: str) -> None:
        """Write-ahead: commit the intent, then apply. Replay applies nothing new."""
        ev = self.ledger.append("effect", {"effect": effect}, idempotency_key=key)
        if ev["payload"]["effect"] not in self.sink:
            self.sink.append(ev["payload"]["effect"])

    def run(self, steps: List[str], kill_before: str = None,
            kill_after: str = None) -> Dict[str, Any]:
        self.start()
        done = set(self.ledger.committed_steps())
        for step in steps:
            if step in done:
                continue                       # already committed; never repeat
            if kill_before == step:
                raise ForcedInterruption(f"killed before {step}")
            self._perform(f"effect:{self.unit.unit_id}:{step}", f"did:{step}")
            if kill_after == step:
                # killed after the effect but before the step commit
                raise ForcedInterruption(f"killed after effect of {step}")
            self.ledger.append("step_committed", {"step": step},
                               idempotency_key=f"step:{self.unit.unit_id}:{step}")
        self.ledger.append("run_finished", {"unit_id": self.unit.unit_id},
                           idempotency_key=f"finish:{self.unit.unit_id}")
        return {"completed": self.ledger.committed_steps()}

    def accepts(self) -> bool:
        """Acceptance is checked against the sealed criteria, not against a story."""
        completed = set(self.ledger.committed_steps())
        return all(c in completed for c in self.unit.acceptance)
