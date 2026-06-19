---
phase: 120-shadow-mode-validation
plan: "01"
subsystem: shadow-governance
tags:
  - shadow-mode
  - promotion-gate
  - otel-metrics
  - db-migration
  - weekly-oneshot
dependency_graph:
  requires:
    - shadow_registry table (pre-existing)
    - signal_ledger + signal_outcomes tables (Phase 095)
    - signal_ledger_full view (Phase 095)
    - shadow_tracking_start_ts column (Phase 119)
    - KafkaProducerClient (src/core/kafka_utils.py)
    - topic_alert_requests (src/core/stream_keys.py)
  provides:
    - services/shadow_validator.py (weekly 5-gate promotion validator)
    - production/migrations/121_signal_ledger_shadow_view.sql (signal_ledger_shadow view)
    - 6 shadow_validation_* OTel point gauges in metrics.py
  affects:
    - shadow_registry (writes is_shadow=FALSE on promotion)
    - shadow_transition_log (audit trail INSERT on promotion)
    - Grafana (6 new gauges observable per-setup)
tech_stack:
  added:
    - scipy.stats.binomtest (already in requirements.txt; now used for promotion gate)
  patterns:
    - oneshot-script (asyncio.run + JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics)
    - asyncpg connection pool (create_db_pool)
    - sequential-gate short-circuit (cheapest gate first)
key_files:
  created:
    - services/shadow_validator.py
    - production/migrations/121_signal_ledger_shadow_view.sql
  modified:
    - src/observability/metrics.py
decisions:
  - "5-gate check uses pnl_r-based metrics only (not was_selected — structurally always False for shadow signals)"
  - "Migration numbered 121 because 120_signal_probe_results.sql already deployed"
  - "Kafka alert is fail-open: DB promotion write never rolled back on Kafka unavailability"
  - "shadow_transition_log column mapping: ci_lower=calibration_corr, win_rate=win_rate (schema reuse per D-05)"
metrics:
  duration: "208 seconds"
  completed_date: "2026-06-10"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 1
---

# Phase 120 Plan 01: Shadow Validator Summary

**One-liner:** Weekly 5-gate statistical promotion validator (scipy binomtest + calibration correlation) with per-setup OTel gauges and signal_ledger_shadow DB view.

## What Was Built

Three artifacts that complete the shadow promotion pipeline for the 22 refactored I7 setups (5 from Phase 118, 17 from Phase 119):

**1. `services/shadow_validator.py`** — weekly oneshot script (313 lines)
- `_SHADOW_VALIDATION_SETUPS` frozenset of 22 verified plugin names with `assert len == 22`
- `_check_promotion_criteria(n_resolved, wins, avg_pnl_r, calibration_corr)` — pure 5-gate function, sequential short-circuit, returns `(bool, reason, detail)`
- Per-setup DB query using parameterized `$1` placeholder, filters `shadow_tracking_start_ts IS NOT NULL` to exclude pre-refactor signals
- Promotion write: `UPDATE shadow_registry SET is_shadow=FALSE ... WHERE component_name=$2 AND is_shadow=TRUE` (concurrent safety guard) + `INSERT INTO shadow_transition_log`
- Kafka alert to `topic_alert_requests` on promotion (fail-open: DB write not rolled back if Kafka down)
- 6 OTel gauges emitted for ALL 22 setups every run (including non-promoting ones)
- Entry point follows `shadow_auditor.py` pattern exactly: `JOB_COMPLETED_TOTAL{"job":"shadow-validator"}` + `flush_and_shutdown_metrics()`

**2. `production/migrations/121_signal_ledger_shadow_view.sql`** — view-only migration
- `CREATE VIEW signal_ledger_shadow AS SELECT * FROM signal_ledger_full WHERE is_shadow = true`
- Applied to live DB; returns 15,914 rows
- Numbered 121 because 120_signal_probe_results.sql was already deployed

**3. `src/observability/metrics.py`** — 6 new point gauges
- `SHADOW_VALIDATION_N`, `SHADOW_VALIDATION_WIN_RATE`, `SHADOW_VALIDATION_P_VALUE`
- `SHADOW_VALIDATION_AVG_PNL_R`, `SHADOW_VALIDATION_CALIBRATION`, `SHADOW_VALIDATION_PROMOTED`
- All via `point_gauge()` helper; label key `setup_plugin` applied at `.set()` call sites

## Gate Logic

```
Gate 1: n_resolved >= 100               (sufficient sample)
Gate 2: win_rate = wins/n >= 50%        (positive outcome rate)
Gate 3: binomtest p < 0.05              (statistically significant vs 50% baseline)
Gate 4: avg_pnl_r > 0                   (positive expectancy)
Gate 5: calibration_corr >= 0.3         (cis_score predicts profitable outcomes)
```

Gates short-circuit on first failure. `was_selected` is intentionally excluded — shadow signals are structurally excluded from winner selection, making that field always `False` for shadow signals.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | bd2e015e | feat(120-01): add 6 shadow_validation_* OTel point gauges |
| 2 | 6daae15a | feat(120-01): create migration 121 signal_ledger_shadow view |
| 3 | 542d8206 | feat(120-01): implement shadow_validator.py weekly oneshot 5-gate promotion |

## Verification Results

- All 6 `SHADOW_VALIDATION_*` gauges importable from `src.observability.metrics`
- `signal_ledger_shadow` view live in DB; `SELECT viewname FROM pg_views WHERE viewname='signal_ledger_shadow'` returns one row
- `_check_promotion_criteria` gate assertions all pass (5 parametrized test cases)
- `ruff check` clean on all changed Python files

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

| Artifact | Status |
|----------|--------|
| services/shadow_validator.py | FOUND |
| production/migrations/121_signal_ledger_shadow_view.sql | FOUND |
| src/observability/metrics.py (modified) | FOUND |
| .planning/phases/120-shadow-mode-validation/120-01-SUMMARY.md | FOUND |
| commit bd2e015e (Task 1 gauges) | FOUND |
| commit 6daae15a (Task 2 migration) | FOUND |
| commit 542d8206 (Task 3 validator) | FOUND |
