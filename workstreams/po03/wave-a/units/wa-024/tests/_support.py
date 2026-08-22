"""Shared fixture helpers for the PO03-WA-024 tests.

Modules are loaded from an explicit path derived from ``__file__`` rather than
from ``sys.path`` or the working directory, which is the working-directory
independence the unit itself argues for.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

UNIT_ROOT = Path(__file__).resolve().parents[1]
HARNESS = UNIT_ROOT / "harness"
REPO_ROOT = Path(__file__).resolve().parents[6]

GIT_FIXTURE_CONFIG = (
    "-c",
    "user.email=po03-wa-024@obzio.invalid",
    "-c",
    "user.name=PO03 WA-024 Fixture",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "tag.gpgsign=false",
    "-c",
    "init.defaultBranch=main",
    "-c",
    "protocol.file.allow=always",
)


def load(name: str) -> ModuleType:
    path = HARNESS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"wa024_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *GIT_FIXTURE_CONFIG, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(["init", "--quiet"], root)


def commit_all(root: Path, message: str) -> str:
    git(["add", "-A"], root)
    git(["commit", "--quiet", "--no-gpg-sign", "-m", message], root)
    return git(["rev-parse", "HEAD"], root).strip()


def corrupt_tail(object_id: str) -> str:
    """Return a forty-character hex id that shares ``object_id``'s short prefix
    but not its full value, mimicking a hand-copied or invented identifier."""
    prefix, tail = object_id[:7], object_id[7:]
    flipped = "".join("0" if char != "0" else "1" for char in tail)
    corrupted = prefix + flipped
    assert len(corrupted) == 40 and corrupted != object_id
    return corrupted
