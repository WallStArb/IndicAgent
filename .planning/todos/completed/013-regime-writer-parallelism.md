# 013 — Batch Pipeline Parallelism (regime_writer, ic_engine)

## Problem

Both `regime_writer.py` and `ic_engine.py` process 58 ETF symbols sequentially with a
single DB connection. `regime_writer.py` runs at ~42 min/symbol (GaussianHMM.fit on ~469k
5m bars via single-threaded hmmlearn EM) — ~40h for step 2 alone. `ic_engine.py` has the
same `for symbol in symbols: for tf in tfs:` pattern. Both are pure batch tools with no
real-time component; parallelism applies identically to both.

## Decision

Parallelize at **symbol level** using `ProcessPoolExecutor` (CPU-bound, GIL won't help with
threads). Each worker owns one symbol + all 4 TFs with its own DB connection.

Real-time intraday regime refitting has negligible value — regimes are slow-moving latent
states estimated over years of data; one day shifts parameters by a statistically
insignificant amount. Live inference (forward-filter step per bar) already runs in
`hmm_regime.py`. The only parallelism target is the periodic batch refit.

## Design

**`regime_writer.py`**
- Add `--workers N` CLI flag (default: `min(cpu_count // 2, 16)`)
- APR-back the default: `infra.regime_writer.workers`
- Symbol loop → `ProcessPoolExecutor.map(process_symbol, symbols, chunksize=1)`
- Each worker opens its own psycopg2 connection; no shared state
- Aggregate results and failures back in the main process
- Add `--incremental` flag: only processes symbols where
  `max(market_data_ohlcv.timestamp) > max(feature_vectors.bar_ts WHERE regime IS NOT NULL)`
  — enables efficient nightly run after market close

**Expected speedup**: 58 symbols / 12 workers × 42 min = ~3.5 rounds ≈ 2.5h (vs 40h)

**`corpus_pipeline_run.sh`**: no changes needed; `--workers` is passed through naturally.

**Nightly cron / systemd**: run `regime_writer.py --incremental` after `BarWriter` flush.
Schedule as a oneshot unit triggered by the roll-batch completion signal or a fixed post-close
time (e.g., 20:30 ET).

## Scope

**`services/regime_writer.py`**
- Symbol loop → `ProcessPoolExecutor.map(process_symbol, symbols, chunksize=1)`
- Add `--workers N` flag (default: APR `infra.regime_writer.workers`, seed = `min(cpu_count // 2, 16)`)
- Add `--incremental` flag: only symbols where `max(ohlcv.timestamp) > max(fv.bar_ts WHERE regime IS NOT NULL)`
- Each worker opens its own psycopg2 connection; no shared state

**`services/ic_engine.py`**
- Same ProcessPoolExecutor pattern
- Add `--workers N` flag (APR `infra.ic_engine.workers`)
- RNG: derive per-worker seed deterministically — `np.random.default_rng(bootstrap_seed + abs(hash(symbol)) % 2**31)`
  so results are reproducible per symbol regardless of scheduling order
- `training_window_end` and `existing_keys` passed as read-only args to each worker
- Aggregate `all_results_global` and health gauges back in main process after pool completes

**APR migrations**: add `infra.regime_writer.workers` and `infra.ic_engine.workers` seeds

## Why Not Cell-Level (symbol × tf)?

232 cells in the queue gives more scheduling flexibility but creates worker imbalance (5m
takes 20 min, 1d takes seconds) and 24+ concurrent DB write streams. Symbol-level is simpler
and nearly as fast.
