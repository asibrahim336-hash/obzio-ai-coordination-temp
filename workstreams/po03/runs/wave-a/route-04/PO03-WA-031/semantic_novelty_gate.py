#!/usr/bin/env python3
"""Reject generated scenarios that duplicate existing tests semantically."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


STOP = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "one", "or", "that", "the", "then", "this", "to", "with",
}
SYNONYMS = {
    "absent": "missing",
    "unavailable": "missing",
    "remove": "delete",
    "removed": "delete",
    "artifact": "file",
    "path": "file",
    "reject": "fail",
    "rejected": "fail",
    "fails": "fail",
    "failure": "fail",
    "succeeds": "pass",
    "accepted": "pass",
    "equivalent": "same",
    "duplicate": "same",
    "identical": "same",
}


def _stem(token: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    return token


def semantic_tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9_]+", text.lower().replace("_", " "))
    normalized = []
    for word in words:
        word = SYNONYMS.get(word, word)
        word = _stem(word)
        if word not in STOP and len(word) > 1:
            normalized.append(word)
    return frozenset(normalized)


def source_semantics(source: str) -> frozenset[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return semantic_tokens(source)
    fragments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            fragments.append(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            fragments.append(node.value)
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                fragments.append(function.id)
            elif isinstance(function, ast.Attribute):
                fragments.append(function.attr)
    return semantic_tokens(" ".join(fragments))


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def qualify_cases(
    cases: Iterable[Mapping[str, Any]],
    existing_tests: Mapping[str, str],
    *,
    threshold: float = 0.72,
) -> dict[str, Any]:
    baseline = {path: source_semantics(source) for path, source in existing_tests.items()}
    candidate_signatures: dict[str, frozenset[str]] = {}
    defects: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            defects.append({"code": "SCENARIO_ID_MISSING", "index": index})
            continue
        signature = semantic_tokens(
            f"{case.get('stimulus', '')} {case.get('oracle', '')}"
        )
        if not signature:
            defects.append({"code": "SCENARIO_SEMANTICS_EMPTY", "case_id": case_id})
            continue
        for existing_id, existing_signature in baseline.items():
            score = similarity(signature, existing_signature)
            if score >= threshold:
                defects.append(
                    {
                        "code": "SEMANTIC_DUPLICATE_OF_EXISTING_TEST",
                        "case_id": case_id,
                        "existing": existing_id,
                        "similarity": round(score, 6),
                    }
                )
        for prior_id, prior_signature in candidate_signatures.items():
            score = similarity(signature, prior_signature)
            if score >= threshold:
                defects.append(
                    {
                        "code": "SEMANTIC_DUPLICATE_GENERATED_SCENARIO",
                        "case_id": case_id,
                        "existing": prior_id,
                        "similarity": round(score, 6),
                    }
                )
        candidate_signatures[case_id] = signature
    return {
        "generated_scenarios_checked": len(candidate_signatures),
        "existing_tests_checked": len(baseline),
        "threshold": threshold,
        "defects": defects,
        "disposition": "PASS" if candidate_signatures and not defects else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--test", type=Path, action="append", default=[])
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8")).get("cases", [])
    existing = {str(path): path.read_text(encoding="utf-8") for path in args.test}
    report = qualify_cases(cases, existing)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["disposition"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
