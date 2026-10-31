---
status: pending
priority: P1
filed: 2026-10-29
source: data lane check of the 186-26 stage 1 output (feature_vectors_v2, tf 1d)
---

# Rebuilt 1d feature columns that are constant or all NULL must not reach the research read

## Status (2026-10-31)

Screened and root-caused; the fixes are batched for the next kernel-edit window (edits under
`src/intelligence/features/` after the 186-26 pin are a code-key change: they apply to later
stages only if the pin moves, so nothing lands between stages). The hma_slope_z fix and its
parity-golden change wait for that window.

## The screen (186-26 stage 1, 5,127,577 rows, 1,257 names, 2005-01-03 to 2026-09-30)

Pooled screen over eight names (SPY, AAPL, MSFT, JPM, XOM, SCCO, HON, KO): of 309 real columns,
18 all NULL and 22 constant. Most are intraday-session concepts degenerate on a daily bar by
construction (`hour_of_day_*`, `minute_of_hour_*`, `in_ny_session`, `in_london_kz`,
`in_overlap`, `power_hour`, `session_time_pos`, `opening_range`, the Asian and overnight session
distances, the intraday return divergences) - not kernel defects, but a column with no
information on a timeframe looks real to a reader. Two groups need a decision: `hma_slope_z`
(below) and the volume-profile/structure outputs on 1d (`poc_dist_atr`, `price_in_value_area`,
`va_position`, `hmm_vol_prob_elevated`, `amd_phase`, `amd_distribution_direction`,
`amd_manipulation_detected`, `manip_strength`, `sweep_detected` constant;
`distance_to_vah_atr`, `distance_to_val_atr`, `va_width_atr`, `nearest_hvn_*`, `nearest_lvn_*`,
`poc_rolling_dist_atr` all NULL): decide per column whether 1d is out of scope (NaN by
declaration in the registry) or the kernel is wrong.

Related property, not a defect: `adx`, `hurst`, `shannon`, `garch_ratio` change only every
`regime_cache_refresh_bars` rows, so on 1d they are piecewise constant for about 30 sessions; a
spec reading them should know the effective lag.

## Root cause of hma_slope_z (fixed in the next batch, not a kernel bug)

`FeatureCache.refresh_regime` appends one HMA slope per refresh (every
`feature.regime.cache_refresh_bars` = 30 rows) and `_zscore_from_deque` returns 0.0 until the
history holds `feature.momentum.zscore_window` = 252 slopes, so the first non-zero value needs
about 252 x 30 = 7,560 rows; SPY 1d has 5,465 rows, so the column is exactly 0.0 on every 1d row
(SPY: 5,465 of 5,465). The 0.0 is a fill that breaks `no_fill`. Fix: return NaN while the
history is short, which changes the v2 cache replay golden parity for the first 7,560 rows and
moves the code pin - apply in the batch, not between stages.

## Same-batch items

- Naming: `FeatureFactoryConfig.dropped_volume_max_fraction` should be
  `volume_dropped_max_fraction` per the key-to-field rule (pure rename across
  `feature_factory.py`, `services/backfill_feature_factory.py`, `services/feature_vector_pipeline.py`,
  `contract/registry.py`, `kernels/cross_tf.py` and tests; outputs unchanged, pin moves).
- Calendar start: `_PMC_RANGE_START = "2005-01-01"` in `src/core/market_calendar.py` is stale
  (canonical 1d starts in 2000 for many names; `snapshot.build_grid` rejects any bar on a day
  the calendar does not know, so no daily panel can start before 2005). Era recount done
  2026-10-30 (era start 2000-01-03 vs 2005-01-03): 41 names newly fall below 0.999 session
  coverage, all 41 among the 1,314 built names (list:
  `191-SESSION-COVERAGE-ERA-2000-NEWLY-FAILING.tsv`; worst STRL 0.9108 with 602 missing
  sessions, CRGY 0.9752, WEYS 0.9468, EFSC 0.9619; most 5-80 sessions). The change moves the
  `session_coverage` era to 2000 on its own (via `MarketCalendar.first_session`, commit
  `0be5cbc91`). Not free: either the data lane backfills the 2000-2004 holes for these names
  first, or the start stays 2005. Decision belongs with the data lane's hold list; the research
  lane does not move `_PMC_RANGE_START` until those names clear.
- Delete list after migration 543: migration 543 serves `fallback` volume (SMART), so
  `market_data_ohlcv_tradeable` has 0 NULL-volume rows on every timeframe (checked 2026-10-30);
  the NULL-volume handling from todos 560/563 has no input on current data. Delete rather than
  carry: `dropped_volume.py`, `Kernel.volume_reset`, `_masked_until_reset`, the dropped-share
  branch, APR key `feature.volume.dropped_max_fraction` (migration 541, retire via a migration)
  and the config field, the NaN handling in `_build_ctf_series`, and `STATUS_INPUT_GAP` /
  `_has_interior_gap` in the regime kernels - each replaced by one loud check that raises on
  non-finite volume reaching a volume kernel (a `venue` bar can still be NULL). Keep: the
  volume-basis segment handling (fallback is now SMART, about 0.75 of SIP, so the Alpaca seam is
  real), `_guard_downstream` if a basis seam can still produce masked rows, the none-mask fix,
  the end-to-end dropped-bar test (repointed at a basis seam) and the non-vacuous invariant
  test. The 1d features built before 543 for the 147 fallback names are stale; rebuild them in
  the same batch. Open measurement: the per-name SMART/SIP median ratio from 2024 is 0.37
  (38 names, p5 0.00, p95 0.82), far below the 0.75 the basis table assumes - thin names and
  differing dates, not a clean ratio; measure on overlapping dates before trusting the basis
  segmentation to remove the level shift.

## Done when

1. `hma_slope_z` is fixed (NaN during warmup) with its test and golden regeneration.
2. Every screened column has a declared timeframe applicability in the registry (UCR), so the S0
   read excludes a column on a timeframe where it carries no information, instead of reading
   zeros.
3. A check in the rebuild's completion record screens each stage's output for constant and
   all-NULL columns per timeframe, so a dead column is named when it appears; run it for the
   later intraday stage as well.
