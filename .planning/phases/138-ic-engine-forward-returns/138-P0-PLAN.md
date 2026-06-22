---
phase: 138-ic-engine-forward-returns
plan: 00
type: execute
wave: 0
depends_on: []
files_modified:
  - services/feature_vector_writer.py
  - production/migrations/158_feature_vector_id.sql
  - services/backfill_feature_factory.py
  - services/service_auditor.py
  - tests/unit/services/test_feature_writer.py
  - tests/unit/services/test_feature_writer_config.py
  - tests/unit/services/test_feature_writer_column_mapping.py
autonomous: true

must_haves:
  truths:
    - "feature_vectors table has a feature_vector_id UUID column populated on every INSERT"
    - "feature_vector_id = SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] cast to UUID"
    - "FeatureVectorWriter class exists at services/feature_vector_writer.py (renamed from feature_writer.py)"
    - "services/feature_writer.py is deleted; all imports/references updated"
    - "FeatureVectorWriter extends BaseWriter — inheritance unchanged"
    - "Hardcoded DSN postgresql://postgres:postgres@localhost:5432/indicagent is gone; Settings().database_url used"
    - "_load_config() JSON file pattern removed; BATCH_SIZE and FLUSH_INTERVAL_SECS read from APR"
    - "All structlog events follow feature_vector_writer.<event> taxonomy (no plain English strings)"
    - "CONSUMER_NAME dead code removed"
    - "_db_connected uses point_gauge() factory not raw meter"
    - "Phase reference removed from docstring"
    - "backfill_feature_factory.py INSERT includes feature_vector_id"
    - "backfill_feature_factory.py log event d06_gate_candidates_below_80pct renamed to coverage_below_threshold"
    - "backfill_feature_factory.py coverage_gate renamed to coverage_threshold throughout"
    - "pytest tests/unit/ -q is GREEN"
  artifacts:
    - path: "services/feature_vector_writer.py"
      provides: "FeatureVectorWriter — renamed, hardcoded DSN removed, APR config, log taxonomy fixed, content_key populated"
      contains: "FeatureVectorWriter"
    - path: "production/migrations/158_feature_vector_id.sql"
      provides: "ALTER TABLE feature_vectors ADD COLUMN feature_vector_id UUID"
      contains: "feature_vector_id"
  key_links:
    - from: "FeatureVectorWriter._record_to_insert_params()"
      to: "feature_vectors.feature_vector_id"
      via: "BaseBatch.content_key(symbol, tf, str(bar_ts_ns), pipeline_version) cast to UUID"
      pattern: "feature_vector_id"
    - from: "backfill_feature_factory._vector_to_params()"
      to: "feature_vectors.feature_vector_id"
      via: "same SHA-256 content_key(symbol, tf, str(bar_ts_ns), pipeline_version)"
      pattern: "feature_vector_id"
---

<objective>
Fix the FeatureVectorWriter (live path) and backfill_feature_factory (batch path) before any
feature_vectors rows are written. Every row written in Phase 138 must have a content_key
(feature_vector_id). Without it the provenance chain is broken from row one — IC scores cannot
reference feature_vector rows by a stable identifier, and replay cannot distinguish rows produced
by different algorithm versions.

This plan also closes all naming, taxonomy, and configuration gaps identified in the 2026-06-22
council review before Phase 138 data is produced. Wrong names in a live system compound — fix
them before they appear in 100,000+ rows of training data.

