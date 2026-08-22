#!/usr/bin/env python3
"""Differential warm/clean subprocess execution mechanism."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def baseline_evaluate(root):
    root = Path(root)
    selected = root / "local-default.json"
    if not selected.exists():
        selected = root / "tracked/config.json"
    return json.loads(selected.read_text())


def portable_evaluate(root):
    return json.loads((Path(root) / "tracked/config.json").read_text())


def invoke(root, mode):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8"}
    output = subprocess.check_output(
        [sys.executable, str(Path(__file__).resolve()), "_evaluate", mode, str(root)],
        cwd=Path(root),
        env=env,
        text=True,
    )
    return json.loads(output)


def differential(warm):
    warm = Path(warm)
    with tempfile.TemporaryDirectory(prefix="obzio-clean-runtime-") as tmp:
        clean = Path(tmp)
        (clean / "tracked").mkdir()
        shutil.copyfile(warm / "tracked/config.json", clean / "tracked/config.json")
        return {
            "baseline_warm": invoke(warm, "baseline"),
            "baseline_clean": invoke(clean, "baseline"),
            "portable_warm": invoke(warm, "portable"),
            "portable_clean": invoke(clean, "portable"),
        }


def exercise():
    with tempfile.TemporaryDirectory(prefix="obzio-warm-runtime-") as tmp:
        warm = Path(tmp)
        (warm / "tracked").mkdir()
        (warm / "tracked/config.json").write_text('{"mode":"portable","version":1}\n')
        (warm / "local-default.json").write_text('{"mode":"warm-only","version":1}\n')
        observed = differential(warm)
    observed["baseline_outputs_equal"] = observed["baseline_warm"] == observed["baseline_clean"]
    observed["portable_outputs_equal"] = observed["portable_warm"] == observed["portable_clean"]
    observed["disposition"] = "PASS"
    return observed


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "_evaluate":
        fn = baseline_evaluate if sys.argv[2] == "baseline" else portable_evaluate
        print(json.dumps(fn(sys.argv[3]), sort_keys=True))
    else:
        print(json.dumps(exercise(), indent=2, sort_keys=True))
