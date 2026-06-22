---
phase: 138-ic-engine-forward-returns
plan: 02
type: execute
wave: 2
depends_on: ["138-01"]
files_modified:
  - src/core/agent/base_batch.py
  - production/migrations/160_ic_engine_tables.sql
  - production/migrations/161_alpha_ic_apr_keys.sql
  - src/config/config_service.py
  - services/service_auditor.py
autonomous: true

must_haves:
  truths:
    - "BaseBatch exists at src/core/agent/base_batch.py with job_name, compute_version, content_key(), run() template method, and D-06 job_completed_total emission"
    - "feature_vectors has rows for at least 14 ETF symbols across 5m/15m/1h/1d"
    - "forward_returns and feature_ic_scores tables exist with correct columns and PK"
    - "feature_ic_scores has is_pooled BOOLEAN DEFAULT false column"
    - "feature_ic_scores has two separate unique indexes: one for pooled rows (is_pooled=true, regime=NULL), one for regime-stratified rows"
    - "alpha.ic.* APR keys with TF-specific bootstrap block sizes (alpha.ic.bootstrap_block_size.5m etc.) are readable via ConfigService.get_sync"
    - "alpha. prefix is in OPS_PREFIXES so alpha.* keys load"
    - "indicagent-regime-writer, indicagent-forward-return-writer, indicagent-ic-engine registered in BOTH _DAG_ORDER AND _ONESHOT_UNITS in service_auditor"
  artifacts:
    - path: "src/core/agent/base_batch.py"
      provides: "BaseBatch abstract base class for all Phase 138+ batch compute oneshots"
      contains: "BaseBatch"
    - path: "production/migrations/160_ic_engine_tables.sql"
      provides: "forward_returns hypertable + feature_ic_scores table DDL"
      contains: "CREATE TABLE forward_returns"
    - path: "production/migrations/161_alpha_ic_apr_keys.sql"
      provides: "alpha.ic.* / alpha.decay.* APR seeds in config_schema + config_state"
      contains: "alpha.ic.min_observations"
    - path: "src/config/config_service.py"
      provides: "alpha. in OPS_PREFIXES"
      contains: "alpha."
    - path: "services/service_auditor.py"
      provides: "_ONESHOT_UNITS with three new regime/IC oneshot entries"
      contains: "indicagent-regime-writer"
  key_links:
    - from: "feature_vectors backfill"
      to: "feature_vectors table"
      via: "backfill_feature_factory.py compute stage"
      pattern: "count.*feature_vectors"
    - from: "ConfigService"
      to: "config_state alpha.ic.* rows"
      via: "get_sync after migration 161 applied"
      pattern: "alpha\\.ic\\."
    - from: "service_auditor._evaluate_service_dynamic"
      to: "_ONESHOT_UNITS check at line 508"
      via: "frozenset membership: if unit in _ONESHOT_UNITS: return"
      pattern: "_ONESHOT_UNITS"
---

<objective>
Run the Phase 137 FeatureFactory backfill (prerequisite that blocks ALL of Phase 138), build BaseBatch (the shared base class for all Phase 138+ batch compute oneshots), and lay down the schema + APR foundation for the IC pipeline. This plan unblocks the regime labeler, outcome labeler, and IC engine.

