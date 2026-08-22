#!/usr/bin/env python3
"""Dependency-free scanner for non-portable filesystem paths.

The scanner is deliberately lexical and fail-closed about scan closure. It
does not follow symlinks, silently skip binary data, or infer exclusions.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence


PROTOCOL_VERSION = "OBZIO-PORTABLE-PATH-SCAN-v1"

_QUOTED_RE = re.compile(
    r"(?P<quote>['\"])(?P<value>(?:\\.|(?! (?P=quote)).)*)(?P=quote)",
    re.VERBOSE,
)
_BARE_CHAR = r"(?:\\[ \t]|[^\s<>'\"`])"
_BARE_RE = re.compile(
    rf"(?<![A-Za-z0-9_])file:///{_BARE_CHAR}+"
    rf"|(?<![A-Za-z0-9_])(?:~|\$HOME|\$\{{HOME\}})(?:/{_BARE_CHAR}+)+"
    rf"|(?<![A-Za-z0-9_])[A-Za-z]:(?:\\|/){_BARE_CHAR}+"
    rf"|(?<![A-Za-z0-9_:/.])/(?!/){_BARE_CHAR}+"
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:(?:\\+|/)")
_VERSIONED_ROUTE_RE = re.compile(r"^/v[0-9]+(?:\.[0-9]+)?(?:/|$)", re.IGNORECASE)
_JSON_POINTER_ROOTS = {
    "components",
    "definitions",
    "properties",
    "schemas",
}
_KNOWN_FILESYSTEM_ROOTS = {
    "Users",
    "Volumes",
    "bin",
    "builds",
    "dev",
    "etc",
    "home",
    "media",
    "mnt",
    "opt",
    "private",
    "proc",
    "root",
    "run",
    "sbin",
    "srv",
    "sys",
    "tmp",
    "usr",
    "var",
    "workspace",
    "workspaces",
}
_TRAILING_PROSE = ",;:!?)]}`"
_RULES = {
    "absolute-posix": "PPATH-ABS-POSIX",
    "absolute-windows": "PPATH-ABS-WINDOWS",
    "home-relative": "PPATH-HOME-RELATIVE",
    "temporary": "PPATH-TEMPORARY",
    "checkout-specific": "PPATH-CHECKOUT-SPECIFIC",
}


def _normalise_path_text(value: str) -> str:
    value = value.replace("\\\\", "\\")
    return value.replace("\\", "/")


def _strip_prose_suffix(value: str) -> str:
    while value and value[-1] in _TRAILING_PROSE:
        value = value[:-1]
    return value


def _effective_path(value: str) -> tuple[str, bool]:
    if value.lower().startswith("file:///"):
        return "/" + value[8:], True
    return value, False


def _is_probable_non_filesystem_literal(path: str, preceding: str) -> bool:
    """Suppress high-frequency URI/route syntax with explicit known shapes.

    This is intentionally narrow. Ambiguous multi-component slash strings
    remain findings. The suppressed shapes are documented as false-negative
    boundaries in the closure contract and limitations.
    """

    if preceding in {"#", "^"}:
        return True
    if "{" in path or "}" in path:
        return True
    if _VERSIONED_ROUTE_RE.match(path):
        return True
    parts = [part for part in path.split("/") if part]
    if parts and parts[0] in _JSON_POINTER_ROOTS:
        return True
    if len(parts) == 1 and parts[0] not in _KNOWN_FILESYSTEM_ROOTS:
        return True
    return False


def _normalise_checkout_roots(checkout_roots: Sequence[str]) -> tuple[str, ...]:
    normalised: list[str] = []
    for root in checkout_roots:
        candidate = _normalise_path_text(root.strip()).rstrip("/")
        if not candidate.startswith("/"):
            raise ValueError(f"checkout root must be absolute: {root!r}")
        if candidate and candidate not in normalised:
            normalised.append(candidate)
    return tuple(sorted(normalised))


def _classify(
    raw_value: str,
    preceding: str,
    checkout_roots: Sequence[str],
) -> tuple[str, tuple[str, ...]] | None:
    value = _strip_prose_suffix(raw_value)
    if not value:
        return None
    effective, _from_file_uri = _effective_path(value)
    normalised = _normalise_path_text(effective)

    categories: list[str] = []
    if normalised.startswith(("~/", "$HOME/", "${HOME}/")):
        categories.append("home-relative")
    elif _WINDOWS_ABSOLUTE_RE.match(value):
        categories.append("absolute-windows")
    elif normalised.startswith("/") and not normalised.startswith("//"):
        if _is_probable_non_filesystem_literal(normalised, preceding):
            return None
        categories.append("absolute-posix")
        if (
            normalised == "/tmp"
            or normalised.startswith("/tmp/")
            or normalised == "/var/tmp"
            or normalised.startswith("/var/tmp/")
        ):
            categories.append("temporary")
        for root in checkout_roots:
            if normalised == root or normalised.startswith(root + "/"):
                categories.append("checkout-specific")
                break
    else:
        return None

    if not categories:
        return None
    return value, tuple(categories)


def _quoted_candidates(line: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int]]]:
    candidates: list[tuple[int, int, str]] = []
    spans: list[tuple[int, int]] = []
    for match in _QUOTED_RE.finditer(line):
        spans.append(match.span())
        value = match.group("value")
        start = match.start("value")
        candidates.append((start, match.end("value"), value))
    return candidates, spans


def _overlaps(span: tuple[int, int], occupied: Iterable[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied)


def scan_text(
    text: str,
    *,
    logical_path: str,
    checkout_roots: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Return deterministic findings for one UTF-8 text artifact."""

    normalised_roots = _normalise_checkout_roots(checkout_roots)
    findings: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        quoted, quoted_spans = _quoted_candidates(line)
        candidates = list(quoted)
        for match in _BARE_RE.finditer(line):
            if not _overlaps(match.span(), quoted_spans):
                candidates.append((match.start(), match.end(), match.group(0)))

        for start, _end, raw_value in sorted(candidates, key=lambda item: item[0]):
            preceding = line[start - 1] if start else ""
            classified = _classify(raw_value, preceding, normalised_roots)
            if classified is None:
                continue
            token, categories = classified
            key = (line_number, start, token)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "path": logical_path,
                    "line": line_number,
                    "column": start + 1,
                    "end_column": start + len(token) + 1,
                    "token": token,
                    "category": categories[-1],
                    "categories": list(categories),
                    "rule_ids": [_RULES[category] for category in categories],
                }
            )
    return findings


