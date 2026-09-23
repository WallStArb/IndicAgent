---
status: pending
priority: P3
filed: 2026-09-23
source: /simplify altitude review of the Phase 174 code review fix branch (fix/174-code-review)
---

# Universe dimensions as database views, with a CI boundary test on raw `instruments` reads

## What

Each eligibility universe (`backfill`, `compute`, `compute_1d`, `live`) now has one
definition in Python: `src/config/settings.py`'s `_ACTIVE_CONTRACTS_DIMENSION_CLAUSES`,
exposed to SQL readers through `dimension_where_clause(dimension, alias)` (174 review WR-01
fix). That closes the drift for readers that call it, but nothing forces a new reader to:
any query can still write `FROM instruments WHERE is_active = true` and silently mean the
wrong universe, which is exactly how the D-09 pilot cohort leaked into TagCalibrator's
BH-FDR family.

The deeper fix is one view per dimension (`instruments_backfill`, `instruments_compute`,
`instruments_compute_1d`, `instruments_live`) in a migration, `dimension_where_clause` and
`get_active_contracts` reading them, and a boundary test in the style of
`tests/unit/test_market_data_ohlcv_boundary.py`: a raw `FROM instruments` read outside the
views needs an allow-list entry with a reason (lookups such as tick sizes, the vocabulary
drift auditor and the API legitimately read every row).

## Why not done in the fix branch

It touches every existing `instruments` reader (about a dozen, several in dormant v2.x code)
and needs a new CI test with an allow-list, which is beyond a review-fix branch. The
accessor removes the duplication that existed; this makes the next one impossible.

## Gate

None. Opportunistic, before the next universe-expansion phase adds readers.
