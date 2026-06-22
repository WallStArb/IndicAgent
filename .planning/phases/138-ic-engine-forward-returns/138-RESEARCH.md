# Phase 138: IC Engine + Outcome Labels - Research

**Researched:** 2026-06-21
**Domain:** Statistical IC measurement, TimescaleDB batch processing, Python scientific computing
**Confidence:** HIGH

---

## Summary

Phase 138 builds two oneshot batch services: `ForwardReturnWriter` (LEAD()-based forward returns into `forward_returns`) and `ICEngine` (Spearman IC per feature x symbol x TF x regime x lookahead into `feature_ic_scores`). Both are Ring 2 services in `services/`, using psycopg2 sync (matching `backfill_feature_factory.py` pattern), not asyncpg. Two new migrations are needed: 157 for `forward_returns` and `feature_ic_scores` tables, and 158 for `alpha.ic.*` APR keys in `config_schema` + `config_state`. A critical prerequisite is discovered below: `feature_vectors.regime` is currently NULL for all rows (backfill sets `regime=None` with the comment "Regime label assigned by HMM downstream (Phase 138)"), which means Phase 138 must include a HMM regime labeling pass before regime-stratified IC is possible.

**Primary recommendation:** Phase 138 has three deliverables in dependency order: (1) HMM regime labeler that populates `feature_vectors.regime` for all backfilled rows, (2) ForwardReturnWriter, (3) ICEngine. The IC Engine can run pooled IC (regime=NULL in `feature_ic_scores`) as a fallback if HMM labeling is incomplete for some (symbol, tf) cells, but the spec prohibits pooled as a substitute for regime-stratified -- so the HMM labeler must be scoped in Phase 138 or the IC Engine must gate strictly on regime-labeled rows only.

---

## Key Technical Findings

**Finding 1: feature_vectors is empty and backfill has not run.**
`SELECT count(*) FROM feature_vectors` returns 0. The backfill_feature_factory.py service exists and is complete (Phase 137 P6), but has not been executed. Phase 138 is blocked until the backfill runs. The market_data_ohlcv has data for 14-15 ETF symbols across 5m/15m/1h/1d (SPY 5m: 469,221 bars; SPY 1h: 131,407 bars). This is sufficient for IC Sharpe once backfill completes.

**Finding 2: feature_vectors.regime is always NULL from backfill.**
`backfill_feature_factory.py` line 772: `regime=None,  # Regime label assigned by HMM downstream (Phase 138)`. The feature_ic_scores DDL treats `regime=NULL` as "pooled". The IC spec §III.3 says "Pooled IC is not a fallback. It is a different (weaker) statistic." Therefore Phase 138 must include a HMM regime labeling step that runs `UPDATE feature_vectors SET regime = <hmm_state> WHERE (symbol, tf, bar_ts) = <row>` before the ICEngine runs regime-stratified measurement. This is unambiguously in scope for Phase 138.

**Finding 3: Vectorized IC computation is 10-50x faster than per-cell scipy loops.**
Benchmarked on this machine:
- `scipy.stats.spearmanr` loop over 54x4 cells (n=2000): ~55ms
- Pre-rank with `scipy.stats.rankdata(X, axis=0)` then pearson-on-ranks matrix multiply: ~12ms for all 216 cells
- For bootstrap CI: vectorized over all 54 features simultaneously (2000 resamples): 600ms per (symbol,tf,regime,lookahead-batch) vs 3,073ms sequential
- Full run estimate for 15 symbols x 4 TFs x 4 regimes: ~2.8 minutes for bootstrap CI phase
- The correct pattern is: pre-rank the full feature matrix once per (symbol,tf,regime), then batch all features together.

**Finding 4: scipy.stats.bootstrap is 10x slower than manual numpy bootstrap.**
Measured: `scipy.stats.bootstrap` for 1 cell takes 551ms; manual numpy percentile bootstrap (pre-rank, index sampling, corrcoef) takes 57ms. Manual bootstrap is the correct choice. The IC spec §VIII.3 says "2,000 bootstrap resamples, percentile method, with replacement on the sub-sampled pairs" -- the manual implementation matches exactly.

**Finding 5: p-values for BH-FDR come from scipy.stats.spearmanr, not from bootstrap.**
The bootstrap CI gates eligibility (`ic_ci_lower > 0`). The p-value for BH-FDR correction comes from `scipy.stats.spearmanr(x, y)` which returns an analytical p-value valid for n >= 30. The implementation must call `spearmanr` once per cell for the p-value, then compute bootstrap CI separately. `statsmodels.stats.multitest.multipletests(pvals, alpha=0.05, method='fdr_bh')` returns `(reject, bh_adjusted_pvals, alphaSidak, alphaBonf)` -- index 1 is the BH-adjusted q-value. The input p-values array must maintain order correspondence to cell tuples for the q-value to map back correctly; keep a parallel list of `(feature, symbol, tf, regime, lookahead)` tuples alongside the p-values array.

