"""Randomised tamper generator and detection campaign for the custody ledger.

The campaign is the executable form of the a1-u01 hypothesis.  It builds clean
ledgers, snapshots their exact bytes, and then for each trial restores the
snapshot, applies one *semantically effective* tamper operation and asks the
verifier for a ruling.  Restoring between trials matters: compounded tamper
operations would let one easily-detected class mask another.

Two obligations are measured separately, because passing one and failing the
other is worthless:

detection
    every applied tamper operation must be reported, and the campaign records
    which finding code caught it so a class cannot be "detected" by an
    unrelated accident;
false positives
    untampered ledgers, including ones re-encoded with different key order and
    indentation, must verify clean.

Operations that would not actually change the stored bytes are discarded rather
than counted, so the mutation total is a count of real tampering.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .canonical import atomic_write_json, canonical, sha256_bytes
from .ledger import (
    ALL_EVENT_KINDS,
    GENESIS_HASH,
    HashChainedLedger,
    Verification,
    row_digest,
)

TAMPER_CLASSES = (
    "MUTATE_FIELD",
    "MUTATE_AND_REHASH_ROW",
    "REWRITE_SUFFIX",
    "TRUNCATE_TAIL",
    "DELETE_MIDDLE_ROW",
    "SWAP_ROWS",
    "DUPLICATE_ROW",
    "INSERT_FORGED_ROW",
    "APPEND_FORGED_ROW",
    "CORRUPT_BYTE",
    "MUTATE_PREV_HASH",
    "MUTATE_ROW_HASH",
    "MUTATE_SEQ",
    "TRUNCATE_LINE",
    "REORDER_TAIL",
    "WIPE_LEDGER",
    "ANCHOR_ROLLBACK",
    "ANCHOR_HEAD_FORGE",
    "ANCHOR_DELETE",
)

# Classes whose outcome space is large enough to keep producing new distinct
# tampered artifacts.  ``WIPE_LEDGER`` and ``ANCHOR_DELETE`` have exactly one
# outcome per fixture, so they are exercised to the per-class floor and then
# retired rather than padded with repeats.
HIGH_VARIETY_CLASSES = tuple(name for name in TAMPER_CLASSES if name not in ("WIPE_LEDGER", "ANCHOR_DELETE"))

_MUTABLE_FIELDS = ("unit_id", "event", "actor", "ts", "fence_token", "obzio_state", "provider_state", "payload")
_EVENTS = tuple(sorted(ALL_EVENT_KINDS))


@dataclass
class Snapshot:
    """The exact bytes of a clean ledger and its sealed anchor."""

    ledger_bytes: bytes
    anchor_bytes: bytes | None
    row_count: int

    def restore(self, ledger: HashChainedLedger) -> None:
        ledger.path.parent.mkdir(parents=True, exist_ok=True)
        ledger.path.write_bytes(self.ledger_bytes)
        if self.anchor_bytes is None:
            ledger.anchor_path.unlink(missing_ok=True)
        else:
            ledger.anchor_path.write_bytes(self.anchor_bytes)


@dataclass
class TamperOp:
    tamper_class: str
    signature: str
    detail: dict[str, Any]


@dataclass
class Trial:
    tamper_class: str
    signature: str
    detected: bool
    codes: tuple[str, ...]


@dataclass
class CampaignResult:
    mutations_applied: int = 0
    distinct_signatures: int = 0
    detected: int = 0
    missed: list[dict[str, Any]] = field(default_factory=list)
    clean_ledgers_checked: int = 0
    false_positives: list[dict[str, Any]] = field(default_factory=list)
    per_class: dict[str, dict[str, Any]] = field(default_factory=dict)
    discarded_ineffective: int = 0

    @property
    def ok(self) -> bool:
        return (
            self.mutations_applied > 0
            and self.detected == self.mutations_applied
            and not self.missed
            and not self.false_positives
            and all(stats["applied"] > 0 for stats in self.per_class.values())
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mutations_applied": self.mutations_applied,
            "distinct_signatures": self.distinct_signatures,
            "detected": self.detected,
            "detection_rate": (self.detected / self.mutations_applied) if self.mutations_applied else 0.0,
            "missed": self.missed,
            "clean_ledgers_checked": self.clean_ledgers_checked,
            "false_positives": self.false_positives,
            "discarded_ineffective_operations": self.discarded_ineffective,
            "per_class": self.per_class,
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# Clean ledger construction
# ---------------------------------------------------------------------------


def build_clean_ledger(ledger: HashChainedLedger, row_count: int, rng: random.Random) -> None:
    for index in range(row_count):
        ledger.append(
            f"unit-{rng.randrange(4):02d}",
            rng.choice(_EVENTS),
            actor=rng.choice(("coordinator", "po03-worker-a1", "po03-worker-a6")),
            provider_state=rng.choice((None, "QUEUED", "RUNNING", "COMPLETED")),
            fence_token=rng.choice((None, 1, 2, 3)),
            payload={"i": index, "note": f"row-{index}", "nested": {"k": rng.randrange(1000)}},
            ts=f"2026-08-22T0{rng.randrange(6, 10)}:{index % 60:02d}:{rng.randrange(60):02d}Z",
        )


def snapshot(ledger: HashChainedLedger) -> Snapshot:
    rows, _ = ledger.read_rows()
    return Snapshot(
        ledger_bytes=ledger.path.read_bytes() if ledger.path.exists() else b"",
        anchor_bytes=ledger.anchor_path.read_bytes() if ledger.anchor_path.exists() else None,
        row_count=len(rows),
    )


# ---------------------------------------------------------------------------
# Tamper operations
# ---------------------------------------------------------------------------


def _lines(ledger: HashChainedLedger) -> list[str]:
    text = ledger.path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def _write_lines(ledger: HashChainedLedger, lines: list[str]) -> None:
    ledger.path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _rows_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines]


def _rechain(rows: list[dict[str, Any]], start: int) -> None:
    """Recompute seq, prev and row digests from ``start`` onwards.

    This is the *strong* adversary: the resulting file is a perfectly valid
    hash chain.  Only the sealed anchor can rule on it.
    """
    previous = rows[start - 1]["row_sha256"] if start > 0 else GENESIS_HASH
    for index in range(start, len(rows)):
        rows[index]["seq"] = index + 1
        rows[index]["prev_sha256"] = previous
        rows[index]["row_sha256"] = row_digest(rows[index])
        previous = rows[index]["row_sha256"]


def _mutate_field(row: dict[str, Any], name: str, rng: random.Random) -> Any:
    current = row.get(name)
    if name == "event":
        new = rng.choice([event for event in _EVENTS if event != current])
    elif name == "fence_token":
        candidates = [value for value in (None, 1, 2, 3, 99) if value != current]
        new = rng.choice(candidates)
    elif name == "payload":
        new = dict(current or {})
        new["tampered_key"] = rng.randrange(10**6)
    elif name in ("provider_state", "obzio_state"):
        candidates = [value for value in (None, "QUEUED", "RUNNING", "COMPLETED", "FAILED") if value != current]
        new = rng.choice(candidates)
    else:
        new = f"tampered-{rng.randrange(10**6)}"
        while new == current:
            new = f"tampered-{rng.randrange(10**6)}"
    row[name] = new
    return new


def _apply(ledger: HashChainedLedger, tamper_class: str, rng: random.Random) -> TamperOp | None:
    """Apply one tamper operation, or return ``None`` when inapplicable."""
    lines = _lines(ledger)
    count = len(lines)
    anchor = ledger.read_anchor()

    if tamper_class == "MUTATE_FIELD":
        if not count:
            return None
        index = rng.randrange(count)
        rows = _rows_from_lines(lines)
        name = rng.choice(_MUTABLE_FIELDS)
        value = _mutate_field(rows[index], name, rng)
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}:{name}", {"row": index, "field": name, "value": value})

    if tamper_class == "MUTATE_AND_REHASH_ROW":
        if not count:
            return None
        index = rng.randrange(count)
        rows = _rows_from_lines(lines)
        name = rng.choice(_MUTABLE_FIELDS)
        _mutate_field(rows[index], name, rng)
        rows[index]["row_sha256"] = row_digest(rows[index])
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}:{name}", {"row": index, "field": name})

    if tamper_class == "REWRITE_SUFFIX":
        if not count:
            return None
        index = rng.randrange(count)
        rows = _rows_from_lines(lines)
        name = rng.choice(_MUTABLE_FIELDS)
        _mutate_field(rows[index], name, rng)
        _rechain(rows, index)
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}:{name}", {"row": index, "field": name})

    if tamper_class == "TRUNCATE_TAIL":
        if count < 1:
            return None
        dropped = rng.randrange(1, count + 1)
        _write_lines(ledger, lines[: count - dropped])
        return TamperOp(tamper_class, f"{tamper_class}:{count}:{dropped}", {"dropped": dropped, "from": count})

    if tamper_class == "DELETE_MIDDLE_ROW":
        if count < 3:
            return None
        index = rng.randrange(0, count - 1)
        _write_lines(ledger, lines[:index] + lines[index + 1 :])
        return TamperOp(tamper_class, f"{tamper_class}:{index}", {"row": index})

    if tamper_class == "SWAP_ROWS":
        if count < 2:
            return None
        first, second = sorted(rng.sample(range(count), 2))
        reordered = list(lines)
        reordered[first], reordered[second] = reordered[second], reordered[first]
        _write_lines(ledger, reordered)
        return TamperOp(tamper_class, f"{tamper_class}:{first}:{second}", {"a": first, "b": second})

    if tamper_class == "DUPLICATE_ROW":
        if not count:
            return None
        index = rng.randrange(count)
        _write_lines(ledger, lines[: index + 1] + [lines[index]] + lines[index + 1 :])
        return TamperOp(tamper_class, f"{tamper_class}:{index}", {"row": index})

    if tamper_class == "INSERT_FORGED_ROW":
        if count < 2:
            return None
        index = rng.randrange(1, count)
        rows = _rows_from_lines(lines)
        forged = dict(rows[index])
        forged["payload"] = {"forged": True, "nonce": rng.randrange(10**6)}
        forged["prev_sha256"] = rows[index - 1]["row_sha256"]
        forged["seq"] = index + 1
        forged["row_sha256"] = row_digest(forged)
        rows.insert(index, forged)
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}", {"row": index})

    if tamper_class == "APPEND_FORGED_ROW":
        if not count:
            return None
        added = rng.randrange(1, 4)
        rows = _rows_from_lines(lines)
        for offset in range(added):
            forged = {
                "seq": len(rows) + 1,
                "ts": "2026-08-22T09:59:59Z",
                "unit_id": "unit-forged",
                "event": "COMPLETED",
                "obzio_state": "COMPLETED",
                "provider_state": "COMPLETED",
                "actor": "coordinator",
                "fence_token": 1,
                "payload": {"forged": True, "offset": offset, "nonce": rng.randrange(10**6)},
                "prev_sha256": rows[-1]["row_sha256"] if rows else GENESIS_HASH,
            }
            forged["row_sha256"] = row_digest(forged)
            rows.append(forged)
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{count}:{added}", {"added": added})

    if tamper_class == "CORRUPT_BYTE":
        if not count:
            return None
        index = rng.randrange(count)
        raw = lines[index].encode("utf-8")
        offset = rng.randrange(len(raw))
        bit = 1 << rng.randrange(8)
        corrupted = bytearray(raw)
        corrupted[offset] ^= bit
        mutated = list(lines)
        mutated[index] = corrupted.decode("utf-8", errors="surrogateescape")
        payload = "".join(line + "\n" for line in mutated).encode("utf-8", errors="surrogateescape")
        ledger.path.write_bytes(payload)
        return TamperOp(
            tamper_class,
            f"{tamper_class}:{index}:{offset}:{bit}",
            {"row": index, "offset": offset, "bit": bit},
        )

    if tamper_class in ("MUTATE_PREV_HASH", "MUTATE_ROW_HASH"):
        if not count:
            return None
        index = rng.randrange(count)
        field_name = "prev_sha256" if tamper_class == "MUTATE_PREV_HASH" else "row_sha256"
        rows = _rows_from_lines(lines)
        rows[index][field_name] = sha256_bytes(str(rng.randrange(10**9)).encode("utf-8"))
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}", {"row": index})

    if tamper_class == "MUTATE_SEQ":
        if not count:
            return None
        index = rng.randrange(count)
        rows = _rows_from_lines(lines)
        rows[index]["seq"] = rows[index]["seq"] + rng.choice((-1, 1, 7, 100))
        _write_lines(ledger, [canonical(row) for row in rows])
        return TamperOp(tamper_class, f"{tamper_class}:{index}", {"row": index})

    if tamper_class == "TRUNCATE_LINE":
        if not count:
            return None
        index = rng.randrange(count)
        raw = lines[index]
        if len(raw) < 4:
            return None
        cut = rng.randrange(1, len(raw) - 1)
        mutated = list(lines)
        mutated[index] = raw[:cut]
        _write_lines(ledger, mutated)
        return TamperOp(tamper_class, f"{tamper_class}:{index}:{cut}", {"row": index, "cut": cut})

    if tamper_class == "REORDER_TAIL":
        if count < 3:
            return None
        size = rng.randrange(2, min(count, 6) + 1)
        mutated = lines[: count - size] + list(reversed(lines[count - size :]))
        _write_lines(ledger, mutated)
        return TamperOp(tamper_class, f"{tamper_class}:{count}:{size}", {"tail": size})

    if tamper_class == "WIPE_LEDGER":
        if not count:
            return None
        ledger.path.write_bytes(b"")
        return TamperOp(tamper_class, f"{tamper_class}:{count}", {"rows_removed": count})

    if tamper_class == "ANCHOR_ROLLBACK":
        if count < 2 or not anchor or "committed_seq" not in anchor:
            return None
        rows = _rows_from_lines(lines)
        target = rng.randrange(1, count)
        atomic_write_json(
            ledger.anchor_path,
            {
                **anchor,
                "committed_seq": target,
                "committed_head": rows[target - 1]["row_sha256"],
                "pending_seq": None,
            },
        )
        return TamperOp(tamper_class, f"{tamper_class}:{target}", {"rolled_back_to": target})

    if tamper_class == "ANCHOR_HEAD_FORGE":
        if not count or not anchor or "committed_head" not in anchor:
            return None
        forged_head = sha256_bytes(str(rng.randrange(10**9)).encode("utf-8"))
        atomic_write_json(ledger.anchor_path, {**anchor, "committed_head": forged_head})
        return TamperOp(tamper_class, f"{tamper_class}:{forged_head[:16]}", {"forged_head": forged_head})

    if tamper_class == "ANCHOR_DELETE":
        if not count or not ledger.anchor_path.exists():
            return None
        ledger.anchor_path.unlink()
        return TamperOp(tamper_class, f"{tamper_class}:{count}", {"rows": count})

    raise ValueError(f"unknown tamper class: {tamper_class}")


def apply_tamper(ledger: HashChainedLedger, tamper_class: str, rng: random.Random) -> TamperOp | None:
    """Apply a tamper operation and confirm it actually changed stored bytes."""
    before = (
        ledger.path.read_bytes() if ledger.path.exists() else b"",
        ledger.anchor_path.read_bytes() if ledger.anchor_path.exists() else None,
    )
    op = _apply(ledger, tamper_class, rng)
    if op is None:
        return None
    after = (
        ledger.path.read_bytes() if ledger.path.exists() else b"",
        ledger.anchor_path.read_bytes() if ledger.anchor_path.exists() else None,
    )
    if before == after:
        return None
    return op


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


def reencode_benignly(ledger: HashChainedLedger, rng: random.Random) -> None:
    """Rewrite every row with different key order and spacing.

    Semantics are untouched, so a verifier that keys on meaning rather than
    bytes must still pass.  Including this in the false-positive set makes the
    zero-false-positive claim meaningful instead of trivial.
    """
    rows = _rows_from_lines(_lines(ledger))
    lines = []
    for row in rows:
        items = list(row.items())
        rng.shuffle(items)
        lines.append(json.dumps(dict(items), separators=(", ", ": ")))
    _write_lines(ledger, lines)


def run_campaign(
    workdir: Path,
    *,
    mutations: int = 1200,
    distinct_target: int = 1000,
    min_per_class: int = 25,
    clean_ledgers: int = 12,
    seed: int = 20260822,
    verifier: Callable[[HashChainedLedger], Verification] | None = None,
) -> CampaignResult:
    """Run the full detection and false-positive campaign under ``workdir``."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    verify = verifier or (lambda ledger: ledger.verify())
    result = CampaignResult()
    result.per_class = {name: {"applied": 0, "detected": 0, "codes": {}} for name in TAMPER_CLASSES}

    # False-positive control: untampered ledgers of assorted shapes, including
    # an empty one and benignly re-encoded copies, must all verify clean.
    fixtures: list[tuple[HashChainedLedger, Snapshot]] = []
    sizes = [0, 1, 2, 3, 5, 8, 13, 21] + [rng.randrange(4, 30) for _ in range(max(0, clean_ledgers - 8))]
    for index, size in enumerate(sizes[:clean_ledgers] if clean_ledgers else []):
        ledger = HashChainedLedger(workdir / f"clean-{index:02d}.jsonl", verify_on_append=False)
        build_clean_ledger(ledger, size, rng)
        verification = verify(ledger)
        result.clean_ledgers_checked += 1
        if not verification.ok:
            result.false_positives.append(
                {"ledger": ledger.path.name, "rows": size, "findings": verification.as_dict()["findings"]}
            )
        if size:
            reencoded = HashChainedLedger(workdir / f"reencoded-{index:02d}.jsonl", verify_on_append=False)
            reencoded.path.write_bytes(ledger.path.read_bytes())
            reencoded.anchor_path.write_bytes(ledger.anchor_path.read_bytes())
            reencode_benignly(reencoded, rng)
            reencoded_verification = verify(reencoded)
            result.clean_ledgers_checked += 1
            if not reencoded_verification.ok:
                result.false_positives.append(
                    {
                        "ledger": reencoded.path.name,
                        "rows": size,
                        "note": "benign re-encoding, semantics unchanged",
                        "findings": reencoded_verification.as_dict()["findings"],
                    }
                )
        if size >= 3:
            fixtures.append((ledger, snapshot(ledger)))

    if not fixtures:
        raise ValueError("campaign needs at least one clean ledger of three or more rows")

    signatures: set[str] = set()
    trials: list[Trial] = []
    attempts = 0
    max_attempts = max(mutations, distinct_target) * 60
    floor_trials = min_per_class * len(TAMPER_CLASSES)
    while attempts < max_attempts:
        if len(trials) >= mutations and len(signatures) >= distinct_target and len(trials) >= floor_trials:
            break
        attempts += 1
        ledger, snap = fixtures[rng.randrange(len(fixtures))]
        if len(trials) < floor_trials:
            tamper_class = TAMPER_CLASSES[len(trials) % len(TAMPER_CLASSES)]
        else:
            tamper_class = HIGH_VARIETY_CLASSES[len(trials) % len(HIGH_VARIETY_CLASSES)]
        snap.restore(ledger)
        op = apply_tamper(ledger, tamper_class, rng)
        if op is None:
            result.discarded_ineffective += 1
            snap.restore(ledger)
            continue
        verification = verify(ledger)
        detected = not verification.ok
        codes = verification.tamper_codes
        # A tamper operation counts as distinct when it leaves a distinct
        # tampered artifact pair, not merely a distinct random draw.
        signature = sha256_bytes(
            ledger.path.name.encode("utf-8")
            + b"\x00"
            + (ledger.path.read_bytes() if ledger.path.exists() else b"")
            + b"\x00"
            + (ledger.anchor_path.read_bytes() if ledger.anchor_path.exists() else b"<absent>")
        )
        trials.append(Trial(tamper_class, signature, detected, codes))
        signatures.add(signature)
        stats = result.per_class[tamper_class]
        stats["applied"] += 1
        stats.setdefault("signatures", set()).add(signature)
        if detected:
            stats["detected"] += 1
            for code in codes:
                stats["codes"][code] = stats["codes"].get(code, 0) + 1
        else:
            result.missed.append(
                {
                    "tamper_class": tamper_class,
                    "signature": signature,
                    "detail": op.detail,
                    "ledger": ledger.path.name,
                    "verification": verification.as_dict(),
                }
            )
        snap.restore(ledger)

    result.mutations_applied = len(trials)
    result.detected = sum(1 for trial in trials if trial.detected)
    result.distinct_signatures = len(signatures)
    for stats in result.per_class.values():
        stats["distinct"] = len(stats.pop("signatures", set()))
    return result
