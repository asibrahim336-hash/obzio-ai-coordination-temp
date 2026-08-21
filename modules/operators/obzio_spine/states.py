"""Canonical operator lifecycle states.

The lifecycle is STRICTLY LINEAR. There are no skips, no back-edges, no
alternate routes. Any attempt to move to a state that is not exactly
ordinal+1 is refused by the machine.

The ordering is load-bearing, not decorative:

  PREFLIGHT                  nothing is trusted yet; identity + gate material bound
  CURRENT_STATE_RECOVERED    operating state rebuilt from durable artefacts
  INPUT_ADMITTED             input passed admission; provenance recorded
  ACTION_EXECUTED            the pack's real work ran
  REQUIRED_ARTEFACTS_PRESENT every declared artefact exists on disk
  MACHINE_CHECKS_PASSED      pack's deterministic checks returned zero failures
  INDEPENDENT_ACCEPTANCE     <-- HARD GATE. producer cannot cross this alone.
  RETURN_STATE_WRITTEN       durable return state flushed and re-read
  COMPLETE                   terminal
"""

from enum import IntEnum


class State(IntEnum):
    PREFLIGHT = 0
    CURRENT_STATE_RECOVERED = 1
    INPUT_ADMITTED = 2
    ACTION_EXECUTED = 3
    REQUIRED_ARTEFACTS_PRESENT = 4
    MACHINE_CHECKS_PASSED = 5
    INDEPENDENT_ACCEPTANCE = 6
    RETURN_STATE_WRITTEN = 7
    COMPLETE = 8


#: The single transition that a producing process may never perform on its own.
GATED_TRANSITION = (State.INDEPENDENT_ACCEPTANCE, State.RETURN_STATE_WRITTEN)

TERMINAL = State.COMPLETE

ORDER = list(State)


def next_state(s: "State") -> "State":
    if s is TERMINAL:
        raise ValueError("COMPLETE is terminal; there is no next state")
    return State(int(s) + 1)
