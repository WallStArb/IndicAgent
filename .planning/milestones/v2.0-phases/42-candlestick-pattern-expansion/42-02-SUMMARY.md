---
phase: 42-candlestick-pattern-expansion
plan: "02"
subsystem: database
tags: [migration, pattern-reliability, bootstrap-priors, candlestick]
dependency_graph:
  requires: []
  provides: [pattern_reliability table, bootstrap priors for 10 patterns]
  affects: [42-03-CandlestickPatternSetup, weight_updater]
tech_stack:
  added: []
  patterns: [idempotent SQL migration, bootstrap priors with is_bootstrap flag]
key_files:
  created:
    - production/migrations/047_pattern_reliability.sql
  modified: []
decisions:
  - "TIMESTAMP WITH TIME ZONE used for last_updated (UTC compliance per CLAUDE.md)"
  - "ON CONFLICT DO NOTHING for idempotency — safe re-runs verified"
  - "Both CREATE TABLE and CREATE INDEX use IF NOT EXISTS guards"
metrics:
  duration_seconds: 77
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
  completed_date: "2026-03-20"
---

# Phase 42 Plan 02: Pattern Reliability Table Summary

Bootstrap-priors migration for adaptive candlestick pattern confidence weights — `pattern_reliability` table created with 10 literature-based priors seeded for Phase 46 ML calibration.

## What Was Built

Migration `047_pattern_reliability.sql` creates the `pattern_reliability` table and seeds 10 bootstrap priors for the new candlestick patterns added in Plan 42-01.

**Table schema:**
```
pattern_reliability (
    pattern_name TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    base_confidence FLOAT NOT NULL,
    sample_size INTEGER DEFAULT 0,
    win_rate FLOAT,
    p_value FLOAT,
    ic_score FLOAT,
    is_bootstrap BOOLEAN DEFAULT true,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (pattern_name, timeframe)
)
```

**Two indexes:**
- `idx_pattern_reliability_bootstrap` — partial index on `is_bootstrap = true` (I7 plugin query path)
- `idx_pattern_reliability_sample_size` — partial index on `sample_size >= 30` (weight_updater calibration gate)

**10 bootstrap priors seeded:**

| Pattern | base_confidence | Tier |
|---------|----------------|------|
| abandoned_baby_bull | 0.70 | 1 |
| abandoned_baby_bear | 0.70 | 1 |
| kicker_bull | 0.70 | 1 |
| kicker_bear | 0.70 | 1 |
| harami_bull | 0.60 | 2 |
| harami_bear | 0.60 | 2 |
| tweezer_top | 0.60 | 2 |
| tweezer_bottom | 0.60 | 2 |
| belt_hold_bull | 0.55 | 2 |
| belt_hold_bear | 0.55 | 2 |

## Tasks Completed

### Task 1: Create migration file
- Created `production/migrations/047_pattern_reliability.sql`
- Table schema with all required columns
- Idempotent INSERT with `ON CONFLICT (pattern_name, timeframe) DO NOTHING`
- Both indexes created with `IF NOT EXISTS` guards
- Commit: `4080bed`

### Task 2: Apply migration and verify
- Migration applied via `docker exec timescaledb psql -U postgres -d indicagent -f /tmp/047_pattern_reliability.sql`
- Table created: confirmed via `\d pattern_reliability`
- 10 bootstrap rows seeded: `SELECT COUNT(*) FROM pattern_reliability WHERE is_bootstrap = true` → 10
- Tier 1 patterns (0.70): abandoned_baby_bull/bear, kicker_bull/bear
- Tier 2 patterns (0.55-0.60): harami_bull/bear, tweezer_top/bottom, belt_hold_bull/bear
- Idempotency verified: re-running returns `INSERT 0 0`, no duplicate rows

## Verification Results

```
docker exec timescaledb psql -U postgres -d indicagent -t -c "SELECT COUNT(*) FROM pattern_reliability WHERE is_bootstrap = true;"
   10
```

All 4 plan success criteria met:
- [x] pattern_reliability table created with PRIMARY KEY (pattern_name, timeframe)
- [x] 10 bootstrap priors seeded with correct literature-based values
- [x] Indexes enable efficient queries for I7 plugin (bootstrap lookup) and weight_updater (calibration updates)
- [x] Migration is idempotent (re-running produces INSERT 0 0, no duplicate rows)

## Deviations from Plan

None — plan executed exactly as written.

One minor improvement: Used `TIMESTAMP WITH TIME ZONE` instead of plain `TIMESTAMP` for `last_updated` column (UTC compliance per CLAUDE.md standards). This is a correctness fix, not a deviation.

## Key Links Established

- `42-03` (CandlestickPatternSetup I7) will query `pattern_reliability` via `_load_pattern_weights()` using `SELECT pattern_name, base_confidence FROM pattern_reliability WHERE is_bootstrap = true OR sample_size >= 30`
- `weight_updater` extension (Plan 42-04) will `UPDATE pattern_reliability SET base_confidence, win_rate, p_value, ic_score, is_bootstrap = false WHERE pattern_name = $1 AND timeframe = $2`

## Self-Check: PASSED

- [x] File exists: `/home/bg/dev/indicagent/production/migrations/047_pattern_reliability.sql` — FOUND
- [x] Commit exists: `4080bed` — FOUND
- [x] Table exists in DB: `\d pattern_reliability` confirms schema
- [x] 10 rows seeded: COUNT(*) = 10 confirmed
