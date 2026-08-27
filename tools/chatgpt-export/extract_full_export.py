#!/usr/bin/env python3
"""Full ChatGPT export coverage extractor.

Produces true denominators, authorship separation, a portable founder-message
JSONL, and a delta against a prior authority index -- from a directory of
ChatGPT export archives.

Portable by construction: Python 3.8+ standard library only, no network, no
installation, no host-specific state. Runs identically on macOS, Windows and
Linux so the same command works on the laptop that this repository outlives.

Counting only. This tool does not interpret content.

Usage:
    python3 extract_full_export.py --input DIR --out DIR
        [--authority-index UNIFIED-AUTHORITY-INDEX-928.json]
        [--shard-mb 45] [--echo-min-count 3] [--no-samples]
"""

import argparse
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import traceback
import zipfile
from collections import Counter, defaultdict

TOOL_VERSION = "1.0.0"

# Fingerprint window and threshold are the instrument for every echo number
# reported downstream; changing them changes the denominator's meaning.
FINGERPRINT_CHARS = 600
SHINGLE_CHARS = 120
SHINGLE_STRIDE = 60

MAGIC = [
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip (empty archive)"),
    (b"PK\x07\x08", "zip (spanned)"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
    (b"\xfd7zXZ", "xz"),
    (b"\x04\x22\x4d\x18", "lz4"),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"7z\xbc\xaf\x27\x1c", "7-zip"),
    (b"Rar!\x1a\x07", "rar"),
    (b"SQLite format 3\x00", "sqlite3 database"),
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF8", "gif"),
    (b"OggS", "ogg"),
    (b"fLaC", "flac"),
    (b"ID3", "mp3"),
    (b"\x00\x61\x73\x6d", "wasm"),
    (b"\x7fELF", "elf executable"),
    (b"MZ", "dos/pe executable"),
    (b"!<arch>", "ar archive"),
    (b"ustar", "tar (offset magic)"),
]


def log(msg):
    sys.stderr.write("[extract] %s\n" % msg)
    sys.stderr.flush()


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def iso(epoch):
    if epoch is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(epoch), dt.timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip()


