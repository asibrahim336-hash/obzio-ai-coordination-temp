# OE-W4 — de-restriction sweep and platform role architecture

Lane `OE-W4-PLATFORM-ROLES` under commission `COM-CUR-ENV-01-20260822-v001`.
Governing input: `../FOUNDER-AUTHORITY-20260822T2225Z.json`.
Base commit `3f3ee110cf9b769e60c664f758c437dcc582afd3`.
Terminal state: `READY_TO_COMMIT`.

Everything here is a **proposal for admission**, not a self-declared binding. It
binds no company strategy, names no model or architecture as bound, and creates
no obligation or spend.

## Read in this order

| File | What it is |
|---|---|
| `DE-RESTRICTION-SWEEP-20260822-v001.md` | Deliverable A, readable. Method, the 22 removals and what each unlocks, the 27 earned controls and the defect each caught, and three removals still live outside this lane's write scope |
| `DE-RESTRICTION-REGISTER-20260822-v001.json` | Deliverable A, structured. 76 constraints, one verdict and justification each. Governs where it differs from the prose |
| `PLATFORM-ROLE-ARCHITECTURE-20260822-v001.md` | Deliverable B, readable. Roles derived from capability asymmetries, the four open questions answered, the overrules and the founder-judgment items |
| `PLATFORM-ROLE-REGISTER-20260822-v001.json` | Deliverable B, structured. 5 platforms, 36 decision classes, 26 functions, 8 return routes |

## Verify it

```bash
python3 tools/derestrictctl.py verify   # exit 0: every verdict carries the evidence its class requires
python3 tools/derestrictctl.py scan     # exit 1 BY DESIGN: 3 removed restrictions are still live
python3 tools/rolectl.py check          # exit 0: 14 invariants hold
python3 tools/negative_tests.py         # exit 0: 20 failure modes rejected
```

Both registers rebuild deterministically:

```bash
python3 tools/build_derestriction_register.py --out /tmp/a.json && diff /tmp/a.json DE-RESTRICTION-REGISTER-20260822-v001.json
python3 tools/build_role_register.py --out /tmp/b.json && diff /tmp/b.json PLATFORM-ROLE-REGISTER-20260822-v001.json
```

**`scan` exiting non-zero is the correct result, not a broken build.** `AI-06`,
`AI-20` and `AI-21` were removed in the register but are still in force in
`commissions/CHATGPT-SIR-01.md`, `state/control-plane.json` and
`commissions/CURSOR-OPERATING-ENVIRONMENT-01.md`. Those paths are outside this
lane's write scope, and two are prohibited paths where a write from this lineage
would silently set currentness for every inheriting branch (`EC-13`). The scanner
reports them so the holder of those paths can act. It will exit 0 once they do.

## Why the tools exist

The founder requires every turn to end in a changed live operation or an
immediately launchable executable, and requires the visibility mechanism in the
architecture to be designed rather than asserted. A register alone would satisfy
neither. So:

- `derestrictctl.py` — verifies the register's evidence discipline, then scans
  live routing surfaces for removed restrictions that are still in force. It is
  negation-aware, so a sentence that *removes* a restriction is classified as a
  `SUPERSESSION_STATEMENT` rather than as a re-inheritance. It did not start that
  way; the pre-fix output is kept as a receipt.
- `rolectl.py` — enforces the authority envelope and contribution ledger:
  single-holder decision classes, founder-reserved classes, acceptance
  independence, runtime-is-not-authority, and a required substitution route per
  function.
- `negative_tests.py` — mutates both registers to trigger 20 named failure modes
  and asserts each is caught. Without it, "the validator works" is an assertion.

## Boundaries kept

Wrote only on `cursor/oe-w4-platform-roles-696d`, only under
`workstreams/so02/control-plane/operating-environment/w4-platform-roles/**` and
`receipts/so02/2026-08-22/oe-w4-platform-roles/**`, from an isolated worktree
(`EC-01`), with every push confirmed by `git ls-remote` (`EC-02`).

No pull request opened, commented on or modified. SW not messaged, operated or
configured. PO-01, PO-03 and MANUS untouched — the `ERROR`-state agent in the
inventory receipt is recorded from list metadata only, with no
`batch-fetch-details` call, no transcript read and no branch access. No
authentication attempted against ChatGPT or any `needsAuth` MCP namespace; the
namespace census reads status, which is not a credential act. No credential value
printed or stored.
