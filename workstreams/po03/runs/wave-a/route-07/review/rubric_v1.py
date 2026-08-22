"""Frozen executable review rubric for PO-03 Wave A independent review (route-07).

Compiled from frozen criteria only: workstreams/po03/evidence/criteria-freeze.json,
workstreams/po03/evidence/source-lock.json, the per-task acceptance contracts,
workstreams/po03/contracts/transactional-result.schema.json and
workstreams/po03/metrics/metric-definitions.json.

This module must be frozen and hashed before any producer conclusion, FINDING
narrative, observed-result prose or route execution receipt is read. It scores a
producer result slot mechanically and never consults producer claims of success.

Standard library only. No network. No writes outside a caller-supplied directory.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

RUBRIC_ID = "PO03-WA-ROUTE07-REVIEW-RUBRIC-v1"

LEGAL_DISPOSITIONS = ("PASS", "FAIL", "NOT_YET", "NOT_SUPPORTED", "OWNER_BLOCKED")
PROHIBITED_SUBORDINATE_TERMINALS = ("COMPLETED", "ACCEPTED")
LEGAL_SUBORDINATE_TERMINAL = "READY_TO_COMMIT"

# Dimensions marked critical gate the recommendation directly: any critical FAIL
# forces RECOMMEND_REJECT regardless of how the remaining dimensions score.
CRITICAL = (
    "R1_EXECUTABLE_UNIT",
    "R2_TESTS_RERUN",
    "R4_MANIFEST_COMPLETE",
    "R5_DISPOSITION_LEGAL",
    "R7_PATH_CONFINEMENT",
    "R8_NO_SELF_ACCEPTANCE",
    "R9_CONTRACT_ECHO",
)
ADVISORY = (
    "R3_COMMANDS_AND_OBSERVED",
    "R6_LIMITATIONS_PRESENT",
    "R10_HYPOTHESIS_EXERCISED",
    "R11_NOT_DUPLICATED",
)
DIMENSIONS = CRITICAL + ADVISORY

MIN_ASSERTIONS = 4
MIN_TEST_FUNCTIONS = 3
MIN_NEGATIVE_CASES = 1
DUPLICATE_SIMILARITY_THRESHOLD = 0.92

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STOPWORDS = frozenset(
    """a an and are as at be by cannot every for from in into is it its no not of on
    or that the their through to with without""".split()
)


@dataclass
class DimensionResult:
    dimension: str
    verdict: str  # PASS | FAIL | NOT_SUPPORTED
    detail: str
    evidence: list = field(default_factory=list)


@dataclass
class SlotReview:
    task_id: str
    slot: str
    frozen_hypothesis: str
    acceptance_contract_sha256: str
    dimensions: list = field(default_factory=list)
    recommendation: str = "RETEST"
    defects: list = field(default_factory=list)
    limitations: list = field(default_factory=list)

    def to_json(self) -> dict:
        out = asdict(self)
        out["dimensions"] = [asdict(d) if not isinstance(d, dict) else d for d in self.dimensions]
        return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - reviewer records the parse failure itself
        return {"__parse_error__": f"{type(exc).__name__}: {exc}"}


def _walk_files(slot: Path) -> list:
    files = []
    for root, dirnames, filenames in os.walk(slot):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            files.append(Path(root) / name)
    return sorted(files)


def _relpath(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _normalized_tokens(source: str) -> list:
    """Identifier/structure token stream used for near-duplicate detection."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return re.findall(r"[A-Za-z_]{3,}", source)
    tokens = []
    for node in ast.walk(tree):
        tokens.append(type(node).__name__)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.append("STR")
    return tokens


def _jaccard(a: list, b: list) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _shingle_ratio(a: list, b: list, width: int = 5) -> float:
    def shingles(seq):
        return {tuple(seq[i : i + width]) for i in range(max(0, len(seq) - width + 1))}

    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


# --------------------------------------------------------------------------- #
# Dimensions
# --------------------------------------------------------------------------- #


def r1_executable_unit(slot: Path, files: list) -> DimensionResult:
    modules = [f for f in files if f.suffix == ".py"]
    if not modules:
        return DimensionResult(
            "R1_EXECUTABLE_UNIT", "FAIL", "slot contains no Python module; prose-only unit"
        )
    parseable, broken = [], []
    for mod in modules:
        try:
            ast.parse(mod.read_text(encoding="utf-8"))
            parseable.append(mod.name)
        except SyntaxError as exc:
            broken.append(f"{mod.name}: {exc}")
    if broken:
        return DimensionResult(
            "R1_EXECUTABLE_UNIT", "FAIL", "module(s) do not parse", broken
        )
    non_test = [m for m in parseable if not m.startswith("test_")]
    if not non_test:
        return DimensionResult(
            "R1_EXECUTABLE_UNIT",
            "FAIL",
            "slot has tests but no component under test",
            parseable,
        )
    return DimensionResult(
        "R1_EXECUTABLE_UNIT", "PASS", f"{len(parseable)} parseable module(s)", parseable
    )