Output: feature_vector_id column in schema, populated by both write paths; FeatureVectorWriter
renamed and cleaned; backfill taxonomy corrected; all unit tests green.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@services/feature_writer.py
@services/backfill_feature_factory.py
@services/service_auditor.py
@src/observability/metrics.py
@src/config/settings.py
@production/migrations/156_feature_vectors_expand.sql
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migration 158 — add feature_vector_id to feature_vectors</name>
  <files>production/migrations/158_feature_vector_id.sql</files>
  <read_first>
    - production/migrations/156_feature_vectors_expand.sql (style: ALTER TABLE pattern)
    - production/migrations/155_feature_vectors.sql (original table DDL — verify feature_vector_id absent)
  </read_first>
  <action>
    Create production/migrations/158_feature_vector_id.sql:

    ALTER TABLE feature_vectors
      ADD COLUMN IF NOT EXISTS feature_vector_id UUID;

    CREATE UNIQUE INDEX IF NOT EXISTS feature_vectors_content_key_uq
      ON feature_vectors (feature_vector_id)
      WHERE feature_vector_id IS NOT NULL;

    COMMENT ON COLUMN feature_vectors.feature_vector_id IS
      'SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID. Content-addressed row key.
       Idempotent across replays. NULL for rows written before migration 158.';

    Apply: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
      -f production/migrations/158_feature_vector_id.sql

    NOTE: Existing rows (currently 0 — backfill has not run) will have feature_vector_id = NULL.
    All new rows from FeatureVectorWriter and backfill_feature_factory will populate it.
    NULL for pre-migration rows is acceptable and distinguishable from populated rows.

    NOTE: Migration numbers in P1 (forward_returns + feature_ic_scores) shift to 159.
    Migration for APR alpha.ic.* keys shifts to 160. Update P1-PLAN.md after this task.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_vectors"` shows feature_vector_id UUID column
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM pg_indexes WHERE tablename='feature_vectors' AND indexname='feature_vectors_content_key_uq';"` returns 1
  </acceptance_criteria>
  <done>feature_vector_id UUID column exists in feature_vectors with unique index.</done>
</task>

