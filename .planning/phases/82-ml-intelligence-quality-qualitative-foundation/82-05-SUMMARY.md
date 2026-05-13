---
phase: 82-ml-intelligence-quality-qualitative-foundation
plan: "05"
subsystem: feature-validation
tags: [feature-validation, shadow-governance, ic-pvalue, timescaledb, fastapi, prometheus]
dependency_graph:
  requires: [82-02, tools/validate_i6_backtest.py, shadow_registry table (077)]
  provides: [validation_results hypertable, shadow_registry.promotion_evidence, GET /api/validation/results]
  affects: [Phase 75 ShadowAuditorAgent governance contract seeded, FeatureValidationComputeAgent daily decisions]
tech_stack:
  added: []
  patterns: [asyncpg parameter binding for JSONB, systemd oneshot timer, FastAPI read-only router with input validation]
key_files:
  created:
    - production/migrations/086_validation_results.sql
    - src/intelligence/services/feature_validation_compute_agent.py
    - services/feature_validation_agent.py
    - production/systemd/indicagent-feature-validation.service
    - production/systemd/indicagent-feature-validation.timer
    - src/api/routes/validation.py
    - tests/unit/test_feature_validation_compute_agent.py
  modified:
    - src/observability/metrics.py
    - src/api/main.py
decisions:
  - "Computation/governance separation enforced: FeatureValidationComputeAgent produces evidence (VALIDATED/TWEAK/KILL) only; Phase 75 ShadowAuditorAgent acts on it"
  - "JSONB promotion_evidence passed as dict to asyncpg — never json.dumps per CLAUDE.md rule"
  - "Timer uses 07:00 UTC (02:00 ET equivalent) for maximum systemd compatibility"
  - "plugin_name API param validated against ^[A-Za-z0-9_\\-]{1,128}$ regex (ASVS L1)"
  - "Individual slice failures caught + logged in try/except — full run never crashes (oneshot exit 0)"
metrics:
  duration_minutes: 22
  completed: "2026-05-13"
  tasks_completed: 3
  tasks_total: 3
  files_created: 7
  files_modified: 2
  tests_added: 6
  tests_passing: 6
---

# Phase 82 Plan 05: FeatureValidationService Summary

Daily IC/p-value computation agent writing VALIDATED/TWEAK/KILL decisions to a `validation_results` hypertable and seeding `shadow_registry.promotion_evidence` as the Phase 75 governance contract.

## What Was Built

### Migration 086 (`production/migrations/086_validation_results.sql`)

