---
status: pending
priority: P0
filed: 2026-09-27
source: phase 186 planning (plan 186-12), confirmed from source 2026-09-27
---

# Intraday macro features read the same day's daily close (lookahead)

## What

`build_cross_asset_series` (`src/intelligence/features/cross_asset_series.py`) keys records by
date, and the record for date d is built from 1d bars dated on or before d (`bisect_right` over
bar dates), so it includes date d's close. `compute_batch` (`src/intelligence/feature_factory.py`
lines 7734 and 7758) looks records up with `bar_ts.date()`. A 5m, 15m or 1h bar at 10:00 ET on
date d therefore reads values built from the 16:00 close of the same day. The factor betas use
the same lookup.

Affected intraday columns: `vix_z`, `flight_quality`, `yield_slope_z`, `tip_tlt_ret_z`,
`hyg_lqd_ret_z`, the three `sb_corr` columns, `equity_beta_z`, `rate_beta_z` and the two macro
products. 1d rows are not affected (a 1d row is stamped for the date whose close it already
includes).

## Exposure

No active research family reads these columns (checked 2026-09-27: `src/intelligence/research`,
research configs, pre-registrations and the verdict ledger; only a coverage note in the phase
179 pre-registration). Any legacy IC or ensemble result on these intraday columns carries the
leak; plan 186-12 task 3 checks summary cards and the ledger and records affected verdicts.

## Fix

Plan 186-12 task 3: failing test first, then align each intraday row to the latest daily close
at or before the bar's end (availability time), then regenerate the golden fixture, which may
change only these columns on intraday cases. Stored `feature_vectors` rows are corrected by the
phase 186 rebuild; until then, no research may read these columns at intraday timeframes.
Plan 186-15 checks the same class in `ctf_by_ts` (higher-timeframe bar starts looked up with
`bisect_right`).
