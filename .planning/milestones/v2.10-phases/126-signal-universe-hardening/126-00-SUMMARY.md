---
phase: 126-signal-universe-hardening
plan: "00"
subsystem: signal-quality
tags: [diagnostic, usdjpy, zone-geometry, data-integrity, wave-0]
dependency_graph:
  requires: []
  provides: [SIGNAL-QUALITY-01, usdjpy-diagnostic-verdict]
  affects: [126-01-zone-width-gate, 127-clean-replay]
tech_stack:
  added: []
  patterns: [sql-diagnostic]
key_files:
  created:
    - docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md
  modified: []
decisions:
  - "USDJPY anomaly primary cause is ZONE GEOMETRY (avg_zone_atr_ratio 0.788x vs EURUSD 1.414x / USDCHF 1.429x); not data quality, not structural/carry"
  - "No data pipeline fix required; no todos/pending item needed"
  - "USDJPY bar data is fit for Phase 127 clean replay, conditional on P126-01 zone width gate deployed first"
  - "schema adaptations: signal_ledger -> signal_ledger_full for pnl_r; i1->atr -> technical_indicators->atr_14; fired_at -> timestamp; timeframe -> tf in intelligence_features"
metrics:
  duration_seconds: 127
  completed_date: "2026-06-15"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
---

# Phase 126 Plan 00: USDJPY Anomaly Diagnostic Summary

USDJPY zone geometry confirmed as sub-ATR (0.788x avg ratio) causing uniform negative pnl_r across all 24 UTC hours; verdict: ZONE GEOMETRY, addressed by Wave 1 P126-01.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Run three USDJPY diagnostic SQL queries | c7b8ffa7 | (queries run, results captured) |
| 2 | Write USDJPY diagnostic findings doc with verdict | c7b8ffa7 | docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md |

## Key Findings

**Query 1 - Bar Completeness:**
- USDJPY: 55,401 total bars, 52,472 valid (94.7%), 50 trading days — identical range to EURUSD/USDCHF
- No bar gaps, no abnormal invalid-bar rate; data quality is sound

**Query 2 - Zone/ATR Ratio (the primary signal):**
| Symbol | avg_zone_atr_ratio | n | avg_pnl_r |
|--------|-------------------|---|-----------|
| EURUSD | 1.414 | 31,238 | +0.267 |
| USDCHF | 1.429 | 24,511 | +0.237 |
| USDJPY | 0.788 | 32,916 | -0.380 |

USDJPY zones average 0.79x ATR — below intrabar noise floor. Direct correlation with pnl_r outcome.

**Query 3 - Time-of-Day:**
- All 24 UTC hours show negative pnl_r for USDJPY (range: -0.203 to -0.540)
- No session or carry regime effect; the problem is systemic geometry, not timing

## Verdict

**ZONE GEOMETRY** - USDJPY avg_zone_atr_ratio of 0.788x vs EURUSD/USDCHF 1.41-1.43x. At 0.79x ATR, zones sit within intrabar noise. Stop-at-entry behavior is systematic and session-independent.

**Action:** Addressed by Wave 1 zone width gate (P126-01). No data pipeline fix needed.

## Replay Fitness

USDJPY bar data is fit for Phase 127 clean replay **after P126-01 is deployed**. Running replay before the zone width gate would poison the ML corpus with sub-ATR zone signals.

## Deviations from Plan

### Schema Adaptations (Rule 1 - Auto-fix)

The design doc queries referenced columns that do not exist in the current schema. Adaptations made with analytical intent preserved:

1. `signal_ledger.fired_at` does not exist - adapted to `signal_ledger_full.timestamp`
2. `signal_ledger.pnl_r` does not exist in base table - adapted to `signal_ledger_full` (outcome-enriched view)
3. `intelligence_features.i1` JSONB column does not exist - adapted to `technical_indicators->>'atr_14'`
4. `intelligence_features.timeframe` column does not exist - adapted to `tf`

All adaptations documented in the diagnostic file under "Column Adaptations from Design Doc" section.

## Self-Check

- [x] `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` exists with `## Verdict` section
- [x] Contains `## Diagnostic Queries`, `## Analysis`, `## Verdict`, `## Replay Fitness` sections
- [x] Verdict names exactly one cause: ZONE GEOMETRY
- [x] Verdict cites specific values from result tables (0.788x vs 1.414x/1.429x)
- [x] No data quality issue found, so no `.planning/todos/pending/` item required
- [x] Commit c7b8ffa7 exists
