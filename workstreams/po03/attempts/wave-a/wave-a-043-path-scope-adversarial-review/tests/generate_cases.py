#!/usr/bin/env python3
"""Generate the frozen hidden adversarial case set for the PO-03 path-scope guard.

The generator is deterministic: running it twice produces byte-identical
``hidden-cases.json``. Cases are frozen and committed before the guard under
review is executed, so every ``predicted_*`` field is a falsifiable prediction
rather than a transcription of observed behaviour.

Two case populations are produced.

``path_cases``
    Pure string inputs handed to ``check_path_scope.violations``. They touch no
    filesystem and no repository.

``git_cases``
    Declarative scenarios executed against throwaway temporary Git repositories
    created under a temporary directory. Each scenario states its operations, so
    the frozen file, not the harness, defines what is exercised.

Every case carries two independent judgements:

``commission_requirement``
    What the PO-03 collision boundary in ``workstreams/po03/COMMISSION.md``
    requires. This is the oracle.

``predicted_guard_*``
    What this reviewer predicted the current guard would do before running it.

A case where the observed guard behaviour contradicts ``commission_requirement``
is a finding against the task hypothesis. A case where observed behaviour
contradicts only the prediction is a refutation of this reviewer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASE_SET_VERSION = "PO03-WAVE-A-043-HIDDEN-CASES-v1"
TASK_ID = "wave-a-043-path-scope-adversarial-review"

ALLOW = "ALLOW"
REJECT = "REJECT"


def _hex(path: str) -> str:
    return path.encode("utf-8", "surrogateescape").hex()


def _display(path: str) -> str:
    return repr(path)


# ---------------------------------------------------------------------------
# Pure path cases
# ---------------------------------------------------------------------------

# (path, family, commission_requirement, predicted_guard, basis, rationale)
PATH_CASES: tuple[tuple[str, str, str, str, str, str], ...] = (
    # --- positive in-allowlist controls: a rejection here is a false positive ---
    (
        "workstreams/po03/tools/check_path_scope.py",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Canonical in-allowlist tool path; the guard must not block its own maintenance.",
    ),
    (
        "receipts/po03/2026-08-22/producer-execution.json",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-receipts",
        "Mandatory receipt path named by the commission.",
    ),
    (
        ".github/workflows/po03-contracts.yml",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workflow",
        "The live PO-03 workflow file itself.",
    ),
    (
        "workstreams/po03/attempts/wave-a/wave-a-043-path-scope-adversarial-review/manifest.json",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "This attempt's own owned slot must remain writable.",
    ),
    (
        "workstreams/po03/.gitignore",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Dotfile inside the allowlist; leading dot must not defeat the prefix test.",
    ),
    (
        "receipts/po03/2026-08-22/nested/deeper/still/inside.json",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-receipts",
        "Deep nesting inside an allowed prefix stays allowed.",
    ),
    (
        "workstreams/po03/control/events/wave-a-043/000001-created.json",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Controller event path used by the live factory.",
    ),
    (
        "workstreams/po03/a file with spaces.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Spaces are legal in Git paths and must not trip normalisation.",
    ),
    (
        "workstreams/po03/quote'and\"double.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Quote characters would be shell-quoted by git without -z; the guard uses -z.",
    ),
    (
        "workstreams/po03/tab\tinside.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Tab inside an allowed path is legal and must not be treated as a separator.",
    ),
    (
        "workstreams/po03/newline\ninside.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Newline in an allowed path; a line-oriented parser would split this case.",
    ),
    (
        "workstreams/po03/\u30d5\u30a1\u30a4\u30eb.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Non-ASCII suffix inside an allowed prefix stays allowed.",
    ),
    (
        "workstreams/po03/caf\u00e9.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "NFC precomposed form inside an allowed prefix.",
    ),
    (
        "workstreams/po03/cafe\u0301.json",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "NFD decomposed form of the same name; must behave identically to the NFC form.",
    ),
    (
        "workstreams/po03/x.py\u200b",
        "positive-control-exotic",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Zero-width space in the leaf name; still inside the allowed prefix.",
    ),
    (
        ".github/workflows/po03-a.yml",
        "positive-control",
        ALLOW,
        ALLOW,
        "commission-allowlist-workflow",
        "Minimal well-formed PO-03 workflow name.",
    ),
    # --- prefix confusables that must be rejected ---
    (
        "workstreams/po03x/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Sibling directory whose name extends po03; a prefix test without the separator would pass it.",
    ),
    (
        "workstreams/po030/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Digit-extended sibling directory.",
    ),
    (
        "workstreams/po03-extra/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Hyphen-extended sibling directory.",
    ),
    (
        "workstreams/po03.bak/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Dot-extended sibling directory.",
    ),
    (
        "workstreams/po03",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "A regular file literally named po03 at the workstreams root is not the po03 subtree.",
    ),
    (
        "receipts/po03x/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Receipts-side sibling directory extension.",
    ),
    (
        "receipts/po03",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Receipts-side bare file named po03.",
    ),
    (
        "workstreams-po03/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Top-level directory that merges the two allowlist components.",
    ),
    (
        "aworkstreams/po03/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Allowed prefix present but not anchored at the start of the path.",
    ),
    (
        "x/workstreams/po03/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Allowed prefix nested one level deep; a substring test would pass it.",
    ),
    (
        "workstreams/po03suffix/receipts/po03/file.json",
        "prefix-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Allowed prefix appears later in the path but the anchored component is not allowed.",
    ),
    # --- case folding ---
    (
        "Workstreams/po03/file.json",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "On a case-insensitive checkout this resolves to the allowed directory; the guard must stay byte-exact.",
    ),
    (
        "workstreams/PO03/file.json",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "Upper-case component name.",
    ),
    (
        "WORKSTREAMS/PO03/FILE.JSON",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "Fully upper-cased allowlist path.",
    ),
    (
        "Receipts/po03/file.json",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "Receipts-side case variant.",
    ),
    (
        ".GitHub/workflows/po03-x.yml",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "Case variant of the .github directory.",
    ),
    (
        ".github/Workflows/po03-x.yml",
        "case-folding",
        REJECT,
        REJECT,
        "commission-readonly",
        "Case variant of the workflows directory.",
    ),
    # --- traversal and separator forms ---
    (
        "workstreams/po03/../po01/producer-result.json",
        "traversal",
        REJECT,
        REJECT,
        "commission-readonly",
        "Traversal out of the allowlist into PO-01 while retaining an allowed prefix.",
    ),
    (
        "workstreams/po03/../../state/ACTIVE_CONTROL_POINTER_CURRENT.json",
        "traversal",
        REJECT,
        REJECT,
        "commission-readonly",
        "Double traversal onto a protected current-pointer file.",
    ),
    (
        "workstreams/po03/./control/x.json",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Non-canonical single-dot component; git never emits it, so fail-closed rejection is correct.",
    ),
    (
        "workstreams//po03/x.json",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Doubled separator collapses to an allowed path under naive normalisation.",
    ),
    (
        "/workstreams/po03/x.json",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Absolute path form.",
    ),
    (
        "./workstreams/po03/x.json",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Relative dot-slash prefix.",
    ),
    (
        "workstreams/po03/",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Directory form with trailing separator.",
    ),
    (
        "..",
        "traversal",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Bare parent reference.",
    ),
    (
        ".",
        "degenerate",
        REJECT,
        REJECT,
        "commission-readonly",
        "Bare current-directory reference is not an allowed file path.",
    ),
    (
        "",
        "degenerate",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Empty string must never be treated as allowed.",
    ),
    (
        " workstreams/po03/x.json",
        "degenerate",
        REJECT,
        REJECT,
        "commission-readonly",
        "Leading space defeats the anchored prefix and must not be stripped.",
    ),
    (
        "workstreams/po03/x.json ",
        "degenerate",
        ALLOW,
        ALLOW,
        "commission-allowlist-workstreams",
        "Trailing space is a legal distinct filename inside the allowlist.",
    ),
    (
        "workstreams\\po03\\x.json",
        "separator",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Windows separators throughout.",
    ),
    (
        "workstreams/po03\\..\\..\\state\\x.json",
        "separator",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Mixed separators with Windows traversal after an allowed prefix.",
    ),
    (
        "workstreams/po03/sub\\file.json",
        "separator",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Backslash inside an otherwise allowed path; Git treats it as an ordinary character, the guard fails closed.",
    ),
    (
        "state/x.json\x00workstreams/po03/y.json",
        "separator",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Embedded NUL attempting to smuggle a protected path in front of an allowed one.",
    ),
    (
        "workstreams/po03/y.json\x00state/x.json",
        "separator",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Embedded NUL with the allowed path first; must still fail closed.",
    ),
    # --- unicode confusables ---
    (
        "workstreams/p\u043e03/file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Cyrillic small o inside po03 renders identically to the allowed directory.",
    ),
    (
        "works\u0442reams/po03/file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Cyrillic te substituted for t in workstreams.",
    ),
    (
        "\uff57orkstreams/po03/file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Fullwidth latin w.",
    ),
    (
        "workstreams\u2044po03\u2044file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Fraction slash used in place of the path separator.",
    ),
    (
        "workstreams/po03\u200b/file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Zero-width space between po03 and the separator breaks the anchored prefix invisibly.",
    ),
    (
        "workstreams/po\u30030\u33333/file.json",
        "unicode-confusable",
        REJECT,
        REJECT,
        "commission-readonly",
        "Ideographic and squared characters mimicking po03.",
    ),
    # --- workflow name lookalikes ---
    (
        ".github/workflows/not-po03.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "PO-03 token present but not anchored at the filename start.",
    ),
    (
        ".github/workflows/po03-guard.yaml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "The commission allowlist names .yml, not .yaml.",
    ),
    (
        ".github/workflows/po03-guard.yml.bak",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "Suffix appended after the allowed extension.",
    ),
    (
        ".github/workflows/po03_guard.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "Underscore instead of the hyphen required by po03-*.yml.",
    ),
    (
        ".github/workflows/PO03-guard.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "Upper-case workflow prefix.",
    ),
    (
        ".github/workflows/sub/po03-guard.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "PO-03 workflow name nested below the workflows directory.",
    ),
    (
        ".github/workflows/po03-guard/payload.yml",
        "workflow-lookalike",
        REJECT,
        ALLOW,
        "commission-allowlist-workflow-glob",
        "The commission glob po03-*.yml does not cross a separator, but a startswith/endswith pair does. Predicted over-permissive.",
    ),
    (
        ".github/workflows/po03-a/b/c/deep.yml",
        "workflow-lookalike",
        REJECT,
        ALLOW,
        "commission-allowlist-workflow-glob",
        "Deeper form of the same predicted separator-crossing weakness.",
    ),
    (
        ".github/workflows/po03-a/.github/workflows/evil.yml",
        "workflow-lookalike",
        REJECT,
        ALLOW,
        "commission-allowlist-workflow-glob",
        "Separator-crossing form that also reintroduces a workflow-looking tail.",
    ),
    (
        ".github/workflowspo03-x.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "Missing separator between the workflows directory and the filename.",
    ),
    (
        ".github/actions/po03-x.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "Correct filename under the wrong directory.",
    ),
    (
        ".github/workflows/po03-.yml",
        "workflow-lookalike",
        ALLOW,
        ALLOW,
        "commission-allowlist-workflow-glob",
        "Degenerate but glob-conformant name where the wildcard matches the empty string.",
    ),
    (
        ".github/workflows/po03-x.yml.yml",
        "workflow-lookalike",
        ALLOW,
        ALLOW,
        "commission-allowlist-workflow-glob",
        "Double extension still matches po03-*.yml because the wildcard absorbs the first .yml.",
    ),
    (
        ".github/workflows/operator-taxonomy-currentness.yml",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "commission-readonly",
        "The other live workflow in this repository is outside PO-03 authority.",
    ),
    (
        ".github/workflows/po03-x.yml/../../../state/x.json",
        "workflow-lookalike",
        REJECT,
        REJECT,
        "fail-closed-non-canonical",
        "Traversal anchored behind an allowed workflow name.",
    ),
    # --- PO-01 non-interference ---
    (
        "workstreams/po01/COMMISSION.md",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 commission file must never be writable by PO-03.",
    ),
    (
        "workstreams/po01/producer-result.json",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 producer artefact.",
    ),
    (
        "receipts/po01/2026-08-22/pack.json",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 receipt namespace.",
    ),
    (
        ".github/workflows/po01-pack.yml",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 workflow file.",
    ),
    (
        "workstreams/po03/../po01/pack/manifest.json",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 reached through traversal from the PO-03 subtree.",
    ),
    (
        "workstreams/po01x/file.json",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 sibling namespace.",
    ),
    (
        "packs/po01/pack.json",
        "po01",
        REJECT,
        REJECT,
        "po01-non-interference",
        "PO-01 pack content under the read-only packs tree.",
    ),
    # --- explicitly read-only estate ---
    (
        "state/ACTIVE_CONTROL_POINTER_CURRENT.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Current programme execution pointer.",
    ),
    (
        "state/operator-system/ACTIVE_INSTRUCTION_STACK.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "The one active instruction stack.",
    ),
    (
        ".cursor/environment.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "pr8-non-interference",
        "PR #8 environment file named as read-only by the commission.",
    ),
    (
        "packs/operator-pack/manifest.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Read-only packs tree.",
    ),
    (
        "modules/operators/runner.py",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Read-only operator modules.",
    ),
    (
        "modules/work_unit_contract/contract.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Read-only work-unit contract module.",
    ),
    (
        "_transport/inbox/file.bin",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Read-only transport tree.",
    ),
    (
        "AGENTS.md",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Repository-wide operator instructions.",
    ),
    (
        "operations/README.md",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Operator entry point.",
    ),
    (
        "scripts/check_operator_taxonomy.py",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Shared taxonomy check invoked before commit.",
    ),
    (
        ".gitattributes",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Root Git attributes could rewrite how content is stored repository-wide.",
    ),
    (
        ".gitmodules",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Root submodule declaration.",
    ),
    (
        ".github/CODEOWNERS",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Review-ownership control outside PO-03 authority.",
    ),
    (
        "dispatch/CURRENT.json",
        "protected-readonly",
        REJECT,
        REJECT,
        "commission-readonly",
        "Read-only dispatch current-pointer file.",
    ),
)


# ---------------------------------------------------------------------------
# Git status-behaviour cases
# ---------------------------------------------------------------------------

IN = "workstreams/po03/control/inside.json"
IN2 = "workstreams/po03/control/inside-two.json"
OUT = "state/ACTIVE_CONTROL_POINTER_CURRENT.json"
OUT2 = "modules/operators/runner.py"
PO01 = "workstreams/po01/producer-result.json"

SEED = {
    IN: '{"seed":"inside"}\n',
    IN2: '{"seed":"inside-two"}\n',
    OUT: '{"seed":"protected-pointer","note":"throwaway fixture only"}\n',
    OUT2: "def runner():\n    return 'protected'\n",
    PO01: '{"seed":"po01-fixture"}\n',
    "README.md": "# throwaway fixture repository\n",
}

# A body large and distinctive enough that Git rename detection scores it at 100%
# when moved unchanged, and at effectively 0% when replaced wholesale.
BODY_A = "".join(f"alpha line {i} of the rename fixture payload\n" for i in range(60))
BODY_B = "".join(f"omega row {i} carrying entirely different content\n" for i in range(60))


def _git_case(
    case_id: str,
    family: str,
    status_class: str,
    description: str,
    operations: list[dict],
    commission_requirement: str,
    predicted_exit_code: int,
    predicted_reported_paths: list[str],
    predicted_violation_paths: list[str],
    rationale: str,
    base: str = "base",
    head: str = "HEAD",
) -> dict:
    return {
        "case_id": case_id,
        "family": family,
        "status_class": status_class,
        "description": description,
        "seed_files": SEED,
        "operations": operations,
        "base_ref": base,
        "head_ref": head,
        "commission_requirement": commission_requirement,
        "predicted_guard_exit_code": predicted_exit_code,
        "predicted_reported_paths": predicted_reported_paths,
        "predicted_violation_paths": predicted_violation_paths,
        "rationale": rationale,
    }


def git_cases() -> list[dict]:
    cases: list[dict] = []

    cases.append(
        _git_case(
            "GIT-001",
            "positive-control",
            "M",
            "Modify a single in-allowlist file.",
            [
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":1}\n'},
                {"op": "commit", "message": "modify inside"},
            ],
            ALLOW,
            0,
            [IN],
            [],
            "Ordinary sanctioned work must pass; a failure here is a false positive that would block PO-03.",
        )
    )
    cases.append(
        _git_case(
            "GIT-002",
            "positive-control",
            "A",
            "Add a new in-allowlist file and a new PO-03 workflow.",
            [
                {"op": "write", "path": "receipts/po03/2026-08-22/new.json", "content": "{}\n"},
                {"op": "write", "path": ".github/workflows/po03-new.yml", "content": "name: x\n"},
                {"op": "commit", "message": "add inside"},
            ],
            ALLOW,
            0,
            [".github/workflows/po03-new.yml", "receipts/po03/2026-08-22/new.json"],
            [],
            "All three allowlist components must be additively writable.",
        )
    )
    cases.append(
        _git_case(
            "GIT-003",
            "positive-control",
            "D",
            "Delete an in-allowlist file.",
            [
                {"op": "delete", "path": IN2},
                {"op": "commit", "message": "delete inside"},
            ],
            ALLOW,
            0,
            [IN2],
            [],
            "Deleting one's own artefact is inside authority.",
        )
    )
    cases.append(
        _git_case(
            "GIT-004",
            "positive-control-exotic",
            "A",
            "Add an in-allowlist file whose name contains a newline.",
            [
                {"op": "write", "path": "workstreams/po03/control/new\nline.json", "content": "{}\n"},
                {"op": "commit", "message": "add exotic inside"},
            ],
            ALLOW,
            0,
            ["workstreams/po03/control/new\nline.json"],
            [],
            "A line-oriented reader would split this into a bogus second path and reject it; -z must prevent that.",
        )
    )
    cases.append(
        _git_case(
            "GIT-005",
            "modified-out",
            "M",
            "Modify a protected out-of-allowlist file.",
            [
                {"op": "write", "path": OUT, "content": '{"seed":"tampered"}\n'},
                {"op": "commit", "message": "modify protected"},
            ],
            REJECT,
            1,
            [OUT],
            [OUT],
            "Core hypothesis: modified out-of-allowlist paths are rejected.",
        )
    )
    cases.append(
        _git_case(
            "GIT-006",
            "added-out",
            "A",
            "Add a new out-of-allowlist file.",
            [
                {"op": "write", "path": "state/PO03-SHOULD-NOT-WRITE.json", "content": "{}\n"},
                {"op": "commit", "message": "add protected"},
            ],
            REJECT,
            1,
            ["state/PO03-SHOULD-NOT-WRITE.json"],
            ["state/PO03-SHOULD-NOT-WRITE.json"],
            "Core hypothesis: added out-of-allowlist paths are rejected.",
        )
    )
    cases.append(
        _git_case(
            "GIT-007",
            "deleted-out",
            "D",
            "Delete a protected out-of-allowlist file.",
            [
                {"op": "delete", "path": OUT},
                {"op": "commit", "message": "delete protected"},
            ],
            REJECT,
            1,
            [OUT],
            [OUT],
            "Core hypothesis: deleted out-of-allowlist paths are rejected.",
        )
    )
    cases.append(
        _git_case(
            "GIT-008",
            "deleted-out-po01",
            "D",
            "Delete a PO-01 artefact.",
            [
                {"op": "delete", "path": PO01},
                {"op": "commit", "message": "delete po01"},
            ],
            REJECT,
            1,
            [PO01],
            [PO01],
            "PO-01 non-interference is absolute; deletion is the most destructive contact form.",
        )
    )
    cases.append(
        _git_case(
            "GIT-009",
            "renamed-in-to-out",
            "R",
            "Rename an in-allowlist file to an out-of-allowlist destination.",
            [
                {"op": "write", "path": IN, "content": BODY_A},
                {"op": "commit", "message": "prepare rename payload"},
                {"op": "tag", "name": "base"},
                {"op": "move", "from": IN, "to": "state/escaped.json"},
                {"op": "commit", "message": "rename inside to outside"},
            ],
            REJECT,
            1,
            ["state/escaped.json"],
            ["state/escaped.json"],
            "The destination escapes the allowlist and must be reported.",
        )
    )
    cases.append(
        _git_case(
            "GIT-010",
            "renamed-out-to-in",
            "R",
            "Rename a protected out-of-allowlist file into the allowlist, deleting the protected path.",
            [
                {"op": "write", "path": OUT, "content": BODY_A},
                {"op": "commit", "message": "prepare protected payload"},
                {"op": "tag", "name": "base"},
                {"op": "move", "from": OUT, "to": "workstreams/po03/control/absorbed.json"},
                {"op": "commit", "message": "rename outside into inside"},
            ],
            REJECT,
            1,
            [OUT, "workstreams/po03/control/absorbed.json"],
            [OUT],
            "This mutation deletes a protected file. Predicted miss: git diff --name-only prints only the rename destination, so the deleted source never reaches the guard.",
        )
    )
    cases.append(
        _git_case(
            "GIT-011",
            "renamed-out-to-out",
            "R",
            "Rename one protected file to another protected path.",
            [
                {"op": "write", "path": OUT, "content": BODY_A},
                {"op": "commit", "message": "prepare protected payload"},
                {"op": "tag", "name": "base"},
                {"op": "move", "from": OUT, "to": "state/renamed-pointer.json"},
                {"op": "commit", "message": "rename outside to outside"},
            ],
            REJECT,
            1,
            [OUT, "state/renamed-pointer.json"],
            ["state/renamed-pointer.json"],
            "Destination is out of allowlist, so at least the destination should be reported even if the source is dropped.",
        )
    )
    cases.append(
        _git_case(
            "GIT-012",
            "renamed-out-to-in-po01",
            "R",
            "Rename a PO-01 artefact into the PO-03 allowlist.",
            [
                {"op": "write", "path": PO01, "content": BODY_A},
                {"op": "commit", "message": "prepare po01 payload"},
                {"op": "tag", "name": "base"},
                {"op": "move", "from": PO01, "to": "workstreams/po03/attempts/absorbed-po01.json"},
                {"op": "commit", "message": "absorb po01 artefact"},
            ],
            REJECT,
            1,
            [PO01, "workstreams/po03/attempts/absorbed-po01.json"],
            [PO01],
            "Same predicted miss as GIT-010, applied to the absolute PO-01 non-interference boundary.",
        )
    )
    cases.append(
        _git_case(
            "GIT-013",
            "renamed-out-to-in-below-threshold",
            "R",
            "Move a protected file into the allowlist while replacing its content, defeating rename detection.",
            [
                {"op": "write", "path": OUT, "content": BODY_A},
                {"op": "commit", "message": "prepare protected payload"},
                {"op": "tag", "name": "base"},
                {"op": "delete", "path": OUT},
                {"op": "write", "path": "workstreams/po03/control/rewritten.json", "content": BODY_B},
                {"op": "commit", "message": "move with rewrite"},
            ],
            REJECT,
            1,
            [OUT, "workstreams/po03/control/rewritten.json"],
            [OUT],
            "Below the similarity threshold Git reports D plus A, so the protected deletion should surface. Contrast with GIT-010.",
        )
    )
    cases.append(
        _git_case(
            "GIT-014",
            "renamed-out-to-in-renames-disabled",
            "R",
            "Repeat the GIT-010 mutation with diff.renames disabled in the repository config.",
            [
                {"op": "write", "path": OUT, "content": BODY_A},
                {"op": "commit", "message": "prepare protected payload"},
                {"op": "tag", "name": "base"},
                {"op": "move", "from": OUT, "to": "workstreams/po03/control/absorbed.json"},
                {"op": "commit", "message": "rename outside into inside"},
                {"op": "git_config", "key": "diff.renames", "value": "false"},
            ],
            REJECT,
            1,
            [OUT, "workstreams/po03/control/absorbed.json"],
            [OUT],
            "Shows whether the outcome of GIT-010 depends on repository or runner configuration rather than on the guard.",
        )
    )
    cases.append(
        _git_case(
            "GIT-015",
            "copied-out-to-in",
            "C",
            "Copy a protected file into the allowlist, leaving the original in place.",
            [
                {"op": "write", "path": OUT, "content": BODY_A},
                {"op": "commit", "message": "prepare protected payload"},
                {"op": "tag", "name": "base"},
                {"op": "copy", "from": OUT, "to": "workstreams/po03/control/copied.json"},
                {"op": "commit", "message": "copy protected content inside"},
            ],
            ALLOW,
            0,
            ["workstreams/po03/control/copied.json"],
            [],
            "No protected path changes, so the guard should pass. Copy detection is off by default, so the entry should appear as A.",
        )
    )
    cases.append(
        _git_case(
            "GIT-016",
            "copied-in-to-out",
            "C",
            "Copy an in-allowlist file to an out-of-allowlist destination.",
            [
                {"op": "write", "path": IN, "content": BODY_A},
                {"op": "commit", "message": "prepare payload"},
                {"op": "tag", "name": "base"},
                {"op": "copy", "from": IN, "to": "state/copied-out.json"},
                {"op": "commit", "message": "copy inside content outside"},
            ],
            REJECT,
            1,
            ["state/copied-out.json"],
            ["state/copied-out.json"],
            "A copy that lands outside the allowlist is a new protected-path write.",
        )
    )
    cases.append(
        _git_case(
            "GIT-017",
            "mixed",
            "AM",
            "Mix one legitimate in-allowlist change with one out-of-allowlist change.",
            [
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":2}\n'},
                {"op": "write", "path": OUT2, "content": "def runner():\n    return 'tampered'\n"},
                {"op": "commit", "message": "mixed change"},
            ],
            REJECT,
            1,
            [IN, OUT2],
            [OUT2],
            "A single escaping path inside an otherwise legitimate commit must fail the whole change.",
        )
    )
    cases.append(
        _git_case(
            "GIT-018",
            "type-change",
            "T",
            "Replace a protected regular file with a symlink.",
            [
                {"op": "delete", "path": OUT},
                {"op": "symlink", "path": OUT, "target": "../workstreams/po03/control/inside.json"},
                {"op": "commit", "message": "typechange protected"},
            ],
            REJECT,
            1,
            [OUT],
            [OUT],
            "Type changes rewrite protected content semantics without editing bytes in place.",
        )
    )
    cases.append(
        _git_case(
            "GIT-019",
            "mode-change",
            "M",
            "Change only the file mode of a protected file.",
            [
                {"op": "chmod", "path": OUT2, "mode": "755"},
                {"op": "commit", "message": "chmod protected"},
            ],
            REJECT,
            1,
            [OUT2],
            [OUT2],
            "A mode-only change is still a mutation of a read-only path.",
        )
    )
    cases.append(
        _git_case(
            "GIT-020",
            "submodule",
            "A",
            "Add an out-of-allowlist gitlink entry.",
            [
                {
                    "op": "gitlink",
                    "path": "modules/vendored",
                    "sha1": "0123456789012345678901234567890123456789",
                },
                {"op": "commit", "message": "add gitlink", "add": False},
            ],
            REJECT,
            1,
            ["modules/vendored"],
            ["modules/vendored"],
            "A submodule pointer outside the allowlist introduces external content into a read-only tree.",
        )
    )
    cases.append(
        _git_case(
            "GIT-021",
            "encoding",
            "A",
            "Add an out-of-allowlist file whose name is not valid UTF-8.",
            [
                {"op": "write_hex", "path_hex": "73746174652f" + "ff" + "2e6a736f6e", "content": "{}\n"},
                {"op": "commit", "message": "add non-utf8 protected path"},
            ],
            REJECT,
            2,
            [],
            [],
            "Undecodable bytes must not silently pass. Exit 2 is an acceptable fail-closed outcome; exit 0 would be a defect.",
        )
    )
    cases.append(
        _git_case(
            "GIT-022",
            "encoding",
            "A",
            "Add an out-of-allowlist file whose name contains a newline.",
            [
                {"op": "write", "path": "state/new\nline.json", "content": "{}\n"},
                {"op": "commit", "message": "add newline protected path"},
            ],
            REJECT,
            1,
            ["state/new\nline.json"],
            ["state/new\nline.json"],
            "Newline in a protected path must not be split into two fragments that both look harmless.",
        )
    )
    cases.append(
        _git_case(
            "GIT-023",
            "history-shape",
            "M",
            "Change a protected file on the base side only, after the fork point.",
            [
                {"op": "tag", "name": "fork"},
                {"op": "branch", "name": "work", "checkout": True},
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":3}\n'},
                {"op": "commit", "message": "work-side legitimate change"},
                {"op": "checkout", "ref": "master"},
                {"op": "write", "path": OUT, "content": '{"seed":"base-side-change"}\n'},
                {"op": "commit", "message": "base-side protected change"},
                {"op": "tag", "name": "base"},
                {"op": "checkout", "ref": "work"},
            ],
            ALLOW,
            0,
            [IN],
            [],
            "With three-dot diff semantics a change made on the base branch is not attributed to this branch. Confirms the guard does not manufacture false positives from divergence.",
        )
    )
    cases.append(
        _git_case(
            "GIT-024",
            "history-shape",
            "M",
            "Merge a branch that changed a protected file, then diff from the pinned base.",
            [
                {"op": "tag", "name": "base"},
                {"op": "branch", "name": "side", "checkout": True},
                {"op": "write", "path": OUT, "content": '{"seed":"side-change"}\n'},
                {"op": "commit", "message": "side protected change"},
                {"op": "checkout", "ref": "master"},
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":4}\n'},
                {"op": "commit", "message": "mainline legitimate change"},
                {"op": "merge", "ref": "side", "message": "merge side"},
            ],
            REJECT,
            1,
            [IN, OUT],
            [OUT],
            "Content merged in from a side branch is present in the head tree and must be attributed.",
        )
    )
    cases.append(
        _git_case(
            "GIT-025",
            "invocation",
            "ERROR",
            "Invoke the guard with the all-zero base SHA that GitHub sends as github.event.before on branch creation.",
            [
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":5}\n'},
                {"op": "commit", "message": "modify inside"},
            ],
            REJECT,
            2,
            [],
            [],
            "The workflow passes github.event.before directly. On branch creation that value is all zeros. Fail-closed exit 2 is correct; exit 0 would be a false green.",
            base="0000000000000000000000000000000000000000",
        )
    )
    cases.append(
        _git_case(
            "GIT-026",
            "invocation",
            "NONE",
            "Run the guard over a range with no changes at all.",
            [{"op": "noop"}],
            ALLOW,
            0,
            [],
            [],
            "An empty change set must pass rather than error.",
        )
    )
    cases.append(
        _git_case(
            "GIT-027",
            "worktree-state",
            "M",
            "Leave an out-of-allowlist modification uncommitted in the working tree.",
            [
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":6}\n'},
                {"op": "commit", "message": "committed legitimate change"},
                {"op": "write", "path": OUT, "content": '{"seed":"uncommitted-tamper"}\n'},
            ],
            ALLOW,
            0,
            [IN],
            [],
            "The guard compares commits, so uncommitted work is out of its remit. Recorded to bound the guard's claim, not as a defect.",
        )
    )
    cases.append(
        _git_case(
            "GIT-028",
            "worktree-state",
            "M",
            "Stage an out-of-allowlist modification without committing it.",
            [
                {"op": "write", "path": IN, "content": '{"seed":"inside","edit":7}\n'},
                {"op": "commit", "message": "committed legitimate change"},
                {"op": "write", "path": OUT, "content": '{"seed":"staged-tamper"}\n'},
                {"op": "stage", "path": OUT},
            ],
            ALLOW,
            0,
            [IN],
            [],
            "Same boundary as GIT-027 for the index rather than the working tree.",
        )
    )
    return cases


def build() -> dict:
    path_cases = []
    for index, (path, family, requirement, predicted, basis, rationale) in enumerate(PATH_CASES, start=1):
        path_cases.append(
            {
                "case_id": f"PP-{index:03d}",
                "family": family,
                "path_display": _display(path),
                "path_hex": _hex(path),
                "commission_requirement": requirement,
                "predicted_guard_disposition": predicted,
                "requirement_basis": basis,
                "rationale": rationale,
            }
        )
    document = {
        "case_set_version": CASE_SET_VERSION,
        "task_id": TASK_ID,
        "decision_changed": [],
        "generator": "tests/generate_cases.py",
        "oracle": "workstreams/po03/COMMISSION.md collision boundary: writable workstreams/po03/**, receipts/po03/**, .github/workflows/po03-*.yml; everything else read-only.",
        "hypothesis_under_test": "The scope guard rejects modified, added, copied, renamed, and deleted out-of-allowlist paths.",
        "safety": "No case mutates this repository. Path cases are pure strings. Git cases run only in throwaway repositories created under a temporary directory and deleted afterwards.",
        "path_case_count": len(path_cases),
        "git_case_count": len(git_cases()),
        "path_cases": path_cases,
        "git_cases": git_cases(),
    }
    return document


def render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "hidden-cases.json"),
    )
    parser.add_argument("--check", action="store_true", help="verify the frozen file matches the generator")
    args = parser.parse_args(argv)
    text = render(build())
    target = Path(args.out)
    if args.check:
        current = target.read_text(encoding="utf-8")
        if current != text:
            print("HIDDEN_CASES_DRIFT: frozen file does not match generator output")
            return 1
        print(f"HIDDEN_CASES_STABLE sha256={hashlib.sha256(text.encode()).hexdigest()}")
        return 0
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} sha256={hashlib.sha256(text.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
