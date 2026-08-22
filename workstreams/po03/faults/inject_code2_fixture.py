#!/usr/bin/env python3
"""Replay the frozen PO-02 Code-2 lost-return fixture."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("a2_fault_lab", Path(__file__).with_name("fault_lab.py"))
LAB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LAB)

raise SystemExit(LAB.cli("a2-u12"))
