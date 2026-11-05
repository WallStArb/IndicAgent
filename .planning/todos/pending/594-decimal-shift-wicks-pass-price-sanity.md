---
status: pending
priority: P0
filed: 2026-11-05
source: lead (indicagent-4d), from the FXY finding in the 2026-11-05 integration triage
---

# Decimal-shifted wicks pass price_sanity; gate the corpus rerun on a rule

## What

`price_sanity` flags a bar only at 10x, and a decimal-shifted print sits at about 9.9x (true
high near the close times 10). Canonical 1d, measured 2026-11-05: 202 bars with a wick of at
least 3x the body (high / max(open, close) or min(open, close) / low), 192 of them `ibkr/named`
before 2016, 8 `ibkr/fallback`, 2 `alpaca/sip_rth`. The tradeable view still serves 59 of them
(34 at 3-5x, 25 at 5-10x). Examples: SPY 2007-05-25 high 1511.7 / close 151.8; BHP 2006-05-26
high 362.76 / close 36.85; GS 2005-09-27 low 12.15 / close 119.77; IWM 2005-01-28 low 6.32 /
close 61.365; EZU 2007-04-23 high 500 / close 57.38; KRE 2007-09-18 high 400 / close 46.18.
Every range kernel (ATR, Garman-Klass, Parkinson, high-low range, bar position) reads these as
real. FXY 2008-09-24 (high 940.3) was quarantined by hand as `operator_bad_bar`; the list is not
the fix for a class.

## Decision (lead)

A rule, not a list, at the bar_scrub altitude (pure function of the bar and its neighbours):
- Detect a decimal shift: a wick whose ratio to the body sits near a power of ten (10, 100), within
  an APR log tolerance, flags `decimal_shift_wick`.
- Measure the false-positive base rate first (feedback memory, 587 lesson): report the ratio
  distribution and the neighbour context (the prior and next session's range) for every 3x+ bar,
  and show that real wide-range days (crash days, halts, gap days) do not fire.
- Quarantine through the existing bar_scrub path; the tradeable view then hides the bar. Prefer
  repairing nothing: raw is untouched; canonical keeps the bar, flagged.
- Same check on 5m, 15m and 1h canonical before the rerun.
- When the rule covers FXY, remove FXY from `operator_bad_bars.csv` (one mechanism per class).

## Done when

The rule lands with its base-rate evidence; the tradeable view serves no bar whose wick is a
decimal shift on any timeframe; a D7 check counts them per name. This gates the 584 rerun pin.
