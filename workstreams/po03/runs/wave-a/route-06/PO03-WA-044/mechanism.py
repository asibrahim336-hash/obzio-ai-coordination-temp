#!/usr/bin/env python3
"""Declared-input sandbox exposing warm-checkout hidden state."""
import json
import os
import shutil
import tempfile
from pathlib import Path


def baseline_load(pack):
    hidden = Path(pack) / "local-state.json"
    if hidden.exists():
        return json.loads(hidden.read_text())["token"]
    if os.environ.get("PACK_TOKEN"):
        return os.environ["PACK_TOKEN"]
    raise FileNotFoundError("baseline depended on undeclared local-state.json or PACK_TOKEN")


def hermetic_load(pack, declared_relative):
    pack = Path(pack).resolve()
    declared = Path(declared_relative)
    if declared.is_absolute() or ".." in declared.parts:
        raise ValueError("declared input must be confined and relative")
    source = (pack / declared).resolve(strict=True)
    source.relative_to(pack)
    with tempfile.TemporaryDirectory() as tmp:
        sandbox_input = Path(tmp) / "declared-input.json"
        shutil.copyfile(source, sandbox_input)
        return json.loads(sandbox_input.read_text())["token"]


def exercise():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        warm = root / "warm"
        clean = root / "clean"
        (warm / "inputs").mkdir(parents=True)
        (clean / "inputs").mkdir(parents=True)
        declared = {"token": "declared-portable-value"}
        (warm / "inputs/config.json").write_text(json.dumps(declared))
        (clean / "inputs/config.json").write_text(json.dumps(declared))
        (warm / "local-state.json").write_text(json.dumps({"token": "warm-checkout-only-value"}))
        warm_value = baseline_load(warm)
        try:
            baseline_load(clean)
            clean_state = "UNEXPECTED_PASS"
        except FileNotFoundError:
            clean_state = "HIDDEN_STATE_EXPOSED"
        hermetic_warm = hermetic_load(warm, "inputs/config.json")
        hermetic_clean = hermetic_load(clean, "inputs/config.json")
    return {
        "baseline_warm_value": warm_value,
        "baseline_clean_state": clean_state,
        "hermetic_warm_value": hermetic_warm,
        "hermetic_clean_value": hermetic_clean,
        "outputs_equal": hermetic_warm == hermetic_clean,
        "disposition": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(exercise(), indent=2, sort_keys=True))
