---
phase: 138-ic-engine-forward-returns
plan: 05
type: execute
wave: 4
depends_on: ["138-02", "138-03"]
files_modified:
  - production/migrations/162_hmm_probability_vector.sql
  - services/regime_writer.py
  - services/forward_return_writer.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "migration 162 applied: feature_vectors has hmm_prob_trending_up, hmm_prob_ranging, hmm_prob_trending_down columns"
    - "regime_writer.py _causal_decode() returns (states, alpha_history); generator replaced by explicit duration-tracking loop; UPDATE writes all 6 enrichment columns"
    - "hmm_prob_trending_up + hmm_prob_ranging + hmm_prob_trending_down sum to 1.0 per bar (within float precision); no hmm_direction_score column"
    - "All regime_writer unit tests updated for tuple return; full suite green"
    - ">95% of feature_vectors rows have regime label + full alpha vector before forward_return_writer runs"
    - "forward_return_writer extends BaseBatch (src/core/agent/base_batch.py); D-06 emission is inherited, not reimplemented"
    - "forward_returns has rows with executable forward log returns ln(open[T+N+1]/open[T+1])"
    - "Forward returns are causal -- no lookahead bias (validated by unit test in P5)"
    - "complete_Nbar=false for the last N rows of each (symbol, tf) series"
    - "Only rows that have a matching feature_vectors row are written (exact bar_ts JOIN)"
    - "WHERE bar_ts <= TRAINING_WINDOW_END guard is explicit in the write path"
    - "Idempotent: re-run writes 0 new rows (ON CONFLICT DO NOTHING)"
    - "forward_return_writer emits D-06 job_completed_total + per-service OTel metrics"
  artifacts:
    - path: "services/forward_return_writer.py"
      provides: "Oneshot computing LEAD()-based forward returns into forward_returns"
      min_lines: 200
    - path: "src/observability/metrics.py"
      provides: "forward_return_writer_rows_written_total, forward_return_writer_run_latency_seconds, forward_returns_coverage"
      contains: "forward_return_writer"
  key_links:
    - from: "forward_return_writer.py"
      to: "forward_returns table"
      via: "INSERT ... ON CONFLICT (symbol, tf, bar_ts) DO NOTHING"
      pattern: "INSERT INTO forward_returns"
    - from: "LEAD() window over market_data_ohlcv"
      to: "forward_returns.return_Nbar"
      via: "ln(open[T+N+1]/open[T+1]) with ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING"
      pattern: "ROWS BETWEEN CURRENT ROW"
    - from: "forward_return_writer WHERE clause"
      to: "TRAINING_WINDOW_END gate"
      via: "WHERE m.timestamp <= %s (TRAINING_WINDOW_END = MAX(bar_ts) FROM feature_vectors)"
      pattern: "TRAINING_WINDOW_END\|training_window_end"
---

<objective>
Build `services/forward_return_writer.py` -- a Ring 2 oneshot that computes executable, causal forward log returns and writes them to forward_returns. This is the dependent variable (Y) for IC measurement.

