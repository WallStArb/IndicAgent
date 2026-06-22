---
phase: 138-ic-engine-forward-returns
plan: 02
type: execute
wave: 2
depends_on: ["138-01"]
files_modified:
  - services/regime_writer.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "feature_vectors.regime is populated with canonical text labels for >95% of rows"
    - "Each (symbol, tf) is decoded with its own HMM fit; per-TF, not a shared 1m model"
    - "Regime labels are causal: forward-filter (alpha-pass only), NOT full-sequence Viterbi"
    - "HMM observation matrix is built from market_data_ohlcv (log-returns + ATR-proxy vol), NOT from feature_vectors which has no OHLCV columns"
    - "regime_writer emits D-06 job_completed_total and per-service OTel metrics"
  artifacts:
    - path: "services/regime_writer.py"
      provides: "Oneshot that UPDATEs feature_vectors.regime via causal forward-filter HMM decoding per (symbol, tf)"
      min_lines: 250
    - path: "src/observability/metrics.py"
      provides: "regime_writer_rows_updated_total, regime_writer_run_latency_seconds, regime_writer_null_regime_remaining"
      contains: "regime_writer"
  key_links:
    - from: "regime_writer.py"
      to: "market_data_ohlcv (observation source)"
      via: "SELECT timestamp, open, high, low, close, volume FROM market_data_ohlcv WHERE symbol=%s AND timeframe=%s ORDER BY timestamp ASC"
      pattern: "market_data_ohlcv"
    - from: "regime_writer.py"
      to: "feature_vectors.regime column"
      via: "UPDATE feature_vectors SET regime = %s WHERE symbol=%s AND tf=%s AND bar_ts=%s"
      pattern: "UPDATE feature_vectors SET regime"
    - from: "regime_writer.py causal_decode()"
      to: "src/intelligence/features/smc_context/hmm_regime.py _forward_step()"
      via: "manual alpha-pass loop mirroring the existing production forward filter"
      pattern: "_forward_pass\\|alpha_pass\\|log_alpha"
---

<objective>
Build `services/regime_writer.py` — a Ring 2 oneshot that populates feature_vectors.regime (currently NULL for ALL rows, RESEARCH.md Finding 2). This is UNTRACKED-but-mandatory scope: regime-stratified IC is impossible without it, and pooled IC is not an acceptable substitute (IC spec §III.3).