<task type="auto">
  <name>Task 2: Rename and fix FeatureVectorWriter (live write path)</name>
  <files>services/feature_vector_writer.py (new), services/feature_writer.py (delete after)</files>
  <read_first>
    - services/feature_writer.py (full file — the source being refactored)
    - src/observability/metrics.py (point_gauge() factory signature)
    - src/config/settings.py (Settings.database_url attribute name)
    - src/core/agent/base_writer.py (BaseWriter.__init__ signature — max_idle_seconds etc.)
  </read_first>
  <action>
    Create services/feature_vector_writer.py as a cleaned version of services/feature_writer.py.
    Apply ALL of the following changes:

    RENAME:
    - File: feature_writer.py → feature_vector_writer.py
    - Class: FeatureWriter → FeatureVectorWriter
    - Update module docstring: remove "Phase 137 P4:" phase reference

    REMOVE _load_config() PATTERN:
    - Delete _load_config() method entirely
    - Delete config_file parameter from __init__
    - Delete self.config references throughout
    - Replace self.config["database"]["dsn"] with self.settings.database_url
      (Settings is already available as self.settings from BaseDaemon)
    - Replace self.config["service"]["health_check_interval"] with
      cfg.get_sync("feature.writer.health_check_interval", 30) via ConfigService
      OR just hardcode 30 as a class constant HEALTH_CHECK_INTERVAL_SECS = 30
      (acceptable since this is not a tunable threshold, it is an operational interval)

    APR-BACK CONSTANTS:
    - Remove module-level BATCH_SIZE = 50 — read from APR at _setup():
      self.BATCH_SIZE = int(cfg.get_sync("threshold.feature_writer.batch_size", 50))
    - Remove module-level FLUSH_INTERVAL_SECS = 5.0 — read from APR at _setup():
      self.FLUSH_INTERVAL_SECS = float(cfg.get_sync("threshold.feature_writer.flush_interval_secs", 5.0))
    NOTE: APR keys threshold.feature_writer.* do not need a migration — they use get_sync()
    with fallback defaults. Add the migration in the follow-on todo; for now fallback is fine.

    REMOVE DEAD CODE:
    - Delete CONSUMER_NAME = "feature_writer_1" (unused)

    FIX _db_connected METRIC:
    - Replace: self._db_connected = _fw_meter.create_gauge(...)
    - With: self._db_connected = point_gauge("feature_writer_db_connected", "DB connection state (1=connected, 0=disconnected)")
    - Remove _fw_meter module-level meter (only used for _db_connected; all others use factory)

    ADD content_key TO INSERT:
    - Import: from src.intelligence.trading.signal_schema import make_signal_id
      OR implement inline: hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
      Use inline import hashlib — do NOT import from signal_schema (Ring 1 domain, not Ring 0)
    - In _record_to_insert_params(): compute feature_vector_id:
        import hashlib
        bar_ts_ns = str(int(record.bar_ts.timestamp() * 1_000_000_000))
        raw = hashlib.sha256(
            f"{record.symbol}|{record.tf}|{bar_ts_ns}|{record.pipeline_version}".encode()
        ).hexdigest()[:32]
        feature_vector_id = uuid.UUID(raw)  # import uuid at top
    - Add feature_vector_id as $1 in _INSERT_FEATURE_VECTOR_SQL (shift all other params +1)
    - Add column feature_vector_id to the INSERT column list (first position)
    - Total params becomes 61

    FIX LOG EVENT TAXONOMY — replace all plain English strings:
    - "Feature Writer Agent started" → "feature_vector_writer.started"
    - "Connected to database" → "feature_vector_writer.db_connected"
    - "Kafka consumer started" → "feature_vector_writer.kafka_consumer_started"
    - "Health check" → "feature_vector_writer.health_check"
    - "Flushed feature_vectors batch" → "feature_vector_writer.batch_flushed"
    - "Shutting down Feature Writer Agent" → "feature_vector_writer.shutdown_started"
    - "Feature Writer Agent stopped" → "feature_vector_writer.stopped"
    - "No database connection — cannot flush" → "feature_vector_writer.flush_no_db"
    - "Error in processing loop" → "feature_vector_writer.process_loop_error"
    - "Error in periodic flush loop" → "feature_vector_writer.flush_loop_error"
    - "Error in health monitor" → "feature_vector_writer.health_monitor_error"

    FIX _maybe_route_to_dlq CALL:
    - Change: await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
    - To: store the parse exception and pass it:
        try:
            ...parse...
        except (TypeError, KeyError, ValueError) as error:
            self._parse_errors_total.add(1)
            return [], [payload]  # keep return contract; DLQ routing happens in _process_loop
      In _process_loop, capture the parse result and pass the real error:
        valid, invalid = self._parse_payload(payload)
        if invalid:
            await self._maybe_route_to_dlq(payload, ValueError("FeatureVectorRecord parse failed"))

    REMOVE getattr FALLBACK in _shutdown():
    - Change: getattr(self, "_total_events", 0) → self._total_events
    - Change: getattr(self, "_total_batches", 0) → self._total_batches
    (these are set in __init__ and always exist)

    After creating services/feature_vector_writer.py, DELETE services/feature_writer.py.
  </action>
  <acceptance_criteria>
    - `python -c "from services.feature_vector_writer import FeatureVectorWriter; print('ok')"` exits 0
    - `python -c "from services.feature_writer import FeatureWriter"` raises ImportError (file deleted)
    - `grep -c "feature_vector_id" services/feature_vector_writer.py` returns >= 3 (column, SQL, compute)
    - `grep -c "postgres:postgres@localhost" services/feature_vector_writer.py` returns 0
    - `grep -c "_load_config\|config_file" services/feature_vector_writer.py` returns 0
    - `grep -c "CONSUMER_NAME" services/feature_vector_writer.py` returns 0
    - `grep -c "Phase 137" services/feature_vector_writer.py` returns 0
    - `grep -c "point_gauge" services/feature_vector_writer.py` returns >= 2
    - `grep "Health check\|Feature Writer Agent\|Connected to database" services/feature_vector_writer.py` returns empty
  </acceptance_criteria>
  <done>FeatureVectorWriter created, feature_writer.py deleted, content_key populated, DSN fixed, log events canonical.</done>
