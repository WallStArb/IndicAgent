---
phase: 138-ic-engine-forward-returns
plan: 06
type: execute
wave: 5
depends_on: ["138-04", "138-05"]
files_modified:
  - production/migrations/164_ic_sortino_winrate.sql
  - services/ic_engine.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "ic_engine extends BaseBatch (src/core/agent/base_batch.py); D-06 emission is inherited, not reimplemented"
    - "feature_ic_scores has one row per (feature, symbol, tf, regime, lookahead, training_window_end)"
    - "Pooled rows have is_pooled=true; regime-stratified rows have is_pooled=false"
    - "Each row carries ic_value, p_value, bootstrap CI, BH-FDR q-value, walk-forward result, IC Sharpe, IC Sortino, IC win rate"
    - "Bootstrap CI uses circular block bootstrap (from batch_agent_memory.py pattern), not iid"
    - "Bootstrap block size is APR-backed and TF-specific: cfg.get_sync(f'alpha.ic.bootstrap_block_size.{tf}', 10)"
    - "Walk-forward has 60-bar purge/embargo between training end and test fold start"
    - "Degenerate features (std < 1e-8) are skipped with IC_ENGINE_CELLS_SKIPPED_TOTAL skip_reason=degenerate_feature"
    - "IC run raises RuntimeError with explicit message if feature_vectors empty, regime all-NULL, or forward_returns empty"
    - "ON CONFLICT targets feature_ic_scores_pooled_uq for pooled rows; feature_ic_scores_regime_uq for regime rows"
    - "Idempotent: second run inserts 0 rows"
    - "ic_engine emits 6 IC health OTel gauges after run: IC_SCORE_GAUGE (per feature x tf x regime), EFFECTIVE_N_GAUGE (per tf x regime), FEATURES_SURVIVING_FDR_GAUGE (per tf x regime), IC_SHARPE_GAUGE, IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE (per feature x tf x regime)"
    - "ic_engine emits 6 per-run OTel metrics + spans"
  artifacts:
    - path: "services/ic_engine.py"
      provides: "Vectorized Spearman IC engine with circular-block-bootstrap CI, BH-FDR, 60-bar-embargo walk-forward, IC Sharpe + Sortino + win rate, BaseBatch inheritance, IC health gauges"
      min_lines: 450
    - path: "src/observability/metrics.py"
      provides: "ic_engine_cells_completed_total, ic_engine_cells_skipped_total, ic_engine_run_latency_seconds, feature_ic_passing_fdr_total, feature_ic_passing_walkforward_total, IC_SCORE_GAUGE, EFFECTIVE_N_GAUGE, FEATURES_SURVIVING_FDR_GAUGE, IC_SHARPE_GAUGE, IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE"
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

POOLED IC ROLE: Pooled rows (is_pooled=true, regime=NULL) are written as DIAGNOSTIC ARTIFACTS ONLY. They exist to compare against regime-stratified IC and catch cases where regime conditioning hurts (degenerate regimes, thin data). Phase 139 ensemble EXCLUSIVELY reads WHERE is_pooled = false rows. The IC discovery report presents pooled IC in a separate "Comparison: Pooled vs. Regime-Stratified" section, clearly marked diagnostic. Never promote a pooled IC score to the ensemble.

IC SHARPE WINDOW DEFINITION: sharpe_window_size = 2000 means 2000 RAW bars per rolling window (before striding). Within each window, IC is computed from non-overlapping subsampled observations at stride = max(subsample_min_stride, lookahead_bars). Gate: n_raw_bars >= sharpe_min_windows * sharpe_window_size (= 20,000 raw bars). Use n_raw_bars (total bars for this symbol/tf/regime before subsampling) for this gate check, NOT n_independent.

TRAINING_WINDOW_END CONSUMER NOTE: feature_ic_scores is an append-only record. When ic_engine reruns with new data, training_window_end changes and new rows are inserted alongside old ones (idempotent per training_window_end). Consumers always query MAX(training_window_end) per (feature_name, symbol, tf, regime, lookahead_bars, is_pooled) to get current scores. No is_current flag needed.

