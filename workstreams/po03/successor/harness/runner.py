#!/usr/bin/env python3
"""Deterministic case runner for the successor-generation suite.

A case is a list of operations applied to a freshly constructed generation plus
a list of assertions over the observed outcomes.  Cases are data, generations
are code, and the runner knows nothing about either beyond the contract in
``controller_api``.  That separation is what lets one frozen suite score a
controller written before the suite existed.

Determinism rules, because a score that cannot be reproduced is not evidence:

* every case gets a private state directory, so cases cannot leak into one
  another and case order cannot change a score;
* time comes only from the injectable clock;
* nothing is read from the environment, and no network is touched.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .controller_api import NOT_SUPPORTED, Clock, Controller, canonical, sha256_text

CHECKS = ("admitted", "reason_code", "detail", "capability_absent")


class CaseError(RuntimeError):
    """Raised when a case is malformed, which is a suite defect, not a score."""


def _dig(payload: Any, dotted: str) -> Any:
    """Read a dotted path out of an outcome detail, returning a sentinel if absent."""
    current: Any = payload
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return _MISSING
        else:
            return _MISSING
    return current


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Missing)

    __hash__ = None  # type: ignore[assignment]


_MISSING = _Missing()


def evaluate_assertion(assertion: dict[str, Any], observed: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(passed, explanation)`` for one assertion against recorded steps."""
    check = assertion.get("check")
    if check not in CHECKS:
        raise CaseError(f"unknown check: {check!r}")
    step = assertion.get("step")
    if step not in observed:
        raise CaseError(f"assertion references unknown step label: {step!r}")
    outcome = observed[step]

    if check == "admitted":
        expected = bool(assertion["expect"])
        actual = bool(outcome["admitted"])
        return actual == expected, f"admitted={actual} expected={expected}"

    if check == "reason_code":
        actual = outcome["reason_code"]
        if "expect" in assertion:
            expected = assertion["expect"]
            return actual == expected, f"reason_code={actual} expected={expected}"
        allowed = list(assertion["one_of"])
        return actual in allowed, f"reason_code={actual} expected one of {allowed}"

    if check == "capability_absent":
        actual = outcome["reason_code"]
        expected = bool(assertion.get("expect", True))
        absent = actual == NOT_SUPPORTED
        return absent == expected, f"not_supported={absent} expected={expected}"

    path = assertion["path"]
    actual = _dig(outcome["detail"], path)
    if "expect" in assertion:
        expected = assertion["expect"]
        return actual == expected, f"detail.{path}={actual!r} expected={expected!r}"
    if "one_of" in assertion:
        allowed = list(assertion["one_of"])
        return actual in allowed, f"detail.{path}={actual!r} expected one of {allowed}"
    if "absent" in assertion:
        expected_absent = bool(assertion["absent"])
        is_absent = isinstance(actual, _Missing) or actual is None
        return is_absent == expected_absent, f"detail.{path} absent={is_absent} expected={expected_absent}"
    raise CaseError(f"detail check for {path!r} has no expectation")


def run_case(
    factory,
    case: dict[str, Any],
    *,
    state_root: Path,
) -> dict[str, Any]:
    """Run one case against one generation and return a per-case record."""
    for required in ("id", "steps", "assert"):
        if required not in case:
            raise CaseError(f"case is missing {required!r}")

    clock = Clock()
    root = state_root / case["id"]
    root.mkdir(parents=True, exist_ok=True)
    controller: Controller = factory(root=root, clock=clock)

    observed: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    error: str | None = None

    for index, step in enumerate(case["steps"]):
        label = step.get("label") or f"s{index + 1}"
        if label in observed:
            raise CaseError(f"duplicate step label {label!r} in case {case['id']}")
        operation = step["op"]
        args = dict(step.get("args", {}))
        try:
            outcome = controller.apply(operation, args).as_json()
        except Exception as exc:  # noqa: BLE001 - a crash is a scored failure, not a harness abort
            outcome = {
                "admitted": False,
                "reason_code": "INVALID_REQUEST",
                "detail": {"crash": f"{type(exc).__name__}: {exc}"},
            }
            error = error or f"{label}: {type(exc).__name__}: {exc}"
        observed[label] = outcome
        trace.append({"label": label, "op": operation, "outcome": outcome})

    failures: list[str] = []
    for assertion in case["assert"]:
        passed, explanation = evaluate_assertion(assertion, observed)
        if not passed:
            failures.append(f"{assertion['check']}@{assertion['step']}: {explanation}")

    return {
        "case_id": case["id"],
        "family": case.get("family", "unclassified"),
        "safety_class": case.get("safety_class"),
        "critical": bool(case.get("critical", False)),
        "criteria": list(case.get("criteria", [])),
        "passed": not failures,
        "failures": failures,
        "crash": error,
        "trace": trace,
    }


def run_suite(factory, cases: list[dict[str, Any]], *, state_root: Path | None = None) -> list[dict[str, Any]]:
    """Run every case in declaration order against one generation.

    ``state_root`` is scratch working space only.  Every value a score depends
    on is derived from the returned records and written to the committed tree by
    the caller, so the scratch directory can be discarded without losing
    evidence.
    """
    owned_scratch = state_root is None
    if owned_scratch:
        state_root = Path(tempfile.mkdtemp(prefix="po03-a8-suite-"))
    try:
        return [run_case(factory, case, state_root=Path(state_root)) for case in cases]
    finally:
        if owned_scratch:
            shutil.rmtree(state_root, ignore_errors=True)


def load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CaseError(f"{path}: no cases")
    seen: set[str] = set()
    for case in cases:
        if case["id"] in seen:
            raise CaseError(f"{path}: duplicate case id {case['id']}")
        seen.add(case["id"])
    return document, cases


def case_set_digest(cases: list[dict[str, Any]]) -> str:
    """Digest the semantic content of a case set so a frozen suite stays frozen."""
    return sha256_text(canonical(cases))
