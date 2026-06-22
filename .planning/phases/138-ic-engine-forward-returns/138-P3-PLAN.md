---
phase: 138-ic-engine-forward-returns
plan: 03
type: execute
wave: 2
depends_on: ["138-01"]
files_modified: []
autonomous: true

must_haves:
  truths:
    - "feature_vectors has rows for at least 14 ETF symbols across 5m/15m/1h/1d"
    - "feature_vectors rows have feature_factory_version = '1.0.0' (not NULL)"
    - "feature_vectors rows have momentum_z_60, momentum_reversal_z, quarter_position, days_to_month_end populated (not NULL)"
    - "feature_vectors rows have bar_close_ts populated (not NULL)"
    - "feature_vector_id UUID is set on all new rows"
    - "SPY 5m row count > 50000"
    - "job_completed_total{job='backfill-feature-factory', status='success'} emitted"
  artifacts:
    - path: "feature_vectors (DB table)"
      provides: "Populated training corpus for IC engine: >=14 symbols x 4 TFs x full history"
      contains: "SELECT count(*) FROM feature_vectors"
  key_links:
    - from: "backfill_feature_factory.py compute stage"
      to: "feature_vectors table"
      via: "feature_vector_to_insert_params() 70-param INSERT (P1 hardened)"
      pattern: "INSERT INTO feature_vectors"
---

<objective>
Run the FeatureFactory backfill to populate feature_vectors with the full ETF history. Pure operational plan — no code written here. P1 hardened the write stack; this plan executes it at scale and verifies the output meets IC engine minimum data requirements.

Runs in parallel with P2 (BaseBatch + IC engine schema) — neither depends on the other. P4 (regime_writer) and P5 (forward_return_writer) both depend on this plan completing.

Output: feature_vectors populated for >=14 symbols x 4 TFs with all P1 fields present; coverage gate passed; D-06 emitted.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
@CLAUDE.md
@services/backfill_feature_factory.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run FeatureFactory backfill to populate feature_vectors</name>
  <files>feature_vectors (DB table — populated, no source file edit)</files>
  <read_first>
    - services/backfill_feature_factory.py (--symbols, --compute-only flags, checkpoint/resume via backfill_status)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 1, Finding 7: SPY 5m ~93K rows)
    - CLAUDE.md (client-id 40; asset_class filter; DB query pattern)
  </read_first>
  <action>
    Execute the FeatureFactory backfill. Idempotent and resumable via backfill_status. Do NOT modify backfill_feature_factory.py.

    1. Confirm OHLCV coverage:
       PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
         SELECT symbol, timeframe, count(*) FROM market_data_ohlcv
         WHERE timeframe IN ('5m','15m','1h','1d')
           AND contract_details->>'asset_class' = 'equity'
         GROUP BY symbol, timeframe ORDER BY symbol, timeframe;"

    2. Run compute-only (OHLCV already populated per RESEARCH.md):
       .venv/bin/python services/backfill_feature_factory.py --compute-only
       Run in background. Poll progress:
       PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
         SELECT tf, count(DISTINCT symbol) AS symbols, count(*) AS rows
         FROM feature_vectors GROUP BY tf ORDER BY tf;"

    3. If --compute-only reports missing OHLCV for any (symbol, tf), run full fetch+compute
       for those symbols with --client-id 40 (never default 56 — exceeds _MAX_CLIENT_ID=50).

    regime stays NULL — that is P4's job.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_vectors;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT tf) FROM feature_vectors WHERE tf IN ('5m','15m','1h','1d');"` returns 4
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m';"` returns > 50000
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE feature_factory_version IS NULL;"` returns 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE bar_close_ts IS NULL;"` returns 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE momentum_z_60 IS NULL AND bar_ts > NOW() - INTERVAL '1 year';"` returns 0
    - `job_completed_total{job="backfill-feature-factory", status="success"}` observable
  </acceptance_criteria>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
      SELECT tf, count(DISTINCT symbol) AS symbols, count(*) AS rows,
             count(*) FILTER (WHERE bar_close_ts IS NOT NULL) AS has_close_ts,
             count(*) FILTER (WHERE momentum_z_60 IS NOT NULL) AS has_mom60
      FROM feature_vectors GROUP BY tf ORDER BY tf;"
  </verify>
  <done>feature_vectors populated: >=14 symbols x 4 TFs; SPY 5m > 50K rows; all P1 fields non-NULL; D-06 emitted.</done>
</task>

</tasks>

<verification>
- feature_vectors populated for >=14 symbols x 4 TFs
- All P1 fields present: feature_factory_version, bar_close_ts, momentum_z_60, momentum_reversal_z, quarter_position, days_to_month_end
- No NULL feature_factory_version or bar_close_ts rows
- D-06 emitted with status=success
</verification>

<success_criteria>
- Task acceptance criteria pass
- SPY 5m > 50K rows; >= 14 distinct symbols; all 4 TFs represented
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-03-SUMMARY.md` documenting row counts per (symbol, tf) and confirmation that all P1 fields are non-NULL in sampled rows.
</output>
