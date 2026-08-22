#!/usr/bin/env python3
"""Explicit mutation harness for false-completion custody guards."""
import json


def valid_completion(case):
    return case["state"] != "COMPLETED" or (
        bool(case["commit_id"])
        and case["parent_ingested"]
        and case["actor"] == "coordinator"
        and case["manifest_valid"]
    )


MUTANTS = {
    "omit_commit": lambda c: c["state"] != "COMPLETED" or (c["parent_ingested"] and c["actor"] == "coordinator" and c["manifest_valid"]),
    "omit_parent_ingestion": lambda c: c["state"] != "COMPLETED" or (bool(c["commit_id"]) and c["actor"] == "coordinator" and c["manifest_valid"]),
    "allow_worker_completion": lambda c: c["state"] != "COMPLETED" or (bool(c["commit_id"]) and c["parent_ingested"] and c["manifest_valid"]),
    "omit_manifest_integrity": lambda c: c["state"] != "COMPLETED" or (bool(c["commit_id"]) and c["parent_ingested"] and c["actor"] == "coordinator"),
}

VALID = {"state": "COMPLETED", "commit_id": "abc", "parent_ingested": True, "actor": "coordinator", "manifest_valid": True}
CASES = [
    VALID,
    {**VALID, "commit_id": None},
    {**VALID, "parent_ingested": False},
    {**VALID, "actor": "worker"},
    {**VALID, "manifest_valid": False},
]


def mutation_run(cases):
    expected = [valid_completion(case) for case in cases]
    killed = {}
    for name, mutant in MUTANTS.items():
        actual = [mutant(case) for case in cases]
        killed[name] = any(a != e for a, e in zip(actual, expected))
    return {
        "cases": len(cases),
        "killed": sorted(name for name, value in killed.items() if value),
        "survived": sorted(name for name, value in killed.items() if not value),
        "score": sum(killed.values()) / len(killed),
    }


def exercise():
    weak = mutation_run([VALID])
    strengthened = mutation_run(CASES)
    return {
        "weak_suite": weak,
        "strengthened_suite": strengthened,
        "required_score": 1.0,
        "disposition": "PASS" if strengthened["score"] == 1.0 else "FAIL",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
