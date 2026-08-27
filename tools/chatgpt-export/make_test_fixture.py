#!/usr/bin/env python3
"""Build a synthetic ChatGPT export whose true counts are known by hand.

The fixture reproduces the awkward parts of a real export rather than a happy
path: a root node carrying no message, a custom-instructions envelope wearing
`author.role == "user"`, a hidden user node, an empty user node, the same
conversation present in two archives at different completeness, a template
repeated across conversations, an archive whose filename says nothing about its
type, a nested archive, and one deliberately corrupt archive.

Expected values are asserted as literals in test_extract_full_export.py so the
check is independent of the extractor's own logic.
"""

import json
import os
import shutil
import sys
import zipfile

BASE = 1781049600          # 2026-06-10T00:00:00Z
LAST = 1787443200          # 2026-08-23T00:00:00Z

C1 = "11111111-1111-4111-8111-111111111111"
C2 = "22222222-2222-4222-8222-222222222222"
C3 = "33333333-3333-4333-8333-333333333333"
C4 = "44444444-4444-4444-8444-444444444444"
C5 = "55555555-5555-4555-8555-555555555555"
C6 = "66666666-6666-4666-8666-666666666666"
C7 = "77777777-7777-4777-8777-777777777777"

ECHO_TEMPLATE = (
    "STANDING AUTHORITY BLOCK. Operate autonomously under founder interest. "
    "Never shrink strategy, scale, model use or autonomy around a local "
    "constraint; mark the route BLOCKED and use the strongest lawful "
    "alternate. Enumerate at depth before analysing. Re-test a blocked route "
    "per asset and per session class before inheriting the block. Declare "
    "reused, extended or superseded per prior artifact by filename. Verify by "
    "content, not by length; a write returning success proves nothing. Counts "
    "bind to their instrument and their instant, so always state the "
    "denominator. Agreement across models is not verification: any countable "
    "claim must be counted against the primary population before it is "
    "reported. Do not compress the answer into one next action. "
) * 2

LONG_UNIQUE = (
    "The platform question is what the harness actually sells once the 3D "
    "surface is the delivery layer rather than the product itself. A harness "
    "that only wraps a model is a thin resale. A harness that carries "
    "evidence, provenance, authority state and return routing is an operating "
    "substrate, and that substrate is what survives a model swap. The open "
    "part of the business is deliberately open and I do not want it filled by "
    "inference from the components we happen to have built first. Treat every "
    "named mechanism as a component, never as the business definition, and "
    "keep the boundary explicit in anything you write down for me. "
)

SUPERSEDED_TEXT = (
    "Earlier framing that I have since replaced: treat the capability factory "
    "as the organising idea and let the marketplace follow from it. I no "
    "longer want this used as the governing description because it collapses "
    "the open part of the direction into the mechanism that happens to be "
    "most legible right now. Keep it as evidence of what I said, not as a "
    "live instruction, and do not route from it. "
)


def msg(role, text, ts, ctype="text", metadata=None, extra=None):
    content = {"content_type": ctype}
    if ctype == "user_editable_context":
        content["user_profile"] = text
        content["user_instructions"] = "Be concise."
    elif ctype in ("code", "execution_output"):
        content["text"] = text
    else:
        content["parts"] = [text]
    if extra:
        content.update(extra)
    return {
        "id": "m-%s-%d" % (role, ts),
        "author": {"role": role, "name": None, "metadata": {}},
        "create_time": ts,
        "update_time": ts,
        "content": content,
        "status": "finished_successfully",
        "end_turn": True,
        "weight": 1.0,
        "metadata": metadata or {},
        "recipient": "all",
    }


def node(message, parent, children):
    return {"id": (message or {}).get("id", "root"), "message": message,
            "parent": parent, "children": children}


def conversation(cid, title, create, nodes):
    return {
        "title": title,
        "create_time": create,
        "update_time": create + 600,
        "mapping": nodes,
        "conversation_id": cid,
        "id": cid,
        "current_node": list(nodes)[-1],
        "is_archived": False,
        "default_model_slug": "gpt-5",
        "safe_urls": [],
        "plugin_ids": None,
        "moderation_results": [],
    }


def c1_rich():
    """5 nodes / 4 messages / 2 user-role, one of which is a context envelope."""
    return conversation(C1, "Strategy kickoff", BASE, {
        "c1n0": node(None, None, ["c1n1"]),
        "c1n1": node(msg("system", "", BASE,
                         metadata={"is_visually_hidden_from_conversation": True}),
                     "c1n0", ["c1n2"]),
        "c1n2": node(msg("user", "What is the strongest route to a 3D platform "
                                 "that sells agent harnesses?", BASE + 60),
                     "c1n1", ["c1n3"]),
        "c1n3": node(msg("assistant", "Several routes are viable.", BASE + 120),
                     "c1n2", ["c1n4"]),
        "c1n4": node(msg("user", "Founder profile text.", BASE + 180,
                         ctype="user_editable_context",
                         metadata={"is_user_system_message": True}),
                     "c1n3", []),
    })


def c1_poor():
    """Same conversation, 3 nodes. Must lose to c1_rich."""
    c = conversation(C1, "Strategy kickoff", BASE, {
        "c1n0": node(None, None, ["c1n2"]),
        "c1n2": node(msg("user", "What is the strongest route to a 3D platform "
                                 "that sells agent harnesses?", BASE + 60),
                     "c1n0", ["c1n3"]),
        "c1n3": node(msg("assistant", "Several routes are viable.", BASE + 120),
                     "c1n2", []),
    })
    return c


