# PO03-WA-055 — three independent candidates ranked by a frozen executable rubric

- Task: `PO03-WA-055`
- Route: `route-07` (`evaluation-and-semantics`)
- Frozen hypothesis: *Three independent candidates are rankable by a frozen executable rubric.*
- Exact model configuration: `claude-opus-5-thinking-high`
- Subordinate terminal report: `READY_TO_COMMIT`

## What was built

`candidate_ranker.py` ranks candidates against a content-addressed rubric. The
rubric digest is computed from its criteria and weights, and `rank()` raises
`RubricMismatch` if the supplied rubric no longer matches the frozen digest — so
the scoring cannot be reconstructed after the preferred answer is known.

Independence is enforced rather than assumed. Candidates with identical score
content collapse, only one candidate per principal survives, and a ranking that
ends up spanning a single model family is refused. Fewer than three independent
candidates is `InsufficientCandidates`, not a low-confidence result.

A missing criterion is `NOT_SUPPORTED`: it lowers `coverage` and is excluded
from the weighted average rather than scoring zero. The output reports the
ranking, the pairwise dominance table, the ties, the declared tie-break rule and
whether the total order is Condorcet-consistent, so a cycle cannot hide behind a
single number.

## Commands and observed result

```
$ python3 -m unittest discover -s . -p 'test_*.py' -v
Ran 22 tests — OK
```

## Hidden and adversarial cases

- All six input permutations of the three candidates must produce an identical
  ranking, and twenty seeded shuffles must produce an identical winner.
- A rubric whose first weight moved from `0.40` to `0.90` must be refused against
  the frozen digest.
- Three clones of one candidate, and three candidates from one model family, must
  both be refused.
- Two candidates with *different* score vectors that weight to the same total
  must tie and then order by the declared rule.

## Defect found while building

The tie test first used two candidates with identical score dictionaries. They
were correctly collapsed by content de-duplication, so no tie ever formed and the
tie-break rule went untested. The case was rebuilt with distinct score vectors
that weight to the same total, which exercises the tie-break instead of the
de-duplicator.

## Limitations

- Scores are supplied in `[0, 1]`. The ranker validates the range but does not
  itself measure candidates; producing the scores is the evaluator's job.
- Independence is approximated by principal identity and score-content equality.
  Two genuinely correlated candidates from different principals would be treated
  as independent.
- Condorcet consistency is reported over the weighted totals. Because a single
  weighted score induces a total order, the check confirms internal consistency
  rather than resolving a true pairwise-preference cycle.

## Disposition

**PASS** — the ranking is permutation-invariant and digest-bound, fewer than
three independent candidates or a single model family is refused, and unscored
criteria lower coverage instead of scoring zero.
