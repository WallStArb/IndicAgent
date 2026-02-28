---
phase: 03-historical-data
plan: 03
subsystem: historical-backfill
tags: [validation, sql-audit, hst-01, hst-02, hst-03, intelligence-features, signal-ledger]
dependency_graph:
  requires:
    - 03-02-SUMMARY.md  # backfill execution + schema fix
  provides:
    - Phase 3 acceptance gate: all HST requirements confirmed
metrics:
  completed: "2026-02-24"
  tasks_completed: 2
  signal_ledger_total: 248261
  signal_ledger_with_feature_ts: 240836
  intelligence_features_backfill: 391564
  orphaned_signals: 0
  date_range: "2026-01-15 to 2026-02-24 (40 days)"
---

# Phase 3 Plan 3: SQL Validation Audit Summary

**One-liner:** All 6 SQL validation blocks pass — 248,261 signals and 391,564 feature rows across 11 symbols, orphaned signals = 0, JSONB structure valid, date ranges aligned. HST-01, HST-02, HST-03 confirmed.

## Tasks Completed

| Task | Name | Outcome |
|------|------|---------|
| 1 | Run SQL validation audit (all 6 blocks) | All pass — results below |
| 2 | Human review + Phase 3 acceptance | APPROVED |

## Validation Results

### BLOCK 1 — signal_ledger

| Check | Result | Threshold | Status |
|-------|--------|-----------|--------|
| Total signals | 248,261 | ≥ 2,700 | ✅ PASS |
| Signals with feature_ts set | 240,836 | > 0 | ✅ PASS |
| Timeframes covered | 1m only | — | NOTE |
| Date range | 2026-01-15 → 2026-02-24 (40 days) | — | ✅ |

### BLOCK 2 — intelligence_features

| Symbol | TF | Rows | From | To |
|--------|----|------|------|----|
| CLJ6 | 1m | 37,305 | 2026-01-15 | 2026-02-24 |
| ESH6 | 1m | 37,117 | 2026-01-15 | 2026-02-24 |
| GCJ6 | 1m | 37,308 | 2026-01-15 | 2026-02-24 |
| HGH6 | 1m | 37,312 | 2026-01-15 | 2026-02-24 |
| NQH6 | 1m | 37,119 | 2026-01-15 | 2026-02-24 |
| PLJ6 | 1m | 37,306 | 2026-01-15 | 2026-02-24 |
| RTYH6 | 1m | 37,122 | 2026-01-15 | 2026-02-24 |
| SIH6 | 1m | 37,308 | 2026-01-15 | 2026-02-24 |
| VXH6 | 1m | 36,940 | 2026-01-16 | 2026-02-24 |
| YMH6 | 1m | 37,124 | 2026-01-15 | 2026-02-24 |
| ZNH6 | 1m | 19,603 | 2026-01-15 | 2026-02-05 |
| **Total** | | **391,564** | | |

**Total (backfill):** 391,564 rows — ✅ PASS (HST-02)

### BLOCK 3 — JOIN Integrity

| Check | Result | Threshold | Status |
|-------|--------|-----------|--------|
| Orphaned signals | **0** | = 0 | ✅ PASS (HST-03) |

### BLOCK 4 — JSONB Structure Sample

Sample row (VXH6, 2026-02-24 05:45:00): `close=21.0, open=21.0, volume=11, rsi_14=85.82`. All columns: `i1_type=object, i3_type=object, i4_type=object`. ✅ PASS

### BLOCK 5 — Empty JSONB Anomalies

| Check | Result | Status |
|-------|--------|--------|
| Rows with empty bar JSONB | 0 | ✅ PASS |
| Rows with empty i1 JSONB | 0 | ✅ PASS |

### BLOCK 6 — Date Coverage Alignment

| Table | From | To |
|-------|------|----|
| signal_ledger | 2026-01-15 | 2026-02-24 |
| intelligence_features (backfill) | 2026-01-15 | 2026-02-24 |

✅ PASS — date ranges aligned exactly.

## Anomalies

| Anomaly | Severity | Resolution |
|---------|----------|------------|
| ZNH6 data ends 2026-02-05 (19,603 rows vs ~37K for others) | WARN | IBKR data gap for ZNH6 in the fetch window — not a pipeline bug. Acceptable for ML training. |
| Only 1m timeframe in both tables | NOTE | Stage 2 ran with --timeframes 1m only; higher TFs not in backfill scope this run. Consistent across both tables — no integrity concern. |
| 6 symbols absent from intelligence_features (BZJ6, NGJ6, SR1H6, 6EH6, 6JH6, BTCH6) | NOTE | These symbols failed Stage 1 qualify check — no OHLCV bars → no feature rows. Expected. |

## HST Requirements Summary

| Requirement | Check | Result | Status |
|-------------|-------|--------|--------|
| HST-01 | signal_ledger ≥ 2,700 rows | 248,261 | ✅ PASS |
| HST-02 | intelligence_features > 0 backfill rows | 391,564 | ✅ PASS |
| HST-03 | Orphaned signals = 0 | 0 | ✅ PASS |

## Self-Check: PASSED

- [x] All 6 SQL validation blocks executed and output captured
- [x] signal_ledger: 248,261 total, 240,836 with feature_ts
- [x] intelligence_features: 391,564 backfill rows across 11 symbols
- [x] Orphaned signals = 0 — JOIN integrity confirmed
- [x] JSONB structure valid — non-null OHLCV and rsi_14, i1/i3/i4 are type 'object'
- [x] Date ranges aligned: both tables cover 2026-01-15 → 2026-02-24
- [x] Anomalies documented (ZNH6 gap, 6 missing symbols) — non-blocking
- [x] Phase 3 accepted: HST-01 ✅, HST-02 ✅, HST-03 ✅