def sha1_hex(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------
# Stage 1: identify every input by content, never by filename
# --------------------------------------------------------------------------

def sniff(path):
    """Return (kind, detail) determined from bytes, not from the extension."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        return "unreadable", str(exc)
    if not head:
        return "empty", "zero bytes"
    for sig, name in MAGIC:
        if head.startswith(sig) or (name.startswith("tar") and sig in head[:512]):
            return name, "magic %s" % binascii.hexlify(sig[:8]).decode()
    stripped = head.lstrip()
    if stripped[:1] in (b"{", b"["):
        return "json", "leading %s" % stripped[:1].decode()
    try:
        head.decode("utf-8")
        return "text", "utf-8 decodable"
    except UnicodeDecodeError:
        return "binary (unidentified)", "no known magic; not utf-8"


def probe_container(path, kind):
    """Confirm a sniffed container really opens, and list what is inside."""
    if kind.startswith("zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                bad = zf.testzip()
                names = zf.namelist()
                return {
                    "opens": True,
                    "entries": len(names),
                    "uncompressed_bytes": sum(i.file_size for i in zf.infolist()),
                    "encrypted": any(i.flag_bits & 0x1 for i in zf.infolist()),
                    "first_corrupt_entry": bad,
                    "sample_names": names[:25],
                }
        except Exception as exc:
            return {"opens": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    if kind in ("gzip", "bzip2", "xz", "tar (offset magic)"):
        try:
            with tarfile.open(path) as tf:
                names = tf.getnames()
                return {"opens": True, "tar": True, "entries": len(names),
                        "sample_names": names[:25]}
        except Exception as exc:
            return {"opens": False, "tar": False,
                    "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"opens": None}


def inventory(input_dir):
    rows = []
    for root, _dirs, files in os.walk(input_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            kind, detail = sniff(path)
            rows.append({
                "path": os.path.relpath(path, input_dir),
                "bytes": os.path.getsize(path),
                "sha256": sha256_file(path),
                "identified_as": kind,
                "identified_by": detail,
                "container": probe_container(path, kind),
            })
    return rows


# --------------------------------------------------------------------------
# Stage 2: extract every archive, recursively, recording exact per-asset errors
# --------------------------------------------------------------------------

def safe_extract_zip(path, dest):
    """Extract without path traversal. Returns (files, errors)."""
    files, errors = [], []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            member = info.filename.replace("\\", "/")
            target = os.path.normpath(os.path.join(dest, member))
            if not target.startswith(os.path.abspath(dest) + os.sep):
                errors.append({"entry": member, "error": "path traversal rejected"})
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                files.append(target)
            except Exception as exc:
                errors.append({"entry": member,
                               "error": "%s: %s" % (type(exc).__name__, exc)})
    return files, errors


def extract_all(inv, input_dir, work_dir, max_depth=4):
    """Recursively extract archives. Each asset gets its own outcome record."""
    results = []
    queue = [(os.path.join(input_dir, r["path"]), r["path"], 0)
             for r in inv if r["identified_as"].startswith("zip")
             or r["container"].get("tar")]
    seen = set()
    while queue:
        path, label, depth = queue.pop(0)
        if path in seen or depth > max_depth:
            continue
        seen.add(path)
        dest = os.path.join(work_dir, re.sub(r"[^A-Za-z0-9._-]", "_", label))
        os.makedirs(dest, exist_ok=True)
        rec = {"archive": label, "depth": depth, "dest": dest}
        try:
            if zipfile.is_zipfile(path):
                files, errors = safe_extract_zip(path, dest)
            else:
                with tarfile.open(path) as tf:
                    tf.extractall(dest)
                files = [os.path.join(dp, f) for dp, _d, fs in os.walk(dest)
                         for f in fs]
                errors = []
            rec.update({"status": "EXTRACTED", "files": len(files),
                        "entry_errors": errors})
            for f in files:
                if zipfile.is_zipfile(f) or f.endswith((".tar", ".tgz", ".tar.gz")):
                    queue.append((f, os.path.relpath(f, work_dir), depth + 1))
        except Exception as exc:
            rec.update({"status": "FAILED",
                        "error": "%s: %s" % (type(exc).__name__, exc),
                        "traceback": traceback.format_exc(limit=3)})
            log("EXTRACT FAILED %s -> %s" % (label, exc))
        results.append(rec)
    return results


# --------------------------------------------------------------------------
# Stage 3: stream conversations.json without loading it whole
# --------------------------------------------------------------------------

def stream_json_array(path, chunk_size=1 << 22, compact_at=1 << 23):
    """Yield each top-level element of a JSON array one at a time.

    A full ChatGPT export decompresses to a conversations.json far larger than
    the archive; json.load on it is the out-of-memory failure this avoids.
    """
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        buf = fh.read(chunk_size)
        pos = 0
        while pos < len(buf) and buf[pos].isspace():
            pos += 1
        if pos >= len(buf) or buf[pos] != "[":
            fh.seek(0)
            root = json.load(fh)
            for item in (root if isinstance(root, list) else [root]):
                yield item
            return
        pos += 1
        while True:
            while True:
                while pos < len(buf) and (buf[pos].isspace() or buf[pos] == ","):
                    pos += 1
                if pos < len(buf):
                    break
                more = fh.read(chunk_size)
                if not more:
                    return
                buf += more
            if buf[pos] == "]":
                return
            while True:
                try:
                    obj, pos = decoder.raw_decode(buf, pos)
                    break
                except ValueError:
                    more = fh.read(chunk_size)
                    if not more:
                        raise
                    buf += more
            yield obj
            if pos > compact_at:
                buf = buf[pos:]
                pos = 0


def find_conversation_files(roots):
    """Locate conversation payloads by structure, not by filename alone."""
    hits = []
    for root in roots:
        if os.path.isfile(root):
            candidates = [root]
        else:
            candidates = [os.path.join(dp, f) for dp, _d, fs in os.walk(root)
                          for f in fs if f.lower().endswith(".json")]
        for path in candidates:
            try:
                if os.path.getsize(path) < 2:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    head = fh.read(65536)
            except OSError:
                continue
            if '"mapping"' in head and ('"author"' in head or '"create_time"' in head):
                hits.append(path)
    return sorted(set(hits))


def extract_text(content):
    """Return (text, content_type, unextractable) for one message payload."""
    if not isinstance(content, dict):
        return "", None, bool(content)
    ctype = content.get("content_type")
    if ctype in ("text", "multimodal_text"):
        parts = content.get("parts") or []
        return ("\n".join(p for p in parts if isinstance(p, str)), ctype, False)
    if ctype in ("code", "execution_output", "thoughts", "reasoning_recap",
                 "tether_quote", "tether_browsing_display", "system_error"):
        return (content.get("text") or "", ctype, False)
    if ctype == "user_editable_context":
        joined = "\n".join(str(content.get(k) or "")
                           for k in ("user_profile", "user_instructions"))
        return joined, ctype, False
    parts = content.get("parts")
    if isinstance(parts, list):
        return ("\n".join(p for p in parts if isinstance(p, str)), ctype, False)
    if isinstance(content.get("text"), str):
        return content["text"], ctype, False
    return "", ctype, True


class Corpus:
    """Accumulates every counted fact. Each attribute is one denominator."""

    def __init__(self):
        self.winner = {}                 # conv_id -> (nodes, source, ordinal)
        self.conversations = {}          # conv_id -> record of the winning copy
        self.conv_sources = defaultdict(set)
        self.duplicate_conversations = 0
        self.total_nodes = 0
        self.message_nodes = 0
        self.role_counts = Counter()
        self.content_type_counts = Counter()
        self.unextractable = 0
        self.user_records = []           # candidate founder-authored messages
        self.user_envelope_total = 0
        self.user_system_context = 0
        self.user_empty = 0
        self.user_hidden = 0
        self.timestamps = []
        self.parse_errors = []

    @staticmethod
    def conv_key(conv):
        mapping = conv.get("mapping") or {}
        cid = conv.get("conversation_id") or conv.get("id")
        if cid is None:
            cid = "unidentified:" + sha1_hex(
                json.dumps(mapping, sort_keys=True)[:4000])
        return cid, mapping

    def index_pass(self, conv, source, ordinal):
        """First pass: choose one winning copy per conversation id.

        The same conversation appears in more than one archive; scanning both
        would inflate every node and message count downstream.
        """
        cid, mapping = self.conv_key(conv)
        self.conv_sources[cid].add(source)
        prior = self.winner.get(cid)
        if prior is None:
            self.winner[cid] = (len(mapping), source, ordinal)
            return
        self.duplicate_conversations += 1
        if len(mapping) > prior[0]:
            self.winner[cid] = (len(mapping), source, ordinal)

    def is_winner(self, conv, source, ordinal):
        cid, _mapping = self.conv_key(conv)
        return self.winner.get(cid) == (len(conv.get("mapping") or {}),
                                        source, ordinal)

    def scan_conversation(self, conv, source):
        cid, mapping = self.conv_key(conv)
        title = conv.get("title")
        self.conversations[cid] = {
            "title": title,
            "create_time": conv.get("create_time"),
            "update_time": conv.get("update_time"),
            "nodes": len(mapping),
            "source": source,
            "is_archived": conv.get("is_archived"),
            "default_model_slug": conv.get("default_model_slug"),
        }
        for node_id, node in mapping.items():
            self.total_nodes += 1
            if not isinstance(node, dict):
                continue
            msg = node.get("message")
            if not isinstance(msg, dict):
                continue
            self.message_nodes += 1
            role = ((msg.get("author") or {}).get("role")) or "unknown"
            self.role_counts[role] += 1
            text, ctype, bad = extract_text(msg.get("content"))
            self.content_type_counts[ctype or "none"] += 1
            if bad:
                self.unextractable += 1
            ts = msg.get("create_time") or conv.get("create_time")
            if ts:
                self.timestamps.append(ts)
            if role != "user":
                continue
            self.user_envelope_total += 1
            meta = msg.get("metadata") or {}
            if meta.get("is_user_system_message") or ctype == "user_editable_context":
                self.user_system_context += 1
                continue
            if meta.get("is_visually_hidden_from_conversation"):
                self.user_hidden += 1
                continue
            norm = normalise(text)
            if not norm:
                self.user_empty += 1
                continue
            self.user_records.append({
                "conversation_id": cid,
                "conversation_title": title,
                "node_id": node_id,
                "timestamp": ts,
                "timestamp_iso": iso(ts),
                "char_count": len(text),
                "content_type": ctype,
                "source_archive": source,
                "fingerprint": sha1_hex(norm[:FINGERPRINT_CHARS]),
                "norm_len": len(norm),
                "text": text,
            })


# --------------------------------------------------------------------------
# Stage 4: authorship separation by template fingerprint
# --------------------------------------------------------------------------

def classify_echo(records, min_count, long_floor=200):
    """Flag fingerprints recurring >= min_count. Returns (counts, families).

    long_floor gives a second, stricter reading over messages long enough that
    recurrence cannot be explained by short conversational filler.
    """
    freq = Counter(r["fingerprint"] for r in records)
    echo_fps = {fp for fp, n in freq.items() if n >= min_count}
    long_freq = Counter(r["fingerprint"] for r in records
                        if r["norm_len"] >= long_floor)
    long_echo_fps = {fp for fp, n in long_freq.items() if n >= min_count}
    for r in records:
        r["echo"] = r["fingerprint"] in echo_fps
        r["echo_strict"] = (r["fingerprint"] in long_echo_fps
                            and r["norm_len"] >= long_floor)
    families = sorted(
        ({"fingerprint": fp, "occurrences": n,
          "example_prefix": next(x["text"][:180] for x in records
                                 if x["fingerprint"] == fp)}
         for fp, n in freq.items() if fp in echo_fps),
        key=lambda d: -d["occurrences"])
    return freq, families


# --------------------------------------------------------------------------
# Stage 5: generic profiler for never-before-read JSON (memories, projects)
# --------------------------------------------------------------------------

def profile_json(obj, samples=True, max_depth=6):
    """Describe an unknown JSON document's shape without assuming a schema."""
    paths = Counter()
    types = defaultdict(Counter)
    examples = {}

    def walk(node, path, depth):
        t = type(node).__name__
        paths[path] += 1
        types[path][t] += 1
        if depth >= max_depth:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, "%s.%s" % (path, k) if path else k, depth + 1)
        elif isinstance(node, list):
            for item in node[:200]:
                walk(item, path + "[]", depth + 1)
        elif samples and path not in examples and isinstance(node, str) and node:
            examples[path] = node[:160]

    walk(obj, "", 0)
    return {
        "root_type": type(obj).__name__,
        "root_len": len(obj) if isinstance(obj, (list, dict)) else None,
        "key_paths": [{"path": p, "count": n,
                       "types": dict(types[p]),
                       "sample": examples.get(p)}
                      for p, n in paths.most_common(120) if p],
    }


