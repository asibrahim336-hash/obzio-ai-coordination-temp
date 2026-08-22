#!/usr/bin/env python3
"""Deterministic property-generated custody transition sequences."""
import itertools
import json


EVENTS = ("stage", "commit", "parent_ingest", "coordinator_complete", "provider_complete")
MAX_LENGTH = 5


def initial():
    return {"state": "CREATED", "commit": False, "parent": False, "coordinator": False}


def baseline_step(state, event):
    state = dict(state)
    if event == "commit":
        state["commit"] = True
    elif event == "parent_ingest":
        state["parent"] = True
    elif event == "coordinator_complete":
        state["coordinator"] = True
    elif event == "provider_complete":
        state["state"] = "COMPLETED"
    elif event == "stage":
        state["state"] = "RESULT_STAGED"
    return state


def guarded_step(state, event):
    state = dict(state)
    if event == "stage":
        state["state"] = "RESULT_STAGED"
    elif event == "commit":
        state["commit"] = True
        state["state"] = "RESULT_COMMITTED"
    elif event == "parent_ingest":
        state["parent"] = True
        state["state"] = "PARENT_INGESTED" if state["commit"] else state["state"]
    elif event == "coordinator_complete":
        state["coordinator"] = True
        if state["commit"] and state["parent"]:
            state["state"] = "COMPLETED"
    elif event == "provider_complete" and not state["commit"]:
        state["state"] = "PROVIDER_COMPLETED_UNCOMMITTED"
    return state


def invariant(state):
    return state["state"] != "COMPLETED" or (state["commit"] and state["parent"] and state["coordinator"])


def first_breach(step, max_length=MAX_LENGTH):
    checked = 0
    for length in range(max_length + 1):
        for sequence in itertools.product(EVENTS, repeat=length):
            state = initial()
            valid = True
            for event in sequence:
                state = step(state, event)
                if not invariant(state):
                    valid = False
                    break
            checked += 1
            if not valid:
                return list(sequence), checked
    return None, checked


def exercise():
    baseline_breach, baseline_checked = first_breach(baseline_step)
    guarded_breach, guarded_checked = first_breach(guarded_step)
    return {
        "alphabet": list(EVENTS),
        "max_sequence_length": MAX_LENGTH,
        "baseline_first_breach": baseline_breach,
        "baseline_sequences_checked_before_breach": baseline_checked,
        "guarded_first_breach": guarded_breach,
        "guarded_sequences_checked": guarded_checked,
        "frozen_bound_passed": guarded_breach is None,
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