Purpose: regime-conditioning is non-negotiable (Renaissance mandate #2). Global IC hides sign flips between trending and ranging regimes.

CRITICAL CORRECTNESS ISSUES FIXED IN THIS REVISION (from REVIEWS.md):
1. HMM obs matrix built from market_data_ohlcv (log-returns + ATR-proxy vol) — NOT feature_vectors which contains no close/OHLCV columns.
2. Decoding uses forward-filter (alpha-pass only), mirroring `src/intelligence/features/smc_context/hmm_regime.py:_forward_step()` — NOT hmmlearn's `model.predict()` which runs full-sequence Viterbi over the complete history and leaks future information.

Output: feature_vectors.regime set to canonical text labels for >95% of rows, per-(symbol, tf) HMM decoding, full D-06 + OTel instrumentation.
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
@src/intelligence/features/smc_context/hmm_regime.py
@services/backfill_feature_factory.py
@src/core/service_utils.py
@src/observability/metrics.py
@src/observability/spans.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add regime_writer OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter(), histogram(), gauge() factories around lines 72-90; existing metric definition blocks for style)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
  </read_first>
  <action>
    In src/observability/metrics.py, add a Phase 138 metrics section defining:
    - REGIME_WRITER_ROWS_UPDATED_TOTAL = _meter.create_counter("regime_writer_rows_updated_total", description="feature_vectors rows with regime set; labels symbol, tf")
    - REGIME_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram("regime_writer_run_latency_seconds", description="Full regime labeler run duration")
    - REGIME_WRITER_NULL_REGIME_REMAINING = _meter.create_gauge("regime_writer_null_regime_remaining", description="feature_vectors rows still regime=NULL after run; labels symbol, tf")
    Do NOT import prometheus_client.
  </action>
  <acceptance_criteria>
    - `grep -c "REGIME_WRITER_ROWS_UPDATED_TOTAL\|REGIME_WRITER_RUN_LATENCY_SECONDS\|REGIME_WRITER_NULL_REGIME_REMAINING" src/observability/metrics.py` returns 3
    - `.venv/bin/python -c "from src.observability.metrics import REGIME_WRITER_ROWS_UPDATED_TOTAL, REGIME_WRITER_RUN_LATENCY_SECONDS, REGIME_WRITER_NULL_REGIME_REMAINING; print('ok')"` exits 0
    - `grep -c "prometheus_client" src/observability/metrics.py` returns 0
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import REGIME_WRITER_ROWS_UPDATED_TOTAL; print('ok')"</verify>
  <done>Three regime_writer metrics importable from metrics.py.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/regime_writer.py oneshot with causal forward-filter HMM decoding</name>
  <files>services/regime_writer.py</files>
  <read_first>
    - src/intelligence/features/smc_context/hmm_regime.py (FULL READ — _forward_step() lines 378-416: the alpha-pass algorithm; _make_initial_state() lines 319-331: uniform prior init; _build_observation() lines 357-376: obs vector construction from log_return + realized_vol. This is the canonical causal HMM path — mirror it exactly.)
    - services/backfill_feature_factory.py (Ring 2 oneshot template: _load_config_service lines ~235-249, argparse, setup_service_logging, JOB_COMPLETED_TOTAL emission at exit, flush_and_shutdown_metrics, psycopg2 sync DB pattern, _JOB constant)
    - src/core/service_utils.py (setup_service_logging, format_iso_ts)
    - src/observability/spans.py (observed_span signature, ATTR_* constants)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Deliverable A, Risk 2, Risk 4)
    - CLAUDE.md (market_data_ohlcv columns: timestamp not ts, timeframe not tf; APR rules: zero hardcoded numerics; UTC timestamps)
  </read_first>
  <action>
    Create services/regime_writer.py as a sync psycopg2 oneshot mirroring backfill_feature_factory.py structure.

    Constants: _JOB = "regime-writer", log file "logs/regime_writer.log" via setup_service_logging.

    OBSERVATION MATRIX SOURCE (fixes HIGH review issue #2):
    The HMM observation matrix MUST be built from market_data_ohlcv, NOT feature_vectors. feature_vectors contains the 54 computed feature fields -- it has NO close, open, high, low, or volume columns. Use:
      SELECT timestamp, open, high, low, close, volume
      FROM market_data_ohlcv
      WHERE symbol = %s AND timeframe = %s
      ORDER BY timestamp ASC
    Build the obs matrix as: log_return = ln(close[t]/close[t-1]) for t>=1, realized_vol = rolling std of log_returns over a configurable window (default 20 bars, APR key feature.hmm.vol_window fallback 20). Shape: (n_bars, 2). This matches the 2D observation path in hmm_regime.py _build_observation() when only log_return + realized_vol are available.

    ALIGNMENT: after forward-filter decoding, align decoded state at timestamp T to the feature_vectors bar_ts by exact timestamp equality (WHERE symbol=%s AND tf=%s AND bar_ts=market_data_ohlcv.timestamp). Only update feature_vectors rows that have a corresponding market_data_ohlcv bar.

    CAUSAL DECODING (fixes HIGH review issue #1):
    DO NOT use hmmlearn GaussianHMM.predict() on the full observation sequence. predict() is full-sequence Viterbi -- it uses the entire past+future path to decode each state, leaking future information even without an explicit backward smoother.

    INSTEAD, implement a causal forward-filter decoder mirroring hmm_regime.py _forward_step():

    def _causal_decode(obs_matrix: np.ndarray, means: np.ndarray, variances: np.ndarray, A: np.ndarray, K: int) -> np.ndarray:
        '''Causal forward-filter (alpha-pass only) HMM decoding.

        At each timestep t, the decoded state = argmax(alpha[t]) where alpha[t]
        depends ONLY on observations obs[0..t] and the prior alpha[t-1].
        No backward pass, no smoothing, no Viterbi over the full sequence.

        Mirrors src/intelligence/features/smc_context/hmm_regime.py:_forward_step()
        for batch-mode use. Do NOT replace with model.predict().
        '''
        n, d = obs_matrix.shape
        states = np.zeros(n, dtype=int)
        alpha = np.full(K, 1.0 / K)  # Uniform prior (mirrors _make_initial_state)
        for t in range(n):
            obs = obs_matrix[t]
            # Emission log-probabilities (diagonal Gaussian)
            log_emit = np.zeros(K)
            for k in range(K):
                diff = obs - means[k, :d]
                var = variances[k, :d]
                log_emit[k] = -0.5 * np.sum(diff**2 / np.maximum(var, 1e-300)) - 0.5 * np.sum(np.log(2 * np.pi * np.maximum(var, 1e-300)))
            # Forward update in log space (mirrors _forward_step)
            log_alpha = np.log(np.maximum(alpha, 1e-300))
            log_alpha_new = np.zeros(K)
            for k in range(K):
                log_trans = log_alpha + np.log(np.maximum(A[:, k], 1e-300))
                max_lt = np.max(log_trans)
                log_alpha_new[k] = max_lt + np.log(np.sum(np.exp(log_trans - max_lt)))
            log_alpha_new += log_emit
            # Normalize
            max_la = np.max(log_alpha_new)
            alpha = np.exp(log_alpha_new - max_la)
            alpha /= np.sum(alpha) if np.sum(alpha) > 0 else 1.0
            states[t] = int(np.argmax(alpha))
        return states

    HMM FITTING: Use hmmlearn GaussianHMM ONLY for parameter estimation (fitting), not for decoding. Fit on the full observation matrix to estimate transition matrix A, emission means, and covariances. Then pass A, means, covariances into _causal_decode() for state assignment. This is the correct separation: fit on history to learn parameters, then decode causally.

    APR loading via _load_config_service(conn): read feature.hmm.n_components (fallback 3), feature.hmm.vol_window (fallback 20). Zero inline numerics -- use cfg.get_sync.

    CANONICAL REGIME LABEL MAPPING (RESEARCH.md Risk 4):
    After _causal_decode() returns integer states, map to canonical text labels deterministically. Sort the K HMM states by their fitted emission mean[0] (log-return dimension):
      - State with highest mean log-return -> "trending_up"
      - State with most negative mean log-return -> "trending_down"
      - Remaining state(s) -> "ranging"
    This produces semantically stable labels regardless of which integer hmmlearn assigns. Define a helper extract in the module:

    def _build_label_map(model: GaussianHMM, n_components: int) -> dict[int, str]:
        means_ret = model.means_[:, 0]  # log-return dimension
        order = np.argsort(means_ret)  # ascending: [-0.001, 0.0, +0.001]
        label_map = {}
        label_map[int(order[-1])] = "trending_up"   # highest mean return
        label_map[int(order[0])]  = "trending_down"  # lowest mean return
        for i in range(n_components):
            if i not in label_map:
                label_map[i] = "ranging"
        return label_map

    Core flow (per RESEARCH.md "Deliverable A"):
    1. argparse: --symbols (nargs='*', default all distinct feature_vectors symbols), --tf (nargs='*', default ['5m','15m','1h','1d'])
    2. Open psycopg2 conn; init_otel_providers; _load_config_service.
    3. For each (symbol, tf):
       - wrap in observed_span("regime_writer.label_symbol_tf", attributes={...symbol, tf...})
       - SELECT timestamp, close FROM market_data_ohlcv WHERE symbol=%s AND timeframe=%s ORDER BY timestamp ASC
       - Compute log_return array; compute realized_vol rolling std (vol_window bars). Discard first vol_window rows where vol is undefined (to avoid NaN).
       - obs_matrix shape [n_valid_bars, 2]
       - Skip (logged warning, continue) if obs_matrix rows < n_components * 50
       - Fit: model = GaussianHMM(n_components=n_components, covariance_type='diag', n_iter=100).fit(obs_matrix)
       - Decode causally: raw_states = _causal_decode(obs_matrix, model.means_, model.covars_[:, :, 0] if diag else model.covars_, model.transmat_, n_components)
         (For 'diag' covariance_type, model.covars_ shape is (K, n_features); for 'full' it is (K, n_features, n_features) -- use diagonal for _causal_decode. For 'diag', covars_ is already the variance vector per state.)
       - label_map = _build_label_map(model, n_components)
       - Build list of (bar_ts, label) by joining the decoded timestamps back to the valid obs slice. The obs_matrix slice starts at bar index vol_window (first valid obs). Match market_data_ohlcv.timestamp to feature_vectors.bar_ts.
       - Batch UPDATE feature_vectors SET regime = %s WHERE symbol=%s AND tf=%s AND bar_ts=%s using psycopg2.extras.execute_batch, batch_size=500.
       - REGIME_WRITER_ROWS_UPDATED_TOTAL.add(n_rows, {"symbol": symbol, "tf": tf})
       - After update: SELECT count(*) FROM feature_vectors WHERE symbol=%s AND tf=%s AND regime IS NULL; REGIME_WRITER_NULL_REGIME_REMAINING.set(remaining, {"symbol": symbol, "tf": tf})
    4. Wrap full run in observed_span("regime_writer.run"); record REGIME_WRITER_RUN_LATENCY_SECONDS at end.
    5. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"|"failure"}) and call flush_and_shutdown_metrics() in finally block. On unhandled exception: log, emit status="failure", flush, sys.exit(1).

    DAG invariant note: this oneshot is exempt from the "only writers touch DB" rule exactly as backfill_feature_factory.py is -- it is a batch labeling tool, not a real-time daemon. Add a docstring comment stating this.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/regime_writer.py --symbols SPY --tf 5m` exits 0
    - After run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND regime IS NULL;"` is < 5% of `SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m'`
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT DISTINCT regime FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND regime IS NOT NULL;"` returns only canonical text values (subset of ranging, trending_up, trending_down) -- NO integer strings like '0'/'1'/'2'
    - Causal decoding present, NOT hmmlearn predict(): `grep -c "model\.predict\b" services/regime_writer.py` returns 0
    - Forward-filter decoder present: `grep -c "_causal_decode\|forward.filter\|alpha_pass\|log_alpha" services/regime_writer.py` returns >= 2
    - OHLCV read from market_data_ohlcv not feature_vectors: `grep -c "market_data_ohlcv" services/regime_writer.py` returns >= 1 AND `grep -n "feature_vectors" services/regime_writer.py` shows feature_vectors referenced only in the UPDATE statement (not in the SELECT for observations)
    - `grep -c "observed_span" services/regime_writer.py` returns >= 2 (run + label_symbol_tf)
    - `grep -c "JOB_COMPLETED_TOTAL" services/regime_writer.py` returns >= 1 and `grep -c "flush_and_shutdown_metrics" services/regime_writer.py` returns >= 1
    - No hardcoded numeric for n_components: `grep -n "n_components" services/regime_writer.py` shows it read via cfg.get_sync (not literal 3)
    - `.venv/bin/ruff check services/regime_writer.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/regime_writer.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m' GROUP BY regime;"</verify>
  <done>regime_writer.py UPDATEs feature_vectors.regime with canonical text labels for >95% of SPY 5m rows; causal forward-filter decoding (not predict()); obs from market_data_ohlcv; D-06 + OTel + spans wired; APR-compliant.</done>
</task>

<task type="auto">
  <name>Task 3: Run regime labeler across all backfilled symbols/TFs</name>
  <files>feature_vectors (DB table — regime column updated)</files>
  <read_first>
    - services/regime_writer.py (just built)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 7: 14-15 symbols)
  </read_first>
  <action>
    Run .venv/bin/python services/regime_writer.py with no symbol filter (defaults to all feature_vectors symbols x 4 TFs). This is a multi-minute HMM fit pass; run in background and poll the null-regime gate. If any (symbol, tf) fails to converge (hmmlearn convergence warning), log it and continue -- do not crash the whole run for one cell. The global gate below must still pass.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0 * count(*) FILTER (WHERE regime IS NULL) / count(*), 2) FROM feature_vectors;"` returns < 5.0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT regime) FROM feature_vectors WHERE regime IS NOT NULL;"` returns >= 2 (real regime separation, not all one label)
    - `job_completed_total{job="regime-writer", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, regime, count(*) FROM feature_vectors WHERE regime IS NOT NULL GROUP BY tf, regime ORDER BY tf, regime;"</verify>
  <done>>95% of all feature_vectors rows have a canonical text regime label; >= 2 distinct regimes present.</done>
</task>

</tasks>

<verification>
- feature_vectors.regime populated with canonical text labels for >95% of rows
- Per-(symbol, tf) HMM decoding (not shared model); causal forward-filter (not Viterbi/predict())
- HMM obs from market_data_ohlcv (log-returns + realized vol); no feature_vectors OHLCV reference
- regime_writer emits D-06 + 3 OTel metrics + 2 spans; APR-compliant
</verification>

<success_criteria>
- All task acceptance criteria pass
- Global null-regime fraction < 5%
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-02-SUMMARY.md` documenting the regime label distribution per (symbol, tf), the canonical label mapping used, and any (symbol, tf) cells that failed HMM convergence.
</output>
