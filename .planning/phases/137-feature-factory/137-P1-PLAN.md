---
phase: 137-feature-factory
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - src/config/config_service.py
  - production/migrations/155_feature_vectors.sql
autonomous: true
requirements: [SC-1, SC-3, SC-5]

threat_model:
  assets:
    - "feature_vectors hypertable (raw feature measurement layer for IC research)"
    - "config_state APR keys (control plane for feature periods and vector membership)"
  threats:
    - id: T1
      description: "alpha.* APR keys written to config_state but rejected by ConfigService.set() because 'alpha.' is absent from OPS_PREFIXES - orphaned keys readable from DB but not writable, silent control-plane drift"
      severity: medium
      mitigation: "Add 'alpha.' to OPS_PREFIXES in the SAME plan as the migration; acceptance criterion asserts ConfigService accepts an alpha.* key after the change"
    - id: T2
      description: "regime_label_source allows 'smoothed' value, admitting lookahead-biased regime labels into the IC corpus (D-07 causal-correctness violation)"
      severity: high
      mitigation: "CHECK constraint regime_label_source IN ('filtered','unknown') in DDL; acceptance criterion asserts an INSERT with 'smoothed' is rejected by the DB"
  block_on: [T2]

must_haves:
  truths:
    - "feature_vectors hypertable exists with 36 typed columns (35 features + pipeline_version) and no JSONB"
    - "An INSERT into feature_vectors with regime_label_source='smoothed' is rejected by the DB"
    - "All feature.* APR keys and alpha.vector.v1_quant.members exist in config_state"
    - "ConfigService.set() accepts a key starting with 'alpha.'"
  artifacts:
    - path: "production/migrations/155_feature_vectors.sql"
      provides: "feature_vectors + backfill_status DDL + feature.* and alpha.* APR seed inserts"
      contains: "CREATE TABLE IF NOT EXISTS feature_vectors"
    - path: "src/config/config_service.py"
      provides: "alpha. registered as an OPS prefix"
      contains: "\"alpha.\""
  key_links:
    - from: "src/config/config_service.py OPS_PREFIXES"
      to: "config_state alpha.vector.v1_quant.members"
      via: "prefix validation gate in ConfigService.set()"
      pattern: "alpha\\."
---

<objective>
Create the persistence and control-plane foundation for Phase 137: the `feature_vectors` TimescaleDB hypertable (36 typed columns, no JSONB), the `backfill_status` checkpoint table, all `feature.*` APR keys, and the `alpha.vector.v1_quant.members` key. Register the `alpha.` namespace prefix in `ConfigService` so the vector-membership key is writable, not just readable.