Purpose: feature_vectors is currently EMPTY (RESEARCH.md Finding 1) and alpha.ic.* APR keys do not exist (Finding 9). Nothing downstream can run until both are fixed. BaseBatch is built here so P2/P3/P4 services can inherit from it — standardizing DB pool lifecycle, D-06 emission, content-addressed key generation, and error handling across all batch compute services. The is_pooled column (not NULL overloading) disambiguates pooled vs. regime-stratified IC rows. The _ONESHOT_UNITS registration prevents the auditor from treating idle IC batch services as dead daemons.
Output: Populated feature_vectors, BaseBatch base class, forward_returns + feature_ic_scores tables (with is_pooled column), seeded alpha.* APR keys including bootstrap_block_size, OPS_PREFIXES updated, service_auditor registrations in both _DAG_ORDER and _ONESHOT_UNITS.
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
  <name>Task 0: Build BaseBatch base class</name>
  <files>src/core/agent/base_batch.py</files>
  <read_first>
    - src/core/agent/base_writer.py (inherit pattern, DB pool lifecycle, error handling style)
    - src/core/agent/base_daemon.py (D-06 job_completed_total emission pattern)
    - src/observability/metrics.py (JOB_COMPLETED_TOTAL counter, counter() factory)
    - src/intelligence/trading/signal_schema.py:make_signal_id (SHA-256 content key pattern to replicate)
  </read_first>
  <action>
    Create src/core/agent/base_batch.py. This is the shared base class for all Phase 138+
    batch compute oneshots (regime_writer, forward_return_writer, ic_engine, and future services).

    Contract:
    - Abstract class (ABC). Subclasses must define: job_name: str, compute_version: str, execute(pool) -> None
    - __init__: accept db_dsn (from Settings), set up structlog logger via setup_service_logging()
    - async run() template method:
        1. _setup_pool() — asyncpg.create_pool(dsn, min_size=2, max_size=10)
        2. t0 = time.monotonic()
        3. try: await self.execute(self._pool)
           status = "success"
        4. except Exception as error: logger.error("batch_computer.failed", error=str(error)); status = "failure"; raise
        5. finally: await _teardown_pool(); _emit_completion(status, time.monotonic() - t0)
    - content_key(*parts: str) -> str staticmethod: SHA-256 of "|".join(str(p) for p in parts), hexdigest()[:32]
      (mirrors make_signal_id pattern from signal_schema.py)
    - _emit_completion(status: str, elapsed_s: float): JOB_COMPLETED_TOTAL.add(1, {"job": self.job_name, "status": status})
      + logger.info("batch_computer.completed", job=self.job_name, status=status, elapsed_s=round(elapsed_s, 2))
    - _setup_pool / _teardown_pool: standard asyncpg pool lifecycle

    Do NOT add OTel histograms for per-row latency here — that belongs in subclasses.
    Do NOT import from src/intelligence/ — this is Ring 0 infrastructure.
  </action>
  <acceptance_criteria>
    - File exists at src/core/agent/base_batch.py
    - Class BaseBatch is importable: from src.core.agent.base_batch import BaseBatch
    - content_key("SPY", "5m", "1719014400000") returns a 32-char hex string deterministically
    - Abstract: instantiating BaseBatch directly raises TypeError
  </acceptance_criteria>
