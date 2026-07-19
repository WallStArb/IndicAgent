---
status: completed
priority: P3
filed: 2026-07-13
closed: 2026-07-19
source: Fable review of todo 104 (calendar/OPEX primitives), `docs/research/signal-temporal-atomic-primitives.md`
---

## Resolution

Migration 235: `UPDATE feature_registry SET group_name = 'structure' WHERE feature_name =
'above_wk_vwap'`. Chose `structure` over `volatility` -- it's the closest existing category
by computation class (price position relative to a reference level, same shape as
`range_position`/`bar_close_pos`/`gap_z`/`high_52w_dist`, all already `structure`). Applied
to the live DB. No test pinned the old `calendar` value. `feature_factory.py`'s
`FEATURE_VECTOR_DOMAIN` dict (a separate, coarser taxonomy used elsewhere, not read by
`feature_registry` or `ic_engine.py`) was left untouched -- out of scope, different
vocabulary (`quant`/`structural`/`regime` vs. `feature_registry`'s CHECK-constrained set).

# `above_wk_vwap` is mis-grouped as `calendar` in `feature_registry`

## Finding

`above_wk_vwap` is registered with `group_name='calendar'` in `feature_registry`, but it is
price-dependent and stateful (reads `FeatureCache`, per `feature_factory.py:21`); it does not
meet the calendar-primitive definition (deterministic, stateless, O(1) function of the bar
timestamp alone, no OHLCV input). The other 21 rows in the `calendar` group are all pure
timestamp arithmetic; this one is the sole exception, evidently grouped there for a
session/week-boundary association rather than its actual computation class.

## Fix

Regroup `above_wk_vwap` to its correct `group_name` (likely `structure` or `volatility`; check
`feature_registry_group_name_check`'s allowed values and pick the closest existing category, or
raise if none fits). No compute change, metadata-only migration.

## Gate

None, independent, small change. Not urgent (P3, hygiene).

## Reference

`docs/research/signal-temporal-atomic-primitives.md`, "Existing Inventory" table, footnote on
`above_wk_vwap`.
