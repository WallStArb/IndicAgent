---
status: closed
priority: P2
filed: 2026-07-18
moved_to_deferred: 2026-07-18
closed: 2026-07-23 — mechanism shipped via Phase 162-02
source: /simplify pass (efficiency review) on the ic_engine cross-sectional bootstrap
  threading commits (28fe12ac, migration 239_ic_engine_cross_sectional_bootstrap_threads.sql)
---

**CLOSED 2026-07-23 (Phase 162-02):** `cross_sectional_bootstrap_threads` is now a per-tf APR
dict (migration 250: `5m=6, 15m=1h=1d=1`), exactly this todo's option (a). The one piece not
literally executed as this file's "Fix" section specified -- a live wall-clock A/B benchmark of
`max_workers=1` vs `=6` on 15m/1h/1d before picking the value, rather than seeding it from the
original migration's reasoning -- is tracked as an open human-verification item in
`.planning/milestones/v3.1-phases/162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t/162-HUMAN-UAT.md`
(item 3), not a separate pending todo.

**Moved to deferred/ 2026-07-18 (priorities/matrix reconciliation pass):** registered as
ROADMAP **Phase 162 "ic_engine Corpus Pipeline Throughput"**, plan 162-01 by name in that
phase's Fable-refined breakdown. Grouped here with sibling todos [122](../pending/122-ic-engine-checkpoint-blind-to-apr-config-drift.md)
(162-02, absorbed into 134) and [134](134-ic-engine-incremental-recompute.md) (162-02 core) for
consistency — all three are Phase 162 raw material, not independently-actionable pending/ items,
same treatment given to todo 026's P1-P3 items once Phase 144 absorbed them. Revive at
`/gsd-plan-phase 162`.

# `cross_sectional_bootstrap_threads` is a single scalar; every other per-tf cost knob in this file is a dict

## Finding

`bootstrap_block_size` (`ic_engine.py:457-459`) is already a per-tf dict
(`{"5m": 78, "15m": 26, "1h": 10, "1d": 10}`) precisely because per-tf cost varies by orders of
magnitude. The new `cross_sectional_bootstrap_threads: int = 1` (migration
`239_ic_engine_cross_sectional_bootstrap_threads.sql`, seeded to 6) is a single scalar wired
uniformly to every tf via `src/intelligence/statistics/ic_math.py`'s
`max_workers=config.cross_sectional_bootstrap_threads`.

The migration measured and justified 6 threads *only* for the worst-case 5m cell
(n=361674, ~8h53m serial). Its own comment states 1d/1h/15m cells finish in "minutes" serially —
yet those cells still get the full 6-thread pool and the batched-barrier loop
(`for b in range(0, n_boot, max_workers)` → 2000/6 ≈ 334 synchronization barriers each run,
each blocking on `pool.map` for the slowest of 6 threads). For small-n cells, per-iteration
compute (rankdata + IC on a few thousand rows) is small enough that thread
dispatch/GIL-reacquisition overhead per batch can approach or exceed the compute saved —
spending overhead on tfs that were never the bottleneck the migration was measuring.

## Why this wasn't fixed inline

Making `cross_sectional_bootstrap_threads` per-tf requires the same treatment
`bootstrap_block_size` originally got: a benchmark run per tf to pick real values (not a guess),
a new migration adding per-tf APR keys, and reseeding `config_state`. The corpus rerun that would
be the natural place to benchmark against was actively running (P0 resource priority) when this
was found — running a competing benchmark script then would have been the wrong call. Filed
instead of guessed at.

## Fix

Once the corpus rerun's DB/CPU load clears: benchmark 15m/1h/1d cross-sectional cells' actual
wall time under `max_workers=1` vs `max_workers=6`, then either (a) convert
`cross_sectional_bootstrap_threads` to a per-tf dict like `bootstrap_block_size` (new migration,
per-tf APR keys), or (b) gate threading on measured row count (`n`) at the
`_compute_cross_sectional_tf` call site instead of a corpus-wide constant, whichever the
benchmark data supports.

## References

- `services/ic_engine.py:457-467` — `bootstrap_block_size` (per-tf, the existing pattern) vs
  `cross_sectional_bootstrap_threads` (scalar, this gap)
- `production/migrations/239_ic_engine_cross_sectional_bootstrap_threads.sql` — the original
  6-thread benchmark, scoped to the 5m worst case only
- `src/intelligence/statistics/ic_math.py` — `_circular_block_bootstrap_ic`'s `max_workers`
  threading implementation