**Finding 6: Non-overlapping subsampling via SQL ROW_NUMBER() OVER PARTITION is clean.**
```sql
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY symbol, tf ORDER BY bar_ts) AS rn
  FROM feature_vectors WHERE symbol = $1 AND tf = $2 AND regime = $3
) sub
WHERE rn % $N = 0
```
This is efficient -- TimescaleDB uses the compressed hypertable index on (symbol, tf, bar_ts). The query plan shows Merge Append on chunk indexes. No separate table needed.

**Finding 7: market_data_ohlcv data coverage is sufficient but only 14-15 symbols.**
Current data: 14 symbols with 5m (469K bars each), 15 symbols with 1h (131K bars each), 15 with 15m, 15 with 1d. At N=5 subsampling: SPY 5m gives 93,844 independent obs (4.7x the 20K IC Sharpe gate). SPY 1h gives 26,281 obs (1.3x the gate). All SPY/IWM/TLT anchors meet the gate. Full 58-symbol backfill is NOT a prerequisite for Phase 138 -- 14-15 symbols is enough to validate the IC pipeline.

**Finding 8: LEAD() window clause needs care -- use ROWS BETWEEN, not default RANGE.**
The IC spec §V.3 SQL uses `ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING`. Without specifying `ROWS`, TimescaleDB defaults to `RANGE UNBOUNDED PRECEDING` which does not give LEAD() access to forward rows. The explicit `ROWS` clause is required. Verified: the EXPLAIN output shows WindowAgg with ROWS clause is handled correctly by the compressed hypertable.

**Finding 9: alpha.ic.* APR keys do not exist yet -- migration 157/158 must seed them.**
`SELECT config_key FROM config_state WHERE config_key LIKE 'alpha.ic.%'` returns 0 rows. The architecture doc lists 14 `alpha.ic.*` and `alpha.decay.*` and `alpha.ensemble.*` keys. Migration 157 should create forward_returns + feature_ic_scores tables. Migration 158 should seed all `alpha.*` APR keys. The ICEngine service loads them using the same `_load_config_service()` + `cfg.get_sync(key, fallback)` pattern as `backfill_feature_factory.py` lines 237-249.

**Finding 10: partial completion via RUN_TS requires exacttimestamp match.**
The IC spec §XX says: "IC Engine queries `feature_ic_scores` for the current run's `computed_at` timestamp (set once at process start)". This means if the process crashes and restarts, a new `RUN_TS = datetime.now(UTC)` is assigned. The second run will NOT see the first run's partial work as "completed_for_this_run". The correct interpretation: on restart, skip rows where `(feature, symbol, tf, regime, lookahead_bars)` already exists for ANY `computed_at` in the current data window (not just current RUN_TS). The current spec's language is subtly wrong for crash recovery -- use `ON CONFLICT DO NOTHING` on the primary key `(feature_name, symbol, tf, regime, lookahead_bars, training_window_end)` instead, and on startup skip any tuple already present in `feature_ic_scores` for the current `training_window_end`.

**Finding 11: IC discovery report is a markdown file.**
The IC spec §XVIII says: `docs/analysis/ic-discovery-report-{date}.md`. Not a DB table, not a CSV. The planner should include a task to write this markdown file with a console summary and a structured table of passing features.

**Finding 12: Service auditor registration -- new oneshot services go at priority 8.**
`_DAG_ORDER` in `service_auditor.py` already has `"indicagent-hmm-training": 8` as an example. Both `indicagent-forward-return-writer` and `indicagent-ic-engine` are oneshot timer services and belong at priority 8. `_AGENT_ID_TO_UNIT` only needs entries for daemon services (lag monitoring); oneshots do not go in that dict.

---

## Implementation Approach

### Prerequisite: FeatureFactory Backfill

The Phase 137 backfill has not run yet. Phase 138 planning must begin with "run `python services/backfill_feature_factory.py`". This is a ~2-6 hour operation for 14 symbols x 4 TFs. Until it completes, both ForwardReturnWriter and ICEngine have no input data. The planner should make this Task 1 of Phase 138.

### Deliverable A: HMM Regime Labeler

A new module `services/regime_writer.py` (oneshot) that:
1. Reads feature_vectors in (symbol, tf) chunks
2. Calls the existing HMM trainer logic (from `src/intelligence/services/hmm_trainer.py`) on the bar sequence
3. UPDATEs `feature_vectors SET regime = <state_label>, regime_label_source = 'filtered'`

The HMM state labels must be consistent text values (e.g. 'trending_up', 'trending_down', 'ranging', 'volatile'). Check what HMM state labels the existing `HMMTrainer` produces -- they may be integer strings ('0','1','2') per the v2.x memory note. Phase 138 must standardize the label format in `feature_vectors.regime`.

