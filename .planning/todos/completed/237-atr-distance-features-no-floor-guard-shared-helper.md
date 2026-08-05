---
status: fixed
priority: P3
filed: 2026-08-03
fixed: 2026-08-05
source: root-causing todo 236's weekly_r1_dist_atr/weekly_r2_dist_atr half via
  superpowers:systematic-debugging
---

## What

Todo 236 found `weekly_r1_dist_atr`/`weekly_r2_dist_atr` hit implausible extreme values (up to
96,512) for a handful of rows, hypothesized as a near-zero-ATR-denominator issue. Root-caused,
not guessed: `feature_factory.py`'s shared `_above`/`_below` helpers (line ~3454-3458), used by
essentially every ATR-normalized distance feature this module computes --
`prior_session_high/low/close_dist_atr`, `overnight_high/low_dist_atr`,
`weekly_pivot/r1/r2/s1/s2_dist_atr`, `asian_session_high/low_dist_atr`, `poc_dist_atr`,
`poc_rolling_dist_atr`, `va_width_atr`, `nearest_level_dist_atr` (15+ columns) -- gate on
`atr_valid = atr_val is not None and math.isfinite(atr_val) and atr_val > 0`. This excludes zero/
negative/non-finite ATR, but NOT a legitimately-positive, numerically-tiny ATR, which is exactly
what makes `(level - close_) / atr_val` blow up.

Confirmed with a live example, not inferred: BIL (an ultra-short-duration T-bill ETF, famously
flat) at 5m in 2012-04 shows a smoothly growing sequence across consecutive bars (53,302 ->
57,403 -> 61,818 -> 66,574 -> 71,695 -> 77,210 for `weekly_r1_dist_atr` alone) -- the signature
of a genuinely near-zero ATR denominator during a real flat period, not noise or a data-entry
error.

**Scale, checked before assuming urgency:** only 3 (`weekly_r1_dist_atr`) and 6
(`weekly_r2_dist_atr`) rows out of the full 25,443,790-row 5m equity corpus cross the specific
magnitude this investigation was scoped around (float16's ~65504 ceiling). Practically rare. But
the underlying gap is structural and shared across 15+ columns -- other (symbol, tf, period)
combinations could plausibly produce smaller-but-still-distorted ratios that never cross any
visible threshold, silently skewing a feature without ever triggering an implausibility check.
This is exactly the class of thing worth fixing at the root (the shared helper) rather than
patching the two columns this investigation happened to notice.

**No longer even the mitigated case (2026-08-03):** the float16 downcast this clip existed for was
itself removed the same day -- 5m's `feature_dtype=np.float16` OOM-killed regardless (LightGBM's
Python bridge upcasts any non-float32/float64 array back to a full float32 copy internally,
defeating the intended memory saving; root-caused via `superpowers:systematic-debugging`).
`nonlinear_interaction_combiner`'s fetch path (`_nonlinear_interaction_combiner_shared.py`) now
uses float32 at every tf including 5m, matching 1h/1d/15m, so the ~9 offending cells (max
~96,512) are comfortably inside float32's range and the clip-before-cast logic was deleted as
dead code rather than kept as an inert safety net. This todo is about the underlying
feature-computation gap, not an unhandled crash risk today -- that conclusion is unchanged, but
there is no longer any clip anywhere protecting against it, mitigated or not.

## Why not fixed in the same session as todo 236

A proper fix needs a real design decision -- what floor value (absolute? relative to price,
e.g. a minimum ATR-as-%-of-close? per-tf, matching how `alpha.ic.bootstrap_block_size.<tf>` is
already tf-calibrated?) -- and per this project's APR mandate, a tunable numeric floor belongs
under `feature.*` in `config_state`, not a hardcoded constant. Applying it to a shared helper
touching 15+ live feature columns is real surface area for a change whose measured practical
impact (3-6 rows corpus-wide) doesn't yet justify rushing it. Confirmed via this project's own
"don't accelerate work steps 1-3 haven't justified" mandate (CLAUDE.md/PRIORITIES.md) that this
is correctly P3, not a guess-fix candidate.

