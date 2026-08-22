"""Planted defect fixture: a generator with undeclared variance.

Emits one declared timestamp beside three undeclared varying fields, at three
different depths -- top level, nested object and array element. The checker must
report exactly the three undeclared ones and must not report the declared
timestamp, which is what distinguishes it from a checker that merely notices
that two runs differ.
"""

import json
import random
import time


def main() -> None:
    document = {
        "schema": "po03-determinism-fixture-v1",
        "stable": "this value never changes",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": f"run-{random.getrandbits(48):012x}",
        "nested": {
            "stable_inner": 7,
            "attempt_token": f"tok-{random.getrandbits(32):08x}",
        },
        "items": [
            {"name": "first", "salt": random.getrandbits(24)},
            {"name": "second", "salt": random.getrandbits(24)},
        ],
    }
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
