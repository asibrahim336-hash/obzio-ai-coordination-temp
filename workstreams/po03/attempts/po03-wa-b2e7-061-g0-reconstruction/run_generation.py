#!/usr/bin/env python3
"""Measure one generation on the frozen public suite and the sealed holdout.

The same runner measures G0, G1 and G2.  Nothing about the suite depends on
which generation is being measured, and the suite freeze record in every output
document states which suite bytes were used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def load_suite(path: Path):
    spec = importlib.util.spec_from_file_location("po03_generation_suite", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--suite", required=True, help="path to generation_suite.py")
    parser.add_argument("--holdout", required=True, help="path to the sealed holdout case file")
    parser.add_argument("--seal", default=None, help="path to holdout-seal.json")
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True, help="path to the generation factory source")
    parser.add_argument("--description", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    suite = load_suite(Path(args.suite).resolve())
    generation = suite.Generation(
        args.name, Path(args.source).resolve(), repo, description=args.description
    )
    payload = suite.run_generation(
        generation,
        Path(args.holdout).resolve(),
        Path(args.seal).resolve() if args.seal else None,
    )
    Path(args.out).write_bytes(suite.canonical(payload))
    summary = {key: value for key, value in payload.items() if key != "records"}
    print(json.dumps(summary, indent=2, sort_keys=True))
    for record in payload["records"]:
        print(f"{record['outcome']:12} {record['case_id']}: {record['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
