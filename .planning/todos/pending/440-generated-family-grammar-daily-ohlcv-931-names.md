---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), section 6.1 (UD-22)
---

# generated_family: register the first grammar over daily OHLCV on the 931 names (attempt 3b)

## What

Discovery without preconceptions: a registered grammar enumerates candidate predictors from
primitives (returns, volume, range, overnight and intraday legs, calendar position, SCH sector
aggregates) with causal operators (lag, difference, trailing mean, z-score and rank,
cross-sectional demean and rank, products of two terms), windows from a fixed menu, depth 2.
Selection and weighting only inside training folds (in-fold IC, then ridge); one grammar
configuration plus selector is one attempt.

1. Write and register the grammar spec (the only preconception is the grammar).
2. Enumerate lazily: never materialize the library (about 5,000 candidates x 931 names x 5,000
   sessions is about 93 GB in float32); per-fold sufficient statistics one candidate block at a
   time, as `combiner.py` does for ridge.
3. Declared memory per generated expression from its windows (E17 L rule, design section 4.5);
   S3 causality probe on a sample of generated members.
4. Run as attempt 3b once the S1 residual target exists on the 931 names and E17's H0 battery has
   ridge cells.

## Done when

The grammar is registered, the enumerator and in-fold selector pass synthetic power and H0 checks,
and attempt 3b is recorded.
