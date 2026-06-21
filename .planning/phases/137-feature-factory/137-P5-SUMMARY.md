---
phase: 137-feature-factory
plan: 5
subsystem: backfill-oneshot
tags: [backfill, ibkr, feature-vectors, checkpoint, coverage]
dependency_graph:
  requires:
    - feature_vectors hypertable (137-P1)
    - backfill_status checkpoint table (137-P1)
    - FeatureFactory.compute() (137-P3)
    - FeatureCache (137-P3)
    - market_data_ohlcv (TimescaleDB)
  provides:
    - services/backfill_feature_factory.py oneshot
    - Two-stage fetch/compute checkpoint per (symbol, tf)
    - feature_vectors populated (IC research corpus - Phase 138 gate)
    - Per-pair coverage vs theoretical_max (D-06 gate data)
  affects:
    - feature_vectors (writes)
    - backfill_status (writes checkpoint state)
    - market_data_ohlcv (Stage 1 writes OHLCV)
tech_stack:
  added: []
  patterns:
    - Oneshot batch script (mirrors run_historical_pipeline.py)
    - psycopg2 batch INSERT (execute_batch)
    - Two-stage checkpoint: fetch_complete + status in backfill_status
    - Chunked sliding-window read from market_data_ohlcv (T3)
    - APR-backed FeatureFactoryConfig from ConfigService cache-only mode
    - OTel job_completed_total{job=backfill-feature-factory, status=success|failure}
key_files:
  created:
    - services/backfill_feature_factory.py
    - tests/unit/services/test_backfill_feature_factory.py
  modified: []
decisions:
  - "Chunked sliding window capped at _READ_CHUNK_BARS=2000 for memory safety (T3), while keeping full array for FeatureFactory stateless compute correctness"
  - "warm_up_bars = config.momentum_zscore_window (252) as dominant rolling window per objective formula"
  - "Cross-asset ETF bars (SPY/TLT/SHY) pre-loaded once at compute stage start and passed to cache.update_cross_asset() per-bar for FeatureCache cross-asset fields"
  - "asyncio.coroutine removed in Python 3.14 - tests use explicit async def helpers for mock coroutines"
metrics:
  duration_minutes: 25
  completed_date: "2026-06-20"
  tasks_completed: 2
  files_changed: 2
---

# Phase 137 Plan 5: Backfill Feature Factory Summary

**One-liner:** Two-stage oneshot (`services/backfill_feature_factory.py`) that fetches IBKR OHLCV history for 58 ETFs into `market_data_ohlcv` and computes `FeatureFactory.compute()` into `feature_vectors`, with independent (symbol, tf) checkpoint/resume via `backfill_status`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Backfill oneshot - IBKR fetch + FeatureFactory compute + two-stage checkpoint | 297cbbd6 | services/backfill_feature_factory.py |
| 2 | Unit tests for checkpoint/resume, coverage accounting, source correctness | 22c29f29 | tests/unit/services/test_backfill_feature_factory.py |

## Verification Results

All acceptance criteria met:

- **--help exits 0**: `python services/backfill_feature_factory.py --help` shows --fetch-only / --compute-only / --client-id flags
- **Zero intelligence_features references**: `grep -n "intelligence_features" services/backfill_feature_factory.py` returns 0 code matches (only comment in docstring line 16)
- **Default client-id is 40**: `_DEFAULT_CLIENT_ID: int = 40` (T2 mitigated)
- **market_data_ohlcv + feature_vectors present**: both strings in source
- **Two-stage checkpoint**: fetch_complete=true set before compute; status='complete' skips compute on resume
- **theoretical_max formula**: exact implementation per objective (depth_years * 252 * bars_per_trading_day(tf)) - warm_up_bars
- **regime_label_source='filtered'**: hardcoded in `_vector_to_params()` (SC-5)
- **job_completed_total emitted**: at exit with job=backfill-feature-factory
- **ruff exits 0**: clean after removing unused imports (dataclasses, json, time)
- **18 unit tests pass**: all CI-clean, no network, no live DB

## Threat Model Resolution

- **T1 (corpus contamination via intelligence_features)**: MITIGATED - source is market_data_ohlcv only; docstring states invariant explicitly; zero SQL references to intelligence_features
- **T2 (client-id collision)**: MITIGATED - _DEFAULT_CLIENT_ID=40 constant; test_default_client_id_is_40 asserts it; CLI --client-id defaults to 40
- **T3 (OOM on large symbol history)**: MITIGATED - sliding window capped at _READ_CHUNK_BARS=2000; never SELECT * whole history
- **T4 (restart re-fetches completed pairs)**: MITIGATED - backfill_status.fetch_complete skips download; status='complete' skips compute; both tested in unit tests

## Coverage Accounting (D-06 Gate)

Theoretical max per TF/depth (warm_up_bars=252):

| TF  | Depth | bars/day | Theoretical Max    |
|-----|-------|----------|--------------------|
| 5m  | 5y    | 78       | (5*252*78) - 252 = 98,028 |
| 15m | 10y   | 26       | (10*252*26) - 252 = 65,268 |
| 1h  | 15y   | 6        | (15*252*6) - 252 = 22,428  |
| 1d  | 20y   | 1        | (20*252*1) - 252 = 4,788   |

Pairs below 80% are flagged with `_logger.warning("coverage_below_gate", ...)` and logged to `logs/backfill_feature_factory.log`. Phase 138 D-06 gate excludes these pairs from IC measurement.

The actual populated counts will be recorded here after the backfill run completes (precondition: IBKR connection and market_data_ohlcv population).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python 3.14 removed asyncio.coroutine**

- **Found during:** Task 2 unit tests
- **Issue:** `asyncio.coroutine` removed in Python 3.14 (`AttributeError: module 'asyncio' has no attribute 'coroutine'`). Test for fetch_resume used the deprecated pattern.
- **Fix:** Replaced with explicit `async def` helper functions for mock coroutines in test_fetch_resume_skips_fetch_complete_pairs.
- **Files modified:** tests/unit/services/test_backfill_feature_factory.py
- **Commit:** 22c29f29

**2. [Rule 1 - Bug] Bar timestamp arithmetic overflow in test helper**

- **Found during:** Task 2 unit tests
- **Issue:** `base_ts.replace(minute=base_ts.minute + i * 5)` overflowed (minute > 59) when n >= 13.
- **Fix:** Changed to `base_ts + timedelta(minutes=i * 5)` for correct incremental timestamps.
- **Files modified:** tests/unit/services/test_backfill_feature_factory.py
- **Commit:** 22c29f29

## Self-Check

Files created:
- [x] FOUND: services/backfill_feature_factory.py
- [x] FOUND: tests/unit/services/test_backfill_feature_factory.py

Commits exist:
- [x] FOUND: 297cbbd6 (feat - backfill_feature_factory.py)
- [x] FOUND: 22c29f29 (test - unit tests)

Acceptance criteria verified:
- [x] --help exits 0 with --fetch-only / --compute-only / --client-id flags
- [x] zero intelligence_features code references (T1)
- [x] default client-id = 40 (T2)
- [x] market_data_ohlcv source + feature_vectors sink confirmed
- [x] two-stage checkpoint tested (fetch_complete + status)
- [x] theoretical_max formula correct (all 4 TFs verified in tests)
- [x] regime_label_source='filtered' in params builder
- [x] job_completed_total emitted at exit
- [x] ruff exits 0
- [x] 18 unit tests pass CI-clean

## Self-Check: PASSED
