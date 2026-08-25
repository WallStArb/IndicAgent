---
status: pending
priority: P2
filed: 2026-08-25
source: Phase 173 Plan 04 Task 3 -- surfaced during the live smoke run's largest-cell
  (equity/5m/low_bull) OOM-regression check
---

# `_compute_cross_sectional_tf`'s chunked fetch query is pathologically slow on the largest
# cross-sectional cell -- pre-existing, not a Phase 173 regression

## What

Running `_compute_cross_sectional_tf` directly against the corpus's largest known
cross-sectional cell (`regime_group='equity'`, `tf='5m'`, `regime_label='low_bull'` --
554,448 `market_regimes` timestamps, 63 peer symbols, 3,097,180 total joined rows,
`training_window_end='2025-12-24T05:15:00+00:00'`) to smoke-test Phase 173 Plan 04's new
broadcast cell (`_compute_one_broadcast_cell`), the chunked fetch loop (`chunk_sql` inside
`services/ic_engine.py::_compute_cross_sectional_tf`, `cs_chunk_ts=5000` timestamps per chunk,
~111 chunks total) took **over 95 minutes and still had not finished fetching** when the run
was killed to make forward progress on the smoke test.

Per-chunk cost was highly variable: the first observed chunk completed in ~2.5s, but chunks
observed later in the same run took 50s-100s+ each, with the underlying `postgres` backend
process pinned at 100% CPU (`top` confirmed, host PID distinct from the container-internal
`pg_stat_activity.pid`) for the query's full duration -- genuinely CPU-bound work server-side,
not a lock wait or idle connection (`pg_stat_activity.wait_event` was NULL throughout, `pg_locks
WHERE NOT granted` returned 0 rows).

## Why this matters

This SQL (`chunk_sql` inside `_compute_cross_sectional_tf`) is **unchanged by Phase 173** --
Plan 04 only adds a new downstream compute function (`_compute_one_broadcast_cell`) that
consumes the fetch's already-materialized arrays; it does not touch the fetch query itself. So
this is a pre-existing performance characteristic of the corpus's largest cell, only now
directly observed because Phase 173's smoke-run task required exercising that exact cell live.
It was not previously caught because: (1) the corpus's last full run against this cell
(`training_window_end='2025-12-24T05:15:00+00:00'`, `computed_at≈2026-08-23`) evidently
completed -- 1192 pre-existing rows existed before this smoke run's archive-then-delete step
removed them -- but nothing recorded how long that run actually took per-cell; ic_engine's own
run logs don't structurally break out per-chunk fetch timing today.

At ~95 minutes and still incomplete for one cell out of the full corpus (`_DEFAULT_TFS = ["1d",
"1h", "15m", "5m"]` × 4 enabled regime_groups × several regime_labels each), if this cell's cost
is representative of other large 5m cells (`rates/5m/flat_wide` at 439K timestamps,
`rates/5m/flat_tight` at 382K, `equity/5m/mid_bull` at 372K, `equity/5m/high_bear` at 359K are
all in the same order of magnitude), the full corpus's cross-sectional pass could be
dramatically slower than assumed -- worth measuring end-to-end, not assumed.

## Side effect this smoke run left behind (already self-healing, no action required)

The smoke run replicated `main()`'s archive-then-delete step (todo 252 pattern) before the kill,
so `feature_ic_scores` currently has **zero live rows** for
`(symbol='POOLED', tf='5m', regime='low_bull', regime_scope='cross_sectional',
training_window_end='2025-12-24T05:15:00+00:00')` -- the pre-existing 1192 rows were archived
cleanly to `feature_ic_scores_history` (confirmed: 3576 rows now present there for this cell,
covering all training_window_end vintages), not lost. This is a normal, recoverable
"crash-mid-recompute" state, structurally identical to what a real corpus pipeline crash would
leave -- and Phase 173's own `broadcast_hash` fingerprint-invalidation change already forces a
full corpus-wide recompute on the next real `ic_engine.py` run regardless of this smoke test, so
this cell will be recomputed as part of that run with no separate follow-up needed purely to
"fix" this gap.

## What needs to happen

1. **Measure, don't assume** (per `docs/foundation/performance-investigation-sop.md`): run
   `EXPLAIN (ANALYZE, BUFFERS)` on `chunk_sql`'s query shape (5-way-ish JOIN:
   `feature_vectors` ⋈ `forward_returns` filtered by `tf`, `bar_ts = ANY(ts_chunk)` (an array of
   up to 5000 timestamps), `symbol = ANY(symbol_list)`, `fr.return_type =
   'executable_open_to_open'`) against a representative large `ts_chunk` to see whether the
   planner is choosing an efficient plan (index scan + chunk exclusion on the `feature_vectors`/
   `forward_returns` hypertables) or falling back to a sequential scan / suboptimal join order
   for this specific filter shape.
2. Check whether `work_mem = '256MB'` (set per-connection at the top of
   `_compute_cross_sectional_tf`) is sufficient for this join's sort/hash requirements at
   `cs_chunk_ts=5000` chunk size, or whether chunks are spilling to disk.
3. Check TimescaleDB chunk exclusion is actually engaging for the `bar_ts = ANY(...)` predicate
   shape (an `ANY(array)` predicate does not always chunk-exclude as cleanly as a `BETWEEN`
   range on some TimescaleDB versions/configurations).
4. If a genuine fix is found (missing index, chunk-exclusion gap, suboptimal `cs_chunk_ts`),
   file it as its own scoped fix -- do not bundle into this todo.

## Scope

Out of scope for Phase 173 (D-05 explicitly locks the fetch phase's shape; Plan 04 reuses it
unmodified). File for future prioritization -- likely relevant before/during the next full
corpus pipeline run, since Phase 173's fingerprint invalidation forces exactly this cell (and
every other cross-sectional cell) to recompute on that run regardless.
