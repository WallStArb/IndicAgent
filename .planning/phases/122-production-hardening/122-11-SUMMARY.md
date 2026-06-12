---
plan: 122-11
status: complete
completed_at: 2026-06-12
---

## Summary

Reverted intelligence_features tier-code column names back to functional names via migration 126, updated all DB column references across the codebase, and removed the erroneous Tier 2 exemption from the naming doc.

**One-liner:** Migration 126 applied (i1/i3/i4/i5 → technical_indicators/regime_features/confluence_scores/pattern_detections); all SQL column refs updated across feature_writer, feature_replay, run_historical_pipeline, API routes, and naming doc fixed.

## What Was Done

1. Created and applied `production/migrations/126_revert_tier_column_names.sql` — 4 RENAME COLUMN statements confirmed via `\d intelligence_features`
2. Updated `services/feature_writer.py` INSERT column list
3. Updated `production/scripts/feature_replay.py` SELECT and row accessors (2 locations)
4. Updated `production/scripts/run_historical_pipeline.py` INSERT column list, comment, and SELECT query (3 locations)
5. Updated `src/api/routes/features.py` — both export and paginated endpoints, tier/col mapping, and row accessors
6. Updated `src/api/routes/signals.py` — join query SELECT and row accessors in both `_build_signal_row` and single-signal endpoint
7. Updated `docs/foundation/naming-system.md` Tier 2 table: removed "DB columns" from i1–i8 exemption, leaving "Topic strings, metric labels" only; updated Stable Conventions note
8. Updated `tests/unit/scripts/test_feature_replay.py` — renamed and corrected column naming tests to enforce functional names

## Verification

- Migration applied: `technical_indicators`, `regime_features`, `confluence_scores`, `pattern_detections` confirmed in `\d intelligence_features`
- No tier-code JSONB accessors (`i1->>`, `i3->>`, etc.) in plan 11 target files
- Unit tests: 42 failed (all pre-existing), 4622 passed
