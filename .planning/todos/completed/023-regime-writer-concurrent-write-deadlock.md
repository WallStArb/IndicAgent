# Todo 023 — regime_writer concurrent write deadlock

## Problem

`regime_writer` runs HMM fitting with `ProcessPoolExecutor` (12 workers, 1 worker per symbol). Each
worker does its own `execute_batch` UPDATE to `feature_vectors` concurrently. On a 54M-row
TimescaleDB hypertable with chunk-level indexes on `(tf, bar_ts)`, 12 concurrent writers lock the
same index pages in unpredictable order → deadlock cascade. On the June 26 corpus run, the deadlock
started within 2 seconds of step 2 launch and cascaded to all 12 workers over 4 hours before
discovery. PostgreSQL's deadlock detector did not break it (not a true cycle; linear wait chain).

## Root Cause

Violated SoC: compute parallelism and write serialization are separate concerns. Workers should own
compute only; the orchestrator should own persistence.

## Fix

Modify `_run_symbol_worker` to return `update_rows` (already built, small in memory) to the main
process instead of doing the UPDATE itself. The main process collects all results and does a single
write pass — either:

1. **Sequential symbol loop** (simplest): main iterates results, calls `_write_regime_results(conn,
   symbol, tf, rows)` one at a time. Zero contention; same total write time since write is fast.
2. **COPY + UPDATE FROM temp** (fastest): COPY all rows into a temp staging table, then single
   `UPDATE feature_vectors SET ... FROM staging WHERE ...`. One pass, one lock acquisition order,
   no deadlock possible.

Option 1 is sufficient. Option 2 is an optimization if step 2 is ever a throughput bottleneck.

## Workaround (current corpus run)

Regime was already fully populated from a previous run. Skipped step 2 entirely and resumed from
step 3. No data loss.

## Impact

Step 2 (regime_writer) is currently skipped on resumption because regime was pre-populated. Fix
before the next full corpus rebuild.

## Resolution (2026-06-26)

Fixed on branch `feat/regime-writer-compute-write-split` (commits 52b76ce0..2c2cb16a).

- `_compute_symbol_tf` — pure HMM compute, runs in workers, returns `(update_rows, converged)` or `None`
- `_write_regime_results` — serial DB write, runs in main process only
- `main()` opens single `write_conn`, calls `_write_regime_results` per cell
- Side-effect fix: `REGIME_WRITER_ROWS_UPDATED_TOTAL` was double-counted in old code; now emitted once in `main()`

## Remaining gaps (minor, acceptable)

- No unit test for `_write_regime_results` (requires DB integration)
- No unit test for `_run_symbol_worker` dict shape `{tf, update_rows, converged}`
