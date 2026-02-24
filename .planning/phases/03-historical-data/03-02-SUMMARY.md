---
phase: 03-historical-data
plan: 02
subsystem: historical-backfill
tags: [backfill, ibkr, stage1, stage2, intelligence-features, signal-ledger, schema-fix]
dependency_graph:
  requires:
    - 03-01-SUMMARY.md  # intelligence_features write path in historical_backfill.py
  provides:
    - 35 days of 1m OHLCV bars in market_data_ohlcv (753,415 rows, 17 symbols)
    - 248,261 signals in signal_ledger with feature_ts populated for Phase 3 rows
    - 391,564 intelligence_features rows (source='backfill') for ML training
key_files:
  modified:
    - production/scripts/historical_backfill.py  (via 03-01)
    - src/intelligence/schemas.py  (schema field type fix — commit 5925222)
    - tests/unit/test_feature_writer_service.py
    - tests/unit/service_tests/test_market_analysis_service.py
    - tests/unit/service_tests/test_signal_generator_service.py
    - tests/unit/test_signal_orchestrator_helpers.py
decisions:
  - "Used --days 35 (5 × 7-day chunks) instead of 365 — enough for ML warmup, avoids long IBKR waits"
  - "ibkr.py uses 6-day chunks as conservative safety margin under IBKR 7-day hard limit"
  - "Stage 2 runs --timeframes 1m only — replay internally uses only 1m bars"
  - "signal_ledger NOT truncated before Stage 2 re-run — old pre-Phase-3 rows remain with feature_ts=NULL"
  - "intelligence_features had 98 debug rows before fix; NOT truncated before re-run — ON CONFLICT DO NOTHING handles idempotency"
  - "Schema field types corrected: SwingDetector pattern/type fields → float (1.0/-1.0/0.0), divergence/detection flags → float confidence scores (not bool)"
metrics:
  completed: "2026-02-24"
  tasks_completed: 3
  stage1_bars: 753415
  stage1_symbols: 17
  stage1_symbols_skipped: 6
  stage2_signals: 248261
  stage2_features: 391564
---

# Phase 3 Plan 2: Run Backfill + Validate Summary

**One-liner:** Ran Stage 1 (IBKR fetch) and Stage 2 (intelligence replay), diagnosed and fixed a silent Pydantic ValidationError in `_build_intelligence_event`, then re-ran Stage 2 successfully — producing 391,564 intelligence_features rows and 248,261 signals linked by feature_ts.

## Tasks Completed

| Task | Name | Outcome |
|------|------|---------|
| 1 | Confirm TWS + Stage 1 strategy | TWS available — chose --days 35 (5 × 7-day chunks) |
| 2 | Run Stage 1 (IBKR fetch) | 753,415 bars, 17 symbols (6 skipped: qualify failed) |
| 3 | Debug + fix + re-run Stage 2 | 391,564 feature rows, 248,261 signals, 0 orphans |

## What Was Built / Fixed

### Stage 1 Result
- **753,415 bars** stored in `market_data_ohlcv` (1m timeframe, 35 days)
- **17 symbols** fetched successfully: ESH6, NQH6, RTYH6, YMH6, CLJ6, GCJ6, SIH6, HGH6, PLJ6, VXH6, ZNH6, ZFH6, ZBH6, ZTH6, ZSH6, ZCH6, ZWH6
- **6 symbols skipped** (qualify failed — insufficient IBKR history): BZJ6, NGJ6, SR1H6, 6EH6, 6JH6, BTCH6

### Stage 2 — Initial Bug Found
First run wrote **354,922 signals** to `signal_ledger` but **0 rows** to `intelligence_features`. Root cause: 12 schema field type mismatches caused a Pydantic `ValidationError` on every single bar, silently suppressed by the `try/except Exception: return None` guard in `_build_intelligence_event`.

**Bug details (commit 5925222):**
- `SwingDetector`: `swing_pattern`, `high_type`, `low_type` declared as `str` — plugins return `1.0/-1.0/0.0` floats
- `RSIDivergence`/`VolumeDivergence`: `rsi_div_*/vol_div_*` declared as `bool` — plugins return float confidence scores
- `BOSCHoCH`/`LiquiditySweeps`/`OrderBlocks`: `detected`/`reclaimed`/`mitigated` declared as `bool` — plugins return `0.0/1.0` float flags

Fix: corrected all 12 field type declarations in `src/intelligence/schemas.py`. Updated 5 test files to use float values matching actual plugin output.

### Stage 2 — Re-run After Fix
- **391,564 rows** in `intelligence_features` (source='backfill')
- **248,261 signals** in `signal_ledger` (1m timeframe only)
- **240,836 signals** with `feature_ts` populated (= signals from Phase 3 re-run)
- **0 orphaned signals** — JOIN integrity intact

## Deviations from Plan

| Deviation | Reason |
|-----------|--------|
| Used --days 35 instead of 365 | Avoids multi-hour IBKR fetch; 35 days sufficient for ML warmup |
| Stage 2 ran --timeframes 1m only | Replay only processes 1m bars internally — other TFs skipped silently |
| Schema fix was an unplanned intermediate step | Bug discovered during Stage 2 initial run; fixed before re-run |
| signal_ledger not truncated before re-run | Pre-Phase-3 rows (feature_ts=NULL) intentionally preserved |

## Self-Check: PASSED

- [x] Stage 1 complete — 753,415 bars in market_data_ohlcv
- [x] Schema fix committed (5925222) — 12 field types corrected
- [x] Stage 2 complete — 391,564 intelligence_features rows
- [x] signal_ledger has 248,261 signals, 240,836 with feature_ts
- [x] Orphaned signals = 0
