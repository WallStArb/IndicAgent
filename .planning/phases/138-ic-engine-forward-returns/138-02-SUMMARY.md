---
phase: 138-ic-engine-forward-returns
plan: "02"
subsystem: database
tags: [asyncpg, timescaledb, apr, config-service, service-auditor, ic-engine, batch-compute]

# Dependency graph
requires:
  - phase: 138-01
    provides: foundation hardening — BaseBatch was planned here but moved to P2; migration numbering resolved

provides:
  - BaseBatch abstract base class at src/core/agent/base_batch.py
  - forward_returns TimescaleDB hypertable (migration 160)
  - feature_ic_scores table with is_pooled column and two partial unique indexes (migration 160)
  - alpha.ic.* and alpha.decay.* APR keys seeded in config_schema + config_state (migration 161)
  - indicagent-regime-writer, indicagent-forward-return-writer, indicagent-ic-engine registered in both _DAG_ORDER and _ONESHOT_UNITS

affects:
  - 138-03 (backfill run — no file conflicts; P3 is DB-only)
  - 138-04 (ForwardReturnWriter extends BaseBatch)
  - 138-05 (ICEngine extends BaseBatch, reads alpha.ic.* APR keys, writes feature_ic_scores)
  - 138-06 (AlphaDecayMonitor reads alpha.decay.* keys)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BaseBatch template method: _setup_pool → execute() → _emit_completion → _teardown_pool"
    - "content_key() staticmethod: SHA-256 32-char hex for app-layer dedup (mirrors signal_schema.make_signal_id)"
    - "is_pooled BOOLEAN flag instead of NULL-overloading for ON CONFLICT target disambiguation in feature_ic_scores"
    - "Two separate partial unique indexes (pooled_uq + regime_uq) vs single NULL-tolerant index"

key-files:
  created:
    - src/core/agent/base_batch.py
    - production/migrations/160_ic_engine_tables.sql
    - production/migrations/161_alpha_ic_apr_keys.sql
  modified:
    - services/service_auditor.py

key-decisions:
  - "is_pooled BOOLEAN (NOT NULL DEFAULT false) on feature_ic_scores instead of relying on NULL regime — Postgres treats two rows with regime IS NULL as distinct in the PK, so NULL overloading cannot serve as a dedup key for pooled rows"
  - "Two partial unique indexes (pooled_uq, regime_uq) rather than a single index — enables precise ON CONFLICT targeting without ambiguity"
  - "TF-specific bootstrap block sizes (5m=78, 15m=26, 1h=10, 1d=10) per Hall & Horowitz O(N^(1/3)) guideline — APR-backed so empirical optimal block length can be updated without code change"
  - "alpha. was already in OPS_PREFIXES from Phase 137 P1 — no change needed"
  - "alpha.ic.subsample_min_stride=5: actual stride=max(5, lookahead_bars) so non-overlapping independence is preserved for all lookaheads including the 20-bar and 60-bar windows"
  - "Three IC oneshots registered in BOTH _DAG_ORDER and _ONESHOT_UNITS — _DAG_ORDER alone is insufficient; the auditor's _evaluate_service_dynamic() only skips dead-daemon detection for units in _ONESHOT_UNITS"

patterns-established:
  - "BaseBatch subclass contract: define job_name + compute_version class attrs + async execute(pool)"
  - "D-06 oneshot: always call flush_and_shutdown_metrics() in run() finally block to drain OTLP"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-06-22
---

# Phase 138 Plan 02: IC Engine Foundation Summary

**BaseBatch base class + forward_returns hypertable + feature_ic_scores with is_pooled flag + 16 alpha.ic/decay APR keys seeded; three IC oneshots registered in service_auditor**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-22T14:44:00Z
- **Completed:** 2026-06-22T14:52:00Z
- **Tasks:** 3
- **Files modified:** 4 (1 created Python, 2 created SQL, 1 modified Python)

## Accomplishments

- Built BaseBatch abstract base class (Ring 0 clean) with template run(), content_key() SHA-256, D-06 emission, and asyncpg pool lifecycle
- Created forward_returns as a TimescaleDB hypertable (3-month chunks, PK on symbol/tf/bar_ts) with executable log return columns and has_gap_before_entry flag
- Created feature_ic_scores with explicit is_pooled BOOLEAN column and two separate partial unique indexes (pooled_uq + regime_uq) solving the ON CONFLICT NULL ambiguity problem
- Seeded all 16 alpha.ic.* and alpha.decay.* APR keys including TF-specific bootstrap block sizes (5m=78, 15m=26, 1h=10, 1d=10)
- Registered three IC oneshots in both _DAG_ORDER (priority 8) and _ONESHOT_UNITS so the service auditor does not misidentify idle batch services as dead daemons

