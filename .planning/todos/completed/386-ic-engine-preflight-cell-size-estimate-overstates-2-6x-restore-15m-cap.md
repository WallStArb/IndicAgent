---
status: closed
priority: P1
filed: 2026-09-21
closed: 2026-09-24
source: 2026-09-17 full corpus ic_engine run died 2026-09-20 09:19 UTC after 2.6 days on a guard artifact; worked around with an APR-only cap raise (migration 347) that leaves the guard loosened until this lands
---

# ic_engine pre-flight cell-size estimate overstates real rows by 2-6x and killed a 2.6 day run; replace it with an exact count and restore `alpha.ic.max_cell_rows` to 15,000,000

## What

Commit `100f0602b` (2026-09-15, Phase 174-05, todo 371) added a pre-flight `CellTooLargeError` check in
`services/ic_engine.py` (about line 4702) that estimates a cross-sectional cell's rows as
`len(regime_timestamps) * len(symbol_list)`. That assumes every symbol has a feature row at every
regime timestamp. Most symbols have far less feature history than the 2006 regime timestamps, so it
overstates. Measured 2026-09-20 by joining `market_regimes` to `feature_vectors` (all 233 symbols, so
an upper bound for the 182-symbol equity group):

| Cell | Estimate | Real rows |
|---|---|---|
| 15m high_bear | 21,523,866 | 4,100,729 |
| 5m high_bear | 64,030,512 | 11,435,299 |
| 5m mid_neutral | 26,468,988 | 12,542,631 (largest real cell) |

Against the 15,000,000 cap the estimate tripped on the first 15m cross-sectional cell, and the run
failed loud after finishing the per-symbol pass and the 1d/1h cells. The estimate is also what selects
disk-backed mode and sizes the scratch-disk headroom check (2.2 x estimate x features x 4 bytes), so
cells run disk-backed and demand scratch space they do not use.

## Current state (temporary)

Migration 347 raised `alpha.ic.max_cell_rows` from 15,000,000 to 100,000,000 so the estimate cannot
trip (largest estimate is 98,055,230, 5m low_bull). `max_cell_rows` is operational (excluded from the
cell fingerprint), so completed cells stayed valid. The post-materialization check reads the same
value against the real count, so the crash-loud guard is loose until this todo lands.

## Fix

1. Replace the estimate with an exact count: the join query takes about 7 s for all 15m and 5m cells of
   a group. The code comment says not to tighten the estimate because an underestimate reintroduces the
   OOM; an exact count is not an underestimate, and the comment's premise (no extra fetch) is cheap to
   drop. Use the exact count for the cap check, the disk-backed decision and the headroom check.
2. Restore `alpha.ic.max_cell_rows` to 15,000,000 (or re-derive from the real largest cell, 12.5M, with
   the usual margin) through a migration, with a `config_history` reason.
3. Add a unit test that a sparse-history cell is not rejected on a full-density estimate.

## Gate

This edits `services/ic_engine.py`, which moves `code_content_key` and invalidates every completed cell
(AST hash of all imported first-party modules). Land it together with the other ic_engine code changes
(todo 385 levers) immediately before the next recompute that is already required, never mid-run. Also
close todo 371 at the same time: its OOM at 5m high_bear (2026-09-07) is fixed by 174-05's disk-backed
accumulator, verified by 5m high_bear completing 2026-09-21 with about 12 GB peak anonymous memory.

## Also seen, unverified

`RuntimeWarning: invalid value encountered in divide` from `src/intelligence/statistics/ic_math.py:1087`
(`np.sqrt(np.where(neg_mask, window_ics**2, 0.0).sum(axis=0) / sum_neg)`), in the rerun's stdout. Looks
like a zero `sum_neg` giving NaN, not a crash. Not checked whether earlier runs emitted it or whether a
NaN reaches a written column.

## Closure (2026-09-24)

All three fix items shipped in migration 353 (perf/ic-engine-speedups, before the 176-08 run):
the exact cross-sectional row count (`_count_cross_sectional_cell_rows`) drives the cap check,
disk-backed decision and headroom check; `alpha.ic.max_cell_rows` is back to 15,000,000; and
`tests/unit/test_ic_engine_cell_memory_bound.py::test_sparse_history_cell_not_rejected_on_full_density_estimate`
pins the sparse-history case. The 176-08 run completed under it. The unverified divide warning
above moved to todo 406.