## Next step

Design an ATR floor for `_above`/`_below` (an APR key, e.g. `feature.atr_normalization.min_atr_pct`
or similar, gated the same way other calibration constants in this module already are) and apply
it once. Before implementing: check whether any OTHER already-computed feature in this corpus
shows the same "smoothly growing, near-zero-denominator" signature at a magnitude below the
float16 threshold (a quick `stddev`/`percentile` scan across the 15+ affected columns, corpus-
wide) to confirm the floor's practical value before spending APR-key design effort on a
theoretical risk.

## Fix applied 2026-08-05

Fixed at the root, ahead of the imminent Phase 151 full-corpus recompute (151-07) rather than
deferred further -- recomputing a known numeric bug would just force a second recompute later.

Went broader than the "shared helper" framing above once the actual blast radius was mapped:
the near-zero-ATR gate wasn't one `_above`/`_below` pair, it was TWO separate copies of the same
inline `atr_val is not None and math.isfinite(atr_val) and atr_val > 0` check (six call sites)
plus a THIRD, narrower `_is_valid_atr(atr_val)` helper already shared by the six SMC compute
functions (six more call sites) -- 12 total call sites across
`_derive_session_vp`/`_compute_sr_dist_atr`/`_compute_swing_structure`/`_compute_trend_structure`/
`_compute_fib_zones`/`_derive_session_levels`/`_compute_order_blocks`/`_compute_fvg`/
`_compute_liquidity_sweeps`/`_compute_liquidity_pools`/`_compute_supply_demand_zones`/
`_compute_bos_choch`. Consolidated all 12 onto the one `_is_valid_atr`, broadened to
`_is_valid_atr(atr_val, close_, min_atr_pct)`: `atr_val >= min_atr_pct * abs(close_)` in addition
to the pre-existing `> 0` check -- relative to close_, not absolute, so it holds across
instruments at any price scale. `_derive_session_vp`/`_derive_session_levels` didn't take
`config: FeatureFactoryConfig` before; added it (4 call-site updates across
`compute()`/`compute_batch()`).

New APR key `feature.atr_normalization.min_atr_pct` (migration 294, applied live), seeded 0.0001
(1bp of price) [conventional], ML learning target: yes. Added `atr_normalization_min_pct` field
to `FeatureFactoryConfig`; hydrated in both `backfill_feature_factory.py` (batch) and
`feature_vector_pipeline.py` (live) plus `feature_vector_pipeline.py`'s `_THRESHOLD_KEYS`
prewarm list (caught by `test_every_key_read_building_feature_factory_config_is_prewarmed` --
missing this step silently ignores `config_state` on the live path forever).

Skipped the corpus-wide stddev/percentile scan this todo's "Next step" suggested doing first --
moot once the decision was "fix now, ahead of the recompute" rather than "decide whether it's
worth fixing": the recompute itself is about to regenerate every affected column from scratch
under the corrected gate, making a pre-fix scan of soon-to-be-replaced data low-value.

Regression tests added: `TestIsValidAtr` in `tests/unit/test_feature_factory.py` (8 pure-function
cases: None/non-finite/zero/negative rejected, ordinary ATR passes, exact-floor boundary,
just-below-floor rejected, floor=0.0 recovers pre-fix `atr_val > 0` behavior, default matches
migration 294's seed) plus an end-to-end BIL-style scenario in
`tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py`
(`test_session_levels_weekly_pivot_tiny_atr_gated_not_exploded`): a near-zero-true-range weekly
bar sequence now gates `weekly_pivot/r1/r2/s1/s2_dist_atr` to `None` instead of exploding, and
disabling the floor on the identical bars recovers non-None values (proves the gate is the floor,
not incidental cold-start).

Verified: `tests/unit/` full suite green (including the new tests), `ruff check` clean on every
touched Python file.