## Task Commits

1. **Task 0: Build BaseBatch base class** - `143a068c` (feat)
2. **Task 1: Migration 160 — forward_returns + feature_ic_scores** - `5a465552` (feat)
3. **Task 2: Migration 161 — APR keys + OPS_PREFIXES + service_auditor** - `bee8b0ec` (feat)

## Files Created/Modified

- `src/core/agent/base_batch.py` - Abstract base for Phase 138+ batch compute oneshots; run() template, content_key() SHA-256, D-06 emission, asyncpg pool lifecycle
- `production/migrations/160_ic_engine_tables.sql` - forward_returns hypertable + feature_ic_scores DDL; is_pooled flag, pooled_uq + regime_uq partial unique indexes
- `production/migrations/161_alpha_ic_apr_keys.sql` - 16 alpha.ic.* and alpha.decay.* APR keys seeded in config_schema + config_state
- `services/service_auditor.py` - Added indicagent-regime-writer, indicagent-forward-return-writer, indicagent-ic-engine to both _DAG_ORDER (priority 8) and _ONESHOT_UNITS

## APR Keys Seeded

| Key | Value | Provenance |
|-----|-------|------------|
| alpha.ic.min_observations | 500 | [rca_analysis] |
| alpha.ic.bootstrap_resamples | 2000 | [conventional] |
| alpha.ic.bootstrap_block_size.5m | 78 | [initial_estimate] |
| alpha.ic.bootstrap_block_size.15m | 26 | [initial_estimate] |
| alpha.ic.bootstrap_block_size.1h | 10 | [conventional] |
| alpha.ic.bootstrap_block_size.1d | 10 | [conventional] |
| alpha.ic.fdr_alpha | 0.05 | [conventional] |
| alpha.ic.walk_forward_folds | 3 | [conventional] |
| alpha.ic.sharpe_window_size | 2000 | [rca_analysis] |
| alpha.ic.sharpe_min_windows | 10 | [conventional] |
| alpha.ic.subsample_min_stride | 5 | [conventional] |
| alpha.ic.min_reliable_n | 100 | [conventional] |
| alpha.decay.ci_lower_threshold | 0.0 | [conventional] |
| alpha.decay.materiality_threshold | 0.005 | [initial_estimate] |
| alpha.decay.regime_shift_fraction | 0.60 | [initial_estimate] |
| alpha.decay.recovery_min_observations | 2000 | [rca_analysis] |

## Decisions Made

- **is_pooled BOOLEAN not NULL-overloading:** Postgres treats two rows with regime IS NULL as distinct in the PK — ON CONFLICT would silently insert duplicate pooled rows rather than updating. Explicit is_pooled=true flag enables precise partial unique index targeting.
- **Two partial unique indexes:** pooled_uq (WHERE is_pooled=true) and regime_uq (WHERE is_pooled=false AND regime IS NOT NULL). Separate indexes because the conflict columns differ between pooled and regime-stratified rows.
- **alpha. already in OPS_PREFIXES:** Added in Phase 137 P1. No change to config_service.py needed; confirmed and documented.
- **subsample_min_stride semantics:** stride = max(subsample_min_stride, lookahead_bars) — ensures independence for all lookahead windows, not just the fast ones. Fixed stride of 5 on 20-bar lookahead produces overlapping returns.

## Deviations from Plan

None - plan executed exactly as written. The `alpha.` prefix was already in OPS_PREFIXES (anticipated in the plan as a check, not a change).

## Issues Encountered

- Pre-commit hook required `.venv/bin/ruff` and `.venv/bin/black` relative to worktree root. Created a symlink from worktree `.venv` -> main repo `.venv` to resolve. Ruff fixed one unused import (`asyncio`) in base_batch.py.

## Next Phase Readiness

- P3 (backfill run) is already underway in a parallel worktree — no dependencies on P2 files, only DB
- P4 (ForwardReturnWriter) can inherit BaseBatch and use forward_returns table immediately
- P5 (ICEngine) can inherit BaseBatch, read alpha.ic.* APR keys via ConfigService.get_sync(), and write to feature_ic_scores using the pooled_uq/regime_uq indexes for ON CONFLICT upserts
- Service auditor will correctly classify all three IC oneshots as inactive-between-runs rather than dead daemons

---
*Phase: 138-ic-engine-forward-returns*
*Completed: 2026-06-22*