def profile_non_conversation_files(work_dir, conversation_files, samples):
    out = []
    skip = set(conversation_files)
    for dp, _d, fs in os.walk(work_dir):
        for f in fs:
            path = os.path.join(dp, f)
            if path in skip or not f.lower().endswith(".json"):
                continue
            size = os.path.getsize(path)
            rec = {"path": os.path.relpath(path, work_dir), "bytes": size,
                   "sha256": sha256_file(path)}
            try:
                if size > (256 << 20):
                    rec["status"] = "SKIPPED_TOO_LARGE_FOR_PROFILER"
                else:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        rec["profile"] = profile_json(json.load(fh), samples)
                    rec["status"] = "PROFILED"
            except Exception as exc:
                rec["status"] = "FAILED"
                rec["error"] = "%s: %s" % (type(exc).__name__, exc)
            out.append(rec)
    return sorted(out, key=lambda r: r["path"])


# --------------------------------------------------------------------------
# Stage 6: portable sharded JSONL
# --------------------------------------------------------------------------

def write_jsonl_shards(records, out_dir, stem, shard_bytes):
    os.makedirs(out_dir, exist_ok=True)
    shards, idx, written, fh, path = [], 1, 0, None, None

    def open_shard(n):
        p = os.path.join(out_dir, "%s.%03d.jsonl" % (stem, n))
        return open(p, "w", encoding="utf-8"), p

    for rec in sorted(records, key=lambda r: (r["timestamp"] or 0, r["node_id"])):
        line = json.dumps({
            "conversation_id": rec["conversation_id"],
            "conversation_title": rec["conversation_title"],
            "node_id": rec["node_id"],
            "timestamp": rec["timestamp"],
            "timestamp_iso": rec["timestamp_iso"],
            "char_count": rec["char_count"],
            "content_type": rec["content_type"],
            "source_archive": rec["source_archive"],
            "fingerprint": rec["fingerprint"],
            "text": rec["text"],
        }, ensure_ascii=False) + "\n"
        blob = line.encode("utf-8")
        if fh is None or (written + len(blob) > shard_bytes and written > 0):
            if fh:
                fh.close()
                shards.append(path)
                idx += 1
            fh, path = open_shard(idx)
            written = 0
        fh.write(line)
        written += len(blob)
    if fh:
        fh.close()
        shards.append(path)
    return [{"file": os.path.basename(p), "bytes": os.path.getsize(p),
             "sha256": sha256_file(p),
             "lines": sum(1 for _ in open(p, encoding="utf-8"))} for p in shards]