def r2_tests_rerun(slot: Path, files: list, timeout: int = 180) -> DimensionResult:
    tests = [f for f in files if f.suffix == ".py" and f.name.startswith("test_")]
    if not tests:
        return DimensionResult("R2_TESTS_RERUN", "FAIL", "no test_*.py present in slot")
    evidence = []
    failed = False
    for test in tests:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "unittest", "discover", "-s", str(slot), "-p", test.name, "-v"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(slot),
        )
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        evidence.append(
            {
                "test": test.name,
                "returncode": proc.returncode,
                "summary": tail[-1] if tail else "",
                "ran": _unittest_count(proc.stderr or proc.stdout),
            }
        )
        if proc.returncode != 0:
            failed = True
    if failed:
        return DimensionResult("R2_TESTS_RERUN", "FAIL", "reviewer rerun failed", evidence)
    total = sum(e["ran"] for e in evidence)
    if total == 0:
        return DimensionResult(
            "R2_TESTS_RERUN", "FAIL", "test module collected zero tests", evidence
        )
    return DimensionResult(
        "R2_TESTS_RERUN", "PASS", f"{total} test(s) rerun green by reviewer", evidence
    )


def _unittest_count(output: str) -> int:
    m = re.search(r"^Ran (\d+) tests?", output or "", re.MULTILINE)
    return int(m.group(1)) if m else 0


def r3_commands_and_observed(slot: Path, files: list) -> DimensionResult:
    candidates = [
        f
        for f in files
        if f.suffix in (".txt", ".log", ".md", ".json")
        and any(tok in f.as_posix().lower() for tok in ("observed", "evidence", "output", "log"))
    ]
    with_command = []
    for cand in candidates:
        text = cand.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(python3?\s+\S+|python3?\s+-m\s+\S+|\$\s+\S+)", text):
            with_command.append(cand.name)
    if not with_command:
        return DimensionResult(
            "R3_COMMANDS_AND_OBSERVED",
            "FAIL",
            "no durable artifact records an executed command with its observed output",
            [c.name for c in candidates],
        )
    return DimensionResult(
        "R3_COMMANDS_AND_OBSERVED", "PASS", "command + observed output recorded", with_command
    )


def r4_manifest_complete(slot: Path, files: list) -> DimensionResult:
    manifests = [f for f in files if f.name in ("manifest.json", "MANIFEST.json")]
    if not manifests:
        return DimensionResult("R4_MANIFEST_COMPLETE", "FAIL", "slot has no manifest")
    manifest_path = manifests[0]
    doc = _read_json(manifest_path)
    if isinstance(doc, dict) and "__parse_error__" in doc:
        return DimensionResult(
            "R4_MANIFEST_COMPLETE", "FAIL", "manifest is not parseable JSON", [doc["__parse_error__"]]
        )
    entries = _manifest_entries(doc)
    if not entries:
        return DimensionResult(
            "R4_MANIFEST_COMPLETE", "FAIL", "manifest declares no artifact entries"
        )
    defects, checked = [], 0
    listed = set()
    by_rel = {_rel_to_slot(f, slot): f for f in files}
    by_name = {}
    for f in files:
        by_name.setdefault(f.name, []).append(f)
    for entry in entries:
        rel = entry.get("path") or entry.get("content_uri") or entry.get("uri")
        digest = entry.get("sha256")
        size = entry.get("bytes", entry.get("size_bytes"))
        if not rel or not digest:
            defects.append(f"entry missing path or sha256: {entry}")
            continue
        rel = str(rel)
        name = Path(rel).name
        target = by_rel.get(rel)
        if target is None:
            suffix_hits = [f for r, f in by_rel.items() if r == rel or rel.endswith("/" + r)]
            if len(suffix_hits) == 1:
                target = suffix_hits[0]
        if target is None and len(by_name.get(name, [])) == 1:
            target = by_name[name][0]
        if target is None or not target.exists():
            defects.append(f"manifested artifact absent from slot: {rel}")
            continue
        listed.add(target.resolve())
        actual_digest = sha256_file(target)
        actual_bytes = target.stat().st_size
        if not _SHA256_RE.match(str(digest)):
            defects.append(f"malformed sha256 for {rel}: {digest}")
        elif actual_digest != digest:
            defects.append(f"sha256 mismatch for {rel}: manifest={digest} actual={actual_digest}")
        if size is None:
            defects.append(f"no byte count for {rel}")
        elif int(size) != actual_bytes:
            defects.append(f"byte count mismatch for {rel}: manifest={size} actual={actual_bytes}")
        checked += 1
    unlisted = [
        _rel_to_slot(f, slot)
        for f in files
        if f.resolve() not in listed and f.resolve() != manifest_path.resolve()
    ]
    if unlisted:
        defects.append(f"artifacts present but not manifested: {sorted(unlisted)}")
    if defects:
        return DimensionResult("R4_MANIFEST_COMPLETE", "FAIL", "manifest reconciliation failed", defects)
    return DimensionResult(
        "R4_MANIFEST_COMPLETE", "PASS", f"{checked} artifact(s) reconciled by sha256 and bytes"
    )


