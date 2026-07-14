---
status: pending
priority: P3
filed: 2026-07-13
source: Fable review of todo 104 (calendar/OPEX primitives), `docs/research/signal-temporal-atomic-primitives.md`
---

# `days_to_month_end` is exactly redundant with `month_position`, remove it

## Finding

`days_to_month_end = (days_in_month - day) / days_in_month = 1 - month_position`, exactly, for
every timestamp; both read the same `calendar.monthrange` in `feature_factory.py`. Perfect
affine complement: Pearson correlation -1, Spearman |IC| identical with flipped sign, perfectly
collinear in any linear stage (`EnsembleICEngine`). Same mathematical-redundancy class as the
migration-211 removal of `new_high_flag`/`new_low_flag` (redundant with
`dist_from_high`/`dist_from_low`).

## Fix

Drop `days_to_month_end`, keep `month_position` (simpler, positively-oriented). Requires:
1. Migration to drop the `days_to_month_end` column/registry row from `feature_registry`.
2. Remove the compute in `src/intelligence/feature_factory.py` and the `FeatureVector` field.
3. Calendar primitive count 22 to 21; `FeatureVector` 150 to 149 total fields.
4. Check for any live consumer (IC scores, ensemble weights referencing it) before dropping,
   same audit pattern as migration 211.

## Gate

None, independent, small change. Not urgent (P3, hygiene), can batch with the next schema
migration rather than running standalone.

## Reference

`docs/research/signal-temporal-atomic-primitives.md`, "Redundancy finding: remove
`days_to_month_end`" section, full derivation.
