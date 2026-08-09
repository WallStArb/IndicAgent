# 290 - `regime_volatility` path: memory-footprint and query-efficiency follow-ups

**Filed:** 2026-08-09
**Source:** Phase 172 execute-phase `/simplify` gate, efficiency-angle review
**Status:** pending, not blocking

## The gaps

Measured during Phase 172's `/simplify` pass over `services/regime_writer.py`,
`services/ic_engine.py`, and `src/config/vocabulary_drift.py`. None are correctness bugs;
all are real, measured cost this phase introduced or left in place. Deliberately deferred
from the phase's own cleanup pass because fixing them touches HMM-fitting/DB-write hot
paths that deserve dedicated review rather than a same-session bolt-on right after a
7-plan corpus relabel landed.

1. **`_build_obs_matrix_volatility`'s `_rolling(..., np.std)` at window=250 allocates
   ~790 MB of transient memory per call, per worker** (`services/regime_writer.py`,
   `_build_obs_matrix_volatility`). Migration 308 set `vol_window`/`vol_of_vol_window` to
   250 (up from the legacy trend path's 20). At the largest 5m cell (395,609 bars) that's
   ~790 MB per `_rolling` call, twice per cell, inside each `ProcessPoolExecutor` worker —
   with a 12-worker pool, up to ~9.5 GB of concurrent transient allocation that did not
   exist before this phase (the legacy path at window 20 peaks at ~63 MB). Real OOM risk on
   a future full-corpus `--refit` run. Fix: chunk the rolling-std reduction in row-blocks
   (bit-identical result, bounded memory), or compute via prefix sums of `x`/`x²`.

2. **Per-cell `count(*)` verification query in `_write_regime_volatility_results`/
   `_write_regime_results`** (~626ms measured on SPY/5m, ~10 min aggregate across a full
   corpus run, serialized on the main write connection). `n_updated` is already known via
   `cur.rowcount` from the JOIN-UPDATE; `null_remaining` could be one `GROUP BY symbol, tf`
   query at end-of-run instead of one scan per cell.

3. **`vocabulary_drift.py`'s new `regime_volatility` namespace query is a second full-window
   `SELECT DISTINCT` scan** over the same `bar_ts` window the existing `regime_hmm` query
   already scans, run sequentially. Combine into one query returning both `array_agg(DISTINCT
   ...)` columns, or dispatch the (already-independent) namespace queries concurrently.

4. **`ops_regime_null_out_and_verify.py`'s per-cell SQL rebuild**: the generalization to
   `_ColumnFamily` replaced precomputed module-level SQL constants with `_build_*()` calls
   inside the per-cell loop, so each `(symbol, tf)` iteration re-joins the owned-column list
   and re-validates the label column. Absolute cost is negligible (microseconds vs
   second-scale queries) but it's a straight regression from precomputed to recomputed —
   free fix: derive these as `_ColumnFamily.__post_init__` fields, computed once.

## Where

- `services/regime_writer.py` — `_build_obs_matrix_volatility`, `_write_regime_volatility_results`,
  `_write_regime_results`
- `services/ic_engine.py` — startup gate (partially addressed: `count(*)` → `EXISTS` fixed in the
  phase's own `/simplify` pass; this todo is the remaining items)
- `src/config/vocabulary_drift.py` — `run_drift_audit`'s per-namespace query loop
- `scripts/ops/corpus/ops_regime_null_out_and_verify.py` — `_ColumnFamily`