def _matches_exclusion(relative: str, patterns: Sequence[str]) -> str | None:
    for pattern in patterns:
        clean = pattern.rstrip("/")
        subtree_root = clean[:-3] if clean.endswith("/**") else None
        if fnmatch.fnmatchcase(relative, clean):
            return pattern
        if subtree_root is not None and (
            relative == subtree_root or relative.startswith(subtree_root + "/")
        ):
            return pattern
    return None


def _display_path(declared_root: str, relative: str | None) -> str:
    root = declared_root.replace(os.sep, "/")
    if relative is None or relative in {"", "."}:
        return root
    return root.rstrip("/") + "/" + relative


def _closure_error(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def scan_paths(
    roots: Sequence[str | Path],
    *,
    checkout_roots: Sequence[str] = (),
    exclude_globs: Sequence[str] = (),
) -> dict[str, object]:
    """Scan an explicit file/directory closure without following symlinks."""

    if not roots:
        raise ValueError("at least one scan root is required")
    normalised_checkout_roots = _normalise_checkout_roots(checkout_roots)
    declared_roots = [os.fspath(root) for root in roots]
    findings: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    scanned_files: list[dict[str, object]] = []
    scanned_real_paths: set[Path] = set()

    def scan_file(path: Path, display: str) -> None:
        try:
            real = path.resolve(strict=True)
        except OSError as exc:
            errors.append(_closure_error("UNREADABLE_PATH", display, str(exc)))
            return
        if real in scanned_real_paths:
            errors.append(
                _closure_error(
                    "DUPLICATE_FILE_IN_CLOSURE",
                    display,
                    "file is reachable through more than one declared root",
                )
            )
            return
        scanned_real_paths.add(real)
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(_closure_error("UNREADABLE_FILE", display, str(exc)))
            return
        if b"\0" in data:
            errors.append(
                _closure_error(
                    "BINARY_FILE_NOT_EXCLUDED",
                    display,
                    "NUL byte encountered; declare an exclusion or provide UTF-8 text",
                )
            )
            return
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            errors.append(
                _closure_error(
                    "NON_UTF8_FILE_NOT_EXCLUDED",
                    display,
                    f"invalid UTF-8 at byte {exc.start}",
                )
            )
            return
        scanned_files.append(
            {
                "path": display,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        findings.extend(
            scan_text(
                text,
                logical_path=display,
                checkout_roots=normalised_checkout_roots,
            )
        )

    for declared in declared_roots:
        root = Path(declared)
        if not root.exists() and not root.is_symlink():
            errors.append(
                _closure_error(
                    "MISSING_ROOT",
                    declared.replace(os.sep, "/"),
                    "declared scan root does not exist",
                )
            )
            continue
        if root.is_symlink():
            errors.append(
                _closure_error(
                    "SYMLINK_ROOT",
                    declared.replace(os.sep, "/"),
                    "symlink roots are not followed",
                )
            )
            continue
        if root.is_file():
            pattern = _matches_exclusion(root.name, exclude_globs)
            if pattern is not None:
                excluded.append(
                    {"path": declared.replace(os.sep, "/"), "pattern": pattern}
                )
            else:
                scan_file(root, declared.replace(os.sep, "/"))
            continue
        if not root.is_dir():
            errors.append(
                _closure_error(
                    "UNSUPPORTED_ROOT_TYPE",
                    declared.replace(os.sep, "/"),
                    "root must be a regular file or directory",
                )
            )
            continue

        for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for dirname in sorted(dirnames):
                child = current_path / dirname
                relative = child.relative_to(root).as_posix()
                pattern = _matches_exclusion(relative, exclude_globs)
                display = _display_path(declared, relative)
                if pattern is not None:
                    excluded.append({"path": display, "pattern": pattern})
                elif child.is_symlink():
                    errors.append(
                        _closure_error(
                            "SYMLINK_IN_CLOSURE",
                            display,
                            "directory symlink is not followed; exclude it explicitly",
                        )
                    )
                else:
                    kept_dirs.append(dirname)
            dirnames[:] = kept_dirs

            for filename in sorted(filenames):
                child = current_path / filename
                relative = child.relative_to(root).as_posix()
                display = _display_path(declared, relative)
                pattern = _matches_exclusion(relative, exclude_globs)
                if pattern is not None:
                    excluded.append({"path": display, "pattern": pattern})
                elif child.is_symlink():
                    errors.append(
                        _closure_error(
                            "SYMLINK_IN_CLOSURE",
                            display,
                            "file symlink is not followed; exclude it explicitly",
                        )
                    )
                elif child.is_file():
                    scan_file(child, display)
                else:
                    errors.append(
                        _closure_error(
                            "UNSUPPORTED_NODE_IN_CLOSURE",
                            display,
                            "node is not a regular file",
                        )
                    )

    findings.sort(key=lambda row: (str(row["path"]), int(row["line"]), int(row["column"])))
    errors.sort(key=lambda row: (row["path"], row["code"]))
    excluded.sort(key=lambda row: (row["path"], row["pattern"]))
    scanned_files.sort(key=lambda row: str(row["path"]))
    status = "ERROR" if errors else ("FINDINGS" if findings else "CLEAN")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "closure": {
            "declared_roots": [root.replace(os.sep, "/") for root in declared_roots],
            "checkout_roots": list(normalised_checkout_roots),
            "exclude_globs": list(exclude_globs),
            "scanned_file_count": len(scanned_files),
            "scanned_bytes": sum(int(row["bytes"]) for row in scanned_files),
            "excluded_path_count": len(excluded),
            "files": scanned_files,
            "excluded": excluded,
        },
        "summary": {
            "finding_count": len(findings),
            "error_count": len(errors),
            "category_counts": {
                category: sum(
                    1 for finding in findings if category in finding["categories"]
                )
                for category in _RULES
            },
        },
        "findings": findings,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan declared UTF-8 artifacts for non-portable paths."
    )
    parser.add_argument("roots", nargs="+", help="files or directories forming the scan closure")
    parser.add_argument(
        "--checkout-root",
        action="append",
        default=[],
        help="absolute checkout root to classify specially (repeatable)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="explicit root-relative glob exclusion (repeatable)",
    )
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    args = parser.parse_args(argv)

    try:
        report = scan_paths(
            args.roots,
            checkout_roots=args.checkout_root,
            exclude_globs=args.exclude,
        )
    except ValueError as exc:
        parser.error(str(exc))
    json.dump(
        report,
        sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    )
    sys.stdout.write("\n")
    if report["errors"]:
        return 2
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
