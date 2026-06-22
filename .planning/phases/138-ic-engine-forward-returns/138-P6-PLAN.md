---
phase: 138-ic-engine-forward-returns
plan: 06
type: execute
wave: 5
depends_on: ["138-04", "138-05"]
files_modified:
  - services/ic_engine.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "ic_engine extends BaseBatch (src/core/agent/base_batch.py); D-06 emission is inherited, not reimplemented"
    - "feature_ic_scores has one row per (feature, symbol, tf, regime, lookahead, training_window_end)"
    - "Pooled rows have is_pooled=true; regime-stratified rows have is_pooled=false"
    - "Each row carries ic_value, p_value, bootstrap CI, BH-FDR q-value, walk-forward result, IC Sharpe"
    - "Bootstrap CI uses circular block bootstrap (from batch_agent_memory.py pattern), not iid"
    - "Bootstrap block size is APR-backed and TF-specific: cfg.get_sync(f'alpha.ic.bootstrap_block_size.{tf}', 10)"
    - "Walk-forward has 60-bar purge/embargo between training end and test fold start"
    - "Degenerate features (std < 1e-8) are skipped with IC_ENGINE_CELLS_SKIPPED_TOTAL skip_reason=degenerate_feature"
    - "IC run raises RuntimeError with explicit message if feature_vectors empty, regime all-NULL, or forward_returns empty"
    - "ON CONFLICT targets feature_ic_scores_pooled_uq for pooled rows; feature_ic_scores_regime_uq for regime rows"
    - "Idempotent: second run inserts 0 rows"
    - "ic_engine emits 4 IC health OTel gauges after run: IC_SCORE_GAUGE (per feature x tf x regime), EFFECTIVE_N_GAUGE (per tf x regime), FEATURES_SURVIVING_FDR_GAUGE (per tf x regime), IC_SHARPE_GAUGE (per feature x tf x regime)"
    - "ic_engine emits 6 per-run OTel metrics + spans"
  artifacts:
    - path: "services/ic_engine.py"
      provides: "Vectorized Spearman IC engine with circular-block-bootstrap CI, BH-FDR, 60-bar-embargo walk-forward, IC Sharpe, BaseBatch inheritance, IC health gauges"
      min_lines: 450
    - path: "src/observability/metrics.py"
      provides: "ic_engine_cells_completed_total, ic_engine_cells_skipped_total, ic_engine_run_latency_seconds, feature_ic_passing_fdr_total, feature_ic_passing_walkforward_total, IC_SCORE_GAUGE, EFFECTIVE_N_GAUGE, FEATURES_SURVIVING_FDR_GAUGE, IC_SHARPE_GAUGE"
      contains: "ic_engine_cells_completed_total"
  key_links:
    - from: "ic_engine.py"
      to: "feature_ic_scores table"
      via: "INSERT ... ON CONFLICT on feature_ic_scores_pooled_uq (pooled) or feature_ic_scores_regime_uq (regime-stratified)"
      pattern: "INSERT INTO feature_ic_scores"
    - from: "feature_vectors (X) JOIN forward_returns (Y)"
      to: "Spearman IC per cell"
      via: "rankdata(X, axis=0) + vectorized corrcoef on ranks"
      pattern: "rankdata"
    - from: "_circular_block_bootstrap_ic() in ic_engine.py"
      to: "_circular_block_bootstrap_ci() in batch_agent_memory.py"
      via: "same circular wrapping algorithm, adapted for IC vector instead of mean PnL"
      pattern: "circular.block\|block_len\|n_blocks"
    - from: "per-cell p_values array"
      to: "passes_fdr"
      via: "multipletests(pvals, method='fdr_bh') with parallel cell tuple list"
      pattern: "multipletests"
---

<objective>
Build `services/ic_engine.py` -- the measurement substrate of the entire v3.0 AlphaEngine. Computes Spearman IC per feature x symbol x TF x regime x lookahead, with circular-block-bootstrap CI, BH-FDR correction, 60-bar-embargo walk-forward validation, and IC Sharpe, into feature_ic_scores.