Purpose: lookahead bias is disqualifying (Renaissance mandate #5). Forward return MUST be ln(open[T+N+1]/open[T+1]) -- entry at next-bar open, exit N bars later at open. NEVER ln(close[T+N]/close[T]).

CORRECTNESS ADDITION (from REVIEWS.md medium concern): The WHERE bar_ts <= TRAINING_WINDOW_END guard is now explicit and required in the action -- not just a comment. This prevents future-gap rows from being written for bars beyond the training cutoff.

Output: forward_returns populated for all backfilled (symbol, tf), with completeness flags, TRAINING_WINDOW_END gate enforced, idempotent, fully instrumented.
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
@services/backfill_feature_factory.py
@src/core/service_utils.py
@src/observability/metrics.py
@src/observability/spans.py
</context>

<tasks>

<task type="auto">
  <name>Task 0: Migration 162 + amend regime_writer to write the full HMM probability vector</name>
  <files>production/migrations/162_hmm_probability_vector.sql, services/regime_writer.py, tests/unit/services/test_regime_writer.py</files>
  <read_first>
    - services/regime_writer.py (FULL READ — _causal_decode() lines 133-192: current return type np.ndarray; _label_symbol_tf() lines 222-380: the generator at lines 320-323 and UPDATE at lines 328-339; understand _build_label_map() state ordering)
    - tests/unit/services/test_regime_writer.py (FULL READ — find all tests that call _causal_decode() or assert on its return type; these break when return becomes a tuple)
    - production/migrations/161_alpha_ic_apr_keys.sql (style reference: header comment block format)
    - CLAUDE.md (UTC timestamps, no hardcoded numerics)
  </read_first>
  <action>
    CONTEXT: regime_writer.py (built in P4) currently writes only feature_vectors.regime (the text label).
    The forward-filter already computes alpha[t] = [P(up), P(ranging), P(down)] at each bar but discards
    it after argmax. This task preserves the full vector. The 3 raw probabilities are ground truth —
    hmm_regime_prob and hmm_entropy are derivatives of them (max(alpha) and -sum(p*log(p))). Storing the
    raw vector in separate typed columns (not JSONB) makes them direct IC features without any decoding.
    hmm_direction_score = P(up) - P(down) is NOT stored — trivially derivable at query time.

    STEP 1 — Create production/migrations/162_hmm_probability_vector.sql:

    -- Migration 162: Add raw HMM forward-filter probability columns to feature_vectors.
    -- Ground truth alpha vector: hmm_regime_prob = max(alpha), hmm_entropy = -sum(p*log(p))
    -- are derivatives. Populated by regime_writer.py alongside regime label.
    -- hmm_direction_score = hmm_prob_trending_up - hmm_prob_trending_down at query time.
    ALTER TABLE feature_vectors
      ADD COLUMN IF NOT EXISTS hmm_prob_trending_up   DOUBLE PRECISION,
      ADD COLUMN IF NOT EXISTS hmm_prob_ranging        DOUBLE PRECISION,
      ADD COLUMN IF NOT EXISTS hmm_prob_trending_down  DOUBLE PRECISION;

    Apply: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/162_hmm_probability_vector.sql

    STEP 2 — Amend services/regime_writer.py (3 surgical changes only):

    Change 1 — _causal_decode() return type:
      Add `alpha_history = np.zeros((n, K))` before the loop.
      At end of each timestep iteration, after computing and normalizing alpha, add:
        alpha_history[t] = alpha
      Change the docstring Returns: line to:
        "Returns: (states, alpha_history) where states[t] = argmax(alpha[t]) and
         alpha_history[t] is the normalized probability vector over K states."
      Change `return states` to `return states, alpha_history`.

    Change 2 — _label_symbol_tf() unpack and loop replacement:
      At the _causal_decode call site, change:
        raw_states = _causal_decode(...)
      to:
        raw_states, alpha_history = _causal_decode(...)

      After computing label_map, add state-index lookups:
        up_state   = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_UP)
        down_state = next(k for k, v in label_map.items() if v == _LABEL_TRENDING_DOWN)
        rang_state = next(k for k, v in label_map.items() if v == _LABEL_RANGING)

      Replace the generator expression for update_params with an explicit loop — the
      generator cannot support index-based alpha_history access and stateful duration
      tracking simultaneously:

        update_rows = []
        prev_state: int | None = None
        duration = 0
        for i, (ts, state_idx) in enumerate(zip(valid_ts, raw_states)):
            state_idx = int(state_idx)
            if state_idx == prev_state:
                duration += 1
            else:
                duration = 1
                prev_state = state_idx
            alpha = alpha_history[i]
            p_up      = float(alpha[up_state])
            p_ranging = float(alpha[rang_state])
            p_down    = float(alpha[down_state])
            prob_val  = float(np.max(alpha))
            entropy_val = float(-np.sum(alpha * np.log(np.maximum(alpha, 1e-300))))
            update_rows.append((
                label_map[state_idx],  # regime
                p_up, p_ranging, p_down,
                prob_val,              # hmm_regime_prob
                entropy_val,           # hmm_entropy
                float(duration),       # hmm_duration
                symbol, tf, ts,
            ))

    Change 3 — expand the UPDATE SQL:
      Replace the existing single-column UPDATE SQL with:
        UPDATE feature_vectors
        SET regime              = %s,
            hmm_prob_trending_up  = %s,
            hmm_prob_ranging      = %s,
            hmm_prob_trending_down = %s,
            hmm_regime_prob       = %s,
            hmm_entropy           = %s,
            hmm_duration          = %s
        WHERE symbol = %s AND tf = %s AND bar_ts = %s
      Pass update_rows (list) to execute_batch instead of the old generator.

    STEP 3 — Update tests/unit/services/test_regime_writer.py:
      Find every test that calls _causal_decode() directly or asserts on its return value.
      Update those tests to unpack the tuple: `states, alpha_history = _causal_decode(...)`.
      Add assertions:
        - alpha_history.shape == (len(obs_matrix), K)
        - np.allclose(alpha_history.sum(axis=1), 1.0)  # probabilities sum to 1 per bar
      Do not add new tests beyond what is needed to fix the broken assertions.
  </action>
  <acceptance_criteria>
    - Migration applied: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM information_schema.columns WHERE table_name='feature_vectors' AND column_name IN ('hmm_prob_trending_up','hmm_prob_ranging','hmm_prob_trending_down');"` returns 3
    - Return type changed: `grep -c "return states, alpha_history" services/regime_writer.py` returns 1
    - Generator gone: `grep -c "update_params\s*=" services/regime_writer.py` returns 0
    - Explicit loop present: `grep -c "update_rows" services/regime_writer.py` returns >= 2 (definition + execute_batch call)
    - UPDATE expanded: `grep -c "hmm_prob_trending_up" services/regime_writer.py` returns >= 2 (SQL + tuple)
    - No direction score stored: `grep -c "hmm_direction_score" services/regime_writer.py` returns 0
    - Smoke test (SPY 5m — verifies code correctness, not corpus coverage):
      `.venv/bin/python services/regime_writer.py --symbols SPY --tf 5m` exits 0
    - Probabilities sum to 1: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT max(abs(hmm_prob_trending_up + hmm_prob_ranging + hmm_prob_trending_down - 1.0)) FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND hmm_prob_trending_up IS NOT NULL;"` returns < 1e-9
    - Tests updated and green: `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` GREEN (no skipped)
    - Full suite: `.venv/bin/pytest tests/unit/ -q` GREEN
    - `.venv/bin/ruff check services/regime_writer.py` passes
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, round(hmm_prob_trending_up::numeric,3) p_up, round(hmm_prob_ranging::numeric,3) p_rang, round(hmm_prob_trending_down::numeric,3) p_down, round((hmm_prob_trending_up+hmm_prob_ranging+hmm_prob_trending_down)::numeric,6) sum1, hmm_duration FROM feature_vectors WHERE symbol='SPY' AND tf='5m' AND hmm_prob_trending_up IS NOT NULL ORDER BY bar_ts LIMIT 5;"</verify>
  <done>Migration 162 applied; _causal_decode returns (states, alpha_history); generator replaced by explicit duration-tracking loop; UPDATE writes all 6 enrichment columns; probabilities sum to 1.0; tests updated and green.</done>
