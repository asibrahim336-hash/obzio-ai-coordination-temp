# PO03-WA-010 — Changed-path enforcement engine

**Hypothesis `H-PO03-WA-010`:** ownership grants plus deny globs can prevent
overlapping subordinate writes before commit.

**Attempt:** `PO03-WA-010-A02`, fence token 2, lease `lease-po03-wa-010-a02`.
Immutable input `workstreams/po03/control/inputs/wave-a/wa-010-a02.json`
(SHA-256 `096d8f69e099ee0abc87d65ed6012720ec16aa7b2bf685b4366d3735ec0fc809`).

## What is here

| Path | Role |
| --- | --- |
| `engine/gitglob.py` | Anchored git-style pathspec matching, plus a decision procedure for whether two patterns can ever match the same path, returning a witness. |
| `engine/ownership.py` | Ownership registry loading, static overlap audit, per-change write admission, `git --name-status -z` parsing, CLI. |
| `engine/reproduce_overlap_prevention.py` | Sanitized reproduction that installs the engine as a real `pre-commit` hook and lets git enforce the decision. |
| `fixtures/` | Disjoint and deliberately overlapping registries; admitted, prohibited, rename/delete and adversarial change sets, each with preregistered reason codes. |
| `tests/` | 118 dependency-free `unittest` cases, including a differential test against git's own pathspec engine and a brute-force property cross-check. |
| `result/` | Executable evidence, the transactional result and the producer return. |

## The two questions the engine answers

**Static overlap, before anything is written.** Two grants are compared as
patterns, not as directory listings, so a collision is found while the tree is
still empty. The comparison is a product-automaton emptiness test over path
segments and then over characters, and it returns a concrete witness path. Every
reported overlap is therefore self-verifying: the test asserts both grants match
the witness.

**Per-change admission.** A deny glob outranks an ownership grant, so a writer
granted `**` still cannot reach `state/**`. A rename is two writes and is checked
on both sides, so it can neither carry a file out of the grant nor drag a foreign
file in. A delete must own the path it removes. A writer presenting a superseded
fence token is refused inside its own subtree.

## Running it

```sh
# Static audit: does any pair of grants collide?
python3 -I engine/ownership.py audit ../../../control/path-ownership.json

# Admission: may this writer commit these staged paths?
python3 -I engine/ownership.py check \
  ../../../control/path-ownership.json \
  --task-input ../../../control/inputs/wave-a/wa-010-a02.json \
  --owner lease-po03-wa-010-a02 --fence 2 --staged --repo <repo>

# Focused suite, no third-party packages
python3 -I -B -m unittest discover -s tests -p 'test_*.py'

# Regenerate every evidence artifact
python3 -I -B result/build_evidence.py
```

Both subcommands exit non-zero when they refuse, which is what makes them usable
as a `pre-commit` hook or a CI gate.

## Why the dialect matters

Git has two glob dialects and they are not interchangeable. A `.gitignore`
pattern with no separator matches a basename at any depth; a `:(glob)` pathspec
is anchored at the tree root. The registry grants are root-relative, so this
engine implements the anchored dialect and is tested against `git ls-files --
':(glob)…'` to prove it rather than merely asserting it.

Anchoring is fail-safe for a grant and fail-dangerous for a deny: a bare
`secrets.json` deny would protect only the repository root. `detect_narrow_deny_patterns`
surfaces that asymmetry with the repair spelled out.

## Scope

Writes are confined to `workstreams/po03/wave-a/units/wa-010/**`. The seeded
registry, contracts, validator, tests and workflow are read only. `state/**`,
`dispatch/**`, PO-01 and PR #8 were never touched. See `result/limitations.json`
for what this engine cannot do — most importantly, it authorises paths rather
than content, and it only binds a writer that actually invokes it.
