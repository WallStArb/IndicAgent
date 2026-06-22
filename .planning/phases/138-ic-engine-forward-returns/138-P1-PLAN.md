---
phase: 138-ic-engine-forward-returns
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - production/migrations/157_ic_engine_tables.sql
  - production/migrations/158_alpha_ic_apr_keys.sql
  - src/config/config_service.py
  - services/service_auditor.py
autonomous: true

must_haves:
  truths:
    - "feature_vectors has rows for at least 14 ETF symbols across 5m/15m/1h/1d"
    - "forward_returns and feature_ic_scores tables exist with correct columns and PK"
    - "alpha.ic.* APR keys are readable via ConfigService.get_sync"
    - "alpha. prefix is in OPS_PREFIXES so alpha.* keys load"
    - "indicagent-forward-return-writer and indicagent-ic-engine registered in service_auditor"
  artifacts:
    - path: "production/migrations/157_ic_engine_tables.sql"
      provides: "forward_returns hypertable + feature_ic_scores table DDL"
      contains: "CREATE TABLE forward_returns"
    - path: "production/migrations/158_alpha_ic_apr_keys.sql"
      provides: "alpha.ic.* / alpha.decay.* APR seeds in config_schema + config_state"
      contains: "alpha.ic.min_observations"
    - path: "src/config/config_service.py"
      provides: "alpha. in OPS_PREFIXES"
      contains: "alpha."
  key_links:
    - from: "feature_vectors backfill"
      to: "feature_vectors table"
      via: "backfill_feature_factory.py compute stage"
      pattern: "count.*feature_vectors"
    - from: "ConfigService"
      to: "config_state alpha.ic.* rows"
      via: "get_sync after migration 158 applied"
      pattern: "alpha\\.ic\\."
---

<objective>
Run the Phase 137 FeatureFactory backfill (prerequisite that blocks ALL of Phase 138) and lay down the schema + APR foundation for the IC pipeline. This plan unblocks the regime labeler, outcome labeler, and IC engine.

Purpose: feature_vectors is currently EMPTY (RESEARCH.md Finding 1) and alpha.ic.* APR keys do not exist (Finding 9). Nothing downstream can run until both are fixed.
Output: Populated feature_vectors, forward_returns + feature_ic_scores tables, seeded alpha.* APR keys, OPS_PREFIXES updated, service_auditor registrations.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
@CLAUDE.md
@docs/plans/2026-06-20-alphaengine-ic-spec.md
@docs/plans/2026-06-20-alphaengine-architecture.md
@production/migrations/156_feature_vectors_expand.sql
@services/backfill_feature_factory.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run FeatureFactory backfill to populate feature_vectors</name>
  <files>feature_vectors (DB table — populated, no source file edit)</files>
  <read_first>
    - services/backfill_feature_factory.py (the service being executed — understand --symbols, --compute-only, checkpointing)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 1, Finding 7, Risk 1)
    - CLAUDE.md (Historical backfill note: client-id 40; instrument asset_class filter)
  </read_first>
  <action>
    Execute the Phase 137 backfill. The service is idempotent and resumable (checkpointed via backfill_status).

    1. Confirm data source coverage first:
       `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT symbol, timeframe, count(*) FROM market_data_ohlcv WHERE timeframe IN ('5m','15m','1h','1d') GROUP BY symbol, timeframe ORDER BY symbol, timeframe;"`
    2. Run compute stage (market_data_ohlcv already has bars per RESEARCH.md, so fetch may be skipped):
       `.venv/bin/python services/backfill_feature_factory.py --compute-only --symbols SPY IWM TLT SHY GLD XLF XLE XLK XLV XLU XLB XLC XLI XLP XLY`
       Run in background; this is a multi-hour operation. Poll backfill_status.
    3. If --compute-only reports missing OHLCV for some (symbol, tf), run the default both-stage mode for those symbols using `--client-id 40` (NOT default 56 which exceeds _MAX_CLIENT_ID=50).
    4. After completion, verify coverage gate below.

    Do NOT modify backfill_feature_factory.py — only run it. regime stays NULL here (it is set in P2).
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors;"` returns > 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_vectors;"` returns >= 14
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT tf) FROM feature_vectors WHERE tf IN ('5m','15m','1h','1d');"` returns 4
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE symbol='SPY' AND tf='5m';"` returns > 50000 (per RESEARCH.md Finding 7: ~93K independent obs at N=5)
    - `job_completed_total{job="backfill-feature-factory", status="success"}` observable (backfill emits it at exit)
  </acceptance_criteria>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(DISTINCT symbol) AS symbols, count(*) AS rows FROM feature_vectors GROUP BY tf ORDER BY tf;"
  </verify>
  <done>feature_vectors populated: >=14 symbols x 4 TFs, SPY 5m > 50K rows.</done>