Purpose: IC is the unit of measure; IC Sharpe is the unit of trust (Renaissance mandate #1). This is the most important file in Phase 138.

MAJOR CORRECTNESS UPDATES IN THIS REVISION (from REVIEWS.md):
1. Bootstrap is circular block bootstrap (not iid). Pattern from production/scripts/batch_agent_memory.py (_circular_block_bootstrap_ci). Block size from APR key alpha.ic.bootstrap_block_size.
2. Walk-forward has 60-bar purge/embargo between train-end and test-start (max(lookahead_bars) = 60). Prevents overlapping forward-return labels from leaking across fold boundary.
3. Degenerate feature skip: features where std(X[:,j]) < 1e-8 are skipped before rankdata with IC_ENGINE_CELLS_SKIPPED_TOTAL{skip_reason="degenerate_feature"}.
4. is_pooled=true for pooled IC rows; is_pooled=false for regime-stratified rows. ON CONFLICT targets two separate indexes.
5. Crash-loud gates are explicit RuntimeError with exact error messages -- not just "should check" language.

Output: feature_ic_scores fully populated, vectorized + statistically correct + idempotent + crash-loud + fully instrumented.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
@CLAUDE.md
@docs/plans/2026-06-20-alphaengine-ic-spec.md
@production/scripts/batch_agent_memory.py
@services/backfill_feature_factory.py
@services/forward_return_writer.py
@src/intelligence/schemas.py
@src/core/service_utils.py
@src/observability/metrics.py
@src/observability/spans.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add ic_engine OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter/gauge/histogram factories; OUTCOME_LABELS_COVERAGE already defined in P3 -- do not redefine)
  </read_first>
  <action>
    In src/observability/metrics.py add (per observability mandate §XIX):
    - IC_ENGINE_CELLS_COMPLETED_TOTAL = _meter.create_counter("ic_engine_cells_completed_total", description="cells with committed feature_ic_scores row; labels symbol, tf, regime")
    - IC_ENGINE_CELLS_SKIPPED_TOTAL = _meter.create_counter("ic_engine_cells_skipped_total", description="cells skipped; labels symbol, tf, skip_reason in {insufficient_n, already_present, missing_regime, degenerate_feature}")
    - IC_ENGINE_RUN_LATENCY_SECONDS = _meter.create_histogram("ic_engine_run_latency_seconds", description="full IC Engine run duration")
    - FEATURE_IC_PASSING_FDR_TOTAL = _meter.create_gauge("feature_ic_passing_fdr_total", description="features passing BH-FDR gate; labels symbol, tf")
    - FEATURE_IC_PASSING_WALKFORWARD_TOTAL = _meter.create_gauge("feature_ic_passing_walkforward_total", description="features passing walk-forward gate; labels symbol, tf")
    Reuse OUTCOME_LABELS_COVERAGE (already defined in P3). No prometheus_client.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python -c "from src.observability.metrics import IC_ENGINE_CELLS_COMPLETED_TOTAL, IC_ENGINE_CELLS_SKIPPED_TOTAL, IC_ENGINE_RUN_LATENCY_SECONDS, FEATURE_IC_PASSING_FDR_TOTAL, FEATURE_IC_PASSING_WALKFORWARD_TOTAL; print('ok')"` exits 0
    - `grep -c "OUTCOME_LABELS_COVERAGE = " src/observability/metrics.py` returns 1 (not redefined)
    - `grep -c "degenerate_feature" src/observability/metrics.py` returns >= 1 (skip_reason documented in description)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import IC_ENGINE_CELLS_COMPLETED_TOTAL; print('ok')"</verify>
  <done>Five ic_engine metrics importable; degenerate_feature skip_reason documented.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/ic_engine.py -- vectorized IC, circular-block-bootstrap CI, BH-FDR, 60-bar-embargo walk-forward, IC Sharpe</name>
  <files>services/ic_engine.py</files>
  <read_first>
    - services/ic_engine.py (the file being created -- does not exist yet)
    - production/scripts/batch_agent_memory.py (_circular_block_bootstrap_ci lines 96-137, _bootstrap_block_length lines 66-75 -- READ THESE CAREFULLY; the circular block bootstrap for IC must mirror this algorithm adapted for an IC vector instead of a scalar mean)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§V forward return, §VIII bootstrap/subsampling, §IX BH-FDR + walk-forward, §X IC Sharpe, §XIV.4 feature_ic_scores columns, §XX restart logic)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Findings 3,4,5,6,10; Risks 3,5,6; Deliverable D computation loop)
    - src/intelligence/schemas.py (FeatureVector -- the 54 field names are the feature_name values)
    - services/backfill_feature_factory.py (Ring 2 oneshot template; _load_config_service; _JOB; JOB_COMPLETED_TOTAL; flush_and_shutdown_metrics)
    - services/forward_return_writer.py (sibling pattern + forward_returns schema usage)
    - src/observability/spans.py (observed_span, ATTR_*)
    - CLAUDE.md (APR rules; UTC; crash-loud > silent-wrong; market_data/feature_vectors column names)
  </read_first>
  <action>
    Create services/ic_engine.py as a sync psycopg2 oneshot. Constants: _JOB = "ic-engine", log "logs/ic_engine.log". vector_domain for all 54 features in Phase 138 is "quant" -- define _VECTOR_DOMAIN = "quant" with a comment.

    The 54 feature names = the field names of FeatureVector (src/intelligence/schemas.py), also the feature_vectors column names. Build:
      _FEATURE_NAMES = [f.name for f in dataclasses.fields(FeatureVector)]
    This stays in sync automatically -- do NOT hardcode 54 names.

    APR loading via _load_config_service(conn): read ALL via cfg.get_sync -- min_observations (alpha.ic.min_observations, fb 500), bootstrap_resamples (alpha.ic.bootstrap_resamples, fb 2000), bootstrap_block_size (alpha.ic.bootstrap_block_size, fb 10), fdr_alpha (alpha.ic.fdr_alpha, fb 0.05), walk_forward_folds (alpha.ic.walk_forward_folds, fb 3), sharpe_window_size (alpha.ic.sharpe_window_size, fb 2000), sharpe_min_windows (alpha.ic.sharpe_min_windows, fb 10), subsampling_n (alpha.ic.subsampling_n, fb 5), min_reliable_n (alpha.ic.min_reliable_n, fb 100). ZERO inline numerics in compute logic.

    Lookaheads [1,5,20,60] map to forward_returns.return_1bar/5bar/20bar/60bar (statistical-concept column names, allowed).

    CRASH-LOUD GATES (Renaissance mandate #9) -- enforced code, not comments. Run at startup BEFORE any compute. Each gate raises RuntimeError with an exact error message:

      n_fv = conn.execute("SELECT count(*) FROM feature_vectors").fetchone()[0]
      if n_fv == 0:
          raise RuntimeError(
              "IC Engine startup gate FAILED: feature_vectors is empty. "
              "Run services/backfill_feature_factory.py first."
          )

      n_regime = conn.execute("SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL").fetchone()[0]
      if n_regime == 0:
          raise RuntimeError(
              "IC Engine startup gate FAILED: feature_vectors.regime is all-NULL. "
              "Run services/regime_writer.py first."
          )

      n_fr = conn.execute("SELECT count(*) FROM forward_returns").fetchone()[0]
      if n_fr == 0:
          raise RuntimeError(
              "IC Engine startup gate FAILED: forward_returns is empty. "
              "Run services/forward_return_writer.py first."
          )

    (Use psycopg2 cursor pattern; adapt execute syntax to match backfill_feature_factory.py psycopg2 pattern.)
    A run that "succeeds" with empty feature_ic_scores is a data-integrity failure -- these gates prevent it.

    RUN constants: RUN_TS = datetime.now(UTC); TRAINING_WINDOW_END = MAX(bar_ts) FROM feature_vectors (locked once at start).

    IDEMPOTENCY (RESEARCH.md Finding 10): on startup, load existing tuples for this training_window_end:
      SELECT feature_name, symbol, tf, regime, lookahead_bars, is_pooled FROM feature_ic_scores WHERE training_window_end = %s
    into a set of tuples. Skip any cell already present (emit IC_ENGINE_CELLS_SKIPPED_TOTAL skip_reason="already_present").

    CIRCULAR BLOCK BOOTSTRAP (fixes REVIEWS.md MEDIUM issue #6 -- replaces iid bootstrap):
    Implement _circular_block_bootstrap_ic() mirroring _circular_block_bootstrap_ci() from production/scripts/batch_agent_memory.py. The algorithm is identical except it operates on an IC vector (shape [n_features]) instead of a scalar mean PnL. Block size comes from APR key alpha.ic.bootstrap_block_size (loaded above):

    def _circular_block_bootstrap_ic(
        ranks_X: np.ndarray,  # shape [n_obs, n_features]
        ranks_Y: np.ndarray,  # shape [n_obs]
        block_size: int,
        n_boot: int,
        rng: np.random.Generator,
    ) -> tuple[np.ndarray, np.ndarray]:
        '''Circular block bootstrap for IC confidence intervals.

        Mirrors production/scripts/batch_agent_memory.py:_circular_block_bootstrap_ci()
        but produces CI vectors over all features simultaneously.
        Block size from APR: alpha.ic.bootstrap_block_size (default 10).
        Circular wrapping eliminates boundary effects at series edges.
        '''
        n, p = ranks_X.shape
        n_blocks = math.ceil(n / block_size)
        boot_ics = np.zeros((n_boot, p))
        for b in range(n_boot):
            starts = rng.integers(0, n, size=n_blocks)
            idx = np.concatenate([
                np.arange(s, s + block_size) % n for s in starts
            ])[:n]  # circular wrap + trim to n
            bX = ranks_X[idx]
            bY = ranks_Y[idx]
            # Vectorized IC for this bootstrap sample
            bX_c = bX - bX.mean(axis=0)
            bY_c = bY - bY.mean()
            denom = np.sqrt((bX_c**2).sum(axis=0) * (bY_c**2).sum())
            boot_ics[b] = np.where(denom > 1e-10, (bX_c * bY_c[:, None]).sum(axis=0) / denom, 0.0)
        ci_lower = np.percentile(boot_ics, 2.5, axis=0)
        ci_upper = np.percentile(boot_ics, 97.5, axis=0)
        return ci_lower, ci_upper

    COMPUTE LOOP -- for each (symbol, tf), wrap in observed_span("ic_engine.compute_symbol_tf"):
      a. Load feature matrix: SELECT bar_ts, regime, <54 feature columns> FROM feature_vectors WHERE symbol=%s AND tf=%s AND bar_ts <= TRAINING_WINDOW_END ORDER BY bar_ts. Load into numpy arrays (X shape [n_bars, 54]).
      b. Load forward returns: JOIN forward_returns by (symbol, tf, bar_ts) -- get return_1bar/5bar/20bar/60bar + complete flags aligned to the same bar_ts order (exact timestamp match, mandate #10).
      c. Distinct regimes for this (symbol, tf): the set of non-NULL regime values present. ALSO compute a pooled pass (is_pooled=True, regime=None).
      d. For each regime in {distinct regimes} + {None for pooled}:
         - mask rows to this regime (pooled = all rows); set is_pooled flag accordingly
         - SUBSAMPLE: keep every subsampling_n-th row (non-overlapping independence) -> X_sub, returns_sub. n_independent = rows kept.
         - if n_independent < min_reliable_n: skip cell, IC_ENGINE_CELLS_SKIPPED_TOTAL.add(1, {symbol, tf, skip_reason:"insufficient_n"}); continue.

         DEGENERATE FEATURE SKIP (fixes REVIEWS.md MEDIUM issue #8):
         Before rankdata, compute feature standard deviations:
           feature_stds = np.std(X_sub, axis=0)  # shape [54]
         For any feature j where feature_stds[j] < 1e-8 (constant or near-constant column):
           - Mark that feature as skipped for this cell
           - IC_ENGINE_CELLS_SKIPPED_TOTAL.add(1, {symbol, tf, skip_reason: "degenerate_feature"})
           - Do NOT compute Spearman for that feature (rankdata on a constant vector is undefined / NaN)
         Only compute IC for non-degenerate features. Store NaN for skipped features in results.

         - PRE-RANK ONCE (for non-degenerate features): ranks_X = scipy.stats.rankdata(X_sub[:, non_degenerate_mask], axis=0)
         - For each lookahead N in [1,5,20,60]:
             - select returns_sub[:,N] filtered to complete_Nbar rows; align ranks_X to those rows.
             - if remaining n < min_reliable_n: skip.
             - ranks_Y = rankdata(returns_N)
             - IC per feature = vectorized Pearson on ranks (corrcoef-based): produces ic_vector shape [n_non_degenerate]. Place NaN for degenerate features.
             - p_value per feature via t-approximation: t = ic * sqrt((n-2) / max(1-ic^2, 1e-10)); p = 2 * (1 - t_cdf(abs(t), df=n-2)).
             - CIRCULAR BLOCK BOOTSTRAP CI (APR-backed block_size): wrap in observed_span("ic_engine.bootstrap_ci"). Call _circular_block_bootstrap_ic(ranks_X, ranks_Y, bootstrap_block_size, bootstrap_resamples, rng). ic_ci_lower/upper from percentile. passes_ci_gate = ic_ci_lower[j] > 0 (for each feature j). NaN for degenerate features.

             WALK-FORWARD WITH 60-BAR EMBARGO (fixes REVIEWS.md MEDIUM issue #7):
             Split the subsampled series chronologically into walk_forward_folds expanding windows. The embargo between training-fold-end and test-fold-start MUST be max(lookaheads) = 60 bars. This prevents overlapping forward-return labels from leaking across the fold boundary. Implementation:

               total_n = len(X_sub)
               embargo_bars = 60  # MUST be max(lookaheads); prevents label overlap
               # Compute fold boundaries: fold k test window ends at total_n * (k+1) / walk_forward_folds
               fold_ics = []
               for k in range(walk_forward_folds):
                   train_end_idx = int(total_n * (k + 1) / (walk_forward_folds + 1))
                   test_start_idx = train_end_idx + embargo_bars  # 60-bar gap
                   test_end_idx = int(total_n * (k + 2) / (walk_forward_folds + 1))
                   if test_start_idx >= test_end_idx or (test_end_idx - test_start_idx) < min_reliable_n:
                       continue  # not enough test data after embargo
                   X_train = X_sub[:train_end_idx]
                   X_test = X_sub[test_start_idx:test_end_idx]
                   Y_test = returns_sub[test_start_idx:test_end_idx, N_idx]
                   # Rerank test data using training ranks as reference (expanding window)
                   ranks_X_test = rankdata(X_test, axis=0)
                   ranks_Y_test = rankdata(Y_test)
                   oos_ic = vectorized_ic(ranks_X_test, ranks_Y_test)  # shape [n_features]
                   fold_ics.append(oos_ic)
               wf_fold_count = len(fold_ics)
               if wf_fold_count > 0:
                   fold_ic_array = np.array(fold_ics)  # shape [n_folds, n_features]
                   wf_pass_count = np.sum(fold_ic_array > 0, axis=0)  # per feature: folds where OOS IC > 0
                   wf_mean = np.mean(fold_ic_array, axis=0)
                   wf_std = np.std(fold_ic_array, axis=0)
                   wf_ic_sharpe = np.where(wf_std > 1e-10, wf_mean / wf_std, 0.0)
                   passes_walkforward = wf_pass_count == walk_forward_folds  # strictest gate
               else:
                   passes_walkforward = np.zeros(n_features, dtype=bool)
               Note: embargo_bars is not a hardcoded magic number -- it equals max(lookaheads) which is always 60 for the [1,5,20,60] lookahead set. Add a comment explaining this derivation.

             - IC SHARPE (IC spec §X.1): only computable if n_independent >= sharpe_min_windows * sharpe_window_size. Below threshold: ic_sharpe=NULL. Compute IC per rolling window of sharpe_window_size, ic_sharpe = mean/std across windows.
             - Append result dict for this cell to a per-(symbol,tf) list AND append p_value to a flat pvals array with a PARALLEL list of (feature_name, regime, lookahead, is_pooled) tuples (order correspondence for FDR).

      e. BH-FDR per (symbol, tf) batch: reject, q_values, _, _ = statsmodels.stats.multitest.multipletests(pvals_array, alpha=fdr_alpha, method='fdr_bh'). multipletests PRESERVES input order. Set bh_adjusted_p and passes_fdr per cell by index.

      f. Batch INSERT all cells INTO feature_ic_scores. For each row, set is_pooled appropriately. Use TWO separate INSERT statements to target the correct unique index:

         For regime-stratified rows (is_pooled=False, regime IS NOT NULL):
           INSERT INTO feature_ic_scores (..., regime, is_pooled, ...)
           VALUES (%s, ..., %s, false, ...)
           ON CONFLICT ON CONSTRAINT feature_ic_scores_regime_uq DO NOTHING

         For pooled rows (is_pooled=True, regime=NULL):
           INSERT INTO feature_ic_scores (..., regime, is_pooled, ...)
           VALUES (%s, ..., NULL, true, ...)
           ON CONFLICT ON CONSTRAINT feature_ic_scores_pooled_uq DO NOTHING

         Do NOT attempt to use the PK as conflict target for regime=NULL rows -- Postgres NULL uniqueness means this silently allows duplicate pooled rows.

      g. IC_ENGINE_CELLS_COMPLETED_TOTAL.add(n_committed, {symbol, tf, regime}); FEATURE_IC_PASSING_FDR_TOTAL.set(n_passing_fdr, {symbol, tf}); FEATURE_IC_PASSING_WALKFORWARD_TOTAL.set(n_passing_wf, {symbol, tf}).

    Wrap full run in observed_span("ic_engine.run"); record IC_ENGINE_RUN_LATENCY_SECONDS. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": ...}) in finally block; flush_and_shutdown_metrics(); sys.exit(1) on failure.

    DAG-invariant docstring note: oneshot batch tool, exempt like backfill_feature_factory.py.
    argparse: --symbols (default all feature_vectors symbols), --tf (default 4 TFs).
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m` exits 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m';"` returns > 0
    - Pooled rows have is_pooled=true: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' AND is_pooled=true AND regime IS NULL;"` returns > 0
    - Regime rows have is_pooled=false: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' AND is_pooled=false AND regime IS NOT NULL;"` returns > 0
    - No rows have is_pooled=false with regime=NULL (the ambiguous case eliminated): `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE is_pooled=false AND regime IS NULL;"` returns 0
    - Circular block bootstrap present: `grep -c "_circular_block_bootstrap_ic\|block_size\|n_blocks" services/ic_engine.py` returns >= 3
    - IID bootstrap absent: `grep -c "scipy.stats.bootstrap" services/ic_engine.py` returns 0
    - 60-bar embargo present: `grep -c "embargo_bars\|embargo" services/ic_engine.py` returns >= 2
    - Degenerate feature skip present: `grep -c "1e-8\|degenerate_feature" services/ic_engine.py` returns >= 2
    - Crash-loud gates are RuntimeError: `grep -c "raise RuntimeError" services/ic_engine.py` returns >= 3
    - Explicit error messages in gates: `grep -n "startup gate FAILED\|is empty\|all-NULL" services/ic_engine.py` returns >= 3 lines
    - bootstrap_block_size from APR: `grep -c "bootstrap_block_size\|alpha\.ic\.bootstrap_block_size" services/ic_engine.py` returns >= 2
    - BH-FDR populated: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE bh_adjusted_p IS NOT NULL AND symbol='SPY' AND tf='5m';"` returns > 0
    - walk-forward populated: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE passes_walkforward IS NOT NULL AND symbol='SPY' AND tf='5m';"` returns > 0
    - IC Sharpe gate: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_sharpe IS NOT NULL AND n_independent < 20000 AND symbol='SPY' AND tf='5m';"` returns 0
    - CRASH-LOUD verified: `.venv/bin/python -c "import sys; sys.exit(0)" && echo "verify gate manually by running with NONEXISTENT symbol and confirming non-zero exit"` -- confirm in acceptance that a fresh test with empty feature_vectors exits non-zero (can be tested by mocking if needed)
    - `grep -c "rankdata" services/ic_engine.py` returns >= 1
    - `grep -c "multipletests" services/ic_engine.py` returns >= 1
    - `grep -c "observed_span" services/ic_engine.py` returns >= 3 (run, compute_symbol_tf, bootstrap_ci)
    - `grep -c "JOB_COMPLETED_TOTAL\|flush_and_shutdown_metrics" services/ic_engine.py` returns >= 2
    - `grep -c "dataclasses.fields\|fields(FeatureVector)" services/ic_engine.py` returns >= 1
    - `.venv/bin/ruff check services/ic_engine.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, is_pooled, count(*), count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' GROUP BY regime, is_pooled;"</verify>
  <done>ic_engine.py produces complete feature_ic_scores rows for SPY 5m; circular-block-bootstrap CI; 60-bar embargo walk-forward; degenerate feature skip; is_pooled column correct; crash-loud gates raise RuntimeError; D-06 + 5 OTel metrics + 3 spans wired; APR-compliant.</done>
</task>

<task type="auto">
  <name>Task 3: Run IC engine across all backfilled symbols/TFs</name>
  <files>feature_ic_scores (DB table -- populated)</files>
  <read_first>
    - services/ic_engine.py (just built)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 3 full-run estimate ~2.8 min bootstrap phase; Risk 3 1h TF marginal)
  </read_first>
  <action>
    Run .venv/bin/python services/ic_engine.py with no symbol filter. Run in background; poll feature_ic_scores counts. Then verify idempotency by re-running SPY 5m.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_ic_scores;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE passes_walkforward = true;"` returns >= 1 (at least one feature survives the hardest gate)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE is_pooled=false AND regime IS NULL;"` returns 0 (no ambiguous rows)
    - Idempotency: capture `SELECT count(*) FROM feature_ic_scores`, re-run `.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m`, count again -- counts EQUAL (0 new rows)
    - `job_completed_total{job="ic-engine", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, is_pooled, count(*) total, count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores GROUP BY tf, is_pooled ORDER BY tf, is_pooled;"</verify>
  <done>feature_ic_scores populated for >=14 symbols x 4 TFs; is_pooled/regime correctly set; idempotent re-run confirmed.</done>
</task>

</tasks>

<verification>
- feature_ic_scores complete: IC, CI (circular block bootstrap), p, BH-FDR q, walk-forward (60-bar embargo), IC Sharpe per cell
- is_pooled=true for pooled rows; is_pooled=false for regime-stratified rows; no is_pooled=false+regime=NULL ambiguity
- bootstrap_block_size from APR (alpha.ic.bootstrap_block_size); no iid bootstrap
- Degenerate features (std < 1e-8) skipped with IC_ENGINE_CELLS_SKIPPED_TOTAL degenerate_feature
- Crash-loud: three RuntimeError gates with explicit messages; no silent empty success
- Idempotent; D-06 + 5 OTel + 3 spans; APR-compliant
</verification>

<success_criteria>
- All task acceptance criteria pass
- At least one feature passes_walkforward across the universe
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-06-SUMMARY.md` documenting feature_ic_scores counts per (symbol, tf, regime, is_pooled), how many features passed FDR and walk-forward, the top features by IC Sharpe, and any (symbol, tf) cells below the 20K IC-Sharpe gate.
</output>