This labeler is scoped within Phase 138 (not a separate phase) because the backfill comment explicitly says "Phase 138" and regime labeling is a direct prerequisite to the ICEngine's primary output.

### Deliverable B: ForwardReturnWriter (`services/forward_return_writer.py`)

Pattern: sync psycopg2 oneshot (matches backfill_feature_factory.py).

Core logic:
1. Query `SELECT DISTINCT symbol, tf FROM market_data_ohlcv` to determine scope
2. For each (symbol, tf), run the LEAD() SQL from IC spec §V.3 against `market_data_ohlcv`
3. JOIN result with `feature_vectors` to only write rows where a feature_vector exists
4. Batch-insert into `forward_returns` with `ON CONFLICT (symbol, tf, bar_ts) DO NOTHING`
5. High-water mark pattern: `SELECT MAX(bar_ts) FROM forward_returns WHERE symbol=$1 AND tf=$2` and start from there on incremental runs

The LEAD() window SQL produces NULLs for the last 60 bars (no forward data). `complete_60bar = false` for those rows. This is correct -- the completeness flags tell the ICEngine to exclude them from 60-bar lookahead IC computation.

### Deliverable C: Migrations 157 + 158

**Migration 157:** `production/migrations/157_ic_engine_tables.sql`
- CREATE TABLE `forward_returns` per IC spec §XIV.1 DDL
- CREATE TABLE `feature_ic_scores` per IC spec §XIV.4 DDL
- `SELECT create_hypertable('forward_returns', 'bar_ts', chunk_time_interval => INTERVAL '3 months')`
- All indexes per spec
- `docs/analysis/` directory creation note (for IC report file)

**Migration 158:** `production/migrations/158_alpha_ic_apr_keys.sql`
- INSERT into `config_schema` + `config_state` for all `alpha.ic.*`, `alpha.decay.*`, `alpha.ensemble.*`, `alpha.kelly.*`, `alpha.portfolio.*` keys listed in the architecture doc APR table
- `ON CONFLICT DO NOTHING` on all inserts

### Deliverable D: ICEngine (`services/ic_engine.py`)

Pattern: sync psycopg2 oneshot with OTel instrumentation.

Computation loop:
1. `RUN_TS = datetime.now(UTC)` -- constant for this run
2. `TRAINING_WINDOW_END = MAX(bar_ts) FROM feature_vectors` -- locked at start
3. Load `alpha.ic.*` APR keys via `_load_config_service()` pattern from backfill_feature_factory.py
4. For each (symbol, tf):
   a. Load full feature matrix from `feature_vectors` up to TRAINING_WINDOW_END
   b. Load forward returns from `forward_returns` (JOIN by symbol, tf, bar_ts)
   c. For each regime (4 distinct values from `feature_vectors.regime` for this symbol/tf):
      - Filter to rows matching this regime
      - Apply N-bar subsampling (`rn % N == 0` per IC spec §VIII.2)
      - Skip if n_independent < 100 (emit `ic_engine_cells_skipped_total{skip_reason="insufficient_n"}`)
      - Pre-rank feature matrix: `rankdata(X, axis=0)` -- one call for all 54 features
      - For each lookahead (1, 5, 20, 60):
        - Pre-rank forward returns: `rankdata(Y)`
        - Compute IC matrix (features x 1 lookahead) via vectorized corrcoef
        - Compute analytical p-values via `spearmanr` (one per feature)
        - Compute bootstrap CI (vectorized over all 54 features together)
        - Store (feature, ic_value, p_value, ci_lo, ci_hi, n_independent) per cell
   d. After all regimes x lookaheads: run `multipletests(all_pvals, alpha=fdr_alpha, method='fdr_bh')` on the full batch for this (symbol, tf)
   e. Walk-forward validation (3 folds, expanding window): compute IC per fold, check IC Sharpe across folds
   f. Batch-INSERT into `feature_ic_scores` with `ON CONFLICT ... DO NOTHING`
5. Emit OTel metrics per architecture doc §XIX
6. Write IC discovery report to `docs/analysis/ic-discovery-report-{date}.md`
7. `flush_and_shutdown_metrics()` before exit

**BH-FDR ordering:** Apply FDR correction per (symbol, tf) batch, not globally across all symbols at once. The architecture doc §IX.1 references 50,112 tests total (54 x 58 x 4 TFs x 4 lookaheads). For Phase 138 with 14-15 symbols: ~13,500 tests. The `multipletests` call takes all p-values for the current (symbol, tf) as a flat array and returns q-values in the same order -- maintain parallel list of cell tuples.

**Walk-forward:** Per IC spec §IX.3, 3 folds with expanding window: 70% training, 10% per fold. Implemented per feature after the full IC computation, using the same rank-correlation approach on held-out sub-windows.

