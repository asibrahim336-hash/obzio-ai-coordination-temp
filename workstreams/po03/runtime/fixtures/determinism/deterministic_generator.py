"""Control fixture: the same document shape with no variance at all.

Proves the checker distinguishes a deterministic generator from a
non-deterministic one, rather than failing everything it is pointed at.
"""

import json


def main() -> None:
    document = {
        "schema": "po03-determinism-fixture-v1",
        "stable": "this value never changes",
        "nested": {"stable_inner": 7},
        "items": [{"name": "first"}, {"name": "second"}],
    }
    print(json.dumps(document, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
