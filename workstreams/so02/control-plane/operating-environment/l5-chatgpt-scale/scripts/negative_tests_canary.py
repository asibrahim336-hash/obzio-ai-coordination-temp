#!/usr/bin/env python3
"""Adversarial tests for the canary's credential-safety guards.

A script that says it never leaks a credential is worth exactly as much as the
test that tries to make it leak one. These tests deliberately attempt each leak
and assert the guard fires. No network call is made and no real credential is
used; the strings below are synthetic and are not valid credentials.

Run:  python3 negative_tests_canary.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
CANARY = HERE / "openai_canary.py"

# Synthetic, structurally key-shaped, never valid. Assembled at runtime so the
# literal never appears in the source file either.
FAKE_KEY = "sk-" + ("CANARYTEST" * 3) + "0000"


def load_canary():
    spec = importlib.util.spec_from_file_location("openai_canary", CANARY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    canary = load_canary()
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"NT-{name} PASSED: guard fired as intended")
        else:
            failures.append(f"NT-{name}: {detail}")
            print(f"NT-{name} FAILED: {detail}")

    # NT1: the exact key value must never be written, even if it somehow ends
    #      up inside a record the script is about to persist.
    payload = json.dumps({"locators": {"conversation_id": "conv_x"},
                          "oops": FAKE_KEY})
    try:
        canary.assert_no_secret(payload, FAKE_KEY)
        check("1", False, "a payload containing the live key was accepted")
    except canary.CanaryError as e:
        check("1", e.code == 3, f"wrong exit code {e.code}")

    # NT2: a credential-shaped string must be refused even when the guard was
    #      not told what the key is. This is the case that matters, because a
    #      leak of some *other* key would otherwise sail through.
    try:
        canary.assert_no_secret(json.dumps({"stray": FAKE_KEY}), None)
        check("2", False, "credential-shaped text was accepted with key=None")
    except canary.CanaryError as e:
        check("2", e.code == 3, f"wrong exit code {e.code}")

    # NT3: an Authorization header accidentally captured into a record must be
    #      refused, since error paths are where headers usually leak.
    bearer = "Authorization: Bearer " + ("A" * 40)
    try:
        canary.assert_no_secret(json.dumps({"debug": bearer}), None)
        check("3", False, "a captured bearer header was accepted")
    except canary.CanaryError as e:
        check("3", e.code == 3, f"wrong exit code {e.code}")

    # NT4: an ordinary clean record must still be writable, or the guard is
    #      just a brick and would be disabled by the first person it annoys.
    clean = json.dumps({"locators": {"conversation_id": "conv_abc123"},
                        "credential_value_recorded": False})
    try:
        canary.assert_no_secret(clean, FAKE_KEY)
        print("NT-4 PASSED: a clean record is still accepted")
    except canary.CanaryError as e:
        failures.append(f"NT-4: clean record rejected ({e})")
        print(f"NT-4 FAILED: clean record rejected ({e})")

    # NT5: passing a credential on the command line must be refused outright,
    #      because argv lands in shell history and process listings.
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = FAKE_KEY
    proc = subprocess.run(
        [sys.executable, str(CANARY), "--model", FAKE_KEY],
        capture_output=True, text=True, env=env, timeout=60,
    )
    combined = proc.stdout + proc.stderr
    check("5", proc.returncode == 3,
          f"exit {proc.returncode}, expected 3")
    check("5b", FAKE_KEY not in combined,
          "the rejected credential was echoed back in the output")

    # NT6: with a key present, --dry-run must still make no call and must not
    #      print the key. This is the mode an operator runs first.
    proc = subprocess.run(
        [sys.executable, str(CANARY), "--dry-run"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    combined = proc.stdout + proc.stderr
    check("6", proc.returncode == 0, f"dry-run exited {proc.returncode}")
    check("6b", FAKE_KEY not in combined, "dry-run echoed the credential")
    check("6c", '"credential_present": true' in proc.stdout,
          "dry-run failed to report credential presence")
    check("6d", '"calls_made_now": 0' in proc.stdout,
          "dry-run did not assert zero calls")

    print()
    if failures:
        print(f"FAIL: {len(failures)} guard(s) did not hold")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: every credential-leak path was refused, and clean records "
          "still write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
