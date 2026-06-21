---
phase: 138-ic-engine-outcome-labels
plan: 04
type: execute
wave: 3
depends_on: ["138-02", "138-03"]
files_modified:
  - services/ic_engine.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "feature_ic_scores has one row per (feature, symbol, tf, regime, lookahead, training_window_end)"
    - "Each row carries ic_value, p_value, bootstrap CI, BH-FDR q-value, walk-forward result, IC Sharpe"
    - "IC computation is vectorized (rank-once + matrix corrcoef), matches scipy.spearmanr"
    - "BH-FDR is applied per (symbol, tf) batch with order-preserving cell mapping"
    - "Walk-forward (3 expanding folds) confirms out-of-sample IC; passes_walkforward stricter than passes_fdr"
    - "IC Sharpe gated at min 20,000 independent obs (10 windows x 2,000); else ic_sharpe=NULL"
    - "IC run CRASHES LOUD if feature_vectors empty, regime all-NULL, or outcome_labels empty"
    - "Idempotent: second run inserts 0 rows (ON CONFLICT DO NOTHING, training_window_end dedup)"
    - "ic_engine emits D-06 job_completed_total + 6 per-service OTel metrics + spans"
  artifacts:
    - path: "services/ic_engine.py"
      provides: "Vectorized Spearman IC engine with bootstrap CI, BH-FDR, walk-forward, IC Sharpe"
      min_lines: 400
    - path: "src/observability/metrics.py"
      provides: "ic_engine_cells_completed_total, ic_engine_cells_skipped_total, ic_engine_run_latency_seconds, feature_ic_passing_fdr_total, feature_ic_passing_walkforward_total"
      contains: "ic_engine_cells_completed_total"
  key_links:
    - from: "ic_engine.py"
      to: "feature_ic_scores table"
      via: "INSERT ... ON CONFLICT DO NOTHING (training_window_end dedup)"
      pattern: "INSERT INTO feature_ic_scores"
    - from: "feature_vectors (X) JOIN outcome_labels (Y)"
      to: "Spearman IC per cell"
      via: "rankdata(X, axis=0) + vectorized corrcoef on ranks"
      pattern: "rankdata"
    - from: "per-cell p_values array"
      to: "passes_fdr"
      via: "multipletests(pvals, method='fdr_bh') with parallel cell tuple list"
      pattern: "multipletests"
---

<objective>
Build `services/ic_engine.py` — the measurement substrate of the entire v3.0 AlphaEngine. Computes Spearman IC per feature x symbol x TF x regime x lookahead, with bootstrap CI, BH-FDR correction, 3-fold walk-forward validation, and IC Sharpe, into feature_ic_scores.

