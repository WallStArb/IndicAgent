---
phase: 138-ic-engine-forward-returns
plan: 03
type: execute
wave: 2
depends_on: ["138-01"]
files_modified:
  - services/forward_return_writer.py
  - src/observability/metrics.py
autonomous: true

must_haves:
  truths:
    - "forward_returns has rows with executable forward log returns ln(open[T+N+1]/open[T+1])"
    - "Forward returns are causal — no lookahead bias (validated by unit test in P5)"
    - "complete_Nbar=false for the last N rows of each (symbol, tf) series"
    - "Only rows that have a matching feature_vectors row are written (exact bar_ts JOIN)"
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
      via: "ln(open[T+N+1]/open[T+1]) with ROWS BETWEEN CURRENT ROW AND N+1 FOLLOWING"
      pattern: "ROWS BETWEEN CURRENT ROW"
---

<objective>
Build `services/forward_return_writer.py` — a Ring 2 oneshot that computes executable, causal forward log returns and writes them to forward_returns. This is the dependent variable (Y) for IC measurement.

Purpose: lookahead bias is disqualifying (Renaissance mandate #5). Forward return MUST be ln(open[T+N+1]/open[T+1]) — entry at next-bar open, exit N bars later at open. NEVER ln(close[T+N]/close[T]).
Output: forward_returns populated for all backfilled (symbol, tf), with completeness flags, idempotent, fully instrumented.
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
  <name>Task 1: Add forward_return_writer OTel metrics to metrics.py</name>
  <files>src/observability/metrics.py</files>
  <read_first>
    - src/observability/metrics.py (counter/gauge/point_gauge factories; existing metric blocks)
  </read_first>
  <action>
    In src/observability/metrics.py add:
    - FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL = _meter.create_counter("forward_return_writer_rows_written_total", description="rows inserted into forward_returns; labels symbol, tf")
    - FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS = _meter.create_histogram("forward_return_writer_run_latency_seconds", description="Full outcome labeler run duration")
    - OUTCOME_LABELS_COVERAGE = _meter.create_gauge("forward_returns_coverage", description="fraction of feature_vectors rows with labeled forward returns; labels lookahead, symbol, tf")
    Note: OUTCOME_LABELS_COVERAGE is shared with the IC engine (P4) — define it once here. No prometheus_client.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python -c "from src.observability.metrics import FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL, FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS, OUTCOME_LABELS_COVERAGE; print('ok')"` exits 0
    - `grep -c "OUTCOME_LABELS_COVERAGE" src/observability/metrics.py` returns 1 (defined exactly once)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.observability.metrics import OUTCOME_LABELS_COVERAGE; print('ok')"</verify>
  <done>Three outcome labeler metrics importable.</done>
</task>

<task type="auto">
  <name>Task 2: Build services/forward_return_writer.py with causal LEAD() forward returns</name>
  <files>services/forward_return_writer.py</files>
  <read_first>
    - services/forward_return_writer.py (the file being created — does not exist yet)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§V forward return formula, §V.3 LEAD() SQL with ROWS BETWEEN, §XIV.1 forward_returns columns)
    - services/backfill_feature_factory.py (Ring 2 oneshot template: argparse, _load_config_service, setup_service_logging, _JOB, JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics, psycopg2 sync, execute_batch insert, high-water-mark pattern)
    - src/core/service_utils.py (setup_service_logging, format_iso_ts)
    - src/observability/spans.py (observed_span, ATTR_*)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Deliverable B, Finding 8 ROWS BETWEEN, Risk 1)
    - CLAUDE.md (UTC timestamps, market_data_ohlcv columns: timestamp not ts, timeframe not tf; APR rules)
  </read_first>
  <action>
    Create services/forward_return_writer.py as a sync psycopg2 oneshot mirroring backfill_feature_factory.py.

    Constants: `_JOB = "forward-return-writer"`, log "logs/forward_return_writer.log". Lookaheads from APR — read alpha.ic.lookaheads if present else module fallback `_LOOKAHEADS = [1, 5, 20, 60]` with a comment that these correspond to return_1bar/5bar/20bar/60bar columns (these are statistical-concept-defining numbers in column names, allowed per APR rules).

    Forward return formula (IC spec §V — executable, causal): for lookahead N, return at bar T = ln(open[T+N+1] / open[T+1]). Entry at T+1 open, exit at T+N+1 open. This is the ONLY correct formula.

    SQL (IC spec §V.3, RESEARCH.md Finding 8) — per (symbol, tf), against market_data_ohlcv (columns: timestamp, symbol, timeframe, open):
    Use a CTE with LEAD() over an explicit `ROWS BETWEEN CURRENT ROW AND 61 FOLLOWING` window ordered by timestamp. Compute open_t1 = LEAD(open, 1), open_t2 = LEAD(open, 2), open_t6 = LEAD(open, 6), open_t21 = LEAD(open, 21), open_t61 = LEAD(open, 61) (i.e. T+1, and T+N+1 for N in 1/5/20/60). Then:
      return_1bar  = ln(open_t2 / open_t1)
      return_5bar  = ln(open_t6 / open_t1)
      return_20bar = ln(open_t21 / open_t1)
      return_60bar = ln(open_t61 / open_t1)
    Completeness: complete_Nbar = (the corresponding open_t{N+1} IS NOT NULL). Last N bars of the series have NULL forward open -> complete_Nbar=false, return_Nbar=NULL.

    JOIN gate: only emit rows where bar_ts has a matching feature_vectors row (exact timestamp equality — RESEARCH.md mandate #10). Use `JOIN feature_vectors fv ON fv.symbol = m.symbol AND fv.tf = m.timeframe AND fv.bar_ts = m.timestamp`. pipeline_version and regime_label_source come from feature_vectors (regime_label_source from fv if present else 'filtered').

    Flow:
    1. argparse --symbols (default all distinct feature_vectors symbols), --tf (default ['5m','15m','1h','1d'])
    2. _load_config_service; init_otel_providers
    3. For each (symbol, tf) wrapped in observed_span("forward_return_writer.label_symbol_tf"):
       - high-water mark: SELECT MAX(bar_ts) FROM forward_returns WHERE symbol=%s AND tf=%s; recompute the tail window (recompute last 61 bars before HWM so previously-incomplete rows get completed) — full recompute is acceptable for first run.
       - run the LEAD() CTE + JOIN, execute_batch INSERT INTO forward_returns (...) ON CONFLICT (symbol, tf, bar_ts) DO NOTHING. To allow completeness back-fill on incremental runs, use an UPSERT variant: `ON CONFLICT (symbol, tf, bar_ts) DO UPDATE SET return_1bar=EXCLUDED.return_1bar, ..., complete_1bar=EXCLUDED.complete_1bar, ...` ONLY for rows whose completeness improved. Decide: for the first full run ON CONFLICT DO NOTHING is sufficient (idempotency test in P5 depends on DO NOTHING behavior). Implement DO NOTHING for the primary idempotency guarantee; document the completeness-backfill consideration in a comment.
       - FORWARD_RETURN_WRITER_ROWS_WRITTEN_TOTAL.add(inserted, {"symbol": symbol, "tf": tf})
    4. After all cells, compute coverage per lookahead: for each (symbol, tf, N): fraction = count(forward_returns with complete_Nbar) / count(feature_vectors). OUTCOME_LABELS_COVERAGE.set(fraction, {"lookahead": str(N), "symbol": symbol, "tf": tf})
    5. Wrap run in observed_span("forward_return_writer.run"); record FORWARD_RETURN_WRITER_RUN_LATENCY_SECONDS.
    6. Emit JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": ...}); flush_and_shutdown_metrics(); sys.exit(1) on failure.

    Zero hardcoded numeric thresholds beyond the statistical-concept lookahead values; any tunable (e.g. batch size) reads cfg.get_sync.
    DAG-invariant docstring note: oneshot batch tool, exempt like backfill_feature_factory.py.
  </action>
  <acceptance_criteria>
    - `.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m` exits 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns WHERE symbol='SPY' AND tf='5m' AND return_5bar IS NOT NULL AND complete_5bar=true;"` returns > 0
    - Causal check via SQL: for an interior SPY 5m bar, return_1bar equals ln(open[T+2]/open[T+1]). Run:
      `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "WITH o AS (SELECT timestamp, open, LEAD(open,1) OVER w o1, LEAD(open,2) OVER w o2 FROM market_data_ohlcv WHERE symbol='SPY' AND timeframe='5m' WINDOW w AS (ORDER BY timestamp ROWS BETWEEN CURRENT ROW AND 2 FOLLOWING)) SELECT ol.return_1bar, ln(o.o2/o.o1) AS expected, abs(ol.return_1bar - ln(o.o2/o.o1)) AS diff FROM forward_returns ol JOIN o ON o.timestamp=ol.bar_ts WHERE ol.symbol='SPY' AND ol.tf='5m' AND ol.complete_1bar AND o.o2 IS NOT NULL ORDER BY ol.bar_ts LIMIT 5;"` — every diff < 1e-9
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns ol LEFT JOIN feature_vectors fv USING(symbol, tf, bar_ts) WHERE ol.symbol='SPY' AND ol.tf='5m' AND fv.bar_ts IS NULL;"` returns 0 (every forward_returns row has a feature_vectors match)
    - `grep -c "ROWS BETWEEN CURRENT ROW" services/forward_return_writer.py` returns >= 1
    - `grep -c "observed_span" services/forward_return_writer.py` returns >= 2
    - `grep -c "JOB_COMPLETED_TOTAL\|flush_and_shutdown_metrics" services/forward_return_writer.py` returns >= 2
    - `.venv/bin/ruff check services/forward_return_writer.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) total, count(*) FILTER (WHERE complete_5bar) c5, count(*) FILTER (WHERE complete_60bar) c60 FROM forward_returns WHERE symbol='SPY' AND tf='5m';"</verify>
  <done>forward_return_writer.py produces causal forward returns for SPY 5m; formula validated against raw LEAD(); JOIN gate clean; D-06 + OTel + spans wired.</done>
</task>

<task type="auto">
  <name>Task 3: Run outcome labeler across all backfilled symbols/TFs</name>
  <files>forward_returns (DB table — populated)</files>
  <read_first>
    - services/forward_return_writer.py (just built)
  </read_first>
  <action>
    Run `.venv/bin/python services/forward_return_writer.py` with no symbol filter (all feature_vectors symbols x 4 TFs). Run in background; poll forward_returns row counts.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM forward_returns;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE complete_5bar)/count(*),1) FROM forward_returns WHERE tf='5m';"` returns > 95.0 (only the last 6 bars per series should be incomplete for 5bar)
    - Re-run idempotency: running `.venv/bin/python services/forward_return_writer.py --symbols SPY --tf 5m` a second time inserts 0 new rows. Capture count before/after; they must be equal.
    - `job_completed_total{job="forward-return-writer", status="success"}` emitted
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(*) FROM forward_returns GROUP BY tf ORDER BY tf;"</verify>
  <done>forward_returns populated for >=14 symbols x 4 TFs; idempotent re-run confirmed.</done>
</task>

</tasks>

<verification>
- forward_returns has causal forward log returns; formula validated against raw LEAD()
- Every forward_returns row has a matching feature_vectors row (exact bar_ts)
- complete_Nbar flags correct; idempotent re-run writes 0 rows
- D-06 + 3 OTel metrics + 2 spans wired; APR-compliant
</verification>

<success_criteria>
- All task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q stays GREEN
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-03-SUMMARY.md` documenting forward_returns row counts per (symbol, tf), completeness fractions per lookahead, and confirmation of the causal formula validation.
</output>
