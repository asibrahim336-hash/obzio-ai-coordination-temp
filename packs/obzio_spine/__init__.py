"""Obzio operator spine: shared lifecycle, gate, checks, manifest.

Shared machinery, NOT shared content. Each pack supplies its own guards,
its own artefacts, its own checks, and its own real work.
"""
from .states import State, GATED_TRANSITION, TERMINAL
from .machine import OperatorMachine, TransitionError, GuardFailure
from . import acceptance, artefacts, checkkit, manifest

__all__ = [
    "State", "GATED_TRANSITION", "TERMINAL",
    "OperatorMachine", "TransitionError", "GuardFailure",
    "acceptance", "artefacts", "checkkit", "manifest",
]