</task>

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
       PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT symbol, timeframe, count(*) FROM market_data_ohlcv WHERE timeframe IN ('5m','15m','1h','1d') GROUP BY symbol, timeframe ORDER BY symbol, timeframe;"
    2. Run compute stage (market_data_ohlcv already has bars per RESEARCH.md, so fetch may be skipped):
       .venv/bin/python services/backfill_feature_factory.py --compute-only --symbols SPY IWM TLT SHY GLD XLF XLE XLK XLV XLU XLB XLC XLI XLP XLY
       Run in background; this is a multi-hour operation. Poll backfill_status.
    3. If --compute-only reports missing OHLCV for some (symbol, tf), run the default both-stage mode for those symbols using --client-id 40 (NOT default 56 which exceeds _MAX_CLIENT_ID=50).
    4. After completion, verify coverage gate below.

    Do NOT modify backfill_feature_factory.py -- only run it. regime stays NULL here (it is set in P2).
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
  <name>Task 2: Migration 157 — forward_returns + feature_ic_scores tables with is_pooled column</name>
  <files>production/migrations/160_ic_engine_tables.sql</files>
  <read_first>
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§XIV.1 forward_returns DDL, §XIV.4 feature_ic_scores DDL)
    - production/migrations/156_feature_vectors_expand.sql (naming + style convention for migrations)
    - production/migrations/155_feature_vectors.sql (create_hypertable + index pattern)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 10: training_window_end is dedup key)
  </read_first>
  <action>
    Create production/migrations/160_ic_engine_tables.sql.

    forward_returns (§XIV.1): columns symbol, tf, bar_ts, pipeline_version, regime_label_source (DEFAULT 'filtered'), return_1bar, return_5bar, return_20bar, return_60bar (all double precision), complete_1bar/complete_5bar/complete_20bar/complete_60bar (boolean DEFAULT false), has_gap_before_entry (boolean DEFAULT false), computed_at (timestamptz DEFAULT now()). PRIMARY KEY (symbol, tf, bar_ts). Then:
    SELECT create_hypertable('forward_returns', 'bar_ts', chunk_time_interval => INTERVAL '3 months');
    CREATE INDEX ON forward_returns (symbol, tf, bar_ts);

    feature_ic_scores (§XIV.4 + review correction): all columns per spec including feature_name, vector_domain, symbol, tf, regime (nullable), lookahead_bars, training_window_end, n_independent, reliable, ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper, passes_ci_gate, bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count, wf_ic_sharpe, passes_walkforward, ic_sharpe, ic_sharpe_n_windows, regime_label_source (DEFAULT 'filtered'), is_decaying (DEFAULT false), decay_detected_at, recovery_eligible_at, computed_at.

    CRITICAL ADDITION (fixes HIGH review issue #4): Add is_pooled BOOLEAN DEFAULT false NOT NULL column to feature_ic_scores. This explicitly distinguishes:
    - Pooled rows: is_pooled=true, regime=NULL (cross-regime IC run)
    - Regime-stratified rows: is_pooled=false, regime='trending_up' etc.
    Using NULL alone to mean "pooled" is dangerous for ON CONFLICT semantics and data interpretation.

    PRIMARY KEY: (feature_name, symbol, tf, regime, lookahead_bars, training_window_end) — Postgres treats each NULL regime as distinct, so this PK works for regime rows but NOT for pooled rows where regime IS NULL.

    TWO SEPARATE UNIQUE INDEXES replacing the partial-index-only approach:

    Index 1 (pooled rows):
    CREATE UNIQUE INDEX feature_ic_scores_pooled_uq
      ON feature_ic_scores (feature_name, symbol, tf, lookahead_bars, training_window_end)
      WHERE is_pooled = true;

    Index 2 (regime-stratified rows):
    CREATE UNIQUE INDEX feature_ic_scores_regime_uq
      ON feature_ic_scores (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
      WHERE is_pooled = false AND regime IS NOT NULL;

    Add a comment block explaining why two indexes: ON CONFLICT for pooled rows targets feature_ic_scores_pooled_uq (WHERE is_pooled=true); ON CONFLICT for regime rows targets feature_ic_scores_regime_uq (WHERE is_pooled=false AND regime IS NOT NULL). Never rely on NULL uniqueness in Postgres.

    Apply the migration:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/160_ic_engine_tables.sql
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d forward_returns"` shows columns return_1bar/5/20/60, complete_*bar, has_gap_before_entry, PK (symbol, tf, bar_ts)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='forward_returns';"` returns 1
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores"` shows is_pooled column (boolean not null default false), ic_sharpe, passes_walkforward, passes_fdr, bh_adjusted_p, training_window_end columns
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT indexname FROM pg_indexes WHERE tablename='feature_ic_scores' AND indexname IN ('feature_ic_scores_pooled_uq','feature_ic_scores_regime_uq');"` returns 2 rows
    - `grep -c "is_pooled" production/migrations/160_ic_engine_tables.sql` returns >= 3 (column def + two index WHERE clauses)
    - migration file exists at production/migrations/160_ic_engine_tables.sql
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores"</verify>
  <done>forward_returns (hypertable) and feature_ic_scores tables exist; is_pooled column present; two unique indexes (pooled_uq + regime_uq) present.</done>
</task>

<task type="auto">
  <name>Task 3: Migration 158 — seed alpha.ic.* / alpha.decay.* APR keys (including bootstrap_block_size) + OPS_PREFIXES + service_auditor</name>
  <files>production/migrations/161_alpha_ic_apr_keys.sql, src/config/config_service.py, services/service_auditor.py</files>
  <read_first>
    - docs/plans/2026-06-20-alphaengine-architecture.md (APR table: alpha.ic.* and alpha.decay.* keys with defaults and provenance)
    - production/migrations/153_hmm_garch_kalman_apr.sql (pattern for config_schema + config_state INSERT with value_type and provenance descriptions)
    - src/config/config_service.py (OPS_PREFIXES — find the tuple/list and confirm whether "alpha." is already present from Phase 137 P1)
    - services/service_auditor.py (_DAG_ORDER dict lines ~57-122; _ONESHOT_UNITS frozenset lines ~170-191 — BOTH must be updated)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 9, Finding 12)
  </read_first>
  <action>
    Create production/migrations/161_alpha_ic_apr_keys.sql. INSERT into config_schema AND config_state (ON CONFLICT DO NOTHING) for these exact keys with these defaults and value_type='int' unless noted:
    - alpha.ic.min_observations = 500 [rca_analysis]
    - alpha.ic.bootstrap_resamples = 2000 [conventional]
    - alpha.ic.bootstrap_block_size.5m = 78 (value_type int) [initial_estimate]
    - alpha.ic.bootstrap_block_size.15m = 26 (value_type int) [initial_estimate]
    - alpha.ic.bootstrap_block_size.1h = 10 (value_type int) [conventional]
    - alpha.ic.bootstrap_block_size.1d = 10 (value_type int) [conventional] — circular block bootstrap block size; optimal block length grows O(N^(1/3)) per Hall & Horowitz 1996; APR allows override without code change; ML-learning-target: no
    - alpha.ic.fdr_alpha = 0.05 (value_type float) [conventional]
    - alpha.ic.walk_forward_folds = 3 [conventional]
    - alpha.ic.sharpe_window_size = 2000 [rca_analysis]
    - alpha.ic.sharpe_min_windows = 10 [conventional]
    - alpha.ic.subsampling_n = 5 [conventional] — non-overlapping subsample stride
    - alpha.ic.min_reliable_n = 100 [conventional] — n_independent threshold for reliable flag
    - alpha.decay.ci_lower_threshold = 0.0 (float) [conventional]
    - alpha.decay.materiality_threshold = 0.005 (float) [initial_estimate]
    - alpha.decay.regime_shift_fraction = 0.60 (float) [initial_estimate]
    - alpha.decay.recovery_min_observations = 2000 [rca_analysis]
    Each description string must end with the provenance tag in brackets and note ML-learning-target status. Match the column set used by migration 153.

    Then in src/config/config_service.py: confirm "alpha." is in OPS_PREFIXES. Phase 137 P1 may have added it. If absent, add the literal "alpha." to the OPS_PREFIXES collection. If already present, leave it and note in the SUMMARY.

    Then in services/service_auditor.py — TWO locations must be updated (fixes HIGH review issue #3):

    LOCATION 1 — _DAG_ORDER dict: add three entries at priority 8 (alongside other oneshots at line ~105):
      "indicagent-regime-writer": 8,  # oneshot; populates feature_vectors.regime
      "indicagent-forward-return-writer": 8,  # oneshot; LEAD() forward returns -> forward_returns
      "indicagent-ic-engine": 8,  # oneshot; Spearman IC -> feature_ic_scores

    LOCATION 2 — _ONESHOT_UNITS frozenset (lines ~170-191): add the same three entries:
      "indicagent-regime-writer",  # Type=oneshot; inactive between IC pipeline runs is correct
      "indicagent-forward-return-writer",  # Type=oneshot; inactive between IC pipeline runs is correct
      "indicagent-ic-engine",  # Type=oneshot; inactive between IC pipeline runs is correct

    REASON: service_auditor._evaluate_service_dynamic() skips services in _ONESHOT_UNITS (line ~508: `if unit in _ONESHOT_UNITS: return`). Without this, an idle ic-engine service will be misidentified as a dead daemon and incorrectly restarted. _DAG_ORDER registration alone is insufficient.

    Do NOT add these to _AGENT_ID_TO_UNIT (oneshots have no Kafka consumer lag monitoring per Finding 12).

    Apply: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/161_alpha_ic_apr_keys.sql
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.ic.%';"` returns >= 12 (includes 4 TF-specific bootstrap_block_size keys)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT config_value FROM config_state WHERE config_key='alpha.ic.bootstrap_block_size.5m';"` returns 78
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT config_value FROM config_state WHERE config_key='alpha.ic.fdr_alpha';"` returns 0.05
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.decay.%';"` returns >= 4
    - `grep -c '"alpha\."' src/config/config_service.py` returns >= 1 (alpha. in OPS_PREFIXES)
    - `grep -c "indicagent-ic-engine\|indicagent-forward-return-writer\|indicagent-regime-writer" services/service_auditor.py` returns >= 6 (3 in _DAG_ORDER + 3 in _ONESHOT_UNITS)
    - `grep -n "indicagent-regime-writer" services/service_auditor.py` shows entries in BOTH _DAG_ORDER block AND _ONESHOT_UNITS block (two separate line numbers)
    - `.venv/bin/python -c "from src.config.config_service import ConfigService; print('ok')"` exits 0 (no syntax error)
    - `.venv/bin/python -c "from services.service_auditor import _ONESHOT_UNITS; assert 'indicagent-regime-writer' in _ONESHOT_UNITS; print('ok')"` exits 0
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ic.%' OR config_key LIKE 'alpha.decay.%' ORDER BY config_key;"</verify>
  <done>All alpha.ic.* (including bootstrap_block_size) and alpha.decay.* keys seeded; OPS_PREFIXES has alpha.; three oneshots in BOTH _DAG_ORDER AND _ONESHOT_UNITS.</done>
</task>

</tasks>

<verification>
- feature_vectors populated for >=14 symbols x 4 TFs
- forward_returns + feature_ic_scores tables exist; is_pooled BOOLEAN column present; two unique indexes (pooled_uq + regime_uq) exist
- alpha.ic.bootstrap_block_size=10 seeded and readable via ConfigService
- alpha. in OPS_PREFIXES; three oneshots in BOTH _DAG_ORDER AND _ONESHOT_UNITS
</verification>

<success_criteria>
- All three task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q stays GREEN (no regression from config_service / service_auditor edits)
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-02-SUMMARY.md` documenting feature_vectors row counts per (symbol, tf), the actual alpha.* keys seeded, whether alpha. was already in OPS_PREFIXES, and confirmation that all three oneshots appear in both _DAG_ORDER and _ONESHOT_UNITS.
</output>