</task>

<task type="auto">
  <name>Task 2: Migration 157 — forward_returns + feature_ic_scores tables</name>
  <files>production/migrations/157_ic_engine_tables.sql</files>
  <read_first>
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§XIV.1 forward_returns DDL, §XIV.4 feature_ic_scores DDL — copy these exactly)
    - production/migrations/156_feature_vectors_expand.sql (naming + style convention for migrations)
    - production/migrations/155_feature_vectors.sql (create_hypertable + index pattern)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 10: training_window_end is dedup key)
  </read_first>
  <action>
    Create `production/migrations/157_ic_engine_tables.sql` with exactly the DDL from IC spec §XIV.1 and §XIV.4:

    forward_returns (§XIV.1): columns symbol, tf, bar_ts, pipeline_version, regime_label_source (DEFAULT 'smoothed'), return_1bar, return_5bar, return_20bar, return_60bar (all double precision), complete_1bar/complete_5bar/complete_20bar/complete_60bar (boolean DEFAULT false), has_gap_before_entry (boolean DEFAULT false), computed_at (timestamptz DEFAULT now()). PRIMARY KEY (symbol, tf, bar_ts). Then:
    `SELECT create_hypertable('forward_returns', 'bar_ts', chunk_time_interval => INTERVAL '3 months');`
    `CREATE INDEX ON forward_returns (symbol, tf, bar_ts);`

    feature_ic_scores (§XIV.4): all columns per spec including feature_name, vector_domain, symbol, tf, regime (nullable), lookahead_bars, training_window_end, n_independent, reliable, ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper, passes_ci_gate, bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count, wf_ic_sharpe, passes_walkforward, ic_sharpe, ic_sharpe_n_windows, regime_label_source (DEFAULT 'smoothed'), is_decaying (DEFAULT false), decay_detected_at, recovery_eligible_at, computed_at. PRIMARY KEY (feature_name, symbol, tf, regime, lookahead_bars, training_window_end). Two indexes per spec.

    IMPORTANT — nullable regime in PK: Postgres treats NULL as distinct in unique constraints. To make `ON CONFLICT DO NOTHING` work for pooled (regime=NULL) rows AND regime-stratified rows, also add a partial unique index that handles NULL regime:
    `CREATE UNIQUE INDEX feature_ic_scores_pooled_uq ON feature_ic_scores (feature_name, symbol, tf, lookahead_bars, training_window_end) WHERE regime IS NULL;`
    Add a comment explaining this. The IC engine in P4 will INSERT with the appropriate ON CONFLICT target depending on whether regime is NULL.

    Apply the migration:
    `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/157_ic_engine_tables.sql`
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d forward_returns"` shows columns return_1bar/5/20/60, complete_*bar, has_gap_before_entry, PK (symbol, tf, bar_ts)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='forward_returns';"` returns 1
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores"` shows ic_sharpe, passes_walkforward, passes_fdr, bh_adjusted_p, training_window_end columns
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT indexname FROM pg_indexes WHERE tablename='feature_ic_scores' AND indexname='feature_ic_scores_pooled_uq';"` returns 1 row
    - migration file exists at production/migrations/157_ic_engine_tables.sql
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores"</verify>
  <done>forward_returns (hypertable) and feature_ic_scores tables exist with exact spec DDL and pooled unique index.</done>
</task>