# --------------------------------------------------------------------------
# Stage 7: delta against the prior authority index
# --------------------------------------------------------------------------

UUIDISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                     r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


DEAD_STATUSES = {"SUPERSEDED", "REVOKED", "RETIRED", "DEAD", "WITHDRAWN"}


def shingles(norm_text, stride=SHINGLE_STRIDE):
    """Hash every `stride`-th window of `SHINGLE_CHARS` characters.

    The index side is shingled densely (stride 1) and the corpus side at
    stride %d, so any overlap of at least %d contiguous normalised characters
    is detected regardless of where an index excerpt starts.
    """
    if len(norm_text) < SHINGLE_CHARS:
        return {sha1_hex(norm_text)[:16]} if norm_text else set()
    return {sha1_hex(norm_text[i:i + SHINGLE_CHARS])[:16]
            for i in range(0, len(norm_text) - SHINGLE_CHARS + 1, stride)}


shingles.__doc__ = shingles.__doc__ % (SHINGLE_STRIDE, SHINGLE_CHARS + SHINGLE_STRIDE)


def harvest_index(index_obj):
    """Collect ids and content shingles from an authority index of unknown shape.

    Every act's `status` and `superseded` fields are read before its content is
    admitted, and superseded content is kept in a separate bucket. A
    content-only query would otherwise report dead authority as live coverage
    (R13).
    """
    live, dead, ids = set(), set(), set()
    statuses = Counter()
    acts = 0

    def is_act(node):
        keys = {k.lower() for k in node}
        return bool(keys & {"act_id", "id", "act"}) and bool(
            keys & {"status", "text", "quote", "content", "superseded",
                    "utterance", "statement"})

    def walk(node, dead_ctx):
        nonlocal acts
        if isinstance(node, dict):
            if is_act(node):
                acts += 1
                status = str(node.get("status", "")).strip().upper() or "UNSPECIFIED"
                statuses[status] += 1
                sup = node.get("superseded")
                dead_ctx = (dead_ctx or status in DEAD_STATUSES
                            or bool(sup) and sup not in (False, "", "none", "None"))
            for k, v in node.items():
                if isinstance(v, str):
                    lk = k.lower()
                    if ("conversation" in lk or "node" in lk or "message" in lk
                            or lk in ("id", "source_id", "src_id")):
                        ids.add(v)
                    ids.update(UUIDISH.findall(v))
                    if len(v) >= 40:
                        (dead if dead_ctx else live).update(
                            shingles(normalise(v), stride=1))
                else:
                    walk(v, dead_ctx)
        elif isinstance(node, list):
            for item in node:
                walk(item, dead_ctx)
        elif isinstance(node, str):
            ids.update(UUIDISH.findall(node))
            if len(node) >= 40:
                (dead if dead_ctx else live).update(
                    shingles(normalise(node), stride=1))

    walk(index_obj, False)
    return {"ids": ids, "live": live, "dead": dead, "acts": acts,
            "statuses": dict(statuses)}


