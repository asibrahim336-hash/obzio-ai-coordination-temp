#!/usr/bin/env python3
"""scan-for-credentials.py — OE-W3-CREDENTIAL-ESTATE

Refuses a commit that carries credential-shaped material.

This exists because the discipline "never print a secret" is unenforceable by
intention alone. Several of this lane's own probes handled live credentials,
and at least one standard tool (`gh auth status`) emits token material into
stdout without being asked to. A mechanical gate is the only reliable control.

Two classes are detected:

  KNOWN   — the literal value of a credential this runtime actually holds, or
            of any credential named in CLOUD_AGENT_ALL_SECRET_NAMES. Matching
            is on the value read from the environment; the value is never
            printed, and only its SHA-256 appears in output.

  SHAPED  — strings matching the published prefix grammar of credentials this
            estate plausibly touches (GitHub, Supabase, Cursor, OpenAI,
            Anthropic, Vercel, Cloudflare, AWS, Slack, generic JWT).

Exit 0 = clean, exit 1 = findings. Run before every commit.
"""

from __future__ import annotations
import hashlib
import os
import re
import sys
from pathlib import Path

# Prefix grammars. Deliberately anchored on documented prefixes plus a length
# floor, so ordinary prose and hex digests do not trip the scanner.
SHAPED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github_token",        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("github_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("supabase_pat",        re.compile(r"\bsbp_[A-Za-z0-9]{20,}")),
    ("supabase_publishable",re.compile(r"\bsb_publishable_[A-Za-z0-9_\-]{16,}")),
    ("supabase_secret",     re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{16,}")),
    ("supabase_legacy_svc", re.compile(r"\bservice_role[\"']?\s*[:=]\s*[\"']eyJ[A-Za-z0-9_\-]{20,}")),
    ("openai_key",          re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("anthropic_key",       re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("vercel_token",        re.compile(r"\b[A-Za-z0-9]{24}\b(?=.{0,40}(?i:vercel[_ -]?token))")),
    ("cloudflare_token",    re.compile(r"\b[A-Za-z0-9_\-]{40}\b(?=.{0,40}(?i:cloudflare|cf[_ -]?api))")),
    ("aws_access_key_id",   re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("slack_token",         re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("jwt",                 re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("url_embedded_userinfo", re.compile(r"://[A-Za-z0-9._~%\-]+:[^@/\s\"']{8,}@")),
]

# Substrings that legitimately appear in this lane's prose and must not be
# mistaken for live material. Each is a documented placeholder or example.
ALLOWED_LITERALS = {
    "abcdefghijklmnopqrst",                 # Supabase's own --project-ref example
    "sbp_0000000000000000000000000000000000000000",   # synthetic, used in a probe
    "key_oew3synthetic0000000000000000000000000000000000000000000000000000",
    "key_oew3argvcanary9999999999999999999999999999",
    "aaaaaaaaaaaaaaaaaaaa",                 # synthetic project ref used in a probe
}

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def known_secret_values() -> dict[str, str]:
    """Live credential values this runtime holds, keyed by variable name."""
    names: set[str] = set()
    for var in ("CLOUD_AGENT_ALL_SECRET_NAMES", "CLOUD_AGENT_INJECTED_SECRET_NAMES"):
        raw = os.environ.get(var, "")
        names.update(n.strip() for n in raw.split(",") if n.strip())
    # Credentials that reach the runtime by other means than secret injection.
    for extra in ("GITHUB_TOKEN", "GH_TOKEN", "CURSOR_API_KEY", "SUPABASE_ACCESS_TOKEN"):
        names.add(extra)

    values: dict[str, str] = {}
    for n in sorted(names):
        v = os.environ.get(n)
        if v and len(v) >= 8:
            values[n] = v

    # The GitHub App installation token is not an environment variable; it is
    # held in the gh config and in the git insteadOf rewrite. Pull it from both.
    for path in (Path.home() / ".config" / "gh" / "hosts.yml", Path.home() / ".gitconfig"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"gh[pousr]_[A-Za-z0-9_.\-]{20,}", text):
            values[f"{path.name}:github_token"] = m.group(0)
    return values


def scan_paths(roots: list[Path]) -> int:
    known = known_secret_values()
    known_digests = {name: hashlib.sha256(v.encode()).hexdigest() for name, v in known.items()}
    print(f"scan-for-credentials: {len(known)} live credential value(s) loaded for exact matching")
    for name, dg in sorted(known_digests.items()):
        print(f"  known: {name} sha256={dg}")

    findings: list[str] = []
    scanned = 0

    for root in roots:
        files = [root] if root.is_file() else [
            p for p in root.rglob("*")
            if p.is_file() and not any(part in SKIP_DIR_NAMES for part in p.parts)
        ]
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1

            for name, value in known.items():
                if value in text:
                    findings.append(
                        f"KNOWN  {path}: contains the literal value of {name} "
                        f"(sha256={known_digests[name]})"
                    )

            for label, pattern in SHAPED_PATTERNS:
                for m in pattern.finditer(text):
                    hit = m.group(0)
                    if any(allowed in hit for allowed in ALLOWED_LITERALS):
                        continue
                    line = text.count("\n", 0, m.start()) + 1
                    digest = hashlib.sha256(hit.encode()).hexdigest()[:16]
                    findings.append(
                        f"SHAPED {path}:{line}: matches {label} "
                        f"(len={len(hit)}, sha256_prefix={digest}) — value withheld"
                    )

    print(f"scan-for-credentials: scanned {scanned} file(s)")
    if findings:
        print(f"scan-for-credentials: {len(findings)} FINDING(S) — commit must not proceed")
        for f in findings:
            print(f"  {f}")
        return 1
    print("scan-for-credentials: CLEAN — zero credential-shaped strings")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:] or ["."]
    sys.exit(scan_paths([Path(a) for a in args]))