</task>

<task type="auto">
  <name>Task 3: Update all references from feature_writer → feature_vector_writer</name>
  <files>services/service_auditor.py, tests/unit/services/test_feature_writer.py, tests/unit/services/test_feature_writer_config.py, tests/unit/services/test_feature_writer_column_mapping.py</files>
  <read_first>
    - services/service_auditor.py (lines referencing feature_writer / FeatureWriter)
    - tests/unit/services/test_feature_writer.py
    - tests/unit/services/test_feature_writer_config.py
    - tests/unit/services/test_feature_writer_column_mapping.py
  </read_first>
  <action>
    Update all files that import or reference the old name:

    services/service_auditor.py:
    - "indicagent-feature-writer" stays as the systemd unit name (operational name, not changed here)
    - "feature_writer" key in _AGENT_ID_TO_UNIT → "feature_vector_writer"
    - Any comment referencing FeatureWriter → FeatureVectorWriter

    tests/unit/services/test_feature_writer*.py:
    - Rename test files:
        test_feature_writer.py → test_feature_vector_writer.py
        test_feature_writer_config.py → test_feature_vector_writer_config.py
        test_feature_writer_column_mapping.py → test_feature_vector_writer_column_mapping.py
    - Update all imports: from services.feature_writer import FeatureWriter
      → from services.feature_vector_writer import FeatureVectorWriter
    - Update all class references: FeatureWriter → FeatureVectorWriter
    - Update any SQL assertions that reference column counts (now 61 columns with feature_vector_id)

    Check for any other imports:
    grep -rn "from services.feature_writer\|from services import feature_writer\|import feature_writer" \
      src/ services/ tests/ --include="*.py"
    Fix any found.
  </action>
  <acceptance_criteria>
    - `grep -rn "from services.feature_writer\|from services import feature_writer" src/ services/ tests/ --include="*.py"` returns empty
    - `grep -rn "class FeatureWriter\b" services/ src/ tests/ --include="*.py"` returns empty
    - `python -c "from services.service_auditor import _AGENT_ID_TO_UNIT; assert 'feature_vector_writer' in _AGENT_ID_TO_UNIT; print('ok')"` exits 0
  </acceptance_criteria>
  <done>All references updated; no dangling imports to deleted feature_writer.py.</done>
</task>

<task type="auto">
  <name>Task 4: Fix backfill_feature_factory.py — content_key + taxonomy</name>
  <files>services/backfill_feature_factory.py</files>
  <read_first>
    - services/backfill_feature_factory.py (full file — already read this session)
    - production/migrations/158_feature_vector_id.sql (column now exists)
  </read_first>
  <action>
    Apply targeted fixes to backfill_feature_factory.py. DO NOT restructure or split the file —
    that is the follow-on todo. Only apply changes needed for data integrity and critical taxonomy.

    ADD content_key TO INSERT:
    - Add `import hashlib, uuid` at the top (if not present)
    - In _INSERT_FEATURE_VECTORS_SQL: add feature_vector_id as the first column, add %s as first param
    - In _vector_to_params(): add feature_vector_id computation as first element of returned tuple:
        bar_ts_ns = str(int(bar_ts.timestamp() * 1_000_000_000))
        raw = hashlib.sha256(
            f"{symbol}|{tf}|{bar_ts_ns}|{pipeline_version}".encode()
        ).hexdigest()[:32]
        feature_vector_id = uuid.UUID(raw)
      Return (feature_vector_id, symbol, tf, ...) — feature_vector_id first to match INSERT column order

    FIX CRITICAL LOG EVENT NAME:
    - "d06_gate_candidates_below_80pct" → "coverage_below_threshold"
      Add threshold=coverage_gate to the structlog call payload

    RENAME coverage_gate → coverage_threshold:
    - All occurrences in run_compute_stage(), _log_coverage_report(), main()
    - The APR key read: cfg.get_sync("threshold.backfill.coverage_gate", 0.80)
      → cfg.get_sync("threshold.backfill.coverage_threshold", 0.80)
      (APR key rename is a follow-on migration; use new key name with same fallback)

    RENAME _TARGET_TFS → _TARGET_TIMEFRAMES:
    - Module-level constant and all references

    FIX COMMENT:
    - "regime=None,  # Regime label assigned by HMM downstream (Phase 138)"
    → "regime=None,  # populated by regime_writer after batch compute completes"

    DO NOT fix: two-stage split, run_fetch_stage/run_compute_stage naming, _STORE_OHLCV_SQL,
    _vector_to_params rename — those are in the follow-on todo and require more structural changes.
  </action>
  <acceptance_criteria>
    - `grep -c "feature_vector_id" services/backfill_feature_factory.py` returns >= 3
    - `grep "d06_gate_candidates_below_80pct" services/backfill_feature_factory.py` returns empty
    - `grep "_TARGET_TFS" services/backfill_feature_factory.py` returns empty
    - `grep "Phase 138" services/backfill_feature_factory.py` returns empty
    - `grep "coverage_gate" services/backfill_feature_factory.py` returns empty
    - `python -c "import services.backfill_feature_factory; print('ok')"` exits 0
  </acceptance_criteria>
  <done>backfill INSERT includes feature_vector_id; coverage_gate renamed; taxonomy fixed.</done>