</task>

<task type="auto">
  <name>Task 1: Add forward_return_writer OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter/gauge/histogram factories; existing metric blocks)
  </read_first>
  <action>
    In src/observability/metrics.py add:
    - FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL = _meter.create_counter("forward_return_writer_rows_written_total", description="rows inserted into forward_returns; labels symbol, tf")
    - FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram("forward_return_writer_run_latency_seconds", description="Full outcome labeler run duration")
    - OUTCOME_LABELS_COVERAGE = _meter.create_gauge("forward_returns_coverage", description="fraction of feature_vectors rows with labeled forward returns; labels lookahead, symbol, tf")
    Note: OUTCOME_LABELS_COVERAGE is shared with the IC engine (P4) -- define it once here. No prometheus_client.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python -c "from src.observability.metrics import FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL, FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS, OUTCOME_LABELS_COVERAGE; print('ok')"` exits 0
    - `grep -c "OUTCOME_LABELS_COVERAGE" src/observability/metrics.py` returns 1 (defined exactly once)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import OUTCOME_LABELS_COVERAGE; print('ok')"</verify>
  <done>Three outcome labeler metrics importable.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/forward_return_writer.py with causal LEAD() forward returns and TRAINING_WINDOW_END gate</name>
  <files>services/forward_return_writer.py</files>
  <read_first>
    - services/forward_return_writer.py (the file being created -- does not exist yet)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§V forward return formula, §V.3 LEAD() SQL with ROWS BETWEEN, §XIV.1 forward_returns columns)
    - services/backfill_feature_factory.py (Ring 2 oneshot template: argparse, _load_config_service, setup_service_logging, _JOB, JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics, psycopg2 sync, execute_batch insert, high-water-mark pattern)
    - src/core/service_utils.py (setup_service_logging, format_iso_ts)
    - src/observability/spans.py (observed_span, ATTR_*)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Deliverable B, Finding 8 ROWS BETWEEN, Risk 1)
    - CLAUDE.md (UTC timestamps, market_data_ohlcv columns: timestamp not ts, timeframe not tf; APR rules)
  </read_first>
  <action>
    Create services/forward_return_writer.py as a sync psycopg2 oneshot mirroring backfill_feature_factory.py.

    Constants: _JOB = "forward-return-writer", log "logs/forward_return_writer.log". Lookaheads from APR -- read alpha.ic.lookaheads if present else module fallback _LOOKAHEADS = [1, 5, 20, 60] with a comment that these correspond to return_1bar/5bar/20bar/60bar columns (these are statistical-concept-defining numbers in column names, allowed per APR rules).

    Forward return formula (IC spec §V -- executable, causal): for lookahead N, return at bar T = ln(open[T+N+1] / open[T+1]). Entry at T+1 open, exit at T+N+1 open. This is the ONLY correct formula.

    TRAINING_WINDOW_END GATE (fixes REVIEWS.md Ollama HIGH concern -- explicit code, not a comment):
    At the start of the run, compute:
      TRAINING_WINDOW_END = psql scalar: SELECT MAX(bar_ts) FROM feature_vectors
    All SQL against market_data_ohlcv MUST include: AND m.timestamp <= TRAINING_WINDOW_END
    This prevents forward-gap rows from being written for bars that have no feature_vectors counterpart (no target label). Use TRAINING_WINDOW_END as a psycopg2 parameter in the WHERE clause -- do NOT inline it as a string. Log its value at INFO before the compute loop starts.

    SQL (IC spec §V.3, RESEARCH.md Finding 8) -- per (symbol, tf), against market_data_ohlcv (columns: timestamp, symbol, timeframe, open):
    Use a CTE with LEAD() over an explicit ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING window ordered by timestamp. Compute:
      open_t1 = LEAD(open, 1) OVER w
      open_t2 = LEAD(open, 2) OVER w
      open_t6 = LEAD(open, 6) OVER w
      open_t21 = LEAD(open, 21) OVER w
      open_t61 = LEAD(open, 61) OVER w
    Then:
      return_1bar  = ln(open_t2 / open_t1)
      return_5bar  = ln(open_t6 / open_t1)
      return_20bar = ln(open_t21 / open_t1)
      return_60bar = ln(open_t61 / open_t1)
    Completeness: complete_Nbar = (the corresponding open_t{N+1} IS NOT NULL). Last N bars of the series have NULL forward open -> complete_Nbar=false, return_Nbar=NULL.

    JOIN gate: only emit rows where bar_ts has a matching feature_vectors row (exact timestamp equality -- RESEARCH.md mandate #10). Use:
      JOIN feature_vectors fv ON fv.symbol = m.symbol AND fv.tf = m.timeframe AND fv.bar_ts = m.timestamp
    The WHERE m.timestamp <= TRAINING_WINDOW_END clause must appear BEFORE the JOIN in the CTE or WHERE clause so the window computation only sees bars within the training window. pipeline_version from fv if present.

    Flow:
    1. argparse --symbols (default all distinct feature_vectors symbols), --tf (default ['5m','15m','1h','1d'])
    2. _load_config_service; init_otel_providers
    3. Compute TRAINING_WINDOW_END = SELECT MAX(bar_ts) FROM feature_vectors. Log at INFO.
    4. For each (symbol, tf) wrapped in observed_span("forward_return_writer.label_symbol_tf"):
       - high-water mark: SELECT MAX(bar_ts) FROM forward_returns WHERE symbol=%s AND tf=%s; recompute the tail window (recompute last 61 bars before HWM so previously-incomplete rows get completed). Full recompute is acceptable for first run.
       - Run the LEAD() CTE + JOIN + WHERE timestamp <= TRAINING_WINDOW_END; execute_batch INSERT INTO forward_returns (...) ON CONFLICT (symbol, tf, bar_ts) DO NOTHING.
       - FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL.add(inserted, {"symbol": symbol, "tf": tf})
    5. After all cells, compute coverage per lookahead: for each (symbol, tf, N): fraction = count(forward_returns with complete_Nbar) / count(feature_vectors). OUTCOME_LABELS_COVERAGE.set(fraction, {"lookahead": str(N), "symbol": symbol, "tf": tf})
    6. Wrap run in observed_span("forward_return_writer.run"); record FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS.
    7. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": ...}) in finally block; flush_and_shutdown_metrics(); sys.exit(1) on failure.

    Zero hardcoded numeric thresholds beyond the statistical-concept lookahead values; any tunable (e.g. batch size) reads cfg.get_sync.
    DAG-invariant docstring note: oneshot batch tool, exempt like backfill_feature_factory.py.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m` exits 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns WHERE symbol='SPY' AND tf='5m' AND return_5bar IS NOT NULL AND complete_5bar=true;"` returns > 0
    - TRAINING_WINDOW_END guard is explicit code: `grep -c "TRAINING_WINDOW_END\|training_window_end" services/forward_return_writer.py` returns >= 2 (computed once + used in WHERE clause)
    - Causal check via SQL: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "WITH o AS (SELECT timestamp, open, LEAD(open,1) OVER w o1, LEAD(open,2) OVER w o2 FROM market_data_ohlcv WHERE symbol='SPY' AND timeframe='5m' WINDOW w AS (ORDER BY timestamp ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING)) SELECT ol.return_1bar, ln(o.o2/o.o1) AS expected, abs(ol.return_1bar - ln(o.o2/o.o1)) AS diff FROM forward_returns ol JOIN o ON o.timestamp=ol.bar_ts WHERE ol.symbol='SPY' AND ol.tf='5m' AND ol.complete_1bar AND o.o2 IS NOT NULL ORDER BY ol.bar_ts LIMIT 5;"` -- every diff < 1e-9
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns ol LEFT JOIN feature_vectors fv USING(symbol, tf, bar_ts) WHERE ol.symbol='SPY' AND ol.tf='5m' AND fv.bar_ts IS NULL;"` returns 0 (every forward_returns row has a feature_vectors match)
    - `grep -c "ROWS BETWEEN CURRENT ROW" services/forward_return_writer.py` returns >= 1
    - `grep -c "observed_span" services/forward_return_writer.py` returns >= 2
    - `grep -c "JOB_COMPLETED_TOTAL\|flush_and_shutdown_metrics" services/forward_return_writer.py` returns >= 2
    - `.venv/bin/ruff check services/forward_return_writer.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) total, count(*) FILTER (WHERE complete_5bar) c5, count(*) FILTER (WHERE complete_60bar) c60 FROM forward_returns WHERE symbol='SPY' AND tf='5m';"</verify>
  <done>forward_return_writer.py produces causal forward returns for SPY 5m; formula validated against raw LEAD(); TRAINING_WINDOW_END gate enforced; JOIN gate clean; D-06 + OTel + spans wired.</done>
</task>

<task type="auto">
  <name>Task 3: Full regime_writer corpus run — all symbols x TFs</name>
  <files>feature_vectors (DB table — regime + enrichment columns populated)</files>
  <read_first>
    - services/regime_writer.py (just amended in Task 0)
  </read_first>
  <precondition>
    feature_vectors must be populated by backfill_feature_factory.py before this task runs.
    Verify: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_vectors WHERE bar_ts IS NOT NULL;"` returns >= 14 symbols.
    Do not proceed if feature_vectors is empty or sparse — regime_writer with insufficient obs
    per cell logs a warning and skips; a near-empty corpus produces no IC value.
  </precondition>
  <action>
    Run the amended regime_writer for all (symbol, tf) combinations. This is the production
    corpus labeling run — NOT a smoke test. All backfilled symbols x 4 TFs.

    Run in background (HMM fitting is CPU-bound, ~minutes per cell):
      nohup .venv/bin/python services/regime_writer.py > logs/regime_writer_corpus.log 2>&1 &

    Poll progress: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, regime, count(*) FROM feature_vectors WHERE regime IS NOT NULL GROUP BY tf, regime ORDER BY tf, regime;"`

    This re-runs over SPY/5m (already smoke-tested in Task 0) — idempotent by value because
    HMM_RANDOM_STATE=42 and same OHLCV data produce identical results. ON CONFLICT is not
    applicable here (UPDATE semantics), so re-run simply overwrites with identical values.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE regime IS NULL)/count(*),2) FROM feature_vectors;"` returns < 5.0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT regime) FROM feature_vectors WHERE regime IS NOT NULL;"` returns >= 2 (real regime separation)
    - Raw probs populated: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE hmm_prob_trending_up IS NULL)/count(*),2) FROM feature_vectors WHERE regime IS NOT NULL;"` returns 0.0 (every labeled row has the full alpha vector)
    - Probs sum to 1 globally: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT max(abs(hmm_prob_trending_up + hmm_prob_ranging + hmm_prob_trending_down - 1.0)) FROM feature_vectors WHERE hmm_prob_trending_up IS NOT NULL;"` returns < 1e-9
    - `job_completed_total{job="regime-writer", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, regime, count(*), round(avg(hmm_prob_trending_up)::numeric,3) avg_p_up, round(avg(hmm_entropy)::numeric,3) avg_ent FROM feature_vectors WHERE regime IS NOT NULL GROUP BY tf, regime ORDER BY tf, regime;"</verify>
  <done>>95% of feature_vectors rows have canonical regime labels + full alpha vector; probabilities sum to 1.0 globally; IC engine has the regime stratification it needs.</done>
</task>

<task type="auto">
  <name>Task 4: Run forward_return_writer across all backfilled symbols/TFs</name>
  <files>forward_returns (DB table -- populated)</files>
  <read_first>
    - services/forward_return_writer.py (just built in Task 2)
  </read_first>
  <precondition>
    Same data gate as Task 3 — feature_vectors must be populated.
    Task 3 and Task 4 are independent and can run concurrently (Task 3 writes to
    feature_vectors regime columns; Task 4 reads feature_vectors bar_ts only and
    writes to forward_returns). No write conflict.
  </precondition>
  <action>
    Run .venv/bin/python services/forward_return_writer.py with no symbol filter (all feature_vectors symbols x 4 TFs). Run in background; poll forward_returns row counts.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM forward_returns;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE complete_5bar)/count(*),1) FROM forward_returns WHERE tf='5m';"` returns > 95.0 (only the last 6 bars per series should be incomplete for 5bar)
    - Re-run idempotency: running `.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m` a second time inserts 0 new rows. Capture count before/after; they must be equal.
    - `job_completed_total{job="forward-return-writer", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(*) FROM forward_returns GROUP BY tf ORDER BY tf;"</verify>
  <done>forward_returns populated for >=14 symbols x 4 TFs; TRAINING_WINDOW_END gate confirmed; idempotent re-run confirmed.</done>
</task>

</tasks>

<verification>
- migration 162 applied; regime_writer _causal_decode returns (states, alpha_history); generator → explicit loop with duration tracking; UPDATE writes regime + 5 enrichment columns; tests green
- >95% of feature_vectors rows have regime labels + full alpha vector (hmm_prob_trending_up/ranging/down sum to 1.0)
- forward_returns has causal forward log returns; formula validated against raw LEAD()
- TRAINING_WINDOW_END gate is explicit in WHERE clause (not just a comment)
- Every forward_returns row has a matching feature_vectors row (exact bar_ts)
- complete_Nbar flags correct; idempotent re-run writes 0 rows
- D-06 + 3 OTel metrics + 2 spans wired; APR-compliant
- P6 IC engine preconditions met: feature_vectors.regime populated, forward_returns populated
</verification>

<success_criteria>
- All task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-05-SUMMARY.md` documenting forward_returns row counts per (symbol, tf), completeness fractions per lookahead, the TRAINING_WINDOW_END value used, and confirmation of the causal formula validation.
</output>
