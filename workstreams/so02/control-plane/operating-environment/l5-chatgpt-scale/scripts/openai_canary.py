#!/usr/bin/env python3
"""Bounded first canary for the OpenAI route.

WHAT IT PROVES
    1. The credential works at all               (GET /v1/models)
    2. A durable, addressable unit of work exists (POST /v1/conversations)
    3. Work can be executed against it            (POST /v1/responses)
    4. The result is retrievable BY IDENTIFIER on a later, separate request
       (GET /v1/conversations/{id} and GET /v1/conversations/{id}/items)
    5. The identifier survives into repository custody with no credential
       material attached.

Step 4 is the whole point. Anything can print a model's answer in the same
process that asked for it. The question this canary answers is whether the
operation can *come back later, by identifier, from somewhere else* and find the
work — because that, not text generation, is what makes a route usable as
durable custody.

WHAT IT DELIBERATELY DOES NOT DO
    - Does not hardcode a model. Model identifiers go stale; it discovers one
      from /v1/models and accepts an override. See --model.
    - Does not print, log or persist the credential. It reads OPENAI_API_KEY
      from the environment, sends it in one header, and scans every byte it is
      about to write to disk for credential-shaped material first.
    - Does not run unbounded. One conversation, one response, a small output
      cap, no tools, no web access, no retries that could multiply spend.
    - Does not delete anything. /v1/conversations retention is "until deleted",
      so disposal is a deliberate later act by whoever owns that decision, not
      a side effect of a test.

USAGE
    # Validate the script today, with no key and no network and no spend:
    python3 openai_canary.py --dry-run

    # Run it the moment the key exists:
    python3 openai_canary.py

    # Options:
    #   --model gpt-...        pin a model instead of discovering one
    #   --out PATH             where to write the locator record
    #   --max-output-tokens N  hard cap on generated tokens (default 256)
    #   --note "..."           free text recorded with the locator

EXIT CODES
    0  canary passed end to end
    2  credential absent from the environment
    3  a preflight or safety check failed (nothing was sent)
    4  an API call failed; see the printed step and status
    5  the result was created but was NOT retrievable by identifier
       (this is the interesting failure: the route generates but does not
        durably address, which would invalidate its use as custody)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_ROOT = "https://api.openai.com/v1"
KEY_ENV = "OPENAI_API_KEY"
TIMEOUT = 120

# The canary asks for a structured answer rather than prose. That is not
# decoration: it is the smallest honest test of whether this route can be made
# to emit machine-checkable state, which is what the operating programme needs
# from it. See OPENAI-API-SURFACE-FINDINGS section 4.
CANARY_SCHEMA = {
    "type": "object",
    "properties": {
        "canary_ok": {"type": "boolean"},
        "route_named": {"type": "string"},
        "one_line_summary": {"type": "string"},
    },
    "required": ["canary_ok", "route_named", "one_line_summary"],
    "additionalProperties": False,
}

CANARY_PROMPT = (
    "Reply with canary_ok true, route_named set to the string "
    "'openai-responses-conversations', and a one_line_summary of at most 20 "
    "words confirming this is a bounded connectivity canary. Do not add "
    "anything else."
)

# Anything matching these must never reach disk. Deliberately broader than the
# current key format, because the next key format is not known today.
SECRET_SHAPES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(step: str, msg: str) -> None:
    print(f"[{now()}] {step:<10} {msg}", file=sys.stderr)


class CanaryError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def assert_no_secret(blob: str, key: str | None) -> None:
    """Refuse to persist anything that looks like a credential."""
    if key and key in blob:
        raise CanaryError(3, "refusing to write: payload contains the API key")
    for pattern in SECRET_SHAPES:
        m = pattern.search(blob)
        if m:
            raise CanaryError(
                3,
                f"refusing to write: payload contains credential-shaped text "
                f"matching {pattern.pattern}",
            )


def call(method: str, path: str, key: str, body: dict | None = None) -> dict:
    url = f"{API_ROOT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        # The URL is safe to show; the Authorization header is never echoed.
        raise CanaryError(4, f"{method} {path} -> HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise CanaryError(4, f"{method} {path} -> network failure: {e.reason}")


def pick_model(key: str, override: str | None) -> tuple[str, str]:
    """Return (model_id, how_it_was_chosen). Never hardcodes a default."""
    if override:
        return override, "operator-supplied via --model"
    env = os.environ.get("OPENAI_CANARY_MODEL")
    if env:
        return env, "operator-supplied via OPENAI_CANARY_MODEL"
    listing = call("GET", "/models", key)
    ids = sorted(m["id"] for m in listing.get("data", []))
    if not ids:
        raise CanaryError(4, "/v1/models returned no models for this credential")
    # Prefer a general-purpose text model; fall back to whatever exists rather
    # than asserting a name that may not be in this organisation's catalogue.
    for candidate in ids:
        low = candidate.lower()
        if low.startswith("gpt-") and not any(
            t in low for t in ("audio", "realtime", "image", "video",
                               "transcribe", "tts", "search", "embedding")
        ):
            return candidate, f"discovered from /v1/models ({len(ids)} available)"
    return ids[0], f"discovered from /v1/models, no gpt- text model matched ({len(ids)} available)"


def run(args: argparse.Namespace) -> dict:
    key = os.environ.get(KEY_ENV)
    if not key:
        raise CanaryError(
            2,
            f"{KEY_ENV} is not set in this environment. Add it in the Cursor "
            f"Dashboard under Cloud Agents -> Secrets, repository-scoped, then "
            f"start a new agent run. This script never accepts a key as an "
            f"argument and never prompts for one.",
        )
    if any(a.startswith("sk-") for a in sys.argv[1:]):
        raise CanaryError(3, "a credential-shaped argument was passed on the "
                             "command line; refusing to run")

    log("preflight", f"{KEY_ENV} present (value never read into output)")

    model, how = pick_model(key, args.model)
    log("model", f"{model} ({how})")

    # -- 1. create the durable, addressable container ----------------------
    # Metadata is capped at 16 pairs / 64-char keys / 512-char values, so it
    # carries a pointer back to repository custody, not the record itself.
    conv = call("POST", "/conversations", key, {
        "metadata": {
            "purpose": "oe-l5-first-canary",
            "lane": "OE-L5-CHATGPT-SCALE",
            "commission": "COM-CUR-ENV-01-20260822-v001",
            "custody": "repository-canonical",
        },
    })
    conv_id = conv.get("id")
    if not conv_id:
        raise CanaryError(4, f"conversation created but no id returned: {conv}")
    log("conversation", f"created {conv_id}")

    # -- 2. execute one bounded unit of work against it --------------------
    resp = call("POST", "/responses", key, {
        "model": model,
        "conversation": conv_id,
        "input": CANARY_PROMPT,
        # Explicit, not omitted: under some retention configurations an omitted
        # store is equivalent to store=false and the result disappears.
        "store": True,
        "max_output_tokens": args.max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "canary_result",
                "strict": True,
                "schema": CANARY_SCHEMA,
            }
        },
    })
    resp_id = resp.get("id")
    log("response", f"created {resp_id} status={resp.get('status')}")

    # -- 3. THE ACTUAL TEST: retrieve by identifier, as a separate request --
    fetched = call("GET", f"/conversations/{conv_id}", key)
    if fetched.get("id") != conv_id:
        raise CanaryError(
            5, f"conversation retrieved by id did not match: {fetched.get('id')}"
        )
    log("retrieve", f"conversation {conv_id} addressable; "
                    f"created_at={fetched.get('created_at')}")

    items = call("GET", f"/conversations/{conv_id}/items", key)
    item_list = items.get("data", [])
    if not item_list:
        raise CanaryError(
            5,
            "conversation is addressable but contains no items: the route "
            "generated output that is not durably retrievable by identifier, "
            "which disqualifies it as custody",
        )
    log("items", f"{len(item_list)} item(s) retrievable by conversation id")

    # Pull the structured payload back out, to prove the round trip carried
    # machine-checkable state and not just prose.
    structured = None
    for item in item_list:
        for part in item.get("content", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                try:
                    candidate = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if isinstance(candidate, dict) and "canary_ok" in candidate:
                    structured = candidate
    log("structured", f"schema-conformant payload recovered: {structured is not None}")

    usage = resp.get("usage") or {}
    return {
        "artifact_id": "OE-L5-OPENAI-CANARY-LOCATOR",
        "recorded_at_utc": now(),
        "lane": "OE-L5-CHATGPT-SCALE",
        "commission": "COM-CUR-ENV-01-20260822-v001",
        "outcome": "PASS",
        "note": args.note,
        "route": {
            "api_root": API_ROOT,
            "credential_env_var_name": KEY_ENV,
            "credential_value_recorded": False,
        },
        "model": {"id": model, "selection": how,
                  "bound_as_decision": False,
                  "note": "recorded as what ran, not as a binding choice"},
        "locators": {
            "conversation_id": conv_id,
            "response_id": resp_id,
            "conversation_created_at": fetched.get("created_at"),
        },
        "addressability_check": {
            "retrieved_conversation_by_id": True,
            "id_matched": True,
            "item_count": len(item_list),
            "structured_payload_recovered": structured is not None,
            "structured_payload": structured,
        },
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "max_output_tokens_requested": args.max_output_tokens,
        },
        "retention_note": (
            "/v1/conversations retains application state until deleted and is "
            "not Zero Data Retention eligible. This conversation persists until "
            "someone deletes it. Deleting the conversation does not delete its "
            "items. Disposal is a separate, owned decision."
        ),
        "reconciliation": {
            "canonical_store": "repository",
            "provider_object_role": "locator only",
            "why": (
                "conversation metadata is capped at 16 pairs of 64-character "
                "keys and 512-character values, which cannot hold provenance, "
                "authority or acceptance state"
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the plan without a key, a call or any spend")
    ap.add_argument("--model", default=None,
                    help="pin a model id instead of discovering one")
    ap.add_argument("--max-output-tokens", type=int, default=256,
                    help="hard cap on generated tokens (default 256)")
    ap.add_argument("--out", default=None,
                    help="path for the locator record")
    ap.add_argument("--note", default="first bounded canary of the OpenAI route")
    args = ap.parse_args()

    default_out = (pathlib.Path(__file__).resolve().parent.parent
                   / "locators" / "openai-canary-locator.json")
    out = pathlib.Path(args.out) if args.out else default_out

    if args.dry_run:
        plan = {
            "mode": "DRY_RUN",
            "checked_at_utc": now(),
            "credential_present": bool(os.environ.get(KEY_ENV)),
            "credential_env_var_name": KEY_ENV,
            "calls_that_would_be_made": [
                "GET  /v1/models                        (skipped if --model given)",
                "POST /v1/conversations                 (metadata: 4 pairs, all pointers)",
                "POST /v1/responses                     (store=true, strict json_schema, "
                f"max_output_tokens={args.max_output_tokens}, no tools)",
                "GET  /v1/conversations/{id}            (the addressability test)",
                "GET  /v1/conversations/{id}/items      (the retrievability test)",
            ],
            "calls_made_now": 0,
            "spend_now": 0,
            "would_write": str(out),
            "safety": {
                "credential_ever_printed": False,
                "credential_ever_written": False,
                "output_scanned_for_secret_shapes": True,
                "deletes_anything": False,
            },
        }
        print(json.dumps(plan, indent=2))
        log("dry-run", "plan validated; no network call was made")
        return 0

    key = os.environ.get(KEY_ENV)
    try:
        record = run(args)
    except CanaryError as e:
        log("FAIL", str(e))
        return e.code

    blob = json.dumps(record, indent=2, sort_keys=False) + "\n"
    assert_no_secret(blob, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding="utf-8")
    log("custody", f"locator written to {out}")
    log("PASS", f"conversation {record['locators']['conversation_id']} "
                f"created, executed and retrieved by identifier")
    print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