NULL CROSS-SECTIONAL FEATURES: momentum_rank_z, volume_rank_z, volatility_rank_z are all-NULL in Phase 138 (cross-sectional fields, populated in Phase 139). They will all be skipped via the std < 1e-8 degenerate gate. Their IC_ENGINE_CELLS_SKIPPED_TOTAL{skip_reason="degenerate_feature"} increments are expected and correct — they represent planned absence, not data error. Log them at DEBUG not WARNING.

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
  <name>Task 0: Run migration 164 — add ic_sortino and ic_win_rate columns</name>
  <files>production/migrations/164_ic_sortino_winrate.sql</files>
  <read_first>
    - production/migrations/164_ic_sortino_winrate.sql
  </read_first>
  <action>
    Apply migration 164 to add ic_sortino and ic_win_rate to feature_ic_scores:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/164_ic_sortino_winrate.sql
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "\d feature_ic_scores" | grep -c "ic_sortino\|ic_win_rate"` returns 2
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "\d feature_ic_scores" | grep "ic_sortino\|ic_win_rate"</verify>
  <done>ic_sortino and ic_win_rate columns present in feature_ic_scores.</done>
</task>

<task type="auto">
  <name>Task 1: Add ic_engine OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter/gauge/histogram factories; OUTCOME_LABELS_COVERAGE already defined in P3 -- do not redefine)
  </read_first>
  <action>
    In src/observability/metrics.py add (per observability mandate §XIX):

    Per-run flow metrics:
    - IC_ENGINE_CELLS_COMPLETED_TOTAL = _meter.create_counter("ic_engine_cells_completed_total", description="cells with committed feature_ic_scores row; labels symbol, tf, regime")
    - IC_ENGINE_CELLS_SKIPPED_TOTAL = _meter.create_counter("ic_engine_cells_skipped_total", description="cells skipped; labels symbol, tf, skip_reason in {insufficient_n, already_present, missing_regime, degenerate_feature}")
    - IC_ENGINE_RUN_LATENCY_SECONDS = _meter.create_histogram("ic_engine_run_latency_seconds", description="full IC Engine run duration")
    - FEATURE_IC_PASSING_FDR_TOTAL = _meter.create_gauge("feature_ic_passing_fdr_total", description="features passing BH-FDR gate; labels symbol, tf")
    - FEATURE_IC_PASSING_WALKFORWARD_TOTAL = _meter.create_gauge("feature_ic_passing_walkforward_total", description="features passing walk-forward gate; labels symbol, tf")

    Post-run IC health gauges (emitted after full run; scraped by Grafana for AlphaEngine health):
    - IC_SCORE_GAUGE = _meter.create_gauge("feature_ic_score", description="Spearman IC value per cell; labels feature_name, symbol, tf, regime, lookahead_bars, is_pooled")
    - EFFECTIVE_N_GAUGE = _meter.create_gauge("ic_engine_effective_n", description="effective independent observations used in IC computation; labels symbol, tf, regime")
    - FEATURES_SURVIVING_FDR_GAUGE = _meter.create_gauge("ic_engine_features_surviving_fdr", description="count of features passing BH-FDR gate per (symbol, tf, regime); labels symbol, tf, regime")
    - IC_SHARPE_GAUGE = _meter.create_gauge("ic_engine_ic_sharpe", description="IC Sharpe ratio per cell (NULL rows not emitted); labels feature_name, symbol, tf, regime, lookahead_bars")
    - IC_SORTINO_GAUGE = _meter.create_gauge("ic_engine_ic_sortino", description="IC Sortino ratio per cell — mean(window_ICs)/semi_deviation(target=0); NULL when all windows positive or gate not met; labels feature_name, symbol, tf, regime, lookahead_bars")
    - IC_WIN_RATE_GAUGE = _meter.create_gauge("ic_engine_ic_win_rate", description="fraction of rolling windows where IC > 0; labels feature_name, symbol, tf, regime, lookahead_bars")

    Reuse OUTCOME_LABELS_COVERAGE (already defined in P5). No prometheus_client.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python -c "from src.observability.metrics import IC_ENGINE_CELLS_COMPLETED_TOTAL, IC_ENGINE_CELLS_SKIPPED_TOTAL, IC_ENGINE_RUN_LATENCY_SECONDS, FEATURE_IC_PASSING_FDR_TOTAL, FEATURE_IC_PASSING_WALKFORWARD_TOTAL, IC_SCORE_GAUGE, EFFECTIVE_N_GAUGE, FEATURES_SURVIVING_FDR_GAUGE, IC_SHARPE_GAUGE, IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE; print('ok')"` exits 0
    - `grep -c "OUTCOME_LABELS_COVERAGE = " src/observability/metrics.py` returns 1 (not redefined)
    - `grep -c "degenerate_feature" src/observability/metrics.py` returns >= 1 (skip_reason documented in description)
    - `grep -c "IC_SCORE_GAUGE\|EFFECTIVE_N_GAUGE\|FEATURES_SURVIVING_FDR_GAUGE\|IC_SHARPE_GAUGE\|IC_SORTINO_GAUGE\|IC_WIN_RATE_GAUGE" src/observability/metrics.py` returns >= 6
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

    SCALES (schema-structural constant — gradient names are column identifiers):
      _SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")
      # Schema holds the concept (fast/mid/slow/extended); APR holds the period in bars
      # (alpha.ic.lookahead.{scale}). Adding a new scale requires a migration; changing
      # a period is an APR update only.

    APR loading via _load_config_service(conn): read ALL via cfg.get_sync --
      lookahead periods: alpha.ic.lookahead.{scale} for each scale in _SCALES (fb: 1, 5, 20, 60)
      min_observations (alpha.ic.min_observations, fb 500), bootstrap_resamples (alpha.ic.bootstrap_resamples, fb 2000),
      bootstrap_block_size (alpha.ic.bootstrap_block_size, fb 10), fdr_alpha (alpha.ic.fdr_alpha, fb 0.05),
      walk_forward_folds (alpha.ic.walk_forward_folds, fb 3), sharpe_window_size (alpha.ic.sharpe_window_size, fb 2000),
      sharpe_min_windows (alpha.ic.sharpe_min_windows, fb 10), subsample_min_stride (alpha.ic.subsample_min_stride, fb 5),
      min_reliable_n (alpha.ic.min_reliable_n, fb 100). ZERO inline numerics in compute logic.
    NOTE: the APR key is alpha.ic.subsample_min_stride (seeded in migration 161) — NOT alpha.ic.subsampling_n.
    Variable name in code: subsample_min_stride. Actual stride used per cell = max(subsample_min_stride, lookahead_bars).

    LOOKAHEADS dict (built from APR):
      _SCALE_FALLBACKS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}
      lookaheads = {scale: int(cfg.get_sync(f"alpha.ic.lookahead.{scale}", fb)) for scale, fb in _SCALE_FALLBACKS.items()}
      # lookaheads["fast"] = 1, lookaheads["mid"] = 5, etc. by default.
      # active_lookaheads list = list(lookaheads.values()) — always process all scales.

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
      b. Load forward returns: JOIN forward_returns by (symbol, tf, bar_ts) -- get return_fast/mid/slow/extended + complete_fast/mid/slow/extended aligned to the same bar_ts order (exact timestamp match, mandate #10).
      c. Distinct regimes for this (symbol, tf): the set of non-NULL regime values present. ALSO compute a pooled pass (is_pooled=True, regime=None).
      d. For each regime in {distinct regimes} + {None for pooled}:
         - mask rows to this regime (pooled = all rows); set is_pooled flag accordingly
         - SUBSAMPLE: compute stride = max(subsample_min_stride, lookahead_bars). Keep every
           stride-th row (non-overlapping independence) -> X_sub, returns_sub.
           n_independent = len(X_sub). This removes the serial autocorrelation that inflates
           naive IC standard errors. stride is per-lookahead (recalculate inside the lookahead loop).
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

             WALK-FORWARD WITH EMBARGO (fixes REVIEWS.md MEDIUM issue #7):
             Split the subsampled series chronologically into walk_forward_folds expanding windows.
             The embargo between training-fold-end and test-fold-start equals max(lookaheads.values())
             bars -- this prevents overlapping forward-return labels from leaking across the fold
             boundary (a bar near train_end has a forward return window that extends embargo_bars
             bars forward; the test set must start after that window closes).

               total_n = len(X_sub)
               embargo_bars = max(lookaheads.values())  # derived from APR; equals 60 for default extended=60
               fold_ics = []
               for k in range(walk_forward_folds):
                   train_end_idx = int(total_n * (k + 1) / (walk_forward_folds + 1))
                   test_start_idx = train_end_idx + embargo_bars
                   test_end_idx = int(total_n * (k + 2) / (walk_forward_folds + 1))
                   if test_start_idx >= test_end_idx or (test_end_idx - test_start_idx) < min_reliable_n:
                       continue  # not enough test data after embargo
                   X_test = X_sub[test_start_idx:test_end_idx]
                   Y_test = returns_sub[test_start_idx:test_end_idx, N_idx]
                   # Spearman IC ranks within the test window (no reference to training distribution
                   # needed -- Spearman correlation is invariant to monotone transforms of each series).
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

             - IC SHARPE / SORTINO / WIN RATE (IC spec §X.1): sharpe_window_size is in RAW bars.
               Gate uses n_raw_bars_regime = count of rows in the regime-masked series (after
               filtering to this specific regime, before subsampling). Gate: n_raw_bars_regime >=
               sharpe_min_windows * sharpe_window_size (default: 10 * 2000 = 20,000 raw bars).
               This is intentionally conservative: thin regimes correctly suppress these metrics
               rather than produce unreliable rolling-window estimates. For example, a trending_down
               regime with only 5,000 bars in a 5m series would not get any rolling window metrics
               (5K < 20K gate). Below threshold: ic_sharpe=NULL, ic_sortino=NULL,
               ic_win_rate=NULL, ic_sharpe_n_windows=NULL. Above threshold: divide the
               regime-masked raw bar series into non-overlapping windows of sharpe_window_size bars;
               within each window subsample at stride=max(subsample_min_stride, lookahead_bars) and
               compute Spearman IC to produce window_ICs (array of per-window IC values). Then:

                 ic_sharpe = mean(window_ICs) / std(window_ICs)   [symmetric penalisation]
                 ic_sharpe_n_windows = len(window_ICs)

                 # Sortino: penalise only negative-IC windows (target = 0)
                 neg_ics = window_ICs[window_ICs < 0]
                 if len(neg_ics) > 0:
                     semi_dev = np.sqrt(np.mean(neg_ics ** 2))     # semi-deviation from 0
                     ic_sortino = mean(window_ICs) / semi_dev if semi_dev > 1e-10 else None
                 else:
                     ic_sortino = None   # all windows positive — ratio undefined

                 ic_win_rate = np.mean(window_ICs > 0)             # fraction of windows IC > 0
             - Append result dict for this cell to a per-(symbol,tf) list AND append p_value to a flat pvals array with a PARALLEL list of (feature_name, regime, lookahead, is_pooled) tuples (order correspondence for FDR).

      e. BH-FDR per (symbol, tf) batch: reject, q_values, _, _ = statsmodels.stats.multitest.multipletests(pvals_array, alpha=fdr_alpha, method='fdr_bh'). multipletests PRESERVES input order. Set bh_adjusted_p and passes_fdr per cell by index.

      f. Batch INSERT all cells INTO feature_ic_scores. For each row, set is_pooled appropriately. Use TWO separate INSERT statements targeting the correct partial unique index.

         CRITICAL: feature_ic_scores_regime_uq and feature_ic_scores_pooled_uq are created with CREATE UNIQUE INDEX (not ADD CONSTRAINT), so ON CONFLICT ON CONSTRAINT is NOT valid — Postgres only allows ON CONFLICT ON CONSTRAINT for table constraints, not indexes. Use the column list + WHERE clause form that exactly matches each partial index predicate:

         For regime-stratified rows (is_pooled=False, regime IS NOT NULL):
           INSERT INTO feature_ic_scores (..., regime, is_pooled, ...)
           VALUES (%s, ..., %s, false, ...)
           ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
             WHERE is_pooled = false AND regime IS NOT NULL
           DO NOTHING

         For pooled rows (is_pooled=True, regime=NULL):
           INSERT INTO feature_ic_scores (..., regime, is_pooled, ...)
           VALUES (%s, ..., NULL, true, ...)
           ON CONFLICT (feature_name, symbol, tf, lookahead_bars, training_window_end)
             WHERE is_pooled = true
           DO NOTHING

         Do NOT attempt ON CONFLICT ON CONSTRAINT — it will fail at runtime. The WHERE clause in ON CONFLICT must exactly match the partial index predicate for Postgres to recognise the index.

      g. IC_ENGINE_CELLS_COMPLETED_TOTAL.add(n_committed, {symbol, tf, regime}); FEATURE_IC_PASSING_FDR_TOTAL.set(n_passing_fdr, {symbol, tf}); FEATURE_IC_PASSING_WALKFORWARD_TOTAL.set(n_passing_wf, {symbol, tf}).

    Wrap full run in observed_span("ic_engine.run"); record IC_ENGINE_RUN_LATENCY_SECONDS. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": ...}) in finally block; flush_and_shutdown_metrics(); sys.exit(1) on failure.

    POST-RUN IC HEALTH GAUGES: after the full compute loop completes (before D-06 emission),
    query feature_ic_scores for the current training_window_end and emit the 4 health gauges.
    This allows Grafana to scrape IC health without needing to parse the discovery report:
      - IC_SCORE_GAUGE.set(ic_value, {"feature_name": ..., "symbol": ..., "tf": ..., "regime": ..., "lookahead_bars": str(n), "is_pooled": str(is_pooled)}) for each non-NULL ic_value row
      - EFFECTIVE_N_GAUGE.set(n_independent, {"symbol": ..., "tf": ..., "regime": ...}) per (symbol, tf, regime) from the compute loop
      - FEATURES_SURVIVING_FDR_GAUGE.set(n_passing_fdr, {"symbol": ..., "tf": ..., "regime": ...}) per (symbol, tf, regime)
      - IC_SHARPE_GAUGE.set(ic_sharpe, {"feature_name": ..., "symbol": ..., "tf": ..., "regime": ..., "lookahead_bars": str(n)}) for each row where ic_sharpe IS NOT NULL
      - IC_SORTINO_GAUGE.set(ic_sortino, {"feature_name": ..., "symbol": ..., "tf": ..., "regime": ..., "lookahead_bars": str(n)}) for each row where ic_sortino IS NOT NULL
      - IC_WIN_RATE_GAUGE.set(ic_win_rate, {"feature_name": ..., "symbol": ..., "tf": ..., "regime": ..., "lookahead_bars": str(n)}) for each row where ic_win_rate IS NOT NULL

    REPORT-ONLY MODE: implement --report-only argparse flag. When set, skip all IC computation;
    query the current feature_ic_scores (MAX training_window_end) and write the IC discovery
    report (markdown + JSON) only. This is the flag P8 Task 5 calls. Implement it in ic_engine.py
    in P6 -- do not defer to P8.

    DAG-invariant docstring note: oneshot batch tool, exempt like backfill_feature_factory.py.
    argparse: --symbols (default all feature_vectors symbols), --tf (default 4 TFs),
    --report-only (skip IC computation; write discovery report from existing feature_ic_scores).
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/ic_engine.py --symbols VUG --tf 1h` exits 0 (VUG 1h is the only symbol with feature_vectors data at this stage; full corpus run is P8)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='VUG' AND tf='1h';"` returns > 0
    - Pooled rows have is_pooled=true: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='VUG' AND tf='1h' AND is_pooled=true AND regime IS NULL;"` returns > 0
    - Regime rows have is_pooled=false: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='VUG' AND tf='1h' AND is_pooled=false AND regime IS NOT NULL;"` returns > 0
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
    - IC Sharpe gate: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_sharpe IS NOT NULL AND ic_sharpe_n_windows < 10 AND symbol='SPY' AND tf='5m';"` returns 0 (ic_sharpe only non-NULL when enough windows exist)
    - ic_win_rate in [0,1]: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_win_rate IS NOT NULL AND (ic_win_rate < 0 OR ic_win_rate > 1);"` returns 0
    - ic_sortino and ic_win_rate co-NULL with ic_sharpe: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_sharpe IS NULL AND ic_win_rate IS NOT NULL;"` returns 0 (win_rate absent when sharpe gate not met)
    - ic_sortino NULL when all windows positive: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_win_rate = 1.0 AND ic_sortino IS NOT NULL;"` returns 0
    - CRASH-LOUD verified: `.venv/bin/python -c "import sys; sys.exit(0)" && echo "verify gate manually by running with NONEXISTENT symbol and confirming non-zero exit"` -- confirm in acceptance that a fresh test with empty feature_vectors exits non-zero (can be tested by mocking if needed)
    - `grep -c "rankdata" services/ic_engine.py` returns >= 1
    - `grep -c "multipletests" services/ic_engine.py` returns >= 1
    - `grep -c "observed_span" services/ic_engine.py` returns >= 3 (run, compute_symbol_tf, bootstrap_ci)
    - `grep -c "JOB_COMPLETED_TOTAL\|flush_and_shutdown_metrics" services/ic_engine.py` returns >= 2
    - `grep -c "dataclasses.fields\|fields(FeatureVector)" services/ic_engine.py` returns >= 1
    - Lookahead periods from APR: `grep -c "alpha\.ic\.lookahead\." services/ic_engine.py` returns >= 4
    - embargo_bars derived: `grep -c "max(lookaheads" services/ic_engine.py` returns >= 1
    - No hardcoded embargo: `grep -c "embargo_bars\s*=\s*60" services/ic_engine.py` returns 0
    - No X_train dead variable: `grep -c "X_train\s*=" services/ic_engine.py` returns 0
    - Report-only flag present: `grep -c "report.only\|report_only" services/ic_engine.py` returns >= 2 (argparse + usage)
    - IC health gauges emitted: `grep -c "IC_SCORE_GAUGE\|EFFECTIVE_N_GAUGE\|FEATURES_SURVIVING_FDR_GAUGE\|IC_SHARPE_GAUGE\|IC_SORTINO_GAUGE\|IC_WIN_RATE_GAUGE" services/ic_engine.py` returns >= 6
    - Per-regime n_raw_bars gate: `grep -c "n_raw_bars_regime\|n_raw_bars" services/ic_engine.py` returns >= 2
    - `grep -c "stride\s*=\s*max" services/ic_engine.py` returns >= 1
    - `.venv/bin/ruff check services/ic_engine.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/ic_engine.py --symbols VUG --tf 1h && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, is_pooled, count(*), count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores WHERE symbol='VUG' AND tf='1h' GROUP BY regime, is_pooled;"</verify>
  <done>ic_engine.py produces complete feature_ic_scores rows for VUG 1h; circular-block-bootstrap CI; embargo = max(lookaheads.values()) bars; degenerate feature skip (DEBUG log); is_pooled correct; crash-loud RuntimeError gates; --report-only flag implemented; 6 IC health gauges emitted (including IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE); ic_sortino (semi-deviation from 0, NULL when all windows positive) and ic_win_rate (% windows IC>0) computed alongside ic_sharpe from same window_ICs array; stride = max(subsample_min_stride, lookahead_bars) per cell; lookahead periods from APR (alpha.ic.lookahead.*); D-06 + 9 OTel + 3 spans; APR-compliant. Full corpus run is P8.</done>
</task>

</tasks>

<verification>
- feature_ic_scores complete for VUG 1h (smoke test): IC, CI (circular block bootstrap), p, BH-FDR q, walk-forward (embargo = max(lookaheads.values()) bars), IC Sharpe, IC Sortino, IC win rate per cell
- is_pooled=true for pooled rows; is_pooled=false for regime-stratified rows; no is_pooled=false+regime=NULL ambiguity
- bootstrap_block_size from APR (alpha.ic.bootstrap_block_size); no iid bootstrap
- Degenerate features (std < 1e-8) skipped with IC_ENGINE_CELLS_SKIPPED_TOTAL degenerate_feature; logged at DEBUG
- Crash-loud: three RuntimeError gates with explicit messages; no silent empty success
- embargo_bars = max(lookaheads.values()); no hardcoded 60; no X_train dead variable
- lookahead periods from APR (alpha.ic.lookahead.*); _SCALES tuple is the schema constant
- 6 IC health gauges emitted post-run: IC_SCORE_GAUGE, EFFECTIVE_N_GAUGE, FEATURES_SURVIVING_FDR_GAUGE, IC_SHARPE_GAUGE, IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE
- --report-only flag implemented and functional
- IC Sharpe / Sortino / win rate gate uses per-regime n_raw_bars; thin regimes correctly yield NULL for all three
- ic_sortino is NULL when all rolling windows have IC > 0 (ratio undefined); ic_win_rate stays populated
- Idempotent; D-06 + 9 OTel signals + 3 spans; APR-compliant; full corpus run deferred to P8
</verification>

<success_criteria>
- All task acceptance criteria pass (VUG 1h smoke test)
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-06-SUMMARY.md` documenting: 7 OTel metrics added (including IC_SORTINO_GAUGE, IC_WIN_RATE_GAUGE), ic_engine.py line count, VUG 1h smoke test results (feature_ic_scores row counts, FDR and walk-forward pass counts, sample ic_sharpe/ic_sortino/ic_win_rate values), and code patterns used (circular bootstrap, embargo, degenerate skip, Sortino semi-deviation). Note that full corpus run is P8.
</output>
