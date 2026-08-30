#!/usr/bin/env python3
"""Validate JSONL against the Obzio cross-surface join schema.

Schema (OBZIO-OPERATOR.md, CURRENT STATE), one JSON object per line:
    surface, conv_id, msg_id, role, channel, ts_iso, chars, text

Two measured rules that silently corrupt the join if broken:
  * strip whitespace on ChatGPT-sourced text, but NEVER on Claude-sourced text
  * never drop an empty message -- emit it with chars 0

This checks those, plus the defects that have actually corrupted this corpus before.
Counting only; it does not modify input.

Usage:
    python3 validate_join_schema.py FILE [FILE ...]
    python3 validate_join_schema.py --quiet FILE      # errors only
    cat x.jsonl | python3 validate_join_schema.py -

Exit status: 0 clean (warnings allowed), 1 errors found, 2 could not read input.
Python 3.8+, standard library only.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

FIELDS = ["surface", "conv_id", "msg_id", "role", "channel", "ts_iso", "chars", "text"]
CHANNELS = {"voice", "typed", "image", "unknown"}

# ChatGPT embeds these as invisible citation delimiters. They are real bytes and
# any transcription that drops them changes the file hash. Reported, never an error.
PRIVATE_USE = re.compile("[\\ue000-\\uf8ff]")

ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


class Report:
    def __init__(self, path):
        self.path = path
        self.errors = []
        self.warnings = []
        self.notes = []

    def err(self, line_no, msg):
        self.errors.append((line_no, msg))

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)


def validate(path, lines, rep):
    rows = []
    seen = defaultdict(set)
    surf_counter = Counter()
    chan_counter = Counter()
    role_counter = Counter()
    empties = 0
    pua_rows = 0
    pua_chars = 0
    chatgpt_unstripped = 0
    claude_rows = 0
    claude_already_stripped = 0

    for i, raw in enumerate(lines, 1):
        if raw.endswith("\n"):
            raw = raw[:-1]
        if i == 1 and raw.startswith("\ufeff"):
            rep.err(i, "file begins with a UTF-8 BOM; strip it")
            raw = raw.lstrip("\ufeff")
        if not raw.strip():
            rep.err(i, "blank line (JSONL must have exactly one object per line)")
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            rep.err(i, "not valid JSON: %s" % e.msg)
            continue
        if not isinstance(obj, dict):
            rep.err(i, "line is %s, expected object" % type(obj).__name__)
            continue

        missing = [f for f in FIELDS if f not in obj]
        if missing:
            rep.err(i, "missing field(s): %s" % ", ".join(missing))
            continue
        extra = [k for k in obj if k not in FIELDS]
        if extra:
            rep.warn("line %d: extra field(s) not in join schema: %s"
                     % (i, ", ".join(sorted(extra))))

        surface = obj["surface"]
        text = obj["text"]
        chars = obj["chars"]
        channel = obj["channel"]

        if not isinstance(text, str):
            rep.err(i, "text is %s, expected string" % type(text).__name__)
            continue
        if not isinstance(chars, int) or isinstance(chars, bool):
            rep.err(i, "chars is %r, expected integer" % (chars,))
        elif chars != len(text):
            rep.err(i, "chars=%d but len(text)=%d -- the count must be derived "
                       "from the text, not carried over from the source"
                    % (chars, len(text)))

        if channel not in CHANNELS:
            rep.err(i, "channel=%r not in %s" % (channel, sorted(CHANNELS)))
        chan_counter[channel] += 1
        role_counter[obj["role"]] += 1
        s = surface.lower() if isinstance(surface, str) else surface
        surf_counter[s] += 1

        if not isinstance(obj["ts_iso"], str) or not ISO.match(obj["ts_iso"]):
            if obj["ts_iso"] is not None:
                rep.err(i, "ts_iso=%r is not an ISO-8601 UTC timestamp" % (obj["ts_iso"],))

        key = (obj["conv_id"], obj["msg_id"])
        if obj["msg_id"] in seen[obj["conv_id"]]:
            rep.err(i, "duplicate msg_id %r within conv_id %r"
                    % (obj["msg_id"], obj["conv_id"]))
        seen[obj["conv_id"]].add(obj["msg_id"])

        if chars == 0:
            empties += 1

        n_pua = len(PRIVATE_USE.findall(text))
        if n_pua:
            pua_rows += 1
            pua_chars += n_pua

        # Whitespace rules, per surface.
        if s == "chatgpt":
            if text != text.strip():
                chatgpt_unstripped += 1
        elif s == "claude":
            claude_rows += 1
            if text == text.strip():
                claude_already_stripped += 1

        rows.append(obj)

    n = len(rows)
    if n == 0:
        rep.err(0, "no valid rows")
        return rep

    # --- the defects that have genuinely corrupted this corpus -----------------

    # Zero empty rows is the signature of a parser silently discarding content.
    if empties == 0:
        rep.warn(
            "ZERO rows with chars=0 across %d rows. Empty messages must be emitted "
            "with chars 0, never dropped. Zero of them is the signature of a parser "
            "silently discarding content -- verify against the source before trusting "
            "this file." % n
        )
    else:
        rep.note("empty rows kept: %d of %d (%.1f%%)" % (empties, n, 100.0 * empties / n))

    if chatgpt_unstripped:
        rep.err(0, "%d ChatGPT-sourced row(s) carry leading/trailing whitespace; "
                   "ChatGPT text must be stripped" % chatgpt_unstripped)

    if claude_rows:
        pct = 100.0 * claude_already_stripped / claude_rows
        if claude_already_stripped == claude_rows:
            rep.warn(
                "ALL %d Claude-sourced rows are already whitespace-stripped. Claude text "
                "must NOT be stripped. This is consistent with a blanket strip having been "
                "applied to every surface -- check the extractor before joining." % claude_rows
            )
        else:
            rep.note("Claude rows: %d, of which %d (%.1f%%) happen to have no outer "
                     "whitespace" % (claude_rows, claude_already_stripped, pct))

    if pua_rows:
        rep.note("private-use characters (U+E000-U+F8FF) present in %d row(s), %d "
                 "characters total -- these are real bytes (ChatGPT citation "
                 "delimiters); preserve them" % (pua_rows, pua_chars))
    elif surf_counter.get("chatgpt"):
        rep.warn(
            "NO private-use characters found in %d ChatGPT rows. ChatGPT embeds "
            "U+E200/U+E201/U+E202 around citation markers; their complete absence can "
            "mean content was retyped rather than transferred byte-exactly."
            % surf_counter["chatgpt"]
        )

    # Channel sanity: 'voice' mislabelling shows up as an implausible distribution.
    if chan_counter and "voice" not in chan_counter:
        rep.note("no rows labelled channel=voice in this file")
    unknown = chan_counter.get("unknown", 0)
    if n and unknown / n > 0.90:
        rep.warn("%.0f%% of rows are channel=unknown -- channel derivation may not be "
                 "running" % (100.0 * unknown / n))

    rep.note("rows: %d | surfaces: %s" % (
        n, ", ".join("%s=%d" % kv for kv in sorted(surf_counter.items()))))
    rep.note("channels: %s" % ", ".join("%s=%d" % kv for kv in sorted(chan_counter.items())))
    rep.note("roles: %s" % ", ".join("%s=%d" % kv for kv in sorted(role_counter.items())))
    rep.note("conversations: %d | total chars: %d"
             % (len(seen), sum(r["chars"] for r in rows)))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="JSONL file(s), or - for stdin")
    ap.add_argument("--quiet", action="store_true", help="errors only")
    args = ap.parse_args()

    failed = False
    for path in args.files:
        try:
            if path == "-":
                lines = sys.stdin.readlines()
                shown = "<stdin>"
            else:
                with open(path, "r", encoding="utf-8", newline="") as fh:
                    lines = fh.readlines()
                shown = path
        except OSError as e:
            print("CANNOT READ %s: %s" % (path, e), file=sys.stderr)
            sys.exit(2)

        rep = validate(shown, lines, Report(shown))
        print("=" * 70)
        print(shown)
        print("=" * 70)
        if not args.quiet:
            for m in rep.notes:
                print("  note    %s" % m)
            for m in rep.warnings:
                print("  WARN    %s" % m)
        for line_no, m in rep.errors[:50]:
            print("  ERROR   line %s: %s" % (line_no, m))
        if len(rep.errors) > 50:
            print("  ERROR   ... and %d more" % (len(rep.errors) - 50))
        verdict = "FAIL (%d error(s))" % len(rep.errors) if rep.errors else "PASS"
        if rep.errors:
            failed = True
        print("  -> %s%s" % (verdict,
                             ", %d warning(s)" % len(rep.warnings) if rep.warnings else ""))

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