</task>

<task type="auto">
  <name>Task 5: Update P1 migration numbers + run unit tests</name>
  <files>.planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md, tests/unit/</files>
  <read_first>
    - .planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md (migration numbers to shift)
  </read_first>
  <action>
    Migration 158 is now used by feature_vector_id. Shift P1 migration numbers:
    - All references to "157_ic_engine_tables.sql" → "159_ic_engine_tables.sql"
    - All references to "158_alpha_ic_apr_keys.sql" → "160_alpha_ic_apr_keys.sql"
    - Rename the actual migration files:
        production/migrations/157_ic_engine_tables.sql → 159_ic_engine_tables.sql
        production/migrations/158_alpha_ic_apr_keys.sql → 160_alpha_ic_apr_keys.sql
      (these files may not exist yet — if they don't, just update P1 plan references)

    Run unit tests:
    .venv/bin/pytest tests/unit/ -q

    Any test failures from the FeatureVectorWriter rename or column count changes must be fixed
    before this task is marked done. The test suite must be GREEN.
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/ -q` exits 0 — all tests green
    - `grep "157_ic_engine\|158_alpha_ic" .planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md` returns empty
    - `grep "159_ic_engine\|160_alpha_ic" .planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md` shows entries
  </acceptance_criteria>
  <done>P1 migration numbers updated to 159/160; pytest green.</done>
</task>

</tasks>

<verification>
- feature_vector_id UUID column exists in feature_vectors table
- Both write paths (FeatureVectorWriter + backfill) populate feature_vector_id on every INSERT
- services/feature_writer.py deleted; services/feature_vector_writer.py exists with FeatureVectorWriter class
- No hardcoded DSN in codebase: grep -r "postgres:postgres@localhost" services/ returns empty
- Log event taxonomy: grep "Health check\|Feature Writer Agent" services/ returns empty
- pytest tests/unit/ -q GREEN
</verification>

<success_criteria>
- All five task acceptance criteria pass
- Both INSERT statements verified to include feature_vector_id via grep
- pytest tests/unit/ -q exits 0
- Council review gaps from 2026-06-22 closed: content_key, DSN, naming, log taxonomy, dead code
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-00-SUMMARY.md`
documenting: migration 158 applied, feature_vector_id column confirmed, both write paths
verified to populate it, FeatureVectorWriter rename complete, test suite green, P1 migration
numbers updated to 159/160.
</output>
