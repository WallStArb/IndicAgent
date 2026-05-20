---
plan: 092-01
phase: 092-signal-quality-completeness
status: complete
completed_at: 2026-05-20
---

# Plan 092-01 Summary: Schema and Compute Primitives

## What Was Built

Established all schema and compute primitives required for distribution-shape metrics and per-entry_type segmentation. Five tasks shipped across four atomic commits.

## Schema Changes

`signal_metrics` table gains seven new columns via idempotent `_ensure_schema()` startup migration:
- `entry_type text NOT NULL DEFAULT '*'`
- `skewness float`, `kurtosis float`, `min_r float`, `p5_r float`, `recovery_factor float`, `cvar_5 float`

Primary key rebuilt to `(track, setup_plugin, tf, regime_type, window_days, symbol, entry_type)`.
PK rebuild is guarded by `information_schema.key_column_usage` check and wrapped in `async with conn.transaction()` with `SET LOCAL statement_timeout = '30s'` per REVIEWS.md Gemini concern.

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/schemas.py` | `MetricsComputedEvent` gains `entry_type: str = "*"` and six optional float distribution fields |
| `src/intelligence/metrics/compute.py` | `DistributionShape` dataclass, `_distribution_shape()` pure helper, `SignalMetricsResult` + `_build_metrics_result()` extended with entry_type and 6 new fields |
| `services/signal_metrics_writer_agent.py` | `_ensure_schema()` coroutine, updated INSERT column list and ON CONFLICT target for new PK |
| `tests/unit/intelligence/test_metrics_compute.py` | `TestDistributionShape` — 8 tests covering all N boundary conditions |

## Consumer Query Guards

All `FROM signal_metrics` queries already carry `AND entry_type = '*'` guards:
- `src/intelligence/pipeline/cache_manager.py` — 4 queries, all pre-guarded (from Phase 091)
- `src/api/routes/signals.py` — 2 queries, both pre-guarded (from Phase 091)
- `src/intelligence/setup_performance_updater.py` — now queries `setup_performance` table, not `signal_metrics`; no guard needed

## Key Implementation Details

- **`recovery_factor` guard uses strict `p5 < -1e-9`** (not `abs(p5) > 1e-9`) per CONTEXT.md D-01. Positive or near-zero p5 means no tail loss exists; ratio is undefined in that case.
- **N thresholds**: skewness/kurtosis at n≥3, p5/cvar_5/recovery_factor at n≥20, min_r at n≥30.
- **`extra="forbid"` preserved** on MetricsComputedEvent — new fields are optional with defaults, so existing emitter paths remain backward-compatible.

## Test Results

- `TestDistributionShape`: 8/8 passed
- Full `test_metrics_compute.py` suite: 32/32 passed
- `test_signal_metrics_writer_agent.py`: 7/7 passed
- Ruff: clean on all modified files

## Deviations from CONTEXT.md

None. All decisions (strict `<` guard, N thresholds, PK columns, nullable float pattern) match CONTEXT.md D-01/D-11 and REVIEWS.md.

## Plan 02 Readiness

Plan 02 can safely proceed:
- `MetricsComputedEvent` accepts `entry_type` without DLQ rejection
- ON CONFLICT target matches the new 7-column PK
- All three consumer queries reject per-entry_type rows (guard in place)
- `_build_metrics_result(entry_type=et)` signature ready for per-entry_type invocation
