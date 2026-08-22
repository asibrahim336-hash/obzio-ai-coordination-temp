"""Route gate findings to the writer who owns the file (unit a3-u02, a3-u04).

The integrated tree fails gates that passed on every branch that produced it.
That is not a contradiction: each cohort's gate ran over a tree holding only
that cohort's files, and a whole-tree property is only testable once the tree is
whole. So the findings are real and almost none of them are mine to fix.

This tool turns a gate report into a routed list. It does two things the raw
report cannot:

* It resolves an owner for every finding from ``control/path-ownership.json``
  rather than from a table written here. A routing table in this file would
  drift from the record that actually governs custody, and would then send work
  to the wrong writer with the confidence of something automated.
* It carries a triage verdict and a one-line justification per finding class,
  read from ``finding-triage.json``. GENUINE and FALSE_POSITIVE are judgements
  and they belong in a document a reader can argue with, not in code.

Nothing here fixes another cohort's file. The output names the minimal change
and stops.

    python3 -I workstreams/po03/runtime/route_findings.py
    python3 -I workstreams/po03/runtime/route_findings.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parents[2]
TRIAGE_PATH = RUNTIME_DIR / "finding-triage.json"
OWNERSHIP_PATH = REPO_ROOT / "workstreams" / "po03" / "control" / "path-ownership.json"

ROUTED_SCHEMA = "po03-routed-findings-v1"


def load_module(name: str, path: Path):
    """Import a sibling module by location, because -I implies -P.

    A script run under ``python3 -I`` gets no script directory on ``sys.path``,
    so a plain import of a module beside this one fails. Loading by location
    works without touching process-global state, which is why this file makes
    no ``sys.path`` mutation of its own.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_triage(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "po03-finding-triage-v1":
        raise ValueError(f"unexpected triage schema: {document.get('schema')!r}")
    return document


def ownership_prefixes(path: Path) -> list[tuple[str, str]]:
    """Owned prefixes, longest first, so the most specific grant wins.

    ``owned_prefixes`` remains the authoritative field until a11-u17 lands the
    typed ``grants`` block, so it is what this reads.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    pairs: list[tuple[str, str]] = []
    for owner, entry in document.get("owners", {}).items():
        for prefix in entry.get("owned_prefixes", []):
            pairs.append((prefix, owner))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


def resolve_owner(relative: str, pairs: list[tuple[str, str]]) -> str:
    for prefix, owner in pairs:
        if relative == prefix or relative.startswith(prefix):
            return owner
    return "UNOWNED"


def triage_for(finding: dict[str, Any], triage: dict[str, Any]) -> dict[str, Any]:
    """Find the most specific triage entry covering this finding.

    An entry that names the disposition beats one that does not, and a per-file
    entry beats a per-class default. The disposition matters because one class
    can appear twice in one file with different roles: the same
    ABS_PATH_LITERAL rule reports a real platform assumption on one line of
    ``boundary_run.py`` and an exempted f-string fragment on another.
    """
    rule = finding["rule"]
    relative = finding["path"]
    disposition = finding["disposition"]
    candidates = [
        entry
        for entry in triage.get("per_finding", [])
        if entry["rule"] == rule and entry["path"] == relative
    ]
    for entry in candidates:
        if entry.get("disposition") == disposition:
            return entry
    for entry in candidates:
        if "disposition" not in entry:
            return entry

    # A role exemption is itself the justification, so a finding a role removed
    # needs no hand-written entry to be accounted for.
    if disposition == "EXEMPT_BY_ROLE":
        roles = triage.get("role_verdicts", {})
        role = finding.get("exempt_role", "")
        return roles.get(
            role,
            {
                "verdict": "FALSE_POSITIVE",
                "justification": f"exempted by syntactic role {role}",
                "minimal_fix": "none required",
            },
        )

    classes = triage.get("per_class", {})
    if rule in classes:
        return classes[rule]
    return {
        "verdict": "UNTRIAGED",
        "justification": "no triage entry covers this finding; it must be judged before routing",
        "minimal_fix": "NOT_YET",
    }


def hermeticity_findings(repo_root: Path) -> list[dict[str, Any]]:
    prober = load_module("po03_hermeticity", RUNTIME_DIR / "hermeticity.py")
    rules = prober.load_rules(RUNTIME_DIR / "hermeticity-rules.json")
    targets = prober.discover(repo_root / rules["scan_root"], rules, repo_root)
    found = prober.scan_paths(targets, rules, repo_root)
    report = prober.build_report(targets, found, rules)
    records = [dict(record, gate="hermeticity", disposition="REPORTED") for record in report["findings"]]
    records += [
        dict(record, gate="hermeticity", disposition="EXEMPT_BY_ROLE")
        for record in report["exempt"]
    ]
    records += [
        dict(record, gate="hermeticity", disposition="ADVISORY") for record in report["advisory"]
    ]
    return records


def ci_surface_findings(repo_root: Path) -> list[dict[str, Any]]:
    checker = load_module("po03_ci_surface", RUNTIME_DIR / "ci_surface.py")
    rules = checker.load_rules(RUNTIME_DIR / "ci-surface-rules.json")
    report = checker.run(rules, repo_root)
    return [
        dict(record, gate="ci_surface", disposition="REPORTED", line=0)
        for record in report["findings"]
    ]


def route(repo_root: Path) -> dict[str, Any]:
    triage = load_triage(TRIAGE_PATH)
    pairs = ownership_prefixes(OWNERSHIP_PATH)
    this_writer = triage["this_writer"]

    routed: list[dict[str, Any]] = []
    for finding in hermeticity_findings(repo_root) + ci_surface_findings(repo_root):
        relative = finding["path"]
        verdict = triage_for(finding, triage)
        routed.append(
            {
                "gate": finding["gate"],
                "owner": resolve_owner(relative, pairs),
                "file": relative,
                "line": finding.get("line", 0),
                "finding_class": finding["rule"],
                "disposition": finding["disposition"],
                "exempt_role": finding.get("exempt_role"),
                "triage": verdict["verdict"],
                "justification": verdict["justification"],
                "minimal_fix": verdict["minimal_fix"],
                "detail": finding.get("detail", ""),
            }
        )
    routed.sort(key=lambda record: (record["owner"], record["file"], record["line"], record["finding_class"]))

    counts: dict[str, dict[str, int]] = {}
    for record in routed:
        gate = counts.setdefault(record["gate"], {})
        gate[record["triage"]] = gate.get(record["triage"], 0) + 1

    by_owner: dict[str, int] = {}
    for record in routed:
        if record["triage"] != "GENUINE":
            continue
        by_owner[record["owner"]] = by_owner.get(record["owner"], 0) + 1

    # The CI-surface population is carried from the triage document rather than
    # recomputed, because the narrowing removed all of it: a verdict that leaves
    # no trace in the live gate still has to be reported somewhere.
    population = triage.get("ci_surface_population", {})
    for entry in population.get("classes", []):
        counts.setdefault("ci_surface", {})
        counts["ci_surface"][entry["verdict"]] = counts["ci_surface"].get(entry["verdict"], 0) + entry[
            "observed_count_here"
        ]

    return {
        "schema": ROUTED_SCHEMA,
        "produced_by": this_writer,
        "routing_authority": "workstreams/po03/control/path-ownership.json, owned_prefixes",
        "observation_pin": triage.get("observation_pin", {}),
        "finding_count": len(routed),
        "triage_counts_by_gate": counts,
        "ci_surface_population": population,
        "genuine_by_owner": by_owner,
        "mine_to_fix": sorted(
            {
                record["file"]
                for record in routed
                if record["owner"] == this_writer and record["triage"] == "GENUINE"
            }
        ),
        "findings": routed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="route PO-03 gate findings to their owners")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--only",
        choices=["GENUINE", "FALSE_POSITIVE", "UNTRIAGED"],
        help="restrict the printed list to one triage verdict",
    )
    args = parser.parse_args(argv)

    try:
        report = route(Path(args.root).resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ROUTE_ERROR: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    for record in report["findings"]:
        if args.only and record["triage"] != args.only:
            continue
        if record["disposition"] != "REPORTED":
            continue
        print(
            f"{record['owner']}\t{record['file']}:{record['line']}\t"
            f"{record['finding_class']}\t{record['triage']}\t{record['minimal_fix']}"
        )
    for gate, verdicts in sorted(report["triage_counts_by_gate"].items()):
        print(f"{gate}: " + ", ".join(f"{name}={count}" for name, count in sorted(verdicts.items())))
    print("genuine by owner: " + json.dumps(report["genuine_by_owner"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
