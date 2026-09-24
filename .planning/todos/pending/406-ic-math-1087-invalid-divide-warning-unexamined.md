---
status: pending
priority: P3
filed: 2026-09-24
source: carried out of todo 386's "Also seen, unverified" section when 386 closed
---

# `ic_math.py` invalid-divide RuntimeWarning never examined

`RuntimeWarning: invalid value encountered in divide` from
`src/intelligence/statistics/ic_math.py` (the `np.sqrt(np.where(neg_mask, window_ics**2,
0.0).sum(axis=0) / sum_neg)` downside-deviation line, ~1087 at the time) appeared in a
2026-09-20 corpus rerun's stdout. Looks like a zero `sum_neg` producing NaN, not a crash.
Not checked: whether earlier runs emitted it, and whether a NaN reaches a written column
(`ic_sortino`?). Check the next corpus run's log, then either guard the zero case explicitly or
confirm the NaN is intended and mapped to NULL.
