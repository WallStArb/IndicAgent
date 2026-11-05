---
status: closed
priority: P0
filed: 2026-11-05
closed: 2026-11-05
source: lead (indicagent-4d), from the FXY finding in the 2026-11-05 integration triage
---

# Isolated wicks and busted-trade prints pass price_sanity; gate the corpus rerun on two rules

## What

`price_sanity` flags a bar only at 10x, and a decimal-shifted print sits at about 9.9x (true
high near the close times 10). Canonical 1d, measured 2026-11-05: 202 bars with a wick of at
least 3x the body (high / max(open, close) or min(open, close) / low), 192 of them `ibkr/named`
before 2016, 8 `ibkr/fallback`, 2 `alpaca/sip_rth`. The tradeable view still served 59 of them.
Examples: SPY 2007-05-25 high 1511.7 / close 151.8; BHP 2006-05-26 high 362.76 / close 36.85;
GS 2005-09-27 low 12.15 / close 119.77; EZU 2007-04-23 high 500 / close 57.38; KRE 2007-09-18
high 400 / close 46.18. Every range kernel (ATR, Garman-Klass, Parkinson, high-low range, bar
position) reads these as real.

## Base rate (the evidence, measured 2026-11-05)

Every canonical bar with a wick of at least 3x, classified by the first brief: decimal shift
(ratio near 10 or 100 and the shifted value inside the neighbours' range), plausible real (wide
neighbours, a known event, or a ratio not near a power of ten), other.

| tf | 3x+ bars | served | decimal shift | other | plausible real |
|---|---|---|---|---|---|
| 1d | 202 | 59 | 21 | 20 | 161 |
| 1h | 74 | 74 | 5 | 6 | 63 |
| 15m | 74 | 72 | 5 | 6 | 63 |
| 5m | 90 | 74 | 4 | 12 | 74 |

Vendors: 1d 192 ibkr/named, 8 ibkr/fallback, 2 alpaca/sip_rth; 5m all ibkr/named; 1h and 15m
derived from the 5m grid. The power-of-ten idea failed: the distance from a power of ten is a
continuum from 0 to 0.15 with no gap (round-number stubs KRE 400, EZU 500 sit at 0.054 to
0.062), and 241 of the 279 served 3x+ bars are not near a power of ten at all but sit in a
neighbourhood spanning at most 1.25x: one class, isolated bad prints. Real wide days are the
ones whose neighbours move too (microcaps BMNR, RCAT, APLD) or the 2010-05-06 stub prints.

Robustness grid (bars flagged / served before the rule) for the adopted rule:

| min_ratio | span | 1d | 1h | 15m | 5m |
|---|---|---|---|---|---|
| 2.5 | 1.25 | 197/63 | 84/84 | 80/78 | 80/66 |
| 2.5 | 1.5 | 205/66 | 85/85 | 84/82 | 84/69 |
| 2.5 | 2.0 | 214/72 | 86/86 | 85/83 | 85/70 |
| 3 | 1.25 | 181/47 | 74/74 | 71/69 | 69/55 |
| 3 | 1.5 | 187/48 | 75/75 | 75/73 | 73/58 |
| 3 | 2.0 | 194/52 | 76/76 | 76/74 | 74/59 |
| 4 | 1.25 | 168/34 | 65/65 | 62/60 | 61/47 |
| 4 | 1.5 | 174/35 | 66/66 | 66/64 | 65/50 |
| 4 | 2.0 | 178/36 | 67/67 | 67/65 | 68/51 |

The span axis is a plateau. The ratio axis slopes, but every narrow-neighbour bar between 2.5x
and 3x (46 inspected across timeframes) is a bad print; real crash and split days appear below
2.5x on 1d (todo 595 holds that band). Between span 1.5 and 2.0 the margin holds microcaps
(BMNR 2023-07-24, PATK 2008-10-06), CORT 2007-09-11 (a 100000 high, its own neighbour wide) and
three already-quarantined bars.

## Decision (lead, 2026-11-05)

A rule, not a list, at the bar_scrub altitude (pure functions of the bar and its neighbours):
- `isolated_wick`: a wick ratio at least `threshold.bar_scrub.isolated_wick.min_ratio` (2.5)
  with the adjacent traded bars plus the body spanning less than
  `threshold.bar_scrub.isolated_wick.max_neighbour_span` (1.5). Seeds `[rca_analysis]`.
- `busted_trade_window`: windows the exchanges broke by rule, from
  `config/bars/busted_trade_windows.csv` (date, ET window, max deviation, citation); it starts
  with 2010-05-06 14:40-15:00 ET, 60% from the last print at or before 14:40. Every bar in the
  window whose high or low lies beyond the deviation flags.
- Both quarantine (migration 580 appends them to `threshold.bar_scrub.quarantine_rules`); raw is
  untouched; canonical keeps the bar, flagged; all four timeframes.
- FXY 2008-09-24 left `operator_bad_bars.csv`: `isolated_wick` flags it (one mechanism per class).
- D7 gains `isolated_wick`: served bars the rule flags, counted per name and timeframe.

## Landed 2026-11-05

Flags written by `ops_scrub_historical_pass.py --rules isolated_wick busted_trade_window --apply`
(dry run first, same counts):

| tf | isolated_wick | busted_trade_window |
|---|---|---|
| 1d | 205 | 32 |
| 1h | 85 | 20 |
| 15m | 84 | 20 |
| 5m | 84 | 34 |

Commit aff4f022c (code, migration 580 applied live). Tradeable view after: none of the 564 flagged bars is served on any timeframe (a join of the flags against `market_data_ohlcv_tradeable`), and the D7 `isolated_wick` check run live finds 0 served of the 24 remaining 2.5x+ candidates. FXY 2008-09-24 is quarantined by `isolated_wick` and its `operator_bad_bar` row is gone (the split calendar audit re-run wrote the 13 remaining rows).

Open edges: two adjacent bad prints widen each other's span and both stay served (measured: the
CORT 2007-09-11 case); new intraday bars are not scrubbed nightly (only the daily rerun calls
the scrub), so D7's `isolated_wick` count is the guard until an intraday scrub runs; derived
15m/1h bars are flagged directly, and a re-derivation that leaves the quarantined 5m bar out
is cleared by the next scrub pass.
