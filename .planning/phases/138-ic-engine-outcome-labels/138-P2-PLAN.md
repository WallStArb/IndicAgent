---
phase: 138-ic-engine-outcome-labels
plan: 02
type: execute
wave: 2
depends_on: ["138-01"]
files_modified:
  - services/regime_labeler.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "feature_vectors.regime is populated with canonical text labels for >95% of rows"
    - "Each (symbol, tf) is decoded with its own HMM (per-TF, not a shared 1m model)"
    - "regime labels are causal (forward Viterbi / filtered, no backward smoother)"
    - "regime_labeler emits D-06 job_completed_total and per-service OTel metrics"
  artifacts:
    - path: "services/regime_labeler.py"
      provides: "Oneshot that UPDATEs feature_vectors.regime via HMM Viterbi decoding per (symbol, tf)"
      min_lines: 200
    - path: "src/observability/metrics.py"
      provides: "regime_labeler_rows_updated_total, regime_labeler_run_latency_seconds, regime_labeler_null_regime_remaining"
      contains: "regime_labeler"
  key_links:
    - from: "regime_labeler.py"
      to: "feature_vectors.regime column"
      via: "UPDATE feature_vectors SET regime = %s WHERE symbol=%s AND tf=%s AND bar_ts=%s"
      pattern: "UPDATE feature_vectors SET regime"
    - from: "regime_labeler.py"
      to: "hmmlearn GaussianHMM (per src/intelligence/services/hmm_trainer.py)"
      via: "fit + predict (Viterbi) on per-(symbol,tf) return/vol obs matrix"
      pattern: "GaussianHMM|\\.predict\\("
---

<objective>
Build `services/regime_labeler.py` — a Ring 2 oneshot that populates feature_vectors.regime (currently NULL for ALL rows, RESEARCH.md Finding 2). This is UNTRACKED-but-mandatory scope: regime-stratified IC is impossible without it, and pooled IC is not an acceptable substitute (IC spec §III.3). This is a hard blocker for the IC Engine (P4).