Idempotent DDL (all statements use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`):

- `CREATE TABLE IF NOT EXISTS validation_results` — columns: `plugin_name TEXT NOT NULL`, `timeframe TEXT NOT NULL`, `regime_type TEXT` (NULL = global slice), `ic DOUBLE PRECISION`, `p_value DOUBLE PRECISION`, `n INTEGER`, `decision TEXT CHECK (decision IN ('VALIDATED','TWEAK','KILL'))`, `bonferroni_corrected BOOLEAN DEFAULT TRUE`, `computed_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `SELECT create_hypertable('validation_results', 'computed_at', if_not_exists => TRUE)` — daily partitioning
- `CREATE INDEX IF NOT EXISTS validation_results_plugin_tf_idx ON validation_results (plugin_name, timeframe, computed_at DESC)` — covering index for primary API query
- `ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB` — Phase 75 contract seed

### FeatureValidationComputeAgent (`src/intelligence/services/feature_validation_compute_agent.py`)

Daily compute agent with clean separation from governance:

- `run()`: queries `shadow_registry` for all `i7_plugin` components, iterates (plugin, tf ∈ {1m,5m,15m,1h}, regime_type ∈ {None, trending, ranging, volatile}) slices
- Skips slices with `n < 30` (insufficient data gate)
- Calls `validate_backtest_results(df, field_name=plugin_name, min_ic=0.05, alpha=0.01, min_n=30)` from `tools.validate_i6_backtest`
- Decision thresholds (delegated to validate_i6_backtest.py): IC > 0.05 AND p < 0.01 (Bonferroni-corrected) AND N ≥ 30 = VALIDATED; IC 0.02–0.05 = TWEAK; IC < 0.02 = KILL
- Inserts one row into `validation_results` via asyncpg parameter binding (no f-string interpolation)
- Updates `shadow_registry.promotion_evidence` with `{decision, ic, p_value, n, timeframe, regime_type, computed_at}` as a Python dict (never `json.dumps` — asyncpg handles JSONB serialisation)
- Increments `FEATURE_VALIDATION_DECISIONS_TOTAL.labels(decision=...)` per slice written
- Individual slice failures caught in `try/except` — logged and skipped; full run completes

### Oneshot Entrypoint + Systemd

- `services/feature_validation_agent.py`: mirrors `ml_training_agent.py` — `asyncio.run(agent.start())`
- `production/systemd/indicagent-feature-validation.service`: `Type=oneshot`, `Restart=no`
- `production/systemd/indicagent-feature-validation.timer`: `OnCalendar=*-*-* 07:00:00 UTC` (02:00 ET equivalent), `Persistent=true`

### API Route (`src/api/routes/validation.py`)

Read-only FastAPI router registered at `/api/validation`:

- `GET /results`: query params `plugin_name: str | None` (validated against `^[A-Za-z0-9_\-]{1,128}$`), `limit: int = Query(default=50, ge=1, le=500)`
- SQL uses `($1::text IS NULL OR plugin_name = $1)` pattern — no string interpolation of user input
- No POST/PUT/DELETE routes — decisions are produced exclusively by the compute agent

### Metrics (`src/observability/metrics.py`)

```python
FEATURE_VALIDATION_DECISIONS_TOTAL = Counter(
    "feature_validation_decisions_total",
    "Total validation decisions written to validation_results per decision label.",
    ["decision"],
)
```

## Test Coverage (6 tests, all passing)

| Test | What It Covers |
|------|----------------|
| `test_skips_slices_below_n_threshold` | n=10 → no validate call, no INSERT |
| `test_validated_decision_writes_row_and_evidence` | IC=0.10, p=0.001, n=100 → VALIDATED INSERT + shadow_registry UPDATE with dict evidence |
| `test_tweak_and_kill_paths` | TWEAK/KILL decision INSERT params verified |
| `test_decision_check_constraint_values` | All three CHECK constraint values exercised |
| `test_metrics_counter_increments_per_decision` | `FEATURE_VALIDATION_DECISIONS_TOTAL.labels(decision=...).inc()` called per slice |
| `test_individual_slice_failure_does_not_crash_run` | plugin_b raises → plugin_a and plugin_c still produce results |

## Governance Architecture

```
FeatureValidationComputeAgent (this phase)
    ↓ writes VALIDATED/TWEAK/KILL evidence
validation_results hypertable
shadow_registry.promotion_evidence
    ↓ read by (Phase 75)
ShadowAuditorAgent → executes promotion/demotion
```

This phase produces *evidence*. Phase 75 *acts* on it. Zero governance logic in this agent.

## Commits

| Hash | Task | Description |
|------|------|-------------|
| e65bd08d | Task 1 | Migration 086 — validation_results hypertable + shadow_registry.promotion_evidence |
| 2f2e411a | Task 2 | FeatureValidationComputeAgent + oneshot entrypoint + systemd timer + metrics |
| 9ceec85a | Task 3 | GET /api/validation/results endpoint + 6 unit tests |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

Files created/modified:
- [x] `production/migrations/086_validation_results.sql` — exists
- [x] `src/intelligence/services/feature_validation_compute_agent.py` — exists, imports clean
- [x] `services/feature_validation_agent.py` — exists
- [x] `production/systemd/indicagent-feature-validation.service` — exists, Type=oneshot
- [x] `production/systemd/indicagent-feature-validation.timer` — exists, 07:00 UTC
- [x] `src/api/routes/validation.py` — exists, `/api/validation/results` registered
- [x] `tests/unit/test_feature_validation_compute_agent.py` — 6/6 passing

Commits:
- [x] e65bd08d — verified in git log
- [x] 2f2e411a — verified in git log
- [x] 9ceec85a — verified in git log

## Self-Check: PASSED
