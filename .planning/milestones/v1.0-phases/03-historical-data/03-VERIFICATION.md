---
status: passed
phase: 03-historical-data
verified_at: "2026-02-28"
verified_by: 09-01-PLAN.md (milestone verification)
requirements:
  - HST-01: passed
  - HST-02: passed
  - HST-03: passed
---

# Phase 03: Historical Data — Verification

## Summary

Phase 03 (Historical Data) has been formally verified against the live TimescaleDB database. All three HST requirements pass.

## Verification Queries

Run against live `indicagent` database on 2026-02-28 using asyncpg direct connection.

### HST-01: signal_ledger row count

**Requirement:** >= 2,700 signals in `signal_ledger`

**Query:**
```sql
SELECT COUNT(*) as n FROM signal_ledger;
```

**Result:** 413,134 rows

**Status: PASSED** (413,134 >> 2,700 threshold)

---

### HST-02: intelligence_features row count

**Requirement:** `intelligence_features` table has rows (feature history exists)

**Query:**
```sql
SELECT COUNT(*) as n FROM intelligence_features;
```

**Result:** 482,571 rows

**Status: PASSED** (482,571 > 0)

---

### HST-03: Orphan signal check (JOIN integrity)

**Requirement:** 0 orphan signals (signals with `feature_ts` set but no matching row in `intelligence_features`)

**Query:**
```sql
SELECT COUNT(*) as orphans
FROM signal_ledger sl
WHERE sl.feature_ts IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM intelligence_features f
    WHERE f.ts = sl.feature_ts
      AND f.symbol = sl.symbol
      AND f.tf = sl.feature_tf
  );
```

**Result:** 0 orphans

**Status: PASSED** (perfect JOIN integrity)

---

## Additional Data Quality Metrics

| Metric | Value |
|--------|-------|
| signal_ledger date range | 2026-01-15 to 2026-02-27 |
| intelligence_features date range | 2026-01-15 to 2026-02-27 |
| Signals with feature_ts linked | 405,709 |
| Signals without feature_ts (pre-Phase-2) | 7,425 |
| Distinct symbols in signal_ledger | 17 |
| Distinct symbols in intelligence_features | 17 |

**Note on NULL feature_ts:** 7,425 signals lack `feature_ts` — these are pre-Phase-2 signals backfilled before the intelligence_features hypertable existed. This is expected and correct per the 02-03 design decision: "Backfill writes NULL for feature_ts/feature_tf — no IntelligenceEvent at replay time; NULL correctly indicates pre-Phase-2 signal." HST-03 orphan check correctly excludes these rows (`WHERE sl.feature_ts IS NOT NULL`).

## Schema Note

The `intelligence_features` hypertable uses column `tf` (not `timeframe`) for the timeframe dimension. The plan's query template referenced `f.timeframe` which required correction to `f.tf` during verification. This is a documentation-only deviation; no code was changed.

## Verdict

**Phase 03 PASSED** — Historical data pipeline is operational with 413K+ signals, 482K+ feature rows, and zero JOIN integrity violations across a 43-day date range covering 17 distinct symbols.
