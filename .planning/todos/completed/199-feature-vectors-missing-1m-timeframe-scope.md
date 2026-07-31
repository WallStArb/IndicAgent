---
status: completed
priority: P3
filed: 2026-07-29
source: Discovered mid-execution of todo 176's Step 1 (full-corpus --refresh recompute) --
  user asked why feature_vectors' row counts looked smaller than expected per symbol/tf,
  which led to comparing against market_data_ohlcv_tradeable and finding a 1m timeframe
  with real (if recent) data that feature_vectors has zero rows for. Confirmed with the user
  same session: not computing 1m features is intentional, existing behavior -- not a gap.
  This todo tracks only the APR-hardcoding cleanup, not a "should we add 1m" scope question.
---

**CLOSED 2026-07-31** -- `_TARGET_TIMEFRAMES` migrated to APR key
`feature.factory.target_timeframes` (migration 278,
`production/migrations/278_feature_factory_target_timeframes_apr.sql`), default value
unchanged (`["5m", "15m", "1h", "1d"]`), byte-identical behavior unless explicitly
reconfigured. The module constant is now `_TARGET_TIMEFRAMES_DEFAULT`, used only as the
APR fallback default (same role as `feature.sr.lookback_by_tf`'s inline dict default and
`alpha.ic.active_scales.{tf}`'s `ACTIVE_SCALES_FALLBACKS_BY_TF`), loaded via a new
`_get_target_timeframes(cfg)` helper (`services/backfill_feature_factory.py`) called from
both `run_fetch_stage()` and `run_compute_stage()`, which feeds `_load_status_map()` and
both TF-iteration loops. Migration 278 applied to the live DB (config_schema/config_state/
config_history rows only). `backfill_feature_factory.py` was not run against live data
(confirmed not currently active in the corpus pipeline -- `ic_engine.py` is the live stage
running). Tests updated/added in `tests/unit/services/test_backfill_feature_factory.py`
(`test_get_target_timeframes_defaults_when_apr_key_absent`,
`test_get_target_timeframes_honors_apr_override`); full file green (28/28).

# `_TARGET_TIMEFRAMES` in backfill_feature_factory.py is a hardcoded list -- should be an APR key (behavioral-list category)

## Context

`market_data_ohlcv_tradeable` has a genuine `1m` timeframe with real data -- 1.85M rows
total across 80 symbols (~23,166 avg/symbol). For SPY specifically it spans 2026-03-23 to
2026-07-28 (~4 months), much shorter than the 20-year depth on 5m/15m/1h/1d, suggesting 1m
ingestion is a relatively recent addition.

`feature_vectors` has zero rows for `tf = '1m'`. Root cause, confirmed by reading the code
(not assumed): `services/backfill_feature_factory.py:92` --

```python
_TARGET_TIMEFRAMES: list[str] = ["5m", "15m", "1h", "1d"]
```

This module-level constant is the sole driver of which timeframes get processed --
`_load_status_map()` (lines 740, 922) and the main compute loop (lines 764, 934) all iterate
`_TARGET_TIMEFRAMES` directly. `1m` was never added to this list, so no backfill or live
compute path populates `feature_vectors` for it, regardless of `--refresh`/`--compute-only`/
worker count.

Notably, `feature.sr.lookback_by_tf` (line 513) already has a `'1m': 60` entry --
`{"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60}` -- suggesting 1m support was at least
partially anticipated elsewhere in the codebase but never wired into the actual target list.

## The finding

Not computing `1m` features is confirmed intentional, existing behavior -- no action needed
on that front. What's still a real architecture violation: per
`docs/foundation/adaptive-parameter-registry.md`'s "behavioral lists" category (lists
controlling WHAT the algorithm processes must be APR-backed JSON, not hardcoded),
`_TARGET_TIMEFRAMES` should be a `feature.factory.target_timeframes` (or similar) APR key,
not a Python list literal. This is true independent of what the list currently contains.

## Not urgent

Purely a governance/consistency cleanup -- doesn't block or affect todo 176's recompute or
any other in-flight work. Low priority.

## Acceptance criteria

- [x] Migrate `_TARGET_TIMEFRAMES` to an APR key (`config_schema`/`config_state` migration +
      `ConfigService.get()` load at init), removing the hardcoded list literal from
      `services/backfill_feature_factory.py:92`