def compute_delta(corpus, founder_records, index_paths):
    if not index_paths:
        return {"status": "NOT_RUN", "reason": "no authority index supplied"}
    ids, live, dead = set(), set(), set()
    acts = 0
    statuses = Counter()
    loaded = []
    for p in index_paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                h = harvest_index(json.load(fh))
            ids |= h["ids"]
            live |= h["live"]
            dead |= h["dead"]
            acts += h["acts"]
            statuses.update(h["statuses"])
            loaded.append({"file": os.path.basename(p), "bytes": os.path.getsize(p),
                           "sha256": sha256_file(p), "acts_detected": h["acts"],
                           "statuses": h["statuses"]})
        except Exception as exc:
            loaded.append({"file": os.path.basename(p), "status": "FAILED",
                           "error": "%s: %s" % (type(exc).__name__, exc)})

    conv_ids = set(corpus.conversations)
    conv_referenced = {c for c in conv_ids if c in ids}
    covered_live = covered_dead_only = absent_msgs = 0
    absent_chars = 0
    absent_by_month = Counter()
    absent_conv = set()
    for r in founder_records:
        sh = shingles(normalise(r["text"]))
        if sh & live:
            covered_live += 1
        elif sh & dead:
            covered_dead_only += 1
        else:
            absent_msgs += 1
            absent_chars += r["char_count"]
            absent_conv.add(r["conversation_id"])
            if r["timestamp_iso"]:
                absent_by_month[r["timestamp_iso"][:7]] += 1
    total = len(founder_records)
    pct = lambda n: round(100.0 * n / total, 2) if total else None
    return {
        "status": "COMPUTED",
        "indexes_loaded": loaded,
        "acts_detected_total": acts,
        "act_status_breakdown": dict(statuses),
        "instrument": (
            "conversation-level = id string match. content-level = %d-char "
            "shingle, index side dense (stride 1), corpus side stride %d, so "
            "an overlap of >= %d contiguous whitespace-normalised characters "
            "is detected. Superseded acts are harvested into a separate bucket "
            "and never counted as live coverage."
            % (SHINGLE_CHARS, SHINGLE_STRIDE, SHINGLE_CHARS + SHINGLE_STRIDE)),
        "conversation_denominator": len(conv_ids),
        "conversations_referenced_by_index": len(conv_referenced),
        "conversations_absent_from_index": len(conv_ids) - len(conv_referenced),
        "founder_message_denominator": total,
        "founder_messages_covered_by_live_acts": covered_live,
        "founder_messages_covered_only_by_superseded_acts": covered_dead_only,
        "founder_messages_absent_from_index": absent_msgs,
        "founder_messages_absent_pct": pct(absent_msgs),
        "founder_messages_not_covered_by_live_authority": absent_msgs + covered_dead_only,
        "founder_messages_not_covered_by_live_authority_pct": pct(absent_msgs + covered_dead_only),
        "absent_characters": absent_chars,
        "conversations_containing_absent_messages": len(absent_conv),
        "absent_messages_by_month": dict(sorted(absent_by_month.items())),
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def render_report(m):
    L = []
    A = L.append
    one_line = lambda s: re.sub(r"\s+", " ", str(s or "")).strip()
    A("# FULL-EXPORT COVERAGE REPORT")
    A("")
    A("Generated %s by `extract_full_export.py` v%s (Python %s)."
      % (m["generated_utc"], m["tool_version"], m["python_version"]))
    A("Counting and structure only. No interpretation of content.")
    A("")
    A("Every number below states the instrument and the population it was")
    A("counted against. A number without its denominator is not a result.")
    A("")

    A("## 1. Asset inventory (identified by content, not filename)")
    A("")
    A("| Asset | Bytes | Identified as | Opens | Entries | Uncompressed |")
    A("|---|---:|---|---|---:|---:|")
    for r in m["inventory"]:
        c = r["container"]
        A("| `%s` | %s | %s | %s | %s | %s |" % (
            r["path"], f'{r["bytes"]:,}', r["identified_as"],
            c.get("opens"), c.get("entries", ""),
            f'{c["uncompressed_bytes"]:,}' if c.get("uncompressed_bytes") else ""))
    A("")
    A("Denominator: %d files walked under the input directory."
      % len(m["inventory"]))
    A("")

    A("## 2. Extraction outcome per archive")
    A("")
    for r in m["extraction"]:
        if r["status"] == "EXTRACTED":
            A("- `%s` (depth %d): **EXTRACTED**, %d files, %d entry errors."
              % (r["archive"], r["depth"], r["files"], len(r["entry_errors"])))
            for e in r["entry_errors"][:10]:
                A("  - entry `%s`: %s" % (e["entry"], one_line(e["error"])))
        else:
            A("- `%s` (depth %d): **FAILED** -- `%s`"
              % (r["archive"], r["depth"], one_line(r.get("error"))))
    A("")

    d = m["denominators"]
    A("## 3. TRUE denominators")
    A("")
    A("| Measure | Count | Instrument |")
    A("|---|---:|---|")
    A("| Conversation payload files parsed | %s | files containing `mapping` + `author`/`create_time` |" % f'{d["conversation_files"]:,}')
    A("| Distinct conversations | %s | deduplicated on `conversation_id`/`id`, richest copy kept |" % f'{d["conversations"]:,}')
    A("| Duplicate conversation copies discarded | %s | same id seen in more than one payload |" % f'{d["duplicate_copies"]:,}')
    A("| Total mapping nodes | %s | every key in every `mapping` |" % f'{d["total_nodes"]:,}')
    A("| Message-bearing nodes | %s | nodes whose `message` is an object |" % f'{d["message_nodes"]:,}')
    A("| User-role envelope messages | %s | `author.role == \"user\"` |" % f'{d["user_envelope"]:,}')
    A("| Date range | %s -> %s | min/max `create_time`, UTC |" % (d["earliest"], d["latest"]))
    A("")
    A("Messages by author role, denominator %s message-bearing nodes:"
      % f'{d["message_nodes"]:,}')
    A("")
    for role, n in sorted(m["role_counts"].items(), key=lambda kv: -kv[1]):
        A("- `%s`: %s" % (role, f"{n:,}"))
    A("")

    a = m["authorship"]
    A("## 4. Authorship separation")
    A("")
    A("`author.role == \"user\"` is an envelope, not authorship. The user-role")
    A("envelope is reduced to an addressable population before echo detection:")
    A("")
    A("| Step | Count | Basis |")
    A("|---|---:|---|")
    A("| User-role envelope | %s | denominator for this section |" % f'{a["envelope"]:,}')
    A("| less system-context injections | %s | `metadata.is_user_system_message` or `content_type == user_editable_context` |" % f'{a["system_context"]:,}')
    A("| less hidden-from-conversation | %s | `metadata.is_visually_hidden_from_conversation` |" % f'{a["hidden"]:,}')
    A("| less empty after normalisation | %s | whitespace-only text |" % f'{a["empty"]:,}')
    A("| **= addressable user messages** | **%s** | **denominator for echo share** |" % f'{a["addressable"]:,}')
    A("")
    A("Fingerprint instrument: whitespace-normalised, first %d characters, "
      "SHA-1, flagged at >= %d recurrences."
      % (FINGERPRINT_CHARS, a["echo_min_count"]))
    A("")
    A("| Class | Count | Share of addressable |")
    A("|---|---:|---:|")
    A("| Template echo | %s | %s%% |" % (f'{a["echo"]:,}', a["echo_pct"]))
    A("| Founder-authored | %s | %s%% |" % (f'{a["founder"]:,}', a["founder_pct"]))
    A("")
    A("Sensitivity reading, same threshold but only messages >= 200 normalised")
    A("characters, so recurrence cannot be short conversational filler:")
    A("echo %s (%s%% of addressable), founder-authored %s."
      % (f'{a["echo_strict"]:,}', a["echo_strict_pct"], f'{a["founder_strict"]:,}'))
    A("")
    A("Top recurring template families, denominator %s addressable messages:"
      % f'{a["addressable"]:,}')
    A("")
    for fam in m["echo_families"][:15]:
        A("- %d occurrences -- `%s`"
          % (fam["occurrences"], fam["example_prefix"].replace("`", "'")[:150]))
    if not m["echo_families"]:
        A("- none: no fingerprint reached the threshold.")
    A("")

    A("## 5. memories and projects, and every other non-conversation JSON")
    A("")
    for r in m["other_json"]:
        A("### `%s`" % r["path"])
        A("")
        A("%s bytes, sha256 `%s`, status %s."
          % (f'{r["bytes"]:,}', r["sha256"][:16] + "...", r["status"]))
        if r.get("error"):
            A("")
            A("Error: `%s`" % one_line(r["error"]))
        p = r.get("profile")
        if p:
            A("")
            A("Root `%s`%s."
              % (p["root_type"],
                 " with %d entries" % p["root_len"] if p["root_len"] is not None else ""))
            if p["key_paths"]:
                A("")
                A("| Path | Occurrences | Types | Sample |")
                A("|---|---:|---|---|")
                for kp in p["key_paths"][:40]:
                    sample = one_line(kp["sample"]).replace("|", "\\|")
                    A("| `%s` | %d | %s | %s |"
                      % (kp["path"], kp["count"], ",".join(kp["types"]), sample))
            else:
                A("")
                A("No key paths: the document is empty.")
        A("")
    if not m["other_json"]:
        A("No non-conversation JSON files were present in the extracted set.")
        A("")

    A("## 6. Portable artefact")
    A("")
    A("`FOUNDER-MESSAGES-FULL.*.jsonl` -- one JSON object per line, one line per")
    A("founder-authored message. Fields: `conversation_id`, `conversation_title`,")
    A("`node_id`, `timestamp`, `timestamp_iso`, `char_count`, `content_type`,")
    A("`source_archive`, `fingerprint`, `text`. Sorted by timestamp. No")
    A("dependency on any host, account or runtime.")
    A("")
    A("| Shard | Lines | Bytes | SHA-256 |")
    A("|---|---:|---:|---|")
    for s in m["shards"]:
        A("| `%s` | %s | %s | `%s` |"
          % (s["file"], f'{s["lines"]:,}', f'{s["bytes"]:,}', s["sha256"][:16] + "..."))
    A("")
    A("Total %s lines across %d shards; denominator is the %s founder-authored"
      % (f'{sum(s["lines"] for s in m["shards"]):,}', len(m["shards"]),
         f'{a["founder"]:,}'))
    A("messages counted in section 4. Messages classified as echo are written")
    A("separately to `ECHO-MESSAGES.*.jsonl` so the split stays auditable and")
    A("reversible; nothing counted is discarded.")
    A("")

    A("## 7. Delta against the prior authority index")
    A("")
    dl = m["delta"]
    if dl["status"] != "COMPUTED":
        A("**NOT RUN** -- %s. Re-run with `--authority-index` to quantify this."
          % dl["reason"])
    else:
        A("Instrument: %s" % dl["instrument"])
        A("")
        for li in dl["indexes_loaded"]:
            A("- `%s`: %s bytes, %s acts detected, statuses %s"
              % (li.get("file"), f'{li.get("bytes", 0):,}',
                 li.get("acts_detected", "?"), li.get("statuses", {})))
        A("")
        A("| Measure | Count | Denominator |")
        A("|---|---:|---|")
        A("| Conversations absent from index | %s | %s conversations in full export |"
          % (f'{dl["conversations_absent_from_index"]:,}',
             f'{dl["conversation_denominator"]:,}'))
        A("| Founder messages covered by a live act | %s | %s founder-authored messages |"
          % (f'{dl["founder_messages_covered_by_live_acts"]:,}',
             f'{dl["founder_message_denominator"]:,}'))
        A("| Founder messages covered ONLY by a superseded act | %s | same |"
          % f'{dl["founder_messages_covered_only_by_superseded_acts"]:,}')
        A("| Founder messages absent from index entirely | %s | same |"
          % f'{dl["founder_messages_absent_from_index"]:,}')
        A("| Characters absent | %s | sum over absent messages |"
          % f'{dl["absent_characters"]:,}')
        A("")
        A("**%s%%** of founder-authored messages have no content match in the"
          % dl["founder_messages_absent_pct"])
        A("supplied index. Counting messages whose only match is a superseded act")
        A("as uncovered live authority raises that to **%s%%**."
          % dl["founder_messages_not_covered_by_live_authority_pct"])
        A("")
        A("Act status was read before content was admitted: an act marked")
        A("SUPERSEDED, or carrying a `superseded` value, is harvested into a")
        A("separate bucket and never counted as live coverage. Status")
        A("breakdown across %d detected acts: %s."
          % (dl["acts_detected_total"], dl["act_status_breakdown"]))
        A("")
        A("Absent messages by month:")
        A("")
        for mo, n in dl["absent_messages_by_month"].items():
            A("- %s: %s" % (mo, f"{n:,}"))
    A("")

    A("## 8. Named blockers")
    A("")
    if m["blockers"]:
        for b in m["blockers"]:
            A("- **%s** -- `%s`" % (b["asset"], one_line(b["error"])))
    else:
        A("None. Every supplied asset opened and parsed.")
    A("")
    return "\n".join(L)


# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="directory holding the export assets")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--authority-index", action="append", default=[],
                    help="prior authority index JSON (repeatable)")
    ap.add_argument("--shard-mb", type=float, default=45.0)
    ap.add_argument("--echo-min-count", type=int, default=3)
    ap.add_argument("--no-samples", action="store_true",
                    help="omit sample values from the JSON profiler")
    ap.add_argument("--keep-extracted", action="store_true")
    args = ap.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    work_dir = os.path.join(out_dir, "_extracted")
    os.makedirs(work_dir, exist_ok=True)
    blockers = []

    log("stage 1/7 inventory")
    inv = inventory(os.path.abspath(args.input))
    for r in inv:
        c = r["container"]
        if c.get("opens") is False:
            blockers.append({"asset": r["path"], "error": c.get("error")})

    log("stage 2/7 extract (%d assets)" % len(inv))
    extraction = extract_all(inv, os.path.abspath(args.input), work_dir)
    for r in extraction:
        if r["status"] == "FAILED":
            blockers.append({"asset": r["archive"], "error": r.get("error")})

    log("stage 3/7 locate and stream conversations")
    conv_files = find_conversation_files([work_dir, os.path.abspath(args.input)])
    corpus = Corpus()

    def label_for(path):
        base = out_dir if path.startswith(out_dir) else os.path.abspath(args.input)
        return os.path.relpath(path, base)

    for scan in (False, True):
        for path in conv_files:
            label = label_for(path)
            try:
                for ordinal, conv in enumerate(stream_json_array(path)):
                    if not isinstance(conv, dict):
                        continue
                    if not scan:
                        corpus.index_pass(conv, label, ordinal)
                    elif corpus.is_winner(conv, label, ordinal):
                        corpus.scan_conversation(conv, label)
            except Exception as exc:
                err = "%s: %s" % (type(exc).__name__, exc)
                if not scan:
                    corpus.parse_errors.append({"file": label, "error": err})
                    blockers.append({"asset": label, "error": err})
                    log("PARSE FAILED %s -> %s" % (label, err))

    log("stage 4/7 authorship separation (%d addressable)" % len(corpus.user_records))
    _freq, families = classify_echo(corpus.user_records, args.echo_min_count)
    founder = [r for r in corpus.user_records if not r["echo"]]
    echo = [r for r in corpus.user_records if r["echo"]]
    addressable = len(corpus.user_records)
    strict_echo = sum(1 for r in corpus.user_records if r["echo_strict"])

    log("stage 5/7 profile memories/projects and other JSON")
    other_json = profile_non_conversation_files(work_dir, conv_files,
                                                not args.no_samples)

    log("stage 6/7 write portable JSONL")
    shard_bytes = int(args.shard_mb * 1000 * 1000)
    shards = write_jsonl_shards(founder, out_dir, "FOUNDER-MESSAGES-FULL", shard_bytes)
    echo_shards = write_jsonl_shards(echo, out_dir, "ECHO-MESSAGES", shard_bytes)

    log("stage 7/7 delta against authority index")
    delta = compute_delta(corpus, founder, args.authority_index)

    seen_assets = set()
    deduped = []
    for b in blockers:
        if b["asset"] not in seen_assets:
            seen_assets.add(b["asset"])
            deduped.append(b)
    blockers = deduped

    ts = [t for t in corpus.timestamps if t]
    metrics = {
        "tool_version": TOOL_VERSION,
        "python_version": sys.version.split()[0],
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "input_dir": os.path.abspath(args.input),
        "inventory": inv,
        "extraction": extraction,
        "conversation_files": [os.path.relpath(p, out_dir) if p.startswith(out_dir)
                               else p for p in conv_files],
        "denominators": {
            "conversation_files": len(conv_files),
            "conversations": len(corpus.conversations),
            "duplicate_copies": corpus.duplicate_conversations,
            "total_nodes": corpus.total_nodes,
            "message_nodes": corpus.message_nodes,
            "user_envelope": corpus.user_envelope_total,
            "earliest": iso(min(ts)) if ts else None,
            "latest": iso(max(ts)) if ts else None,
        },
        "role_counts": dict(corpus.role_counts),
        "content_type_counts": dict(corpus.content_type_counts),
        "unextractable_content_payloads": corpus.unextractable,
        "authorship": {
            "envelope": corpus.user_envelope_total,
            "system_context": corpus.user_system_context,
            "hidden": corpus.user_hidden,
            "empty": corpus.user_empty,
            "addressable": addressable,
            "echo_min_count": args.echo_min_count,
            "fingerprint_chars": FINGERPRINT_CHARS,
            "echo": len(echo),
            "founder": len(founder),
            "echo_pct": round(100.0 * len(echo) / addressable, 2) if addressable else None,
            "founder_pct": round(100.0 * len(founder) / addressable, 2) if addressable else None,
            "echo_strict": strict_echo,
            "founder_strict": addressable - strict_echo,
            "echo_strict_pct": round(100.0 * strict_echo / addressable, 2) if addressable else None,
        },
        "echo_families": families,
        "other_json": other_json,
        "shards": shards,
        "echo_shards": echo_shards,
        "delta": delta,
        "parse_errors": corpus.parse_errors,
        "blockers": blockers,
    }

    with open(os.path.join(out_dir, "coverage-metrics.json"), "w",
              encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, ensure_ascii=False)
    report_path = os.path.join(out_dir, "FULL-EXPORT-COVERAGE-REPORT.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(render_report(metrics))

    manifest = {"generated_utc": metrics["generated_utc"],
                "tool_version": TOOL_VERSION, "outputs": []}
    for name in sorted(os.listdir(out_dir)):
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            manifest["outputs"].append({"file": name, "bytes": os.path.getsize(p),
                                        "sha256": sha256_file(p)})
    with open(os.path.join(out_dir, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    if not args.keep_extracted:
        shutil.rmtree(work_dir, ignore_errors=True)

    log("done -> %s" % report_path)
    print(json.dumps({
        "conversations": len(corpus.conversations),
        "message_nodes": corpus.message_nodes,
        "user_envelope": corpus.user_envelope_total,
        "addressable": addressable,
        "echo": len(echo),
        "founder_authored": len(founder),
        "shards": len(shards),
        "blockers": len(blockers),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