Purpose: IC is the unit of measure; IC Sharpe is the unit of trust (Renaissance mandate #1). This is the most important file in Phase 138. Every gate (regime-conditioning, FDR, walk-forward, IC Sharpe minimum-N) must be present.
Output: feature_ic_scores fully populated for backfilled universe, vectorized + correct + idempotent + crash-loud + fully instrumented.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md
@CLAUDE.md
@docs/plans/2026-06-20-alphaengine-ic-spec.md
@docs/ideas/analog-engine-ic-factory.md
@services/backfill_feature_factory.py
@services/outcome_writer.py
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
    - src/observability/metrics.py (counter/gauge/point_gauge factories; OUTCOME_LABELS_COVERAGE already defined in P3 — do not redefine)
  </read_first>
  <action>
    In src/observability/metrics.py add (per observability mandate §XIX):
    - IC_ENGINE_CELLS_COMPLETED_TOTAL = _meter.create_counter("ic_engine_cells_completed_total", description="cells with committed feature_ic_scores row; labels symbol, tf, regime")
    - IC_ENGINE_CELLS_SKIPPED_TOTAL = _meter.create_counter("ic_engine_cells_skipped_total", description="cells skipped; labels symbol, tf, skip_reason in {insufficient_n, already_present, missing_regime}")
    - IC_ENGINE_RUN_LATENCY_SECONDS = _meter.create_histogram("ic_engine_run_latency_seconds", description="full IC Engine run duration")
    - FEATURE_IC_PASSING_FDR_TOTAL = _meter.create_gauge("feature_ic_passing_fdr_total", description="features passing BH-FDR gate; labels symbol, tf")
    - FEATURE_IC_PASSING_WALKFORWARD_TOTAL = _meter.create_gauge("feature_ic_passing_walkforward_total", description="features passing walk-forward gate; labels symbol, tf")
    Reuse OUTCOME_LABELS_COVERAGE (already defined). No prometheus_client.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python -c "from src.observability.metrics import IC_ENGINE_CELLS_COMPLETED_TOTAL, IC_ENGINE_CELLS_SKIPPED_TOTAL, IC_ENGINE_RUN_LATENCY_SECONDS, FEATURE_IC_PASSING_FDR_TOTAL, FEATURE_IC_PASSING_WALKFORWARD_TOTAL; print('ok')"` exits 0
    - `grep -c "OUTCOME_LABELS_COVERAGE = " src/observability/metrics.py` returns 1 (not redefined)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import IC_ENGINE_CELLS_COMPLETED_TOTAL; print('ok')"</verify>
  <done>Five ic_engine metrics importable.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/ic_engine.py — vectorized IC, bootstrap CI, BH-FDR, walk-forward, IC Sharpe</name>
  <files>services/ic_engine.py</files>
  <read_first>
    - services/ic_engine.py (the file being created — does not exist yet)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§V forward return, §VIII bootstrap/subsampling, §IX BH-FDR + walk-forward, §X IC Sharpe, §XIV.4 feature_ic_scores columns, §XX restart logic)
    - docs/ideas/analog-engine-ic-factory.md ("What Simons Would Demand" — all 7 points are mandatory design constraints)
    - .planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md (Findings 3,4,5,6,10; Risks 3,5,6; "Deliverable D" computation loop)
    - src/intelligence/schemas.py (FeatureVector — the 54 field names are the feature_name values; these map to feature_vectors columns)
    - services/backfill_feature_factory.py (Ring 2 oneshot template; _load_config_service; _JOB; JOB_COMPLETED_TOTAL; flush_and_shutdown_metrics)
    - services/outcome_writer.py (sibling pattern + outcome_labels schema usage)
    - src/observability/spans.py (observed_span, ATTR_*)
    - CLAUDE.md (APR rules; UTC; crash-loud > silent-wrong; market_data/feature_vectors column names)
  </read_first>
  <action>
    Create services/ic_engine.py as a sync psycopg2 oneshot. Constants: `_JOB = "ic-engine"`, log "logs/ic_engine.log". vector_domain for all 54 features in Phase 138 is "quant" (V2/V3/V4 vectors are Phase 139+) — define `_VECTOR_DOMAIN = "quant"` with a comment.

    The 54 feature names = the field names of FeatureVector (src/intelligence/schemas.py), which are also the feature_vectors column names. Build `_FEATURE_NAMES = [f.name for f in dataclasses.fields(FeatureVector)]` so the list stays in sync automatically (do NOT hardcode 54 names).

    APR loading via _load_config_service(conn): read all via cfg.get_sync — min_observations (alpha.ic.min_observations, fb 500), bootstrap_resamples (alpha.ic.bootstrap_resamples, fb 2000), fdr_alpha (alpha.ic.fdr_alpha, fb 0.05), walk_forward_folds (alpha.ic.walk_forward_folds, fb 3), sharpe_window_size (alpha.ic.sharpe_window_size, fb 2000), sharpe_min_windows (alpha.ic.sharpe_min_windows, fb 10), subsampling_n (alpha.ic.subsampling_n, fb 5), min_reliable_n (alpha.ic.min_reliable_n, fb 100). ZERO inline numerics in compute logic.

    Lookaheads: [1,5,20,60] mapping to outcome_labels.return_1bar/5bar/20bar/60bar (statistical-concept column names, allowed).

    CRASH-LOUD GATES (Renaissance mandate #9) — run at startup BEFORE any compute, raise RuntimeError with a clear message if violated:
      - `SELECT count(*) FROM feature_vectors` == 0 -> raise "feature_vectors is empty"
      - `SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL` == 0 -> raise "regime column is all-NULL — run regime_writer first"
      - `SELECT count(*) FROM outcome_labels` == 0 -> raise "outcome_labels is empty — run outcome_writer first"
    A run that "succeeds" with empty feature_ic_scores is a data-integrity failure.

    RUN constants: RUN_TS = datetime.now(UTC); TRAINING_WINDOW_END = MAX(bar_ts) FROM feature_vectors (locked once at start).

    IDEMPOTENCY (RESEARCH.md Finding 10): on startup, load existing tuples for this training_window_end:
      `SELECT feature_name, symbol, tf, regime, lookahead_bars FROM feature_ic_scores WHERE training_window_end = %s` into a set. Skip any cell already present (emit IC_ENGINE_CELLS_SKIPPED_TOTAL skip_reason="already_present"). INSERT uses ON CONFLICT DO NOTHING. For regime=NULL pooled rows rely on the feature_ic_scores_pooled_uq partial index (migration 157).

    COMPUTE LOOP — for each (symbol, tf), wrap in observed_span("ic_engine.compute_symbol_tf"):
      a. Load feature matrix: SELECT bar_ts, regime, <54 feature columns> FROM feature_vectors WHERE symbol=%s AND tf=%s AND bar_ts <= TRAINING_WINDOW_END ORDER BY bar_ts. Load into numpy arrays (X shape [n_bars, 54]).
      b. Load forward returns: JOIN outcome_labels by (symbol, tf, bar_ts) — get return_1bar/5bar/20bar/60bar + complete flags aligned to the same bar_ts order (exact timestamp match, mandate #10).
      c. Distinct regimes for this (symbol, tf): the set of non-NULL regime values present. ALSO compute a pooled (regime=NULL) pass.
      d. For each regime in {distinct regimes} + {None pooled}:
         - mask rows to this regime (pooled = all rows)
         - SUBSAMPLE: keep every subsampling_n-th row (non-overlapping independence, RESEARCH.md Finding 6) -> X_sub, returns_sub. n_independent = rows kept.
         - if n_independent < min_reliable_n: skip cell, IC_ENGINE_CELLS_SKIPPED_TOTAL.add(1, {symbol, tf, skip_reason:"insufficient_n"}); continue.
         - reliable = n_independent >= min_reliable_n (always true here given the skip) but also flag rows where n_independent >= min_observations differently if spec distinguishes; store reliable per §XIV.4.
         - PRE-RANK ONCE: ranks_X = scipy.stats.rankdata(X_sub, axis=0)  (RESEARCH.md Finding 3 — one call for all 54 features)
         - For each lookahead N in [1,5,20,60]:
             - select returns_sub[:,N] filtered to complete_Nbar rows; align ranks_X to those rows.
             - if remaining n < min_reliable_n: skip.
             - ranks_Y = rankdata(returns_N)
             - IC per feature = Pearson correlation between ranks_X[:,j] and ranks_Y, computed VECTORIZED via the standard centered-dot formula (corrcoef on ranks) — produces ic_vector shape [54]. This equals Spearman rho.
             - p_value per feature via scipy.stats.spearmanr (RESEARCH.md Finding 5 — analytical p for n>=30). Acceptable to call spearmanr per feature for the p-value, or use the t-approximation; the unit test in P5 validates the IC value against spearmanr to 1e-10.
             - BOOTSTRAP CI (RESEARCH.md Finding 4 — manual numpy, NOT scipy.stats.bootstrap): wrap in observed_span("ic_engine.bootstrap_ci"). bootstrap_resamples resamples with replacement on the subsampled index; recompute rank-correlation per resample VECTORIZED over all 54 features simultaneously. ic_ci_lower = 2.5th percentile, ic_ci_upper = 97.5th percentile per feature. passes_ci_gate = ic_ci_lower > 0.
             - WALK-FORWARD (3 expanding folds, IC spec §IX.3): split the subsampled series chronologically; expanding-window training, measure IC on each out-of-sample fold; wf_pass_count = folds where OOS IC > 0; wf_ic_sharpe = mean(fold_IC)/std(fold_IC); passes_walkforward = (wf_pass_count == wf_fold_count) AND meets IC Sharpe min-N. passes_walkforward is a HARDER gate than passes_fdr (mandate #4).
             - IC SHARPE (IC spec §X.1): only computable if n_independent >= sharpe_min_windows * sharpe_window_size (= 10*2000 = 20,000). Below threshold: ic_sharpe=NULL, ic_sharpe_n_windows = n_windows_computed, passes_walkforward=false for IC-Sharpe purposes (RESEARCH.md Risk 3). Compute IC per rolling window of sharpe_window_size, ic_sharpe = mean/std across windows.
             - Append a result dict for this cell to a per-(symbol,tf) list AND append p_value to a flat pvals array with a PARALLEL list of (feature_name, regime, lookahead) tuples (RESEARCH.md Finding 5 — order correspondence for FDR).
      e. BH-FDR per (symbol, tf) batch (RESEARCH.md "BH-FDR ordering"): reject, q_values, _, _ = statsmodels.stats.multitest.multipletests(pvals_array, alpha=fdr_alpha, method='fdr_bh'). multipletests PRESERVES input order — q_values[i] corresponds to cell tuple i. Set bh_adjusted_p and passes_fdr per cell by index.
      f. Batch INSERT all cells INTO feature_ic_scores with ON CONFLICT DO NOTHING. For regime IS NOT NULL use the PK; for regime IS NULL rely on the partial unique index (migration 157) — use a separate INSERT statement targeting `ON CONFLICT (feature_name, symbol, tf, lookahead_bars, training_window_end) WHERE regime IS NULL DO NOTHING` for pooled rows, and the PK conflict target for regime-stratified rows.
      g. IC_ENGINE_CELLS_COMPLETED_TOTAL.add(n_committed, {symbol, tf, regime}); FEATURE_IC_PASSING_FDR_TOTAL.set(n_passing_fdr, {symbol, tf}); FEATURE_IC_PASSING_WALKFORWARD_TOTAL.set(n_passing_wf, {symbol, tf}).

    Wrap full run in observed_span("ic_engine.run"); record IC_ENGINE_RUN_LATENCY_SECONDS. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": ...}); flush_and_shutdown_metrics(); sys.exit(1) on failure.

    DAG-invariant docstring note: oneshot batch tool, exempt like backfill_feature_factory.py.
    argparse: --symbols (default all feature_vectors symbols), --tf (default 4 TFs).
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m` exits 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m';"` returns > 0
    - At least some features show edge: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' AND ic_ci_lower > 0;"` returns >= 1
    - regime-stratified rows exist: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT regime) FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' AND regime IS NOT NULL;"` returns >= 2
    - BH-FDR populated: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE bh_adjusted_p IS NOT NULL AND symbol='SPY' AND tf='5m';"` returns > 0
    - walk-forward populated: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE passes_walkforward IS NOT NULL AND symbol='SPY' AND tf='5m';"` returns > 0
    - IC Sharpe respects gate: every row with ic_sharpe IS NOT NULL has n_independent >= 20000 — `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE ic_sharpe IS NOT NULL AND n_independent < 20000 AND symbol='SPY' AND tf='5m';"` returns 0
    - CRASH-LOUD verified: `.venv/bin/python services/ic_engine.py --symbols NONEXISTENT_SYMBOL --tf 5m` exits non-zero with a RuntimeError mentioning empty data (no silent empty success)
    - `grep -c "rankdata" services/ic_engine.py` returns >= 1 and `grep -c "scipy.stats.bootstrap" services/ic_engine.py` returns 0 (manual bootstrap only)
    - `grep -c "multipletests" services/ic_engine.py` returns >= 1
    - `grep -c "observed_span" services/ic_engine.py` returns >= 3 (run, compute_symbol_tf, bootstrap_ci)
    - `grep -c "JOB_COMPLETED_TOTAL\|flush_and_shutdown_metrics" services/ic_engine.py` returns >= 2
    - `dataclasses.fields(FeatureVector)` used for feature names: `grep -c "dataclasses.fields\|fields(FeatureVector)" services/ic_engine.py` returns >= 1
    - `.venv/bin/ruff check services/ic_engine.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, count(*), count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores WHERE symbol='SPY' AND tf='5m' GROUP BY regime;"</verify>
  <done>ic_engine.py produces complete feature_ic_scores rows for SPY 5m with IC, CI, p, BH-FDR q, walk-forward, IC Sharpe; vectorized; regime-stratified; crash-loud; D-06 + 5 OTel metrics + 3 spans wired; APR-compliant.</done>
</task>

<task type="auto">
  <name>Task 3: Run IC engine across all backfilled symbols/TFs</name>
  <files>feature_ic_scores (DB table — populated)</files>
  <read_first>
    - services/ic_engine.py (just built)
    - .planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md (Finding 3 full-run estimate ~2.8 min bootstrap phase; Risk 3 1h TF marginal)
  </read_first>
  <action>
    Run `.venv/bin/python services/ic_engine.py` with no symbol filter. Run in background; poll feature_ic_scores counts. Then verify idempotency by re-running SPY 5m.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_ic_scores;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE passes_walkforward = true;"` returns >= 1 (at least one feature survives the hardest gate)
    - Idempotency: capture `SELECT count(*) FROM feature_ic_scores`, re-run `.venv/bin/python services/ic_engine.py --symbols SPY --tf 5m`, count again — counts EQUAL (0 new rows, ON CONFLICT DO NOTHING)
    - `job_completed_total{job="ic-engine", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(*) total, count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores GROUP BY tf ORDER BY tf;"</verify>
  <done>feature_ic_scores populated for >=14 symbols x 4 TFs; idempotent re-run confirmed.</done>
</task>

</tasks>

<verification>
- feature_ic_scores complete: IC, CI, p, BH-FDR q, walk-forward, IC Sharpe per cell
- Vectorized IC; regime-stratified; FDR per (symbol,tf) batch order-preserving
- Walk-forward stricter than FDR; IC Sharpe gated at 20K obs; crash-loud on empty data
- Idempotent; D-06 + 5 OTel + 3 spans; APR-compliant
</verification>

<success_criteria>
- All task acceptance criteria pass
- At least one feature passes_walkforward across the universe
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-outcome-labels/138-04-SUMMARY.md` documenting feature_ic_scores counts per (symbol, tf, regime), how many features passed FDR and walk-forward, the top features by IC Sharpe, and any (symbol, tf) cells below the 20K IC-Sharpe gate.
</output>