Purpose: Every downstream plan (FeatureFactory compute, writer retarget, backfill) depends on this schema and these APR keys existing. The `alpha.` prefix is a one-line blocker that, if missed, silently orphans the vector-membership key.
Output: Migration 155 applied; `feature_vectors` and `backfill_status` exist; `feature.*` + `alpha.vector.v1_quant.members` seeded; `alpha.` in OPS_PREFIXES.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@.planning/phases/137-feature-factory/137-RESEARCH.md
@.planning/phases/137-feature-factory/A-PATTERNS.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Register alpha. prefix in ConfigService OPS_PREFIXES</name>
  <files>src/config/config_service.py</files>
  <read_first>
    - src/config/config_service.py (read OPS_PREFIXES tuple at line ~39 and the set() validation gate at line ~75 - see current state before editing)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (section "src/config/config_service.py" - exact one-line change)
  </read_first>
  <action>
    Add the string literal `"alpha."` to the `OPS_PREFIXES` class-level tuple in `ConfigService`. The tuple already contains `"regime."`, `"swarm."`, `"alert."`, `"ai."`, `"feature."`, `"threshold."`, `"roll."`, `"cross_asset."`, `"macro."`, `"ui."`, `"weights."`. Append `"alpha.",` as a new element. This is a single-line addition - do not refactor the surrounding validation logic. The prefix gate at the `set()` method (`if not any(key.startswith(prefix) for prefix in self.OPS_PREFIXES)`) consumes this tuple; no other change is needed.
  </action>
  <verify>
    .venv/bin/python -c "from src.config.config_service import ConfigService; assert 'alpha.' in ConfigService.OPS_PREFIXES, 'alpha. missing'; print('OK')"
  </verify>
  <acceptance_criteria>
    - `src/config/config_service.py` OPS_PREFIXES tuple contains the literal `"alpha."`
    - `.venv/bin/python -c "from src.config.config_service import ConfigService; print('alpha.' in ConfigService.OPS_PREFIXES)"` prints `True`
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Write migration 155 - feature_vectors + backfill_status + APR seeds</name>
  <files>production/migrations/155_feature_vectors.sql</files>
  <read_first>
    - production/migrations/153_hmm_garch_kalman_apr.sql (idempotent APR seeding pattern: ON CONFLICT DO NOTHING for config_schema and config_state; this is the exact template)
    - production/migrations/154_instrument_metadata.sql (confirm 155 is the next free number)
    - .planning/phases/137-feature-factory/137-CONTEXT.md (the `<specifics>` section - this is the BINDING 35-column list grouped by cadence; do NOT use any DDL from v30-ground-up-architecture.md which contains extra columns like rsi_fast/cci_fast not in the locked list)
    - .planning/phases/137-feature-factory/137-RESEARCH.md ("Code Examples" - feature_vectors DDL, backfill_status DDL, APR Seeding Migration with exact config_schema/config_state rows)
  </read_first>
  <action>
    Create `production/migrations/155_feature_vectors.sql`, idempotent and safe to re-run. Five sections:

    (1) CREATE TABLE IF NOT EXISTS feature_vectors with these columns: `symbol text NOT NULL`, `tf text NOT NULL`, `bar_ts timestamptz NOT NULL`, `pipeline_version text NOT NULL`, `regime text`, `regime_label_source text NOT NULL DEFAULT 'filtered' CHECK (regime_label_source IN ('filtered','unknown'))`, then the 35 feature columns all typed `double precision` grouped exactly per 137-CONTEXT.md `<specifics>`: Bar-level (14): momentum_z_5, momentum_z_20, range_position, bar_close_pos, gap_z, informed_flow, volume_z, ofi_z, cvd_slope_z, cmf, rel_volume, vwap_dev_sigma, atr_z, vol_ratio. Session-level (4): poc_dist_atr, va_position, sr_support_dist, sr_resist_dist. Regime-level (7): hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio, hma_slope_z, adx. Cross-asset (3): vix_z, flight_quality, yield_slope_z. Calendar (5): in_ny_session, in_overlap, dow_sin, dow_cos, month_position. Cross-timeframe (3): ctf_momentum, ctf_vwap_align, ctf_regime_align. PRIMARY KEY (symbol, tf, bar_ts). No JSONB columns. Then `SELECT create_hypertable('feature_vectors','bar_ts', chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE);` and `SELECT add_compression_policy('feature_vectors', INTERVAL '6 months', if_not_exists => TRUE);`

    (2) CREATE TABLE IF NOT EXISTS backfill_status with: symbol text NOT NULL, tf text NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','complete','failed')), rows_written bigint, theoretical_max bigint, started_at timestamptz, completed_at timestamptz, error_msg text, PRIMARY KEY (symbol, tf).

    (3) INSERT INTO config_schema the 16 feature.* keys (value_type, default_value, description with [conventional]/[initial_estimate] provenance) per 137-RESEARCH.md APR Seeding Migration: feature.momentum.window_short=5, feature.momentum.window_long=20, feature.momentum.zscore_window=252, feature.volume.zscore_window=20, feature.ofi.zscore_window=20, feature.cvd.slope_bars=5, feature.cmf.period=20, feature.vol.short_bars=5, feature.vol.long_bars=20, feature.hma.period=20, feature.adx.period=14, feature.hurst.window=252, feature.garch.window=100, feature.vix.zscore_window=252, feature.yield_curve.zscore_window=252, feature.regime.cache_refresh_bars=30. ON CONFLICT (config_key) DO NOTHING.

    (4) INSERT INTO config_state the same 16 keys with config_value = default and version = 1. ON CONFLICT (config_key) DO NOTHING.

    (5) INSERT INTO config_schema and config_state the key `alpha.vector.v1_quant.members` value_type 'str', value = `momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum`, version 1, description `[initial_estimate] V1 Quant vector constituent primitives. Mutable via APR. IC discovery may prune members.`. ON CONFLICT (config_key) DO NOTHING.

    Match the exact column names of config_schema/config_state used by migration 153 (read it first - confirm whether the columns are config_key/value_type/default_value/description for config_schema and config_key/config_value/version for config_state).
  </action>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/155_feature_vectors.sql && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_vectors"
  </verify>
  <acceptance_criteria>
    - Running the migration twice in a row both exit 0 (idempotent)
    - `SELECT count(*) FROM information_schema.columns WHERE table_name='feature_vectors'` returns 41 (6 meta + 35 feature columns)
    - `SELECT data_type FROM information_schema.columns WHERE table_name='feature_vectors' AND data_type='jsonb'` returns 0 rows
    - `SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='feature_vectors'` returns 1
    - `INSERT INTO feature_vectors (symbol,tf,bar_ts,pipeline_version,regime_label_source) VALUES ('TEST','5m',now(),'3.0.0','smoothed')` fails with a CHECK constraint violation
    - `SELECT count(*) FROM config_state WHERE config_key LIKE 'feature.%'` returns >= 16
    - `SELECT config_value FROM config_state WHERE config_key='alpha.vector.v1_quant.members'` returns the 8-member comma list
  </acceptance_criteria>
</task>

</tasks>

<verification>
- Migration 155 applies cleanly and is idempotent (run twice, both succeed)
- feature_vectors has 41 columns, zero JSONB, is a hypertable with 3-month chunks and 6-month compression
- regime_label_source CHECK rejects 'smoothed'
- backfill_status exists with status CHECK
- 16 feature.* keys + alpha.vector.v1_quant.members in config_state
- ConfigService.OPS_PREFIXES contains 'alpha.'
</verification>

<success_criteria>
SC-1 (feature_vectors hypertable with 36 typed columns) satisfied: table exists, typed columns, hypertable.
SC-3 (all feature.* APR keys seeded) satisfied: 16 keys + vector membership in config_state.
SC-5 (regime_label_source='filtered' forward Viterbi only) enforced at DB layer: CHECK constraint admits only 'filtered'/'unknown'.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P1-SUMMARY.md`
</output>
