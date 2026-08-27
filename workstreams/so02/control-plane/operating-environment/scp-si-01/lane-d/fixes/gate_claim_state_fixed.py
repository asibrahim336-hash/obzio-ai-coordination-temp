#!/usr/bin/env python3
"""SCP-SI-01 lane D — proposed-fixed mirror of `.cursor/hooks/gate_claim_state.py`.

This file is the shipped hook's logic PLUS the exact two mechanism changes
proposed in `patches/gate_claim_state.py.patch` (DEF-SCP-D-03:
`strong_receipt_health` replaces the `RECEIPT_HINTS` substring search;
DEF-SCP-D-04: `PROJECTION_WORDS` is matched in both word orders — this extra
header comment block is the only textual difference beyond those two). It
exists so the canonical harness (`verify_hooks.py`) can run BOTH the real,
unmodified hook and this corrected mirror against the same fixtures via
subprocess, exactly as `run_gate` already does, without this lane writing to
`.cursor/hooks/` or to `l1-cursor-baseline`'s namespace directly. The patch
file is generated from the unmodified source plus only the two functional
changes, so it applies cleanly against `.cursor/hooks/gate_claim_state.py`
without carrying this note.

--- original docstring below, unchanged ---

stop-hook gate against unsupported completion claims.

This estate's recurring failure is not that work is not done. It is that
proposed, launched, observed, completed and accepted collapse into one word.
A pull request, an archive or an acknowledgement gets recorded as capability.

This gate reads the artifacts the turn actually wrote and refuses to let the
turn end quietly when a terminal claim appears without the evidence that claim
requires. It does not judge the work. It only checks that the claimed state and
the evidence present are the same state.

Contract (https://cursor.com/docs/hooks.md):
  stdin   JSON {"conversation_id","generation_id","model","status","loop_count",...}
  stdout  JSON {"followup_message": str}  - enqueues one more turn
  A stop hook cannot deny. Its lever is the follow-up message, so the gate
  states the discrepancy precisely and lets the agent resolve it.
  `loop_limit` in hooks.json bounds how many times this can re-fire.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Terminal claims that require evidence, mapped to what must accompany them.
TERMINAL_CLAIMS = {
    "COMPLETED": "a receipt manifest with per-file sha256 and a bundle_sha256",
    "ACCEPTED": "an independent acceptance record naming an acceptor who is not the producer",
    "QUALIFIED": "end-to-end route evidence including remote byte-for-byte read-back by immutable SHA",
    "VERIFIED": "the command that was run and the output that was observed",
    "MERGED": "the merge commit SHA on the target branch",
    "DEPLOYED": "the deployment target and a post-deployment observation",
}

# Words that describe a projection, never a capability.
PROJECTION_WORDS = r"(pull request|PR #\d+|\.zip\b|archive|acknowledg|hand ?off|handover)"

RECEIPT_HINTS = ("MANIFEST.json", "EVIDENCE-MANIFEST.json", "bundle_sha256")
SELF_ACCEPT_HINT = re.compile(
    r'"(acceptor|accepted_by)"\s*:\s*"(?!null)', re.IGNORECASE
)

_MANIFEST_BASENAMES = ("MANIFEST.json", "EVIDENCE-MANIFEST.json")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def strong_receipt_health(changed_files: list) -> bool:
    """A receipt is a manifest that parses, covers something, and reads back true.

    EARNED (DEF-SCP-D-03, SCP-SI-01 lane D): `RECEIPT_HINTS` matched a
    substring anywhere in a changed file's NAME OR PROSE BODY, so a note
    saying "see MANIFEST.json" with no such file anywhere in the tree set
    `saw_receipt = True`, and a manifest with `entries: []` and
    `bundle_sha256: "0"*64` (which is not the hash of `[]` and could not be
    the hash of any real entry list) also satisfied it. Both are
    FALSE_SUCCESS: a `COMPLETED` claim certified on shape, not on a read-back
    receipt. This recomputes rather than greps: the manifest must actually
    parse, carry at least one real entry, bind its own bundle_sha256, and at
    least one entry's declared hash must match what the file on disk hashes
    to right now.
    """
    import hashlib as _hashlib
    import json as _json

    for f in changed_files:
        if Path(f).name not in _MANIFEST_BASENAMES:
            continue
        try:
            manifest = _json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, _json.JSONDecodeError):
            continue
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            continue
        if not all(
            isinstance(e, dict) and e.get("path")
            and isinstance(e.get("sha256"), str) and _SHA256_RE.match(e["sha256"])
            for e in entries
        ):
            continue
        recomputed = _hashlib.sha256(
            _json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if manifest.get("bundle_sha256") != recomputed:
            continue
        read_back_confirmed = False
        for entry in entries:
            entry_path = Path(entry["path"])
            if not entry_path.is_file():
                continue
            try:
                actual = _hashlib.sha256(entry_path.read_bytes()).hexdigest()
            except OSError:
                continue
            if actual == entry["sha256"]:
                read_back_confirmed = True
                break
        if read_back_confirmed:
            return True
    return False


def changed_files() -> list:
    """Files this turn added or modified, staged or unstaged, plus untracked."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return []
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in r.stdout.splitlines():
        if len(line) > 3:
            out.append(line[3:].strip().strip('"'))
    return out


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    if payload.get("status") != "completed":
        # An aborted or errored turn is already visibly unfinished.
        sys.exit(0)

    files = changed_files()
    if not files:
        sys.exit(0)

    text_files = [
        f for f in files
        if Path(f).suffix.lower() in {".json", ".md", ".jsonl", ".yml", ".yaml", ".txt"}
        and Path(f).is_file()
    ]

    findings = []
    saw_receipt = False
    claims_found = set()
    projection_hits = []
    self_accept_hits = []

    # EARNED (DEF-SCP-D-03): a receipt is recomputed, never grepped for.
    saw_receipt = strong_receipt_health(files)

    for f in text_files:
        try:
            body = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        upper = body.upper()
        for claim in TERMINAL_CLAIMS:
            if re.search(rf"\b{claim}\b", upper):
                claims_found.add(claim)
        if re.search(PROJECTION_WORDS, body, re.IGNORECASE):
            # EARNED (DEF-SCP-D-04): the original pattern required the
            # completion word to follow the projection phrase, so "COMPLETED
            # ... a pull request" (completion word FIRST) was never matched —
            # the exact word order the hook's own docstring names as the
            # failure to catch. Both orders are searched now.
            completion_words = r"\b(complete|completed|done|delivered|shipped)\b"
            for m in re.finditer(
                rf"{PROJECTION_WORDS}[^.\n]{{0,80}}{completion_words}"
                rf"|{completion_words}[^.\n]{{0,80}}{PROJECTION_WORDS}",
                body, re.IGNORECASE,
            ):
                projection_hits.append(f"{f}: …{m.group(0).strip()}…")
        if SELF_ACCEPT_HINT.search(body):
            self_accept_hits.append(f)

    if ("COMPLETED" in claims_found or "QUALIFIED" in claims_found) and not saw_receipt:
        findings.append(
            "A terminal claim (COMPLETED or QUALIFIED) appears in this turn's artifacts, but no "
            "receipt manifest carrying per-file sha256 and a bundle_sha256 was written. "
            f"Required for that claim: {TERMINAL_CLAIMS['COMPLETED']}."
        )

    if "ACCEPTED" in claims_found and self_accept_hits:
        findings.append(
            "An ACCEPTED claim appears alongside a non-null acceptor field written by this same "
            f"turn ({', '.join(sorted(set(self_accept_hits))[:3])}). A producer cannot record its "
            "own acceptance. Independent acceptance is REQUESTED_NOT_GRANTED until an acceptor "
            "that is not this run issues it."
        )

    if projection_hits:
        findings.append(
            "A projection is described as completion. A pull request, an archive, a handover or an "
            "acknowledgement is a projection of work, never the capability itself:\n  - "
            + "\n  - ".join(projection_hits[:5])
        )

    if not findings:
        sys.exit(0)

    print(json.dumps({
        "followup_message": (
            "STOP GATE — claim state and evidence do not match.\n\n"
            + "\n\n".join(f"{i}. {f}" for i, f in enumerate(findings, 1))
            + "\n\nDo one of two things before finishing, and say which one you did:\n"
              "  (a) supply the missing evidence, or\n"
              "  (b) downgrade the claim to the state the evidence actually supports "
              "(PROPOSED, LAUNCHED, OBSERVED, READY_TO_COMMIT), and say plainly what is "
              "still missing and why.\n\n"
            "Do not restate the claim more confidently. Do not add a note explaining that the "
            "evidence is coming. Change the artifact or change the claim."
        )
    }))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never let the gate wedge a turn
        sys.exit(0)
