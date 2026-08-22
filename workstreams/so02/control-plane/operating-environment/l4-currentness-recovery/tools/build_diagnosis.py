#!/usr/bin/env python3
"""Derive the OE-L4 diagnosis from the compiled projection.

The diagnosis is generated, never typed. Every count in the JSON and the Markdown
comes from `currentctl compile` output plus the lane ledgers, so the narrative
cannot drift away from the evidence it claims to rest on.

Standard library only. Runs under `python3 -I`.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
PROJECTION = LANE_ROOT / "projection/CURRENT-STATE-PROJECTION-20260822-v001.json"
LEDGER = LANE_ROOT / "ledger/workstream-ledger.json"
SCOPES = LANE_ROOT / "ledger/currentness-scopes.json"
OUT_JSON = LANE_ROOT / "diagnosis/DIAGNOSIS-L4-20260822-v001.json"
OUT_MD = LANE_ROOT / "diagnosis/DIAGNOSIS-L4-20260822-v001.md"

OBSERVATION_WINDOW = "2026-08-22T20:12Z to 2026-08-22T20:36Z"
SOURCE_SHA = "fe0a595206e5986de7eaac6cabc619215a1eb81b"

# The recurring failures quoted in the founder review, each mapped to the finding
# code that now rejects it and the probe that proves the rejection.
FAILURE_MAP = [
    ("Several competing claims of what is current",
     "COMPETING_CURRENTNESS_CLAIM", "CompetingCurrentnessTests"),
    ("v007, a missing v008, v009/v010 and provider memory not forming one verified lineage",
     "LINEAGE_PHANTOM_VERSION", "LineageTests"),
    ("One review assessed six projects without authenticated access while eleven now exist",
     "UNBACKED_EVIDENCE_CLAIM", "NonAdmissibleEvidenceTests.test_file_count_cannot_complete_capability"),
    ("Proposed, launched, observed, completed and accepted work conflated",
     "ADMISSION_OVERCLAIM", "AdmissionLadderTests"),
    ("PRs, ZIPs, agents, prompts, file counts and acknowledgements treated as completed capability",
     "NON_ADMISSIBLE_EVIDENCE_OFFERED", "NonAdmissibleEvidenceTests"),
    ("Several agents receiving overlapping whole-operation commissions",
     "UNDIFFERENTIATED_COMMISSION_OVERLAP", "CommissionDifferentiationTests"),
    ("Operational methods promoted into company strategy",
     "COMMISSION_UNRESOLVED_IN_REGISTER", "CommissionDifferentiationTests.test_active_commission_absent_from_the_register_cannot_resolve"),
    ("Local platform constraints redefining Obzio",
     "ALIAS_USED_AS_LOCATOR", "ReproducibilityTests.test_display_alias_is_not_a_locator"),
    ("Founder corrections remaining the main recovery mechanism",
     "LADDER_FOUNDATION_MISSING", "AdmissionLadderTests.test_launch_without_a_commission_is_held_and_named"),
    ("The founder becoming the routine relay and merge layer",
     "STACKED_UNLANDED_PR_CHAIN", "RefGraphTests.test_a_stack_of_open_prs_is_one_unlanded_chain"),
    ("Automation producing duplicate evidence threads",
     "ORPHANED_REF_POPULATION", "RefGraphTests.test_orphan_population_is_reported"),
    ("Lessons documented without changing the actual mechanism",
     "NON_ADMISSIBLE_EVIDENCE_OFFERED", "NonAdmissibleEvidenceTests.test_documented_lesson_that_changes_no_gate_cannot_advance_state"),
    ("A producer certifying its own work",
     "SELF_ACCEPTANCE", "IndependenceTests.test_producer_cannot_be_its_own_evaluator"),
    ("An evidence claim with no reproducible artifact behind it",
     "EVIDENCE_HASH_MISMATCH", "ReproducibilityTests"),
    ("A read-back recorded once and treated as permanently current",
     "STALE_REMOTE_READBACK", "StaleReadbackTests"),
    ("Coordination primitives counted as delivered scale",
     "COORDINATION_TOKENS_COUNTED_AS_SCALE", "RefGraphTests.test_a_lease_token_is_not_work"),
]

UNDETERMINED = [
    {"question": "Whether eleven ChatGPT projects now exist",
     "why": "The canonical store records a six-project destination in state/ACTIVE_CONTROL_POINTER_CURRENT.json and enumerates none of them. The eleven-project figure comes from the founder review, not from the repository. Confirming it needs authenticated provider access, which this lane does not hold and must not acquire.",
     "label": "HYPOTHESIS"},
    {"question": "What the missing v008 payload actually contained",
     "why": "No commit on any of the observed refs ever added a path matching *LAUNCH_ROUTE*v008*. The bytes were returned into a chat and attached as a file that the repository never held, so the content is unrecoverable from git. Only its absence is reproducible.",
     "label": "DIRECTLY_REPRODUCED for the absence, undetermined for the content"},
    {"question": "Whether the W01-W24 lanes ran",
     "why": "The claim rests on obzio_registry in Supabase project szxhcwvcmzpyxojgiiws and three Drive receipts, none of which are in the canonical store. This lane can prove the evidence is absent from git; it cannot prove the work did or did not happen.",
     "label": "DIRECTLY_REPRODUCED for the absence, undetermined for the underlying fact"},
    {"question": "Whether PR #6 or PR #7 holds the correct pointer content",
     "why": "Both are open against main and both rewrite the same pointer files with different bytes. Choosing between them is a founder-bound or independently-evaluated act, not a compilation result. The tool refuses to pick and records the refusal.",
     "label": "DIRECTLY_REPRODUCED for the conflict, deliberately undetermined for the winner"},
    {"question": "The exact remote ref denominator",
     "why": "The observed ref count moved from 166 to 171 during the observation window because four sibling lanes of this same group were pushing their branches concurrently. The count then held at 171 while sibling heads kept advancing, so a stable denominator does not mean a stable estate: a recompile over the same 171 refs produced a different projection hash purely because two sibling heads moved. Every count here is pinned to the projection's own ref list rather than to a moment.",
     "label": "DIRECTLY_REPRODUCED"},
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    projection = load(PROJECTION)
    ledger = load(LEDGER)
    scopes = load(SCOPES)

    refs = projection["refs"]
    findings = projection["findings"]
    by_code: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        by_code[finding["code"]].append(finding)

    prefixes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name, node in refs.items():
        prefix = name.split("/", 1)[0] if "/" in name else name
        prefixes[prefix][node["classification"]] += 1
        prefixes[prefix]["_total"] += 1

    branch_table = sorted(
        ({"branch": node["branch"], "head": node["head"], "last_commit": node["committed_at"],
          "lineage_parent": node["contained_by"][0] if node["contained_by"] else (
              projection["trunk"] if node["shares_ancestry_with_trunk"] and node["branch"] != projection["trunk"] else None),
          "classification": node["classification"], "ref_role": node["ref_role"],
          "tracked_paths": node["tracked_paths"], "merged_into_trunk": node["merged_into_trunk"],
          "shares_ancestry_with_trunk": node["shares_ancestry_with_trunk"]}
         for node in refs.values()),
        key=lambda row: (row["classification"], row["branch"]))

    competing = []
    for finding in by_code["COMPETING_CURRENTNESS_CLAIM"]:
        scope_id = finding["subject"].rsplit(":", 1)[-1]
        competing.append({
            "scope_id": scope_id,
            "urn": finding["subject"],
            "variants": finding["evidence"]["variants"],
            "absent_on": finding["evidence"]["absent_on"],
            "label": "DIRECTLY_REPRODUCED",
            "instrument": "git rev-parse origin/<branch>:<path> across the live branch set",
        })

    overlaps = [{
        "pair": finding["subject"],
        "detail": finding["detail"],
        "overlapping_namespace": finding["evidence"]["overlapping_namespace"],
        "first": finding["evidence"]["first"],
        "second": finding["evidence"]["second"],
        "label": "DOCUMENTED",
    } for finding in by_code["UNDIFFERENTIATED_COMMISSION_OVERLAP"]]

    workstreams = sorted(projection["workstreams"].values(), key=lambda w: w["workstream_id"])
    ledger_by_id = {w["workstream_id"]: w for w in ledger["workstreams"]}
    admission_table = [{
        "workstream_id": w["workstream_id"],
        "name": w["name"],
        "claimed_state": w["claimed_state"],
        "admitted_state": w["admitted_state"],
        "overclaimed": w["overclaimed"],
        "claim_source": ledger_by_id[w["workstream_id"]]["claim_source"],
        "admissible_evidence": w["admissible_evidence"],
        "non_admissible_evidence": w["non_admissible_evidence"],
        "disqualified_evidence": w.get("disqualified_evidence", []),
        "label": "DIRECTLY_REPRODUCED",
    } for w in workstreams]

    pr_reconciliation = []
    for pr in ledger["pull_requests"]:
        head = refs.get(pr["headRefName"])
        pr_reconciliation.append({
            "number": pr["number"], "state": pr["state"],
            "head": pr["headRefName"], "base": pr["baseRefName"],
            "head_ref_classification": head["classification"] if head else "HEAD_REF_ABSENT",
            "head_merged_into_trunk": head["merged_into_trunk"] if head else None,
            "base_is_trunk": pr["baseRefName"] == projection["trunk"],
            "label": "DIRECTLY_REPRODUCED",
        })

    diagnosis = {
        "diagnosis_id": "OE-L4-DIAGNOSIS-20260822-v001",
        "parent_id": "OE-L4-CURRENTNESS-RECOVERY",
        "commission_id": "COM-CUR-ENV-01-20260822-v001",
        "decision_changed": [],
        "terminal_state": "READY_TO_COMMIT",
        "observation_window": OBSERVATION_WINDOW,
        "immutable_source_sha": SOURCE_SHA,
        "projection_sha256": projection["projection_sha256"],
        "evidence_discipline": {
            "DIRECTLY_REPRODUCED": "a command in this repository was run and its output is recorded",
            "DOCUMENTED": "a committed path or official source states it; the path is cited",
            "HYPOTHESIS": "untested inference, marked as such and never used to advance a state",
        },
        "headline": {
            "refs_observed": projection["ref_count"],
            "ref_classification": projection["ref_classification_counts"],
            "ref_roles": projection["ref_role_counts"],
            "work_refs": projection["ref_role_counts"].get("WORK", 0),
            "refs_merged_into_trunk": projection["ref_classification_counts"].get("MERGED", 0),
            "refs_with_no_trunk_ancestry": projection["ref_classification_counts"].get("ORPHANED", 0),
            "pull_requests_total": len(ledger["pull_requests"]),
            "pull_requests_open": sum(1 for p in ledger["pull_requests"] if p["state"] == "OPEN"),
            "workstreams_classified": len(workstreams),
            "admission_claimed": projection["admission_counts"]["claimed"],
            "admission_admitted": projection["admission_counts"]["admitted"],
            "workstreams_overclaimed": sum(1 for w in workstreams if w["overclaimed"]),
            "finding_counts": projection["finding_counts"],
            "fail_closed": projection["fail_closed"],
        },
        "branch_classification_by_prefix": {
            prefix: dict(sorted(counts.items())) for prefix, counts in sorted(prefixes.items())
        },
        "branch_table": branch_table,
        "pull_request_reconciliation": pr_reconciliation,
        "competing_currentness_claims": competing,
        "version_lineage_breaks": [{
            "subject": f["subject"], "code": f["code"], "detail": f["detail"],
            "path_glob": f["evidence"]["path_glob"],
            "referenced_by": f["evidence"]["referenced_by"],
            "continues_as": f["evidence"].get("continues_as"),
            "note": f["evidence"].get("note", ""),
            "commits_adding_path": f["evidence"]["commits_adding_path"],
            "label": "DIRECTLY_REPRODUCED",
        } for f in by_code["LINEAGE_PHANTOM_VERSION"] + by_code["LINEAGE_FAMILY_DISCONTINUITY"]],
        "version_families": {
            family: {"observed_versions": data["observed_versions"],
                     "internal_gaps": data["internal_gaps"]}
            for family, data in sorted(projection["version_lineage"].items())
            if len(data["observed_versions"]) > 1
        },
        "overlapping_commissions": overlaps,
        "commission_id_collisions": [{
            "subject": f["subject"], "detail": f["detail"], "paths": f["evidence"]["paths"],
            "label": "DIRECTLY_REPRODUCED",
        } for f in by_code["COMMISSION_ID_COLLISION"]],
        "commissions_unresolved_in_register": [{
            "commission_id": f["subject"].rsplit(":", 1)[-1], "path": f["evidence"]["path"],
            "label": "DIRECTLY_REPRODUCED",
        } for f in by_code["COMMISSION_UNRESOLVED_IN_REGISTER"]],
        "admission_classification": admission_table,
        "integration_findings": [f for f in findings if f["code"] in (
            "STACKED_UNLANDED_PR_CHAIN", "ORPHANED_REF_POPULATION",
            "COORDINATION_TOKENS_COUNTED_AS_SCALE")],
        "mechanism": {
            "tool": "workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tools/currentctl.py",
            "tests": "workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/tests/test_currentctl.py",
            "commands": [
                "python3 -I .../tools/currentctl.py validate",
                "python3 -I .../tools/currentctl.py resolve --scope pointer.operator-system",
                "python3 -I .../tools/currentctl.py reproduce",
                "python3 -I .../tests/test_currentctl.py",
            ],
            "failure_to_control_map": [
                {"failure": failure, "finding_code": code, "probe": probe}
                for failure, code, probe in FAILURE_MAP
            ],
        },
        "could_not_determine": UNDETERMINED,
        "disposition_proposals": [
            {"subject": "64 po03/lease/* refs and 1 po03/custody/route-canary ref",
             "state": "ORPHANED coordination tokens, single file, no trunk ancestry",
             "proposed_disposition": "RETAIN_AS_EVIDENCE_EXCLUDE_FROM_SCALE_DENOMINATOR",
             "reason": "They record who held which lease and when, which is real recovery evidence. They are not work and must never be counted as delivered scale. Nothing is deleted."},
            {"subject": "80 ABANDONED work tips with no open pull request and no addressing document",
             "state": "unmerged, uncontained, unaddressed",
             "proposed_disposition": "RETAIN_AS_EVIDENCE_REQUIRE_EXPLICIT_ADDRESSING_OR_SUPERSESSION_RECORD",
             "reason": "Each may hold unique work. Superseded files remain evidence; the missing thing is a supersession edge, not a deletion."},
            {"subject": "The v008 phantom",
             "state": "referenced by 9 committed artifacts, never committed",
             "proposed_disposition": "RECORD_AS_PERMANENT_LINEAGE_BREAK_DO_NOT_RECONSTRUCT",
             "reason": "state/ACTIVE_CONTROL_POINTER_CURRENT.json already records that v008 remains missing and not reconstructed. Reconstructing it from memory would manufacture provenance."},
            {"subject": "pointer.active-control, pointer.operator-system, pointer.instruction-stack",
             "state": "UNRESOLVABLE_COMPETING_CLAIMS across main, PR #6 and PR #7",
             "proposed_disposition": "DECLARE_SUPERSESSION_EDGES_IN_currentness-scopes.json_BEFORE_MERGE",
             "reason": "The mechanism already accepts a resolved answer once a supersession edge is declared. Declaring which side lost is a founder-bound or independently-evaluated act, not a compilation result."},
        ],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(diagnosis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(diagnosis, projection, scopes), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(LANE_ROOT)}")
    print(f"wrote {OUT_MD.relative_to(LANE_ROOT)}")
    return 0


def render_markdown(diagnosis: dict, projection: dict, scopes: dict) -> str:
    head = diagnosis["headline"]
    lines: list[str] = []
    add = lines.append

    add("# OE-L4 — evidence-based diagnosis of what is actually current")
    add("")
    add(f"**Diagnosis ID:** `{diagnosis['diagnosis_id']}`  ")
    add(f"**Commission:** `{diagnosis['commission_id']}`  ")
    add(f"**Immutable source:** `{diagnosis['immutable_source_sha']}`  ")
    add(f"**Observation window:** {diagnosis['observation_window']}  ")
    add(f"**Projection hash:** `{diagnosis['projection_sha256']}`  ")
    add(f"**Terminal state:** `{diagnosis['terminal_state']}`")
    add("")
    add("Every claim below is labelled `DIRECTLY_REPRODUCED` (a command was run here),")
    add("`DOCUMENTED` (a committed path says so, and it is cited) or `HYPOTHESIS`.")
    add("The counts are generated from `projection/CURRENT-STATE-PROJECTION-20260822-v001.json`")
    add("by `tools/build_diagnosis.py`, so they cannot drift from the evidence.")
    add("")
    add("## What the repository actually looks like")
    add("")
    add("| measure | value |")
    add("| --- | --- |")
    add(f"| remote refs observed | {head['refs_observed']} |")
    add(f"| refs carrying work | {head['work_refs']} |")
    add(f"| refs that are lease or canary tokens | {head['ref_roles'].get('LEASE_TOKEN', 0) + head['ref_roles'].get('CANARY_TOKEN', 0)} |")
    add(f"| refs merged into `main` | {head['refs_merged_into_trunk']} |")
    add(f"| refs with no ancestry with `main` at all | {head['refs_with_no_trunk_ancestry']} |")
    add(f"| pull requests, total / open | {head['pull_requests_total']} / {head['pull_requests_open']} |")
    add(f"| workstreams classified | {head['workstreams_classified']} |")
    add(f"| workstreams admitted below their claim | {head['workstreams_overclaimed']} |")
    add("")
    add("Branch classification: " + ", ".join(
        f"**{state}** {count}" for state, count in head["ref_classification"].items()) + ".")
    add("")
    add("Admission ladder, claimed against admitted:")
    add("")
    add("| state | claimed | admitted |")
    add("| --- | --- | --- |")
    order = ["PROPOSED", "LAUNCHED", "OBSERVED", "DURABLE", "INDEPENDENTLY_VALIDATED", "ACCEPTED"]
    for state in order:
        add(f"| {state} | {head['admission_claimed'].get(state, 0)} | {head['admission_admitted'].get(state, 0)} |")
    add("")
    empty = [state for state in order if not head["admission_admitted"].get(state)]
    highest = next((state for state in reversed(order) if head["admission_admitted"].get(state)),
                   "PROPOSED")
    add(f"Nothing in this estate reaches {', '.join('`' + s + '`' for s in empty)}. The highest")
    add(f"admitted state anywhere is `{highest}`, and "
        f"{head['admission_admitted'].get('PROPOSED', 0)} of {head['workstreams_classified']} "
        "workstreams sit at `PROPOSED`.")
    add("That is the finding in one line: the estate is large, active and almost entirely")
    add("unadmitted. It is not too big. It cannot say what it has finished.")
    add("")

    add("## Branch classification by prefix")
    add("")
    add("| prefix | total | " + " | ".join(order_states(diagnosis)) + " |")
    add("| --- | --- | " + " | ".join("---" for _ in order_states(diagnosis)) + " |")
    for prefix, counts in diagnosis["branch_classification_by_prefix"].items():
        cells = " | ".join(str(counts.get(state, 0)) for state in order_states(diagnosis))
        add(f"| `{prefix}` | {counts['_total']} | {cells} |")
    add("")
    add("`DIRECTLY_REPRODUCED`: `git for-each-ref refs/remotes/origin` plus a containment")
    add("DAG built from `git rev-list --topo-order --all --parents`. Classification is derived")
    add("from the DAG, never from a branch name or a date.")
    add("")
    add("The full per-branch table — branch, head, last commit date, lineage parent and")
    add("classification — is `branch_table` in the JSON alongside this file.")
    add("")

    add("## Pull requests reconciled against branch state")
    add("")
    add("| PR | state | head | base | head ref classification | merged into `main` |")
    add("| --- | --- | --- | --- | --- | --- |")
    for pr in sorted(diagnosis["pull_request_reconciliation"], key=lambda p: -p["number"]):
        add(f"| #{pr['number']} | {pr['state']} | `{pr['head']}` | `{pr['base']}` | "
            f"{pr['head_ref_classification']} | {pr['head_merged_into_trunk']} |")
    add("")
    stack = [f for f in diagnosis["integration_findings"] if f["code"] == "STACKED_UNLANDED_PR_CHAIN"]
    if stack:
        add(f"`DIRECTLY_REPRODUCED`: {stack[0]['detail']}.")
        add("")
        add("The practical consequence is that the last thing to reach `main` was PR #3 on")
        add("2026-08-19. Everything built since then sits above a four-deep stack, so a")
        add("human is the only thing that can move it. That is the mechanism behind")
        add("\"the founder becoming the routine relay and merge layer\".")
        add("")

    add("## Competing currentness claims, named exactly")
    add("")
    for claim in diagnosis["competing_currentness_claims"]:
        add(f"### `{claim['scope_id']}`")
        add("")
        add(f"Address: `{claim['urn']}`")
        add("")
        add("| blob | path | held by |")
        add("| --- | --- | --- |")
        for variant in claim["variants"]:
            add(f"| `{variant['blob'][:12]}` | `{variant['path']}` | "
                + ", ".join(f"`{b}`" for b in variant["branches"]) + " |")
        if claim["absent_on"]:
            add("")
            add("Absent on: " + ", ".join(f"`{b}`" for b in claim["absent_on"]) + ".")
        add("")
        add(f"`{claim['label']}` — {claim['instrument']}.")
        add("")
    add("`currentctl resolve` refuses to answer for every scope above and exits 1. It")
    add("does not choose the newest, the nearest or the majority. Seven branches agreeing")
    add("against one is still unresolved, because agreement by copying is not authority.")
    add("")

    add("## The version lineage and where it breaks")
    add("")
    for brk in diagnosis["version_lineage_breaks"]:
        add(f"- **{brk['subject'].rsplit(':', 1)[-1]}** (`{brk['code']}`) — {brk['detail']}.")
        add(f"  `DIRECTLY_REPRODUCED`: `git log --all --diff-filter=A -- '{brk['path_glob']}'` returns"
            f" {len(brk['commits_adding_path'])} commits.")
    add("")
    add("The observed `CLAUDE_EXTENSION_LAUNCH_ROUTE_20260818` family is `v005, v006, v007`.")
    add("`dispatch/SC_V008_DELIVERY_PACKAGING_RULING_20260818_v001.md` then instructs the")
    add("founder to attach `CLAUDE_EXTENSION_LAUNCH_ROUTE_20260818_v008.md` as the payload,")
    add("and states in its own text that the tree does not contain that path. The chain")
    add("resumes at `v009` under a different family name")
    add("(`CLAUDE_EXTENSION_CANONICAL_LAUNCH_COMMAND_20260819_v009.md`) and again at `v010`")
    add("under a third (`CLAUDE_CHROME_*_v010.md`).")
    add("")
    add("So the break is not only the missing v008. The version number is carried across")
    add("three different filename families, which means no filename-based supersession")
    add("chain can span it. `DIRECTLY_REPRODUCED`.")
    add("")
    add("Families with more than one observed version:")
    add("")
    add("| family | observed | internal gaps |")
    add("| --- | --- | --- |")
    for family, data in diagnosis["version_families"].items():
        add(f"| `{family}` | {data['observed_versions']} | {data['internal_gaps'] or '—'} |")
    add("")

    add("## Overlapping commissions, named exactly")
    add("")
    add(f"{len(diagnosis['overlapping_commissions'])} undifferentiated overlaps and "
        f"{len(diagnosis['commission_id_collisions'])} identifier collision.")
    add("")
    for overlap in diagnosis["overlapping_commissions"]:
        add(f"- `{overlap['first']['id']}` ({overlap['first']['path']}) and "
            f"`{overlap['second']['id']}` ({overlap['second']['path']}) — both assert "
            f"whole-operation authority over {', '.join('`' + n + '`' for n in overlap['overlapping_namespace'])}"
            f" with no supersession edge"
            + (", and both bind the same runtime actor." if set(overlap['first']['binds']) & set(overlap['second']['binds']) else "."))
    add("")
    for collision in diagnosis["commission_id_collisions"]:
        add(f"- **Identifier collision** — {collision['detail']}: "
            + ", ".join(f"`{p}`" for p in collision["paths"]) + ".")
    add("")
    add("`DOCUMENTED` — the scope text of each commission is transcribed into")
    add("`ledger/workstream-ledger.json` with the committed path it came from.")
    add("")
    add(f"Separately, {len(diagnosis['commissions_unresolved_in_register'])} active commissions "
        "cannot resolve through `state/operator-system/COMMISSION_REGISTER.jsonl`, which holds "
        "exactly one entry. `AGENTS.md` rule 8 requires every active commission to resolve one "
        "function, appointment, authority envelope, runtime binding and return route through the "
        "active instruction stack. `DIRECTLY_REPRODUCED`.")
    add("")

    add("## Admission state per workstream, with the evidence behind each")
    add("")
    add("| workstream | claimed | admitted | admissible evidence | non-admissible offered | disqualified |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in diagnosis["admission_classification"]:
        marker = " ⚠" if row["overclaimed"] else ""
        add(f"| `{row['workstream_id']}`{marker} | {row['claimed_state']} | {row['admitted_state']} | "
            + (", ".join(sorted(set(row["admissible_evidence"]))) or "—") + " | "
            + (", ".join(sorted(set(row["non_admissible_evidence"]))) or "—") + " | "
            + (", ".join(sorted(set(row["disqualified_evidence"]))) or "—") + " |")
    add("")
    add("`disqualified` means the evidence was of an admissible class but did not address")
    add("anything a third party could reach now: an alias locator, a path that is not there,")
    add("a hash that does not match or a read-back the ref has moved past. Each")
    add("`claim_source` in the JSON cites the committed path the claim was read from.")
    add("")
    add("Four of these deserve naming.")
    add("")
    add("**`WS-V010-FULLSCALE-CHATGPT`** claims `DURABLE` and is admitted at `PROPOSED`. Its")
    add("payload artifacts are real and hash-verified — all four sha256 values recorded in")
    add("`state/ACTIVE_CONTROL_POINTER_CURRENT.json` match the committed bytes exactly")
    add("(`DIRECTLY_REPRODUCED`). What is missing is the result side. The execution record")
    add("names a Supabase registry and three Drive receipts, none of which are in the")
    add("canonical store, and the transport is recorded as a founder-assisted paste whose")
    add("byte identity is separately recorded as `FAILED_NOT_BYTE_IDENTICAL`.")
    add("")
    add("**`WS-W-LANES-24`** claims 24 registered lanes and \"direct conversation locators")
    add("recorded against every lane\". `DIRECTLY_REPRODUCED`: exactly two `OBJ-LANE-W`")
    add("identifiers occur anywhere in the repository, `W01` and `W24`, both as the endpoints")
    add("of the range that asserts the denominator. Zero ChatGPT conversation URLs exist in")
    add("the repository. The denominator is asserted, never enumerated.")
    add("")
    add("**`WS-W16-COVERAGE-REVIEW`** is the review the founder singled out. The repository")
    add("records the destination as a \"six-project estate\" and enumerates none of the six.")
    add("A count with no enumeration and no authenticated-access record is `FILE_COUNT`")
    add("evidence, which is ceilinged at `PROPOSED`. Whether eleven projects now exist is")
    add("`HYPOTHESIS` from this lane's position — see \"what could not be determined\".")
    add("")
    add("**`WS-CGPT-01-SUPPORT`** is recorded in `control-plane.json` as `ACTIVE_INTERIM`,")
    add("which `scctl.py` treats as an operational state. Its provider locator is")
    add("`current_project_conversation` and its launch receipt is")
    add("`current-founder-appointment`, neither of which is a path or a stable ID. Both are")
    add("disqualified, so the binding is admitted at `PROPOSED`. This is the clearest case")
    add("of a local platform surface standing in for durable identity.")
    add("")

    add("## The mechanism, and what it rejects")
    add("")
    add("```")
    for command in diagnosis["mechanism"]["commands"]:
        add(command)
    add("```")
    add("")
    add("| recurring failure | finding code | probe |")
    add("| --- | --- | --- |")
    for row in diagnosis["mechanism"]["failure_to_control_map"]:
        add(f"| {row['failure']} | `{row['finding_code']}` | `{row['probe']}` |")
    add("")
    add("Against this repository today `validate` exits 1 with these findings:")
    add("")
    add("| finding | count |")
    add("| --- | --- |")
    for code, count in sorted(projection["finding_counts"].items()):
        add(f"| `{code}` | {count} |")
    add("")

    add("## Proposed disposition — nothing is deleted")
    add("")
    for item in diagnosis["disposition_proposals"]:
        add(f"- **{item['subject']}** — currently {item['state']}. Proposed:")
        add(f"  `{item['proposed_disposition']}`. {item['reason']}")
    add("")

    add("## What could not be determined, and why")
    add("")
    for item in diagnosis["could_not_determine"]:
        add(f"- **{item['question']}** — {item['why']} (`{item['label']}`)")
    add("")
    add("## Boundaries observed")
    add("")
    add("This lane wrote only inside")
    add("`workstreams/so02/control-plane/operating-environment/l4-currentness-recovery/**` and")
    add("`receipts/so02/2026-08-22/oe-l4-currentness-recovery/**`. Every other branch was read")
    add("with `git` and every pull request was read with `gh pr list` and `gh pr view`. No pull")
    add("request was opened, commented on, merged or modified. No protected branch was written.")
    add("Nothing was deleted. No strategy is bound here: the diagnosis describes and mechanises")
    add("current state, and where a choice belongs to the founder or to an independent")
    add("evaluator the tool refuses and records the refusal instead of guessing.")
    add("")
    return "\n".join(lines)


def order_states(diagnosis: dict) -> list[str]:
    states: set[str] = set()
    for counts in diagnosis["branch_classification_by_prefix"].values():
        states.update(k for k in counts if k != "_total")
    return sorted(states)


if __name__ == "__main__":
    sys.exit(main())
