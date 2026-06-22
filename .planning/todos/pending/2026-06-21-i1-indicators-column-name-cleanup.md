# TODO: I1Indicators column name APR cleanup

**Created:** 2026-06-21
**Scope:** v2.x schema retirement (low urgency — resolves naturally in v3.0)

## Problem

`I1Indicators` in `src/intelligence/schemas.py` (line 82) uses period numbers in column
names: `rsi_14`, `atr_14`, `atr_20`, `macd_12_26_9`, `bb_20_2_upper`, `stoch_k_14_3`, etc.

Per CLAUDE.md: "Numbers in column names are only valid when the number defines the
statistical concept, not when it is a tunable parameter." These are tunable periods.

## Why deferred

`I1Indicators` is the v2.x plugin output schema still used by ~30 source files:
AI context (`src/intelligence/ai/context.py`), narrative routes, bar history seeder,
state serializer, and many tests. Renaming requires touching all of them.

In v3.0, `I1Indicators` and the old plugin pipeline are retired. This cleanup resolves
naturally when those consumers are migrated to `FeatureVector` in Phase 140+.

## Action when unblocked

Rename `I1Indicators` fields to functional names (`rsi_fast`, `atr_mid`, etc.) after
v2.x AI context / narrative consumers are migrated to v3.0 FeatureVector reads.
