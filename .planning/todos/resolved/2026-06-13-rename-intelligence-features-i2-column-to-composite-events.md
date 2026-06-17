---
created: 2026-06-13T04:35:52.622Z
title: Rename intelligence_features i2 column to composite_events
area: database
files:
  - docs/superpowers/plans/2026-06-12-rename-i2-to-composite-events.md
  - production/migrations/
  - services/feature_writer.py
  - production/scripts/run_historical_pipeline.py
  - production/scripts/feature_replay.py
  - production/scripts/validate_alpha.py
  - src/persistence/repository/feature_snapshot_repository.py
  - src/persistence/logic/warmup_provider.py
  - src/intelligence/services/bar_history_seeder.py
  - tests/unit/scripts/test_feature_replay.py
  - tests/unit/persistence/test_warmup_provider.py
---

## Problem

Phase 122 renamed the i2 tier to `composite_events` in code (Pydantic field, plugin tier key, in-memory frames) but left the `intelligence_features` DB column still named `i2`. This is an inconsistency — all other tier columns use functional names (`trend_following`, `momentum`, etc.) but `i2` remains a tier code. The full implementation plan is already written and scoped.

## Solution

Implement `docs/superpowers/plans/2026-06-12-rename-i2-to-composite-events.md` as a standalone phase (Phase 123):

1. Migration 127: `ALTER TABLE intelligence_features RENAME COLUMN i2 TO composite_events`
2. Update SQL strings in feature_writer, run_historical_pipeline, feature_replay, validate_alpha
3. Fix tier→column mappings in bar_history_seeder and warmup_provider (seeder files had scrambled mappings pre-122; confirm all are correct)
4. Update SELECT lists in feature_snapshot_repository
5. Update test assertions

Scope boundary: DB column names and SQL strings only. Python-layer identifiers (`frames["i2"]`, `event.i2`, `I2Events`, `Tier.I2`) are unchanged.
