---
phase: 125-apr-full-migration-all-three-tiers
plan: A
type: execute
wave: 1
depends_on: []
files_modified:
  - production/migrations/132_phase125_param_store.sql
autonomous: true
requirements:
  - APR-01
  - APR-02

must_haves:
  truths:
    - "All 10 new APR keys exist in config_schema, config_state, and config_history after migration"
    - "migration is idempotent: running it twice produces no error and no duplicate rows"
    - "min_zone_width_atr keys are distinct from the existing min_width_atr key (0.25)"
    - "ConfigService.get_sync for all 10 new keys returns expected defaults without error after migration runs"
  artifacts:
    - path: "production/migrations/132_phase125_param_store.sql"
      provides: "Triple-insert for 10 new config keys"
      contains: "threshold.cis.fire_threshold"
  key_links:
    - from: "production/migrations/132_phase125_param_store.sql"
      to: "config_state table"
      via: "psql migration apply"
      pattern: "ON CONFLICT \\(config_key\\) DO NOTHING"
---

<objective>
Seed all 10 new APR keys required by Phase 125 into the database via migration 132.

Purpose: Establish the DB records that Plans B, D, and E will read via ConfigService.get_sync(). Phase 126 also depends on the 4 zone-width keys existing before it wires the consumption code. Nothing reads these keys yet — migration only, zero behavior change.
Output: production/migrations/132_phase125_param_store.sql, applied to the live DB.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-CONTEXT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Write migration 132 with 10 new APR keys</name>
  <read_first>
    - production/migrations/129_plugin_param_store.sql (canonical triple-insert format — replicate exactly)
    - production/migrations/131_phase124_param_store.sql (most recent migration — verify 132 is next)
  </read_first>
  <files>production/migrations/132_phase125_param_store.sql</files>
  <action>
    Create production/migrations/132_phase125_param_store.sql using the triple-insert pattern from migration 129 exactly. Each of the 10 keys gets: (1) INSERT into config_schema with ON CONFLICT (config_key) DO NOTHING, (2) INSERT into config_state with ON CONFLICT (config_key) DO NOTHING, (3) INSERT into config_history.

    The 10 keys are:

    CIS gate constants (3 keys) — provenance [initial_estimate], ML learning targets:
      threshold.cis.fire_threshold | float | 0.35 | min 0.0, max 1.0
      threshold.cis.bucket_agree_min | int | 3 | min 1, max 6
      threshold.cis.bucket_noise_floor | float | 0.1 | min 0.0, max 1.0

    Zone entry width gate (4 keys) — provenance [rca_analysis], Phase 126 contract:
      feature.zone_engine.min_zone_width_atr | float | 1.5 | min 0.0, max 10.0
      feature.zone_engine.min_zone_width_atr.equity_etf | float | 1.5 | min 0.0, max 10.0
      feature.zone_engine.min_zone_width_atr.forex | float | 1.0 | min 0.0, max 10.0
      feature.zone_engine.min_zone_width_atr.futures | float | 1.5 | min 0.0, max 10.0

    AnchoredVWAPReversion weights (3 keys) — provenance [initial_estimate], ML learning targets:
      weights.vwap_reversion.sigma_magnitude | float | 0.40 | min 0.0, max 1.0
      weights.vwap_reversion.hurst_quality | float | 0.35 | min 0.0, max 1.0
      weights.vwap_reversion.vol_stability | float | 0.25 | min 0.0, max 1.0

    Description field conventions (from docs/foundation/parameter-store.md):
      - CIS keys: "[initial_estimate] <description>. ML learning target."
      - Zone keys: "[rca_analysis] Phase 126 zone entry width gate for <asset class>. Noise-band analysis. Not a learning target until Phase 126 consumption code ships."
      - VWAP weight keys: "[initial_estimate] <factor> weight in AnchoredVWAPReversionPlugin. ML learning target."

    config_history rows: changed_by = 'migration_132', reason = 'Phase 125 APR seed: <cluster name>'

    DO NOT modify or reference feature.zone_engine.min_width_atr (already seeded at 0.25 in migration 129 — different key, different purpose).
  </action>
  <verify>
    Apply migration: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/132_phase125_param_store.sql

    Verify all 10 keys in config_state:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'threshold.cis.%' OR config_key LIKE 'feature.zone_engine.min_zone_width_atr%' OR config_key LIKE 'weights.vwap_reversion.%' ORDER BY config_key;"

    Expected: 10 rows returned with correct values (0.35, 3, 0.1, 1.5, 1.5, 1.0, 1.5, 0.40, 0.35, 0.25).

    Verify idempotency:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/132_phase125_param_store.sql
    (No error, row count unchanged for config_state)

    Verify min_width_atr unchanged:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key = 'feature.zone_engine.min_width_atr';"
    Expected: 1 row, value = 0.25

    Verify ConfigService.get_sync returns defaults for all 10 keys (confirms DB load chain is wired):
    .venv/bin/python -c "
    from src.config.config_service import ConfigService
    import asyncio
    async def check():
        cs = ConfigService()
        await cs.initialize()
        keys = [
            ('threshold.cis.fire_threshold', 0.35),
            ('threshold.cis.bucket_agree_min', 3),
            ('threshold.cis.bucket_noise_floor', 0.1),
            ('feature.zone_engine.min_zone_width_atr', 1.5),
            ('feature.zone_engine.min_zone_width_atr.equity_etf', 1.5),
            ('feature.zone_engine.min_zone_width_atr.forex', 1.0),
            ('feature.zone_engine.min_zone_width_atr.futures', 1.5),
            ('weights.vwap_reversion.sigma_magnitude', 0.40),
            ('weights.vwap_reversion.hurst_quality', 0.35),
            ('weights.vwap_reversion.vol_stability', 0.25),
        ]
        for key, default in keys:
            val = cs.get_sync(key, default)
            print(f'{key}: {val}')
        await cs.close()
    asyncio.run(check())
    "
    Expected: all 10 keys print without error
  </verify>
  <done>10 rows exist in config_state with the exact keys and values specified above. The existing min_width_atr row is unmodified. Running the migration a second time produces no error and no duplicate rows. ConfigService.get_sync returns expected values for all 10 keys without error.</done>
</task>

</tasks>

<verification>
SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'threshold.cis.%' OR config_key LIKE 'feature.zone_engine.min_zone_width_atr%' OR config_key LIKE 'weights.vwap_reversion.%';
Expected result: 10

SELECT COUNT(*) FROM config_history WHERE changed_by = 'migration_132';
Expected result: 10
</verification>

<success_criteria>
migration 132 applied cleanly. 10 new config keys exist in config_state with correct values. Idempotency verified. Existing keys untouched. ConfigService.get_sync returns expected defaults for all 10 keys.
</success_criteria>

<output>
After completion, create .planning/phases/125-apr-full-migration-all-three-tiers/125-A-SUMMARY.md
</output>
