---
status: pending
priority: P3
filed: 2026-08-03
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
