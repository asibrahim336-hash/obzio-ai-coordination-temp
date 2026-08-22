#!/usr/bin/env python3
"""SYNTHETIC fixture: qualification improperly depends on process memory."""

from __future__ import annotations

import json


FIXTURE_LABEL = "SYNTHETIC_PROCESS_MEMORY_QUALIFIER"
_producer_memory = False


def prime_producer_memory() -> None:
    global _producer_memory
    _producer_memory = True


def qualify() -> dict[str, object]:
    return {
        "fixture_label": FIXTURE_LABEL,
        "qualified": _producer_memory,
        "dependency": "module_global_process_memory",
    }


if __name__ == "__main__":
    print(json.dumps(qualify(), sort_keys=True))
