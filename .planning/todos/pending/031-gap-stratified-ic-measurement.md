---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** correctness
**Priority:** P1
**Effort:** 3-4h (ic_engine changes + migration + corpus re-run)
**Benefit:** Eliminates hidden bias from mixing overnight-gap and intraday return distributions in IC measurement; upstream fix that improves all downstream ensemble weights and thresholds
**Risk:** Low code risk; corpus re-run required to see effect (non-trivial time cost)
**Gate:** None — this is the first gap in the execution chain
---

# 031 — Gap-Stratified IC Measurement

First in the correctness gap execution chain. See design doc:
`docs/plans/2026-06-30-alphaengine-correctness-gaps.md`

## What

Separate IC measurement in `ic_engine.py` for bars where
`forward_returns.has_gap_before_entry = true` vs `false`.
`has_gap_before_entry` is already populated in `forward_returns` and ignored today.

Gate the change behind `alpha.ic.gap_stratified = false` so it can be enabled after
validating the effect on IC distributions.

## Files

- `services/ic_engine.py`
  - `_compute_symbol_tf()` — split aligned rows by gap mask; compute IC on non-gap
    observations (primary) and gap observations (diagnostic separately)
  - `_compute_pooled_cross_sectional()` — same split
  - Write both populations to `feature_ic_scores` with `has_gap_before_entry` column
    flagging which population the row represents
- New migration:
  - `ALTER TABLE feature_ic_scores ADD COLUMN has_gap_before_entry boolean`
  - INSERT `alpha.ic.gap_stratified = false` into `config_schema` + `config_state`
  - INSERT `alpha.ic.gap_ic_divergence_threshold = 0.02` into `config_schema` + `config_state`

## Verification

1. Migration applies cleanly
2. `pytest tests/unit/ -q` green
3. Run ic_engine on a single symbol/tf; confirm `feature_ic_scores` contains rows for
   both `has_gap_before_entry = true` and `false`
4. Confirm production ensemble still uses non-gap rows (primary path unchanged while
   `alpha.ic.gap_stratified = false`)

## Unblocks

- todo 032 (empirical thresholds) — needs clean non-gap IC corpus
