#!/usr/bin/env python3
"""Verify the extractor against a fixture whose counts were derived by hand.

Every expected value below is a literal worked out from the fixture's
construction, not a value produced by the extractor. A test that asserted the
tool agrees with itself would prove nothing (R4, R7).

Run:  python3 test_extract_full_export.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import make_test_fixture as fixture  # noqa: E402

# Hand-derived from make_test_fixture.py. See the table in RUN-ON-LAPTOP.md.
EXPECTED = {
    "input_files": 7,
    "conversations": 7,
    "duplicate_copies": 2,
    "total_nodes": 20,
    "message_nodes": 19,
    "user_envelope": 11,
    "earliest": "2026-06-10T00:00:00+00:00",
    "latest": "2026-08-23T00:00:00+00:00",
    "roles": {"user": 11, "assistant": 7, "system": 1},
    "system_context": 1,
    "hidden": 1,
    "empty": 1,
    "addressable": 8,
    "echo": 3,
    "founder": 5,
    "echo_strict": 3,
    "profiled_json": 4,
    "blocker_assets": ["broken-archive.zip"],
    "delta_conversations_absent": 6,
    "delta_covered_live": 1,
    "delta_covered_superseded_only": 1,
    "delta_absent": 3,
}

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%-52s got %r  want %r" % (label, got, want))
        print("  FAIL %-50s got %r want %r" % (label, got, want))
    else:
        print("  ok   %-50s %r" % (label, got))


def run(tmp):
    inp, index = fixture.build(os.path.join(tmp, "fx"))
    out = os.path.join(tmp, "out")
    cmd = [sys.executable, os.path.join(HERE, "extract_full_export.py"),
           "--input", inp, "--out", out, "--authority-index", index,
           "--keep-extracted"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("extractor exited %d" % proc.returncode)
    with open(os.path.join(out, "coverage-metrics.json"), encoding="utf-8") as fh:
        return out, json.load(fh)


def edge_cases(tmp):
    """Shapes a real export contains that the main fixture does not.

    A parser that only ever meets well-formed input will meet these on the
    laptop instead, where there is no chance to iterate.
    """
    inp = os.path.join(tmp, "edge", "input")
    os.makedirs(inp)

    def m(role, text, ctype="text"):
        content = {"content_type": ctype}
        if ctype == "multimodal_text":
            content["parts"] = [text, {"content_type": "image_asset_pointer",
                                       "asset_pointer": "file-service://x"}]
        else:
            content["parts"] = [text]
        return {"id": "m", "author": {"role": role}, "create_time": 1781049600,
                "content": content, "metadata": {}}

    def n(message):
        return {"id": "x", "message": message, "parent": None, "children": []}

    # A conversations.json whose root is an object rather than an array.
    with zipfile.ZipFile(os.path.join(inp, "dictroot.zip"), "w") as zf:
        zf.writestr("conversations.json", json.dumps({
            "conversation_id": "dict-root-1", "title": "dict root",
            "create_time": 1781049600,
            "mapping": {"a": n(m("user", "root-is-a-dict payload"))}}))

    # Null mapping, absent id, multimodal parts, and malformed nodes.
    with zipfile.ZipFile(os.path.join(inp, "weird.zip"), "w") as zf:
        zf.writestr("conversations.json", json.dumps([
            {"conversation_id": "null-map", "mapping": None,
             "create_time": 1781049600},
            {"title": "no id at all", "create_time": 1781049600,
             "mapping": {"z": n(m("user", "message in a conversation with no id"))}},
            {"conversation_id": "multimodal", "create_time": 1781049600,
             "mapping": {"q": n(m("user", "image plus text",
                                  ctype="multimodal_text"))}},
            {"conversation_id": "badnode", "create_time": 1781049600,
             "mapping": {"b1": "not-a-dict", "b2": n(None),
                         "b3": n(m("user", "ok after bad nodes"))}},
        ]))
        zf.writestr("chat.html", "<html><body>" + "x" * 5000 + "</body></html>")
        zf.writestr("truncated.json", '{"broken": ')
        zf.writestr("subdir/nested/deep.json", '{"deep": true}')

    with zipfile.ZipFile(os.path.join(inp, "empty-convs.zip"), "w") as zf:
        zf.writestr("conversations.json", "[]")

    # zipfile cannot write encrypted archives; skip this case where the zip
    # CLI is absent rather than fail for a reason unrelated to the extractor.
    plain = os.path.join(tmp, "edge", "plain.zip")
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("secret.json", '{"a":1}')
    encrypted = os.path.join(inp, "encrypted.zip")
    if shutil.which("zip"):
        subprocess.run(["zip", "-q", "-P", "hunter2", encrypted, plain],
                       check=False)

    # The hash-named Drive object may not be an archive at all.
    with open(os.path.join(inp, "9c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60718293"),
              "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)

    out = os.path.join(tmp, "edge", "out")
    proc = subprocess.run([sys.executable,
                           os.path.join(HERE, "extract_full_export.py"),
                           "--input", inp, "--out", out],
                          capture_output=True, text=True)
    check("survives every malformed input", proc.returncode, 0)
    with open(os.path.join(out, "coverage-metrics.json"), encoding="utf-8") as fh:
        m2 = json.load(fh)

    hashed = [r for r in m2["inventory"] if r["path"].startswith("9c1d")][0]
    check("non-archive identified by offset magic", hashed["identified_as"],
          "mp4/mov/m4a container")
    check("object-rooted conversations.json parsed",
          m2["denominators"]["conversations"] >= 5, True)
    check("malformed nodes skipped without loss",
          m2["authorship"]["addressable"], 4)
    blocked = {b["asset"] for b in m2["blockers"]}
    if os.path.exists(encrypted):
        check("encrypted archive named as a blocker",
              any("encrypted" in b for b in blocked), True)
    else:
        print("  skip encrypted-archive case: no zip CLI on this host")
    check("unparseable json named as a blocker",
          any("truncated.json" in b for b in blocked), True)
    lines = []
    for s in m2["shards"]:
        with open(os.path.join(out, s["file"]), encoding="utf-8") as fh:
            lines += [json.loads(x) for x in fh if x.strip()]
    texts = {x["text"] for x in lines}
    check("multimodal text part recovered", "image plus text" in texts, True)
    check("message recovered after malformed sibling nodes",
          "ok after bad nodes" in texts, True)
    check("conversation with no id still gets a stable key",
          any(str(x["conversation_id"]).startswith("unidentified:")
              for x in lines), True)


def main():
    tmp = tempfile.mkdtemp(prefix="export-verify-")
    try:
        # Guard the fixture's own preconditions before trusting any assertion.
        assert len(fixture.LONG_UNIQUE) >= 350, "excerpt window too short"
        assert len(fixture.SUPERSEDED_TEXT) >= 350, "excerpt window too short"
        assert len(fixture.ECHO_TEMPLATE) >= 600, "template shorter than fingerprint"

        out, m = run(tmp)
        d, a, dl = m["denominators"], m["authorship"], m["delta"]

        print("\n-- identification --")
        check("input files inventoried", len(m["inventory"]), EXPECTED["input_files"])
        hashed = [r for r in m["inventory"] if r["path"].startswith("1f7c9e")][0]
        check("hash-named file identified by bytes", hashed["identified_as"], "zip")
        check("hash-named file opens", hashed["container"]["opens"], True)

        print("\n-- extraction --")
        failed = [r for r in m["extraction"] if r["status"] == "FAILED"]
        check("archives that failed to open", len(failed), 1)
        check("named blockers", [b["asset"] for b in m["blockers"]],
              EXPECTED["blocker_assets"])
        check("nested archive was reached",
              any(r["depth"] == 1 for r in m["extraction"]), True)

        print("\n-- true denominators --")
        check("distinct conversations", d["conversations"], EXPECTED["conversations"])
        check("duplicate copies discarded", d["duplicate_copies"],
              EXPECTED["duplicate_copies"])
        check("total mapping nodes", d["total_nodes"], EXPECTED["total_nodes"])
        check("message-bearing nodes", d["message_nodes"], EXPECTED["message_nodes"])
        check("user-role envelope", d["user_envelope"], EXPECTED["user_envelope"])
        check("earliest create_time", d["earliest"], EXPECTED["earliest"])
        check("latest create_time", d["latest"], EXPECTED["latest"])
        check("role counts", m["role_counts"], EXPECTED["roles"])

        print("\n-- authorship separation --")
        check("system-context injections", a["system_context"], EXPECTED["system_context"])
        check("hidden user nodes", a["hidden"], EXPECTED["hidden"])
        check("empty user nodes", a["empty"], EXPECTED["empty"])
        check("addressable user messages", a["addressable"], EXPECTED["addressable"])
        check("template echo", a["echo"], EXPECTED["echo"])
        check("founder-authored", a["founder"], EXPECTED["founder"])
        check("echo under strict length floor", a["echo_strict"], EXPECTED["echo_strict"])
        check("echo family detected", len(m["echo_families"]), 1)
        check("echo family occurrences",
              m["echo_families"][0]["occurrences"] if m["echo_families"] else None, 3)

        print("\n-- memories and projects --")
        names = sorted(os.path.basename(r["path"]) for r in m["other_json"])
        check("non-conversation JSON profiled", len(m["other_json"]),
              EXPECTED["profiled_json"])
        check("memories.json present", "memories.json" in names, True)
        check("projects.json present", "projects.json" in names, True)
        check("all profiles succeeded",
              all(r["status"] == "PROFILED" for r in m["other_json"]), True)
        mem = [r for r in m["other_json"]
               if r["path"].endswith("memories.json")][0]
        paths = {kp["path"] for kp in mem["profile"]["key_paths"]}
        check("memory content path discovered", "memories[].content" in paths, True)
        check("memory settings discovered",
              "settings.memory_enabled" in paths, True)
        proj = [r for r in m["other_json"]
                if r["path"].endswith("projects.json")][0]
        ppaths = {kp["path"] for kp in proj["profile"]["key_paths"]}
        check("project instructions discovered",
              "projects[].instructions" in ppaths, True)

        print("\n-- portable artefact, verified by content --")
        lines = []
        for s in m["shards"]:
            with open(os.path.join(out, s["file"]), encoding="utf-8") as fh:
                lines += [json.loads(x) for x in fh if x.strip()]
        check("jsonl lines", len(lines), EXPECTED["founder"])
        check("shard line total matches metrics",
              sum(s["lines"] for s in m["shards"]), EXPECTED["founder"])
        required = {"conversation_id", "node_id", "timestamp", "char_count", "text"}
        check("every line carries the required fields",
              all(required <= set(x) for x in lines), True)
        check("char_count matches its own text",
              all(x["char_count"] == len(x["text"]) for x in lines), True)
        check("no echo text leaked into founder shards",
              any(fixture.ECHO_TEMPLATE[:200] in x["text"] for x in lines), False)
        check("unique long message is present",
              any(fixture.LONG_UNIQUE[:120] in x["text"] for x in lines), True)
        check("message only reachable via nested archive is present",
              any("nested archive" in x["text"] for x in lines), True)
        check("lines sorted by timestamp",
              [x["timestamp"] for x in lines],
              sorted(x["timestamp"] for x in lines))
        echo_lines = sum(s["lines"] for s in m["echo_shards"])
        check("echo written separately, nothing dropped",
              echo_lines + len(lines), EXPECTED["addressable"])

        print("\n-- delta against the authority index (R13) --")
        check("delta computed", dl["status"], "COMPUTED")
        check("acts detected", dl["acts_detected_total"], 3)
        check("act status breakdown", dl["act_status_breakdown"],
              {"CURRENT": 2, "SUPERSEDED": 1})
        check("conversations absent from index",
              dl["conversations_absent_from_index"],
              EXPECTED["delta_conversations_absent"])
        check("covered by a live act", dl["founder_messages_covered_by_live_acts"],
              EXPECTED["delta_covered_live"])
        check("covered ONLY by a superseded act",
              dl["founder_messages_covered_only_by_superseded_acts"],
              EXPECTED["delta_covered_superseded_only"])
        check("absent from the index entirely",
              dl["founder_messages_absent_from_index"], EXPECTED["delta_absent"])

        print("\n-- report and manifest --")
        report = os.path.join(out, "FULL-EXPORT-COVERAGE-REPORT.md")
        check("report written", os.path.isfile(report), True)
        text = open(report, encoding="utf-8").read()
        check("report states the founder denominator", "5" in text, True)
        check("report names the blocker", "broken-archive.zip" in text, True)
        check("report shows the memories key paths",
              "memories[].content" in text, True)
        manifest = json.load(open(os.path.join(out, "MANIFEST.json"),
                                  encoding="utf-8"))
        check("manifest hashes every output",
              all(len(o["sha256"]) == 64 for o in manifest["outputs"]), True)

        print("\n-- sharding under a forced small limit --")
        out2 = os.path.join(tmp, "out2")
        subprocess.run([sys.executable,
                        os.path.join(HERE, "extract_full_export.py"),
                        "--input", os.path.join(tmp, "fx", "input"),
                        "--out", out2, "--shard-mb", "0.001"],
                       capture_output=True, text=True, check=True)
        with open(os.path.join(out2, "coverage-metrics.json"),
                  encoding="utf-8") as fh:
            m2 = json.load(fh)
        check("splits into multiple shards", len(m2["shards"]) > 1, True)
        check("no line lost when sharding",
              sum(s["lines"] for s in m2["shards"]), EXPECTED["founder"])
        check("every shard under the limit",
              all(s["bytes"] <= 1000 or s["lines"] == 1 for s in m2["shards"]), True)

        print("\n-- malformed and unexpected inputs --")
        edge_cases(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    if failures:
        print("FAILED %d check(s):" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
