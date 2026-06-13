---
created: 2026-06-13T09:06:53.255Z
title: Tier→DB column mapping — single source of truth + fix broken SQL
area: database
files:
  - tools/backtest_i6_plugin.py
  - tools/backtest_macro_factors.py
  - production/scripts/validate_alpha.py
  - src/api/routes/narrative.py
---

## Problem

The `intelligence_features` table uses functional column names for tier data:

| Python tier key | DB column name |
|----------------|----------------|
| i1 | technical_indicators |
| i2 | composite_events |
| i3 | regime_features |
| i4 | confluence_scores |
| i5 | pattern_detections |
| i6 | cross_timeframe_context |
| smc | smc |
| i7 | trading_signals |

There is no single source of truth for this mapping. Every file maintains its own, and several are wrong. Three files are actively broken at runtime:

1. `tools/backtest_i6_plugin.py` — SELECTs `i2, i3, i4, i5` as column names; reads `row["i2"]`, `row["i3"]`, `row["i4"]`, `row["i5"]` — these columns don't exist.

2. `tools/backtest_macro_factors.py` — SQL uses `ic.i4` column reference directly — doesn't exist.

3. `production/scripts/validate_alpha.py` — `tier_to_column` dict maps `I1→"i1"`, `I3→"i3"`, `I4→"i4"`, `I5→"i5"`, `I6→"i6"`, `I7→"i7"` (lines 96-103). These values are interpolated directly into `SELECT {column} FROM intelligence_features` (line 394). Every tier validation query fails at runtime.

Root cause: no authoritative mapping constant exists. Each file invented its own after migrations 125-127 renamed the columns.

## Solution

**Step 1 — Single source of truth**

Add `TIER_DB_COLUMNS: dict[str, str]` to `src/intelligence/schemas.py` (or a new `src/core/db/column_map.py`):

```python
TIER_DB_COLUMNS = {
    "i1": "technical_indicators",
    "i2": "composite_events",
    "i3": "regime_features",
    "i4": "confluence_scores",
    "i5": "pattern_detections",
    "i6": "cross_timeframe_context",
    "i7": "trading_signals",
    "smc": "smc",
}
```

**Step 2 — Fix the three broken files**

- `tools/backtest_i6_plugin.py`: update SELECT to use functional column names with `AS i2`, `AS i3`, `AS i4`, `AS i5` aliases; row reads stay as-is
- `tools/backtest_macro_factors.py`: fix `ic.i4` → `ic.confluence_scores`; verify hmm_regime lives in `smc` not `i4`
- `production/scripts/validate_alpha.py`: replace `tier_to_column` dict with import from the new constant; update key casing if needed (`"I1"` vs `"i1"`)

**Step 3 — Startup validation (Renaissance guard)**

Add a `validate_intelligence_features_columns(conn)` check at service startup (or as a pytest fixture) that queries `information_schema.columns` and asserts every value in `TIER_DB_COLUMNS` exists as a real column. Silent wrong answers are worse than loud crashes.

## Verified-correct files (do not change)
`narrative.py` (fixed 2026-06-13), `signals.py`, `features.py`, `feature_replay.py`, `bar_history_seeder.py`, `warmup_provider.py`, `feature_snapshot_repository.py`
