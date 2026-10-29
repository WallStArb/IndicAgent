---
status: pending
priority: P0
filed: 2026-10-29
source: data lane diagnosis of the 186-26 intraday D-32 gate
---

# 5m slot_coverage counts a slot with no trades as missing for Alpaca SIP years

The 5m `slot_coverage` verdict fails 1,248 of 1,529 names against the 0.995 worst-year threshold, and
that blocks the intraday stage of the 186-26 feature rebuild (`check_bar_coverage` reads it). The gate is
measuring something the data cannot satisfy for thinly traded names:

- Canonical 5m is Alpaca SIP from 2016-01-04 (D-191-P). A SIP aggregate bar exists only for a 5-minute
  slot in which a trade printed. A slot with no trade has no bar, and that is a correct answer, not a gap.
- `slot_coverage` credits a missing slot only when it lies inside an answered window, and the answered
  windows it reads are `ohlcv_request` rows with route `SMART` and what_to_show `TRADES`
  (`COVERAGE_ROUTE`, `COVERAGE_WHAT_TO_SHOW` in `src/intelligence/bars/gap_plan.py`). The Alpaca 5m
  history was loaded without request windows: `ohlcv_request` holds Alpaca SIP rows only from
  2026-10-06 on (6,141 bars, 23 no_data), while `ohlcv_load` records 40,579 applied Alpaca 5m loads
  with `requested_start` 2016-01-01 to `requested_end` 2026-10-28.
- Measured: AAPL passes (0.9952; the short sessions are half days with 42 bars). MSM has 1,073 of its
  2,721 sessions since 2016 with fewer than 78 bars and not a half day, worst-year coverage 0.975.
  Worst-year coverage over the universe: 1,144 names at or above 0.9, 38 below 0.1.

## Fix

Count a slot as answered when it lies inside the requested range of an applied vendor load for that
series (`ohlcv_load.requested_start` to `requested_end`, outcome applied), in addition to the existing
IBKR answered windows. A load that returned zero bars for a range is an answer. Keep the existing
rule for IBKR-sourced years (a bar, or an answered window that a stored row corroborates).

Review points: the load range must cover the slot's session day inclusive of the end date; a refused or
failed load is not an answer; a range answered by SIP does not cover a day the vendor had no session
for (use the session calendar, as `answered_slots` already does); the 0.995 threshold stays an APR value.
Then re-run the audit and recount: names still below the threshold are real gaps, to be named holds.

Related and already fixed: `grid_parity` compared SIP-derived buckets to IBKR bars (commit 51e2cc323);
`coverage_cache` was starved by the fetcher lock (fix in progress, migration 542).