def _rel_to_slot(path: Path, slot: Path) -> str:
    try:
        return path.relative_to(slot).as_posix()
    except ValueError:
        return path.as_posix()


def _manifest_entries(doc) -> list:
    if isinstance(doc, list):
        return [e for e in doc if isinstance(e, dict)]
    if not isinstance(doc, dict):
        return []
    for key in ("artifacts", "files", "entries", "manifest"):
        value = doc.get(key)
        if isinstance(value, list):
            return [e for e in value if isinstance(e, dict)]
        if isinstance(value, dict):
            return [
                {"path": k, **v} if isinstance(v, dict) else {"path": k, "sha256": v}
                for k, v in value.items()
            ]
    return []


def r5_disposition_legal(slot: Path, files: list) -> DimensionResult:
    found = []
    for f in files:
        if f.suffix not in (".json", ".md", ".txt"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for token in LEGAL_DISPOSITIONS:
            if re.search(rf"\b{token}\b", text):
                found.append((f.name, token))
    dispositions = sorted({t for _, t in found})
    if not dispositions:
        return DimensionResult(
            "R5_DISPOSITION_LEGAL", "FAIL", "no explicit frozen-criteria disposition present"
        )
    illegal = []
    for f in files:
        if f.suffix != ".json":
            continue
        doc = _read_json(f)
        if not isinstance(doc, dict):
            continue
        for key in ("disposition", "outcome", "verdict", "first_pass_outcome"):
            value = doc.get(key)
            if isinstance(value, str) and value not in LEGAL_DISPOSITIONS:
                illegal.append(f"{f.name}:{key}={value}")
    if illegal:
        return DimensionResult(
            "R5_DISPOSITION_LEGAL", "FAIL", "disposition outside the frozen enum", illegal
        )
    return DimensionResult(
        "R5_DISPOSITION_LEGAL", "PASS", f"disposition(s) {dispositions} within frozen enum"
    )


def r6_limitations_present(slot: Path, files: list) -> DimensionResult:
    for f in files:
        if f.suffix not in (".json", ".md", ".txt"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\blimitation", text, re.IGNORECASE):
            doc = _read_json(f) if f.suffix == ".json" else None
            if isinstance(doc, dict):
                value = doc.get("limitations")
                if isinstance(value, list) and not value:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
            return DimensionResult("R6_LIMITATIONS_PRESENT", "PASS", "limitations recorded", [f.name])
    return DimensionResult("R6_LIMITATIONS_PRESENT", "FAIL", "no non-empty limitations statement")


def r7_path_confinement(slot: Path, files: list, owned_prefix: str, repo_root: Path) -> DimensionResult:
    strays = []
    for f in files:
        real = f.resolve()
        try:
            rel = real.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            strays.append(f"{f} escapes the repository root")
            continue
        if not rel.startswith(owned_prefix):
            strays.append(rel)
        if f.is_symlink():
            strays.append(f"symlink indirection: {rel}")
    if strays:
        return DimensionResult("R7_PATH_CONFINEMENT", "FAIL", "artifact outside owned subtree", strays)
    return DimensionResult(
        "R7_PATH_CONFINEMENT", "PASS", f"{len(files)} artifact(s) inside {owned_prefix}"
    )


def r8_no_self_acceptance(slot: Path, files: list) -> DimensionResult:
    defects = []
    seen_state = None
    for f in files:
        if f.suffix != ".json":
            continue
        doc = _read_json(f)
        if not isinstance(doc, dict):
            continue
        acc = doc.get("independent_acceptance")
        if isinstance(acc, dict):
            state = acc.get("state")
            seen_state = state or seen_state
            if state in ("ACCEPTED", "REJECTED"):
                defects.append(f"{f.name}: producer slot asserts terminal acceptance {state}")
            reviewer = acc.get("reviewer_id")
            producer = doc.get("completion_actor") or doc.get("worker_id")
            if reviewer and producer and str(reviewer) == str(producer):
                defects.append(f"{f.name}: reviewer_id equals producer identity {reviewer}")
        elif isinstance(acc, str):
            seen_state = acc
            if acc in ("ACCEPTED", "REJECTED"):
                defects.append(f"{f.name}: producer slot asserts terminal acceptance {acc}")
        for key in ("subordinate_terminal_state", "terminal_state", "report_state"):
            value = doc.get(key)
            if isinstance(value, str) and value in PROHIBITED_SUBORDINATE_TERMINALS:
                defects.append(f"{f.name}:{key}={value} exceeds the subordinate ceiling")
    if defects:
        return DimensionResult("R8_NO_SELF_ACCEPTANCE", "FAIL", "self-acceptance surface", defects)
    return DimensionResult(
        "R8_NO_SELF_ACCEPTANCE",
        "PASS",
        f"no producer self-acceptance (independent_acceptance={seen_state})",
    )


def r9_contract_echo(
    slot: Path, files: list, expected_acceptance_sha: str, expected_manifest_sha: str, task_id: str
) -> DimensionResult:
    defects, echoed = [], []
    for f in files:
        if f.suffix != ".json":
            continue
        doc = _read_json(f)
        if not isinstance(doc, dict):
            continue
        acc = doc.get("acceptance_contract_sha256")
        if acc is not None:
            echoed.append(f.name)
            if acc != expected_acceptance_sha:
                defects.append(
                    f"{f.name}: acceptance_contract_sha256={acc} != frozen {expected_acceptance_sha}"
                )
        man = doc.get("immutable_input_manifest_sha256")
        if man is not None and man != expected_manifest_sha:
            defects.append(
                f"{f.name}: immutable_input_manifest_sha256={man} != frozen {expected_manifest_sha}"
            )
        tid = doc.get("task_id")
        if tid is not None and tid != task_id:
            defects.append(f"{f.name}: task_id={tid} != {task_id}")
    if not echoed:
        return DimensionResult(
            "R9_CONTRACT_ECHO", "FAIL", "no artifact binds the slot to its frozen acceptance contract"
        )
    if defects:
        return DimensionResult("R9_CONTRACT_ECHO", "FAIL", "frozen contract binding broken", defects)
    return DimensionResult("R9_CONTRACT_ECHO", "PASS", "frozen contract hashes echoed", echoed)


def r10_hypothesis_exercised(slot: Path, files: list, hypothesis: str) -> DimensionResult:
    tests = [f for f in files if f.suffix == ".py" and f.name.startswith("test_")]
    if not tests:
        return DimensionResult("R10_HYPOTHESIS_EXERCISED", "FAIL", "no tests to exercise hypothesis")
    assertions = 0
    test_funcs = []
    negative = 0
    corpus = []
    for test in tests:
        src = test.read_text(encoding="utf-8")
        corpus.append(src)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return DimensionResult("R10_HYPOTHESIS_EXERCISED", "FAIL", f"unparseable test {test.name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                test_funcs.append(node.name)
            if isinstance(node, ast.Assert):
                assertions += 1
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.startswith("assert"):
                    assertions += 1
                if node.func.attr in ("assertRaises", "assertRaisesRegex"):
                    negative += 1
            if isinstance(node, ast.withitem):
                pass
        negative += len(re.findall(r"assertRaises|expects?_fail|must_fail|reject|FAIL", src))
    tokens = {t for t in re.findall(r"[a-z]{4,}", hypothesis.lower()) if t not in _STOPWORDS}
    joined = " ".join(corpus).lower()
    covered = sorted(t for t in tokens if t[:6] in joined)
    coverage = len(covered) / len(tokens) if tokens else 0.0
    shortfalls = []
    if assertions < MIN_ASSERTIONS:
        shortfalls.append(f"only {assertions} assertions (< {MIN_ASSERTIONS})")
    if len(test_funcs) < MIN_TEST_FUNCTIONS:
        shortfalls.append(f"only {len(test_funcs)} test functions (< {MIN_TEST_FUNCTIONS})")
    if negative < MIN_NEGATIVE_CASES:
        shortfalls.append("no negative/adversarial case")
    if coverage < 0.34:
        shortfalls.append(f"hypothesis lexical coverage {coverage:.2f} < 0.34 ({covered})")
    if shortfalls:
        return DimensionResult(
            "R10_HYPOTHESIS_EXERCISED", "FAIL", "hypothesis under-exercised", shortfalls
        )
    return DimensionResult(
        "R10_HYPOTHESIS_EXERCISED",
        "PASS",
        f"{assertions} assertions across {len(test_funcs)} tests, coverage {coverage:.2f}",
    )


def r11_not_duplicated(slot: Path, files: list, cohort: dict, task_id: str) -> DimensionResult:
    """cohort maps task_id -> {module_name: source} for every other reviewed slot."""
    mine = {
        f.name: f.read_text(encoding="utf-8")
        for f in files
        if f.suffix == ".py"
    }
    if not mine:
        return DimensionResult("R11_NOT_DUPLICATED", "NOT_SUPPORTED", "no module to compare")
    hits = []
    my_digests = {sha256_bytes(src.encode()) for src in mine.values()}
    for other_id, modules in cohort.items():
        if other_id == task_id:
            continue
        for name, src in modules.items():
            if sha256_bytes(src.encode()) in my_digests:
                hits.append(f"byte-identical to {other_id}/{name}")
                continue
            for my_name, my_src in mine.items():
                a, b = _normalized_tokens(my_src), _normalized_tokens(src)
                ratio = _shingle_ratio(a, b)
                if ratio >= DUPLICATE_SIMILARITY_THRESHOLD and _jaccard(a, b) > 0.9:
                    hits.append(f"{my_name} ~{ratio:.2f} structural overlap with {other_id}/{name}")
    if hits:
        return DimensionResult("R11_NOT_DUPLICATED", "FAIL", "duplicated unit", sorted(set(hits)))
    return DimensionResult("R11_NOT_DUPLICATED", "PASS", f"{len(mine)} module(s) structurally distinct")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


def recommend(dimensions: list) -> str:
    by_name = {d.dimension: d for d in dimensions}
    for name in CRITICAL:
        d = by_name.get(name)
        if d is None or d.verdict == "FAIL":
            return "RECOMMEND_REJECT"
        if d.verdict == "NOT_SUPPORTED":
            return "RETEST"
    for name in ADVISORY:
        d = by_name.get(name)
        if d is not None and d.verdict == "FAIL":
            return "RETEST"
    return "RECOMMEND_ACCEPT"


def review_slot(
    repo_root: Path,
    slot_rel: str,
    task_id: str,
    hypothesis: str,
    acceptance_sha: str,
    manifest_sha: str,
    owned_prefix: str,
    cohort: dict | None = None,
) -> SlotReview:
    slot = repo_root / slot_rel
    review = SlotReview(
        task_id=task_id,
        slot=slot_rel,
        frozen_hypothesis=hypothesis,
        acceptance_contract_sha256=acceptance_sha,
    )
    if not slot.is_dir():
        review.dimensions = [
            DimensionResult(name, "FAIL", "result slot does not exist") for name in DIMENSIONS
        ]
        review.recommendation = "RECOMMEND_REJECT"
        review.defects = [f"missing slot {slot_rel}"]
        return review
    files = _walk_files(slot)
    dims = [
        r1_executable_unit(slot, files),
        r2_tests_rerun(slot, files),
        r4_manifest_complete(slot, files),
        r5_disposition_legal(slot, files),
        r7_path_confinement(slot, files, owned_prefix, repo_root),
        r8_no_self_acceptance(slot, files),
        r9_contract_echo(slot, files, acceptance_sha, manifest_sha, task_id),
        r3_commands_and_observed(slot, files),
        r6_limitations_present(slot, files),
        r10_hypothesis_exercised(slot, files, hypothesis),
        r11_not_duplicated(slot, files, cohort or {}, task_id),
    ]
    review.dimensions = dims
    review.recommendation = recommend(dims)
    review.defects = [f"{d.dimension}: {d.detail}" for d in dims if d.verdict == "FAIL"]
    review.limitations = [
        f"{d.dimension}: {d.detail}" for d in dims if d.verdict == "NOT_SUPPORTED"
    ]
    return review


def rubric_self_hash() -> str:
    return sha256_file(Path(__file__))


if __name__ == "__main__":
    print(json.dumps({"rubric_id": RUBRIC_ID, "sha256": rubric_self_hash()}, indent=2))
