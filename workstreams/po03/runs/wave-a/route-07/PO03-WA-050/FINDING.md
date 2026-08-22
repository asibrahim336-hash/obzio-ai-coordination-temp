# PO03-WA-050 — self-acceptance stays blocked when identities are aliased

- Task: `PO03-WA-050`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *A producer cannot self-accept through identity aliasing.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`acceptance_authority.py` resolves any identity claim to a **durable principal**
before the distinctness test is applied. The durable key is
`function::appointment`; display names, handles, e-mail forms and declared
aliases are all routes to that key, never identities in their own right.

`normalize_identity()` defeats the aliasing vectors that break a naive string
comparison: NFKC compatibility folding, zero-width and soft-hyphen insertion,
Cyrillic/Greek/fullwidth homoglyph substitution, case folding, separator
variation and the `handle@domain` form.

The component also enforces the repository operator rule that `Operator D`,
`Claude extension`, `Claude browser operator` and `principal AI operator` are
historical or colloquial aliases: they resolve normally inside `alias`,
`runtime`, `runtime_binding` and `provenance` fields, and raise
`IdentityRoutingError` when used to route a reviewer.

Finally, `authorize_acceptance()` refuses a consequential decision unless the two
sides sit in different frontier model families, and the record it returns states
that no terminal state is granted — the permitted reviewer outputs are exactly
`RECOMMEND_ACCEPT`, `RECOMMEND_REJECT`, `RETEST`.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 17 tests — OK
```

## Hidden and adversarial cases

`test_every_alias_of_the_producer_is_blocked_as_reviewer` runs eight aliasing
attacks against the same producing principal — case, separator, e-mail,
homoglyph, zero-width, appointment identifier, function identifier and display
name — and asserts `SelfAcceptanceBlocked` for every one. Every prohibited
routing alias is swept in a separate subtest, and the same alias is then shown
resolving correctly in a provenance field, so the rule constrains routing without
destroying evidence.

## Limitations

- The homoglyph table covers the confusables actually reachable from Latin
  handles in this repository. It is not a complete Unicode confusables mapping,
  so a sufficiently exotic script substitution could still resolve to no
  registered principal — which fails closed with `IdentityRoutingError` rather
  than authorising, but reports the wrong reason.
- Model-family separation is checked from the recorded `model_family` field. The
  component cannot itself observe which model executed; that binding is runtime
  evidence supplied by the caller.
- Identity registration is trusted input. A poisoned registry that files a
  producer alias under a second principal would defeat the check; registry
  integrity is a custody concern, not an identity-resolution concern.

## Disposition

**PASS** — every aliased spelling of the producing principal is refused as its
own reviewer, and consequential acceptance additionally requires a second
frontier family.
