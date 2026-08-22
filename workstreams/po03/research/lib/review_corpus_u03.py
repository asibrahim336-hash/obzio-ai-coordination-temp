"""An 8-snippet seeded-defect corpus used to compare two review methodologies
in a5-u03. Four defects are purely syntactic/structural (a static, pattern-
based reviewer catches them; a single-call correctness check cannot, because
none of them change a single fresh call's return value). Four defects are
purely semantic (a property/example-based dynamic reviewer catches them by
comparing against a reference implementation; a syntactic pattern matcher has
no anti-pattern to match, because the code "looks" unremarkable).
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path


# --- static-only defects (no static anti-pattern reviewer would ever emit a
# false negative on; each still returns a "correct-looking" value on the one
# fresh, valid-input call a scoped correctness property would make) ---------


def parse_amount(raw):
    """Spec: parse a decimal string to int; raise ValueError on invalid input."""
    try:
        return int(raw)
    except:  # noqa: E722 -- deliberately bare, this is the seeded defect
        pass


def append_item(item, bucket=[]):  # noqa: B006 -- deliberately mutable default
    """Spec: return a new list containing exactly [item]."""
    bucket.append(item)
    return bucket


_call_counter = {"n": 0}


def increment_on_call(key):
    """Spec: return a monotonically increasing counter value."""
    global _call_counter
    _call_counter["n"] += 1
    return _call_counter["n"]


def read_first_line(path):
    """Spec: return the first line of the file at path, stripped."""
    f = open(path)  # noqa: SIM115 -- deliberately not a `with` block
    line = f.readline().strip()
    return line


# --- dynamic-only defects (no fresh single-call correctness property is
# violated by anything a syntactic pattern matcher can see; the bug only
# shows up when output is compared against a reference on generated inputs) -


def sum_all(values):
    """Spec: return the sum of every element in values."""
    total = 0
    for i in range(len(values) - 1):  # off-by-one: drops the last element
        total += values[i]
    return total


def both_positive(x, y):
    """Spec: return True iff both x and y are strictly positive."""
    if x > 0 or y > 0:  # should be `and`
        return True
    return False


def larger_of(a, b):
    """Spec: return the larger of a and b."""
    if a < b:
        return a  # swapped: returns the smaller value
    return b


def safe_average(values):
    """Spec: return the arithmetic mean, or None for an empty list."""
    return sum(values) / len(values)  # raises ZeroDivisionError on []


STATIC_ONLY_DEFECTS = {
    "bare_except": parse_amount,
    "mutable_default_argument": append_item,
    "global_mutable_state_without_reset": increment_on_call,
    "resource_leak": read_first_line,
}

DYNAMIC_ONLY_DEFECTS = {
    "off_by_one": sum_all,
    "incorrect_boolean_logic": both_positive,
    "swapped_comparison": larger_of,
    "unhandled_empty_input": safe_average,
}


def reference_sum_all(values):
    return sum(values)


def reference_both_positive(x, y):
    return x > 0 and y > 0


def reference_larger_of(a, b):
    return a if a > b else b


def reference_safe_average(values):
    return sum(values) / len(values) if values else None


DYNAMIC_REFERENCES = {
    "off_by_one": reference_sum_all,
    "incorrect_boolean_logic": reference_both_positive,
    "swapped_comparison": reference_larger_of,
    "unhandled_empty_input": reference_safe_average,
}


def generate_dynamic_inputs(defect_class: str, rng: random.Random, n: int = 30) -> list[tuple]:
    if defect_class == "off_by_one":
        return [(tuple(rng.randint(-10, 10) for _ in range(rng.randint(1, 8))),) for _ in range(n)]
    if defect_class == "incorrect_boolean_logic":
        return [(rng.randint(-5, 5), rng.randint(-5, 5)) for _ in range(n)]
    if defect_class == "swapped_comparison":
        return [(rng.randint(-100, 100), rng.randint(-100, 100)) for _ in range(n)]
    if defect_class == "unhandled_empty_input":
        return [(tuple(rng.randint(0, 10) for _ in range(rng.randint(0, 5))),) for _ in range(n)]
    raise ValueError(defect_class)


def static_defect_fresh_call_args(name: str, tmp_dir: Path):
    """One valid, unremarkable fresh-call invocation per static-only snippet,
    used to prove the dynamic reviewer's scoped correctness property genuinely
    does not fire on these -- not that it was never tried."""
    if name == "bare_except":
        return ("42",)
    if name == "mutable_default_argument":
        return ("x", [])
    if name == "global_mutable_state_without_reset":
        return ("k1",)
    if name == "resource_leak":
        sample = tmp_dir / "sample.txt"
        sample.write_text("hello\nworld\n", encoding="utf-8")
        return (str(sample),)
    raise ValueError(name)