<task type="auto">
  <name>Task 3: Migration 158 — seed alpha.ic.* / alpha.decay.* APR keys + OPS_PREFIXES + service_auditor</name>
  <files>production/migrations/158_alpha_ic_apr_keys.sql, src/config/config_service.py, services/service_auditor.py</files>
  <read_first>
    - docs/plans/2026-06-20-alphaengine-architecture.md (APR table lines ~476-488: alpha.ic.* and alpha.decay.* keys with defaults and provenance)
    - production/migrations/153_hmm_garch_kalman_apr.sql (pattern for config_schema + config_state INSERT with value_type and provenance descriptions)
    - src/config/config_service.py (OPS_PREFIXES — find the tuple/list and confirm whether "alpha." is already present from Phase 137 P1)
    - services/service_auditor.py (_DAG_ORDER dict, lines ~57-91; _LAG_THRESHOLDS — oneshots need DAG_ORDER only, not _AGENT_ID_TO_UNIT per RESEARCH.md Finding 12)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 9, Finding 12)
  </read_first>
  <action>
    Create `production/migrations/158_alpha_ic_apr_keys.sql`. INSERT into config_schema AND config_state (ON CONFLICT DO NOTHING) for these exact keys with these defaults and value_type='int' unless noted:
    - alpha.ic.min_observations = 500 [rca_analysis]
    - alpha.ic.bootstrap_resamples = 2000 [conventional]
    - alpha.ic.fdr_alpha = 0.05 (value_type float) [conventional]
    - alpha.ic.walk_forward_folds = 3 [conventional]
    - alpha.ic.sharpe_window_size = 2000 [rca_analysis]
    - alpha.ic.sharpe_min_windows = 10 [conventional]
    - alpha.ic.subsampling_n = 5 [conventional] — non-overlapping subsample stride (RESEARCH.md Finding 6/7)
    - alpha.ic.min_reliable_n = 100 [conventional] — n_independent threshold for reliable flag
    - alpha.decay.ci_lower_threshold = 0.0 (float) [conventional]
    - alpha.decay.materiality_threshold = 0.005 (float) [initial_estimate]
    - alpha.decay.regime_shift_fraction = 0.60 (float) [initial_estimate]
    - alpha.decay.recovery_min_observations = 2000 [rca_analysis]
    Each description string must end with the provenance tag in brackets and note ML-learning-target status where relevant. Match the column set used by migration 153.

    Then in src/config/config_service.py: confirm "alpha." is in OPS_PREFIXES. Phase 137 P1 may have added it. If absent, add the literal `"alpha."` to the OPS_PREFIXES collection. If already present, leave it and note that in the SUMMARY.

    Then in services/service_auditor.py _DAG_ORDER: add two entries at priority 8 (alongside indicagent-hmm-training:8 and indicagent-ml-training:8):
      "indicagent-regime-writer": 8,  # oneshot; populates feature_vectors.regime
      "indicagent-forward-return-writer": 8,  # oneshot; LEAD() forward returns -> forward_returns
      "indicagent-ic-engine": 8,  # oneshot; Spearman IC -> feature_ic_scores
    Do NOT add these to _AGENT_ID_TO_UNIT (oneshots have no lag monitoring per Finding 12).

    Apply: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/158_alpha_ic_apr_keys.sql`
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.ic.%';"` returns >= 8
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT config_value FROM config_state WHERE config_key='alpha.ic.fdr_alpha';"` returns 0.05
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.decay.%';"` returns >= 4
    - `grep -c '"alpha\."' src/config/config_service.py` returns >= 1 (alpha. in OPS_PREFIXES)
    - `grep -c "indicagent-ic-engine\|indicagent-forward-return-writer\|indicagent-regime-writer" services/service_auditor.py` returns >= 3
    - `.venv/bin/python -c "from src.config.config_service import ConfigService; print('ok')"` exits 0 (no syntax error)
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ic.%' OR config_key LIKE 'alpha.decay.%' ORDER BY config_key;"</verify>
  <done>All alpha.ic.* and alpha.decay.* keys seeded and loadable; OPS_PREFIXES has alpha.; three oneshots in _DAG_ORDER.</done>
</task>

</tasks>

<verification>
- feature_vectors populated for >=14 symbols x 4 TFs
- forward_returns + feature_ic_scores tables exist with exact spec DDL
- alpha.ic.* / alpha.decay.* APR keys readable via ConfigService
- alpha. in OPS_PREFIXES; oneshots registered in service_auditor _DAG_ORDER
</verification>

<success_criteria>
- All three task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q stays GREEN (no regression from config_service / service_auditor edits)
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-01-SUMMARY.md` documenting feature_vectors row counts per (symbol, tf), the actual alpha.* keys seeded, and whether alpha. was already in OPS_PREFIXES.
</output>