def echo_conv(cid, title, ts):
    return conversation(cid, title, ts, {
        "n1": node(msg("user", ECHO_TEMPLATE, ts), None, ["n2"]),
        "n2": node(msg("assistant", "Acknowledged.", ts + 60), "n1", []),
    })


def c3_rich():
    """4 nodes: echo, reply, an empty user node, and a hidden user node."""
    ts = BASE + 86400 * 3
    return conversation(C3, "Echo run 2", ts, {
        "n1": node(msg("user", ECHO_TEMPLATE, ts), None, ["n2"]),
        "n2": node(msg("assistant", "Acknowledged.", ts + 60), "n1", ["n3"]),
        "n3": node(msg("user", "", ts + 120), "n2", ["n4"]),
        "n4": node(msg("user", "system ping", ts + 180,
                       metadata={"is_visually_hidden_from_conversation": True}),
                   "n3", []),
    })


def c5():
    ts = BASE + 86400 * 30
    return conversation(C5, "Delta probe", ts, {
        "n1": node(msg("user", LONG_UNIQUE, ts), None, ["n2"]),
        "n2": node(msg("assistant", "print('ok')", ts + 60, ctype="code"),
                   "n1", ["n3"]),
        "n3": node(msg("user", "yes go ahead", ts + 120), "n2", []),
    })


def c6():
    ts = BASE + 86400 * 50
    return conversation(C6, "Plain json shard", ts, {
        "n1": node(msg("user", SUPERSEDED_TEXT, ts), None, ["n2"]),
        "n2": node(msg("assistant", "Recorded.", ts + 60), "n1", []),
    })


def c7():
    return conversation(C7, "Nested archive", LAST - 60, {
        "n1": node(msg("user", "Only reachable through the nested archive.",
                       LAST - 60), None, ["n2"]),
        "n2": node(msg("assistant", "Understood.", LAST), "n1", []),
    })


def write_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members.items():
            if isinstance(payload, bytes):
                zf.writestr(name, payload)
            else:
                zf.writestr(name, json.dumps(payload, ensure_ascii=False))


def build(root):
    if os.path.isdir(root):
        shutil.rmtree(root)
    inp = os.path.join(root, "input")
    os.makedirs(inp)

    write_zip(os.path.join(inp, "conversations-000.zip"), {
        "conversations.json": [c1_rich(), echo_conv(C2, "Echo run 1", BASE + 86400),
                               conversation(C3, "Echo run 2", BASE + 86400 * 3, {
                                   "n1": node(msg("user", ECHO_TEMPLATE,
                                                  BASE + 86400 * 3), None, ["n2"]),
                                   "n2": node(msg("assistant", "Acknowledged.",
                                                  BASE + 86400 * 3 + 60), "n1", []),
                               })],
    })

    write_zip(os.path.join(inp, "CHATGPT-EXPORT-10JUN2026-TO-23AUG2026.zip"), {
        "conversations.json": [c1_poor(), c3_rich(),
                               echo_conv(C4, "Echo run 3", BASE + 86400 * 10), c5()],
        "user.json": {"id": "user-abc", "email": "founder@example.invalid",
                      "chatgpt_plus_user": True},
        "message_feedback.json": [],
    })

    write_zip(os.path.join(inp, "memories-000.zip"), {
        "memories.json": {
            "memories": [
                {"id": "mem-1", "content": "Prefers portable, dependency-free "
                                           "artefacts that survive a machine change.",
                 "created_at": "2026-07-02T10:00:00Z", "source": "conversation"},
                {"id": "mem-2", "content": "Treats named mechanisms as components, "
                                           "not as the business definition.",
                 "created_at": "2026-08-11T09:30:00Z", "source": "explicit"},
            ],
            "settings": {"memory_enabled": True, "reference_chat_history": True},
        },
    })

    write_zip(os.path.join(inp, "projects-000.zip"), {
        "projects.json": {
            "projects": [
                {"id": "proj-1", "name": "Obzio platform",
                 "instructions": "Keep the open part of the direction open.",
                 "created_at": "2026-06-15T08:00:00Z",
                 "files": [{"name": "brief.md", "bytes": 4096}],
                 "conversation_ids": [C5]},
            ],
        },
    })

    # Filename carries no type information; identification must come from bytes.
    inner = os.path.join(root, "inner-conversations.zip")
    write_zip(inner, {"conversations.json": [c7()]})
    with open(inner, "rb") as fh:
        inner_bytes = fh.read()
    os.remove(inner)
    write_zip(os.path.join(inp, "1f7c9e3b5a2d4e6f8a0b1c2d3e4f5a6b7c8d9e0f"),
              {"inner-conversations.zip": inner_bytes})

    # Truncated central directory: must surface as a named blocker, not silence.
    with open(os.path.join(inp, "broken-archive.zip"), "wb") as fh:
        fh.write(b"PK\x03\x04" + b"\x00" * 64 + b"truncated before the directory")

    with open(os.path.join(inp, "conversations-011(1).json"), "w",
              encoding="utf-8") as fh:
        json.dump([c6()], fh, ensure_ascii=False)

    index = {
        "index_version": "unified-authority-index-test",
        "acts": [
            {"act_id": "A001", "status": "CURRENT", "superseded": None,
             "source_conversation_id": C1,
             "quote": LONG_UNIQUE[100:350]},
            {"act_id": "A002", "status": "SUPERSEDED", "superseded": "A003",
             "quote": SUPERSEDED_TEXT[100:350]},
            {"act_id": "A003", "status": "CURRENT", "superseded": None,
             "quote": "short"},
        ],
    }
    index_path = os.path.join(root, "UNIFIED-AUTHORITY-INDEX-TEST.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False)
    return inp, index_path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "_fixture"
    i, x = build(target)
    print("input=%s\nindex=%s" % (i, x))