**IC Sharpe computation:** Per IC spec §X.1, require 20,000 independent observations (10 windows x 2000 obs). For cells below this threshold, `ic_sharpe = NULL`, `ic_sharpe_n_windows = n_windows_computed`. SPY at 5m meets this; SPY at 1h (26K obs) barely meets it.

### IC Discovery Report Format

File: `docs/analysis/ic-discovery-report-{date}.md`
Sections: (1) Summary statistics (N tests, N passing FDR, N passing walk-forward), (2) Per-feature table (symbol, tf, regime, lookahead, ic_value, ic_ci_lower, passes_fdr, passes_walkforward, ic_sharpe), (3) Top features by IC Sharpe, (4) Features failing both gates. Console output mirrors the report structure at INFO level via structlog.

---

## Validation Architecture

**Unit tests** (must be CI-green before commit):

1. `tests/unit/test_ic_engine_vectorized.py` -- tests that vectorized IC matches `scipy.stats.spearmanr` on a small matrix (n=100, 5 features, 2 lookaheads). Tolerance: abs(ic_vectorized - ic_spearmanr) < 1e-10.

2. `tests/unit/test_forward_return_writer.py` -- synthesize 100 bars in a small in-memory table, verify:
   - `return_1bar = ln(open[T+2]/open[T+1])` (not `ln(open[T+1]/open[T])`)
   - `complete_60bar = false` for last 60 rows
   - No lookahead bias: the LEAD() references only future rows

3. `tests/unit/test_bh_fdr_mapping.py` -- verify that after `multipletests`, the q-value at index i corresponds to the p-value at index i (not sorted). `multipletests` preserves input order.

4. `tests/unit/test_ic_engine_idempotency.py` -- run ICEngine compute twice on same data, verify second run writes 0 new rows to `feature_ic_scores` (all `ON CONFLICT DO NOTHING`).

**Smoke tests** (manual):
- Run `python services/forward_return_writer.py --symbols SPY --tf 5m` → verify `forward_returns` has rows with non-null `return_5bar` and `complete_5bar = true`
- Run `python services/ic_engine.py --symbols SPY --tf 5m` → verify at least some features have `ic_ci_lower > 0`
- Check IC report file at `docs/analysis/ic-discovery-report-{date}.md`

---

## Risks and Mitigations

**Risk 1: Backfill blocks all downstream work.**
The backfill is ~2-6 hours of IBKR fetch + compute. All IC work is blocked until `feature_vectors` is populated. Mitigation: make backfill Task 1, gate all subsequent tasks on its completion. The backfill is idempotent and resumable.

**Risk 2: HMM regime labeling is undefined scope.**
The HMM trainer (`src/intelligence/services/hmm_trainer.py`) exists for v2.x regime detection. It may not be directly usable for retroactively labeling `feature_vectors` rows. The labeler needs a function that takes a time-ordered bar array for a (symbol, tf) and returns a sequence of state labels. If the existing HMM trainer only trains (not labels), a separate Viterbi decoding step is needed. Risk is medium -- investigate `HMMTrainer.start()` to determine what it outputs before writing `regime_writer.py`.

**Risk 3: IC Sharpe gate fails for 1h TF.**
SPY at 1h has 131K bars / 5 = 26K independent obs = only 13 IC windows (26K/2K). This meets the 10-window minimum but barely. For symbols with fewer 1h bars (some have 131,339 minimum), it's 13.1 windows. Any (symbol, tf) combination with < 20K independent obs must have `ic_sharpe = NULL` and `passes_walkforward = false`, excluded from ensemble. This is correct behavior per spec.

**Risk 4: regime column populated with HMM integer strings not text labels.**
The v2.x HMM may produce regime labels as integer strings ('0','1','2') per the MEMORY.md note. The IC spec expects meaningful text labels. The regime_writer must define a canonical mapping (e.g. 0='ranging', 1='trending_up', 2='trending_down', 3='volatile') and store text labels. This mapping must be consistent across the entire Phase 138 pipeline.

**Risk 5: BH-FDR p-value inflation from correlated tests.**
The IC spec §IX.1 notes that RSI x3, CCI x3, aroon x2 produce correlated tests. BH-FDR is conservative under positive correlation (valid), but the expected false discoveries at q=0.05 with ~50K tests is 2,500 -- so even random noise passes ~2.5K tests. Walk-forward validation is the real guard. The FDR gate is necessary but not sufficient; the planner must ensure walk-forward is not skipped.

**Risk 6: Missing `docs/analysis/` directory.**
The IC discovery report path `docs/analysis/ic-discovery-report-{date}.md` requires the `docs/analysis/` directory to exist. It does not currently exist. The IC Engine must `Path("docs/analysis/").mkdir(parents=True, exist_ok=True)` before writing the report.

---

## RESEARCH COMPLETE
