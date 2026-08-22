"""Preregistered vs post-hoc acceptance criteria, compared on real code (a5-u05).

``SPEC`` is the written specification for ``is_valid_username``. Five
candidate implementations each violate exactly one spec clause at a
specific boundary. The two criteria-generation *processes* are then applied
to all five candidates and their actual escaped-defect counts are compared.
"""

from __future__ import annotations

from typing import Callable

SPEC_TEXT = (
    "is_valid_username(s): True iff s is a str, 3 <= len(s) <= 16, s[0] is not "
    "a digit, and every character is alphanumeric or '_'."
)


def spec_reference(s: object) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) < 3 or len(s) > 16:
        return False
    if s[0].isdigit():
        return False
    return all(ch.isalnum() or ch == "_" for ch in s)


def impl_missing_max_length(s: str) -> bool:
    if len(s) < 3:
        return False
    if s[0].isdigit():
        return False
    return all(ch.isalnum() or ch == "_" for ch in s)


def impl_allows_leading_digit(s: str) -> bool:
    if len(s) < 3 or len(s) > 16:
        return False
    return all(ch.isalnum() or ch == "_" for ch in s)


def impl_allows_empty(s: str) -> bool:
    if len(s) > 16:
        return False
    if len(s) > 0 and s[0].isdigit():
        return False
    return all(ch.isalnum() or ch == "_" for ch in s)


def impl_off_by_one_min_length(s: str) -> bool:
    if len(s) < 4 or len(s) > 16:
        return False
    if s[0].isdigit():
        return False
    return all(ch.isalnum() or ch == "_" for ch in s)


def impl_allows_invalid_char(s: str) -> bool:
    if len(s) < 3 or len(s) > 16:
        return False
    if s[0].isdigit():
        return False
    return all(ch.isalnum() or ch in "_-" for ch in s)


CANDIDATE_IMPLEMENTATIONS: dict[str, Callable[[str], bool]] = {
    "missing_max_length": impl_missing_max_length,
    "allows_leading_digit": impl_allows_leading_digit,
    "allows_empty": impl_allows_empty,
    "off_by_one_min_length": impl_off_by_one_min_length,
    "allows_invalid_char": impl_allows_invalid_char,
}

# One boundary input per candidate that specifically exercises the clause it
# violates -- this is what a spec-derived (preregistered) suite must include
# to be complete, and what a happy-path sample (post-hoc) will not think to
# construct.
BOUNDARY_INPUT_FOR_DEFECT = {
    "missing_max_length": "a" * 17,
    "allows_leading_digit": "1abc",
    "allows_empty": "",
    "off_by_one_min_length": "abc",
    "allows_invalid_char": "abc-def",
}

PREREGISTERED_SUITE = [
    "",
    "ab",
    "abc",
    "a" * 16,
    "a" * 17,
    "1abc",
    "abc-def",
    "valid_user1",
]

POST_HOC_HAPPY_PATH_SAMPLE = [
    "valid_user1",
    "another_ok_name",
    "typical_login7",
]


def run_preregistered_suite(candidate: Callable[[str], bool]) -> list[str]:
    """Independent of the candidate: derived once from SPEC_TEXT. Returns the
    list of inputs on which candidate disagrees with the spec reference."""
    failures = []
    for case in PREREGISTERED_SUITE:
        if candidate(case) != spec_reference(case):
            failures.append(case)
    return failures


def generate_post_hoc_suite(candidate: Callable[[str], bool]) -> dict[str, bool]:
    """Models confirmation-biased criteria: run the candidate on a small
    happy-path sample and record ITS OWN outputs as 'expected'."""
    return {case: candidate(case) for case in POST_HOC_HAPPY_PATH_SAMPLE}


def run_post_hoc_suite_against_spec(post_hoc_oracle: dict[str, bool]) -> list[str]:
    """Check the post-hoc oracle (built from one candidate) against the true
    spec. Failures here are cases the post-hoc process would have flagged had
    it disagreed with spec on its own sample -- which, by construction of the
    five candidates above, none of them do."""
    return [case for case, expected in post_hoc_oracle.items() if expected != spec_reference(case)]
