---
status: pending
priority: P1
filed: 2026-10-29
source: data lane check of the 186-26 stage 1 output (feature_vectors_v2, tf 1d)
---

# Rebuilt 1d feature columns that are constant or all NULL must not reach the research read

After the 1d rebuild (5,127,577 rows, 1,257 names, 2005-01-03 to 2026-09-30), a pooled screen over
eight names (SPY, AAPL, MSFT, JPM, XOM, SCCO, HON, KO) finds, of 309 real columns, 18 all NULL and 22
constant. Most are intraday-session concepts that are degenerate on a daily bar by construction
(`hour_of_day_*`, `minute_of_hour_*`, `in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`,
`session_time_pos`, `opening_range`, the Asian and overnight session distances, the intraday return
divergences). Those are not defects of the kernels, but a column with no information on a timeframe
looks real to a reader.

Two groups need a closer look because a daily bar should give them values:

- `hma_slope_z` is exactly 0 on every row for every name checked (SPY: 5,465 of 5,465). It sits in the
  `bar_statistics_refresh` group beside `hurst`, `shannon`, `garch_ratio` and `adx`, which vary. A zero
  column is a silent wrong answer.
- Volume-profile and structure outputs on 1d: `poc_dist_atr`, `price_in_value_area`, `va_position`,
  `hmm_vol_prob_elevated`, `amd_phase`, `amd_distribution_direction`, `amd_manipulation_detected`,
  `manip_strength`, `sweep_detected` are constant; `distance_to_vah_atr`, `distance_to_val_atr`,
  `va_width_atr`, `nearest_hvn_*`, `nearest_lvn_*`, `poc_rolling_dist_atr` are all NULL. Decide for each
  whether 1d is out of scope for the concept (then it is NaN by declaration) or the kernel is wrong.

Related property, not a defect: `adx`, `hurst`, `shannon`, `garch_ratio` change only every
`regime_cache_refresh_bars` rows (the replay of the v2 cache cadence), so on 1d they are piecewise
constant for about 30 sessions. A research spec reading them should know the effective lag.

## Root cause of `hma_slope_z` (research lane, 2026-10-29)

Not a kernel bug: a placeholder. `FeatureCache.refresh_regime` appends one HMA slope per refresh
(every `feature.regime.cache_refresh_bars` = 30 rows) and `_zscore_from_deque` returns 0.0 until the
history holds `feature.momentum.zscore_window` = 252 slopes, so the first non-zero value needs about
252 x 30 = 7,560 rows. SPY 1d has 5,465 rows, so the column is 0.0 on every row of every 1d name; it
becomes non-zero on 5m and 15m after about 7,560 rows (a warmup of 0.0 on the first two to three
months, then real values). The 0.0 is a fill that breaks `no_fill` (warmup masked by declared memory,
NaN not 0.0). The fix is a kernel edit: return NaN while the history is short (`bar_statistics_refresh`
declared memory then covers 252 x 30 rows, or the output is NaN-masked by the guard's memory rule),
which changes the golden parity of the v2 cache replay for the first 7,560 rows. It moves the code
pin, so apply it to every stage in one rebuild, not between stages.

## Naming alignment for the same batch (research lane, 2026-10-29)

The config field `FeatureFactoryConfig.dropped_volume_max_fraction` should be `volume_dropped_max_fraction`
to follow the repo's key-to-field rule (`feature.amihud.min_valid_fraction` is `amihud_min_valid_fraction`,
`feature.volume.dropped_max_fraction` is `volume_dropped_max_fraction`). A pure rename of
`feature_factory.py`, `services/backfill_feature_factory.py`, `services/feature_vector_pipeline.py`,
`contract/registry.py`, `kernels/cross_tf.py` and their tests; outputs do not change, but it moves the
code pin, so it rides in this batch rather than between 186-26 stages.

## Calendar coverage for the same batch (research lane, 2026-10-29)

`_PMC_RANGE_START = "2005-01-01"` in `src/core/market_calendar.py` (comment: "1d goes back to 2006")
is stale: canonical 1d now starts in 2000 for many names, and `snapshot.build_grid` rejects any bar on
a day the calendar does not know, so no daily panel can start before 2005 (the daily residual family
amended its start for this, prereg section 10). Move the start to 2000-01-01 in the rebuild batch; the
module is imported by `backfill_feature_factory.py`, so it moves the code pin.

## Done when

1. `hma_slope_z` is explained or fixed (kernel or replay), and the fix is recorded with its test.
2. Every other column above has a declared timeframe applicability in the registry (UCR), so the S0
   read excludes a column on a timeframe where it carries no information, instead of reading zeros.
3. A check in the rebuild's completion record screens each stage's output for constant and all-NULL
   columns per timeframe, so a dead column is named when it appears. Run it for the later intraday
   stage as well.

Edits under `src/intelligence/features/` after the 186-26 pin are a code-key change: they apply to
later stages only if the pin moves, so batch them with the next kernel edit window.