Purpose: regime-conditioning is non-negotiable (Renaissance mandate #2). Global IC hides sign flips between trending and ranging regimes.
Output: feature_vectors.regime set to canonical text labels for >95% of rows, per-(symbol, tf) HMM decoding, full D-06 + OTel instrumentation.
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
@services/backfill_feature_factory.py
@src/intelligence/services/hmm_trainer.py
@src/core/service_utils.py
@src/observability/metrics.py
@src/observability/spans.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add regime_labeler OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter(), gauge(), point_gauge() factories around lines 72-90; existing metric definition blocks for style)
    - .planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md
  </read_first>
  <action>
    In src/observability/metrics.py, add a Phase 138 metrics section defining:
    - REGIME_LABELER_ROWS_UPDATED_TOTAL = _meter.create_counter("regime_labeler_rows_updated_total", description="feature_vectors rows with regime set; labels symbol, tf")
    - REGIME_LABELER_RUN_LATENCY_SECONDS = _meter.create_histogram("regime_labeler_run_latency_seconds", description="Full regime labeler run duration")
    - REGIME_LABELER_NULL_REGIME_REMAINING = _meter.create_gauge("regime_labeler_null_regime_remaining", description="feature_vectors rows still regime=NULL after run; labels symbol, tf")
    Use _meter.create_gauge for the point gauge (matches point_gauge helper). Do NOT import prometheus_client.
  </action>
  <acceptance_criteria>
    - `grep -c "REGIME_LABELER_ROWS_UPDATED_TOTAL\|REGIME_LABELER_RUN_LATENCY_SECONDS\|REGIME_LABELER_NULL_REGIME_REMAINING" src/observability/metrics.py` returns 3
    - `.venv/bin/python -c "from src.observability.metrics import REGIME_LABELER_ROWS_UPDATED_TOTAL, REGIME_LABELER_RUN_LATENCY_SECONDS, REGIME_LABELER_NULL_REGIME_REMAINING; print('ok')"` exits 0
    - `grep -c "prometheus_client" src/observability/metrics.py` returns 0
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import REGIME_LABELER_ROWS_UPDATED_TOTAL; print('ok')"</verify>
  <done>Three regime_labeler metrics importable from metrics.py.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/regime_labeler.py oneshot with per-(symbol,tf) HMM decoding</name>
  <files>services/regime_labeler.py</files>
  <read_first>
    - services/regime_labeler.py (the file being created — does not exist yet)
    - src/intelligence/services/hmm_trainer.py (FULL READ — _build_symbol_obs, _fit_hmm, _build_obs_matrix; understand n_components=3, covariance_type='diag', obs matrix is per-symbol log returns + vol to prevent cross-symbol contamination; what _fit_hmm returns)
    - services/backfill_feature_factory.py (Ring 2 oneshot template: _load_config_service lines 235-249, argparse, setup_service_logging, JOB_COMPLETED_TOTAL emission at exit, flush_and_shutdown_metrics, psycopg2 sync DB pattern, _JOB constant)
    - src/core/service_utils.py (setup_service_logging, format_iso_ts)
    - src/observability/spans.py (observed_span signature, ATTR_* constants)
    - .planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md (Deliverable A, Risk 2, Risk 4)
    - CLAUDE.md (APR rules: zero hardcoded numerics; DAG invariant: only writers touch DB but oneshots are exempt like backfill; D-06; UTC timestamps)
  </read_first>
  <action>
    Create services/regime_labeler.py as a sync psycopg2 oneshot mirroring backfill_feature_factory.py structure.

    Constants: `_JOB = "regime-labeler"`, log file "logs/regime_labeler.log" via setup_service_logging.

    Canonical regime label mapping (RESEARCH.md Risk 4 — HMM produces integer states, IC spec wants text). Order HMM states by mean return then volatility to assign deterministic labels. Define module constant with explanatory comment:
      _REGIME_LABELS = {0: "ranging", 1: "trending_up", 2: "trending_down"}  # n_components=3 default
    Sort states so state with lowest |mean return| -> "ranging", highest positive mean -> "trending_up", lowest (most negative) mean -> "trending_down". Map the fitted-state index to label via this ordering so labels are semantically stable across symbols. Add a docstring note that n_components is an APR key (feature.hmm.n_components) and the label set adapts if it changes.

    APR loading via _load_config_service(conn) (copy pattern from backfill): read feature.hmm.n_components (fallback 3) and feature.hmm.covariance_type if present (fallback 'diag'). Zero inline numerics — use cfg.get_sync.

    Core flow (per RESEARCH.md "Deliverable A" + intel-07 per-TF requirement):
    1. argparse: --symbols (nargs='*', default all distinct feature_vectors symbols), --tf (nargs='*', default ['5m','15m','1h','1d'])
    2. Open psycopg2 conn; init_otel_providers; _load_config_service.
    3. For each (symbol, tf):
       - wrap in observed_span("regime_labeler.label_symbol_tf", attributes={...symbol, tf...})
       - SELECT bar_ts, close, momentum_z_5, atr_z (or equivalent return/vol features) FROM feature_vectors WHERE symbol=%s AND tf=%s ORDER BY bar_ts ASC. Build the SAME obs matrix the HMMTrainer uses (log returns + volatility proxy) so labels are consistent with v3.0 feature semantics. Reuse HMMTrainer._build_symbol_obs logic (import the function or replicate the exact transform; do NOT silently diverge).
       - Skip (with a logged warning) if < n_components*50 bars.
       - Fit GaussianHMM(n_components, covariance_type, n_iter from APR or fallback) on the obs. Use forward Viterbi decoding: `states = model.predict(obs)` (filtered/causal — the predict path; do NOT use any backward smoothing). Map states to canonical text via _REGIME_LABELS after sorting states by mean return.
       - Batch UPDATE feature_vectors SET regime = %s WHERE symbol=%s AND tf=%s AND bar_ts=%s using execute_batch (psycopg2.extras), batching ~500 rows.
       - REGIME_LABELER_ROWS_UPDATED_TOTAL.add(n_rows, {"symbol": symbol, "tf": tf})
       - After update, SELECT count(*) FROM feature_vectors WHERE symbol=%s AND tf=%s AND regime IS NULL; REGIME_LABELER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})
    4. Wrap the whole run in observed_span("regime_labeler.run"); record REGIME_LABELER_RUN_LATENCY_SECONDS at end.
    5. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"|"failure"}) and call flush_and_shutdown_metrics() before exit. On any unhandled exception: log, emit status="failure", flush, sys.exit(1).

    DAG invariant note: this oneshot is exempt from the "only writers touch DB" rule exactly as backfill_feature_factory.py is — it is a batch labeling tool, not a real-time daemon. Add a docstring comment stating this.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/regime_labeler.py --symbols SPY --tf 5m` exits 0
    - After run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND regime IS NULL;"` returns < 5% of `SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m'`
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT DISTINCT regime FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND regime IS NOT NULL;"` returns only canonical text values (subset of ranging, trending_up, trending_down) — NO integer strings like '0'/'1'/'2'
    - `grep -c "observed_span" services/regime_labeler.py` returns >= 2 (run + label_symbol_tf)
    - `grep -c "JOB_COMPLETED_TOTAL" services/regime_labeler.py` returns >= 1 and `grep -c "flush_and_shutdown_metrics" services/regime_labeler.py` returns >= 1
    - `grep -c "model.predict\|\.predict(" services/regime_labeler.py` returns >= 1 (Viterbi/filtered decoding)
    - No hardcoded numeric threshold for n_components: `grep -n "n_components" services/regime_labeler.py` shows it read via cfg.get_sync
    - `.venv/bin/ruff check services/regime_labeler.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/regime_labeler.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m' GROUP BY regime;"</verify>
  <done>regime_labeler.py UPDATEs feature_vectors.regime with canonical text labels for >95% of SPY 5m rows; D-06 + OTel + spans wired; APR-compliant.</done>
</task>

<task type="auto">
  <name>Task 3: Run regime labeler across all backfilled symbols/TFs</name>
  <files>feature_vectors (DB table — regime column updated)</files>
  <read_first>
    - services/regime_labeler.py (just built)
    - .planning/phases/138-ic-engine-outcome-labels/138-RESEARCH.md (Finding 7: 14-15 symbols)
  </read_first>
  <action>
    Run `.venv/bin/python services/regime_labeler.py` with no symbol filter (defaults to all feature_vectors symbols x 4 TFs). This is a multi-minute-to-hour HMM fit pass; run in background and poll the null-regime gate. If any (symbol, tf) fails to converge, log it and continue (do not crash the whole run for one cell — but the global gate below must still pass).
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0 * count(*) FILTER (WHERE regime IS NULL) / count(*), 2) FROM feature_vectors;"` returns < 5.0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT regime) FROM feature_vectors WHERE regime IS NOT NULL;"` returns >= 2 (real regime separation, not all one label)
    - `job_completed_total{job="regime-labeler", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, regime, count(*) FROM feature_vectors WHERE regime IS NOT NULL GROUP BY tf, regime ORDER BY tf, regime;"</verify>
  <done>>95% of all feature_vectors rows have a canonical text regime label.</done>
</task>

</tasks>

<verification>
- feature_vectors.regime populated with canonical text labels for >95% of rows
- Per-(symbol, tf) HMM decoding (not shared model); causal Viterbi/filtered
- regime_labeler emits D-06 + 3 OTel metrics + 2 spans; APR-compliant
</verification>

<success_criteria>
- All task acceptance criteria pass
- Global null-regime fraction < 5%
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-outcome-labels/138-02-SUMMARY.md` documenting the regime label distribution per (symbol, tf), the canonical label mapping used, and any (symbol, tf) cells that failed HMM convergence.
</output>
