---
status: closed
priority: P1
filed: 2026-11-05
source: lead (indicagent-4d), from the todo 594 robustness grid
closed: 2026-11-13
---

# Wide wicks between 2.0x and 2.5x on 1d need a second witness

## Status (measured 2026-11-09, todo 595 lane)

Band enumerated: 60 bars, exact reproduction of the table below. Both witnesses measured and
neither separates bad prints from real crash days. The day's 5m path contains the 1d extreme
in exactly one bar on every covered day (34/60), bad prints and real events alike, with the
same spike shape and overlapping times of day; next-day confirmation has an empty rejection
arm (no bar of any class revisits its extreme) and a non-separating continuation arm
(28/29 bad vs 14/15 event trade through the close). The structural cause: canonical 1d,
canonical 5m and `ohlcv_raw` 5m all come off the same vendor tape, and the fake prints are
real rows of it. Recommendation in `docs/research/wick-band-2.0-2.5-second-witness.md`: keep
the `isolated_wick` 2.5 floor, no rule for this band; the 1.75 extension was measured and
rejected (captures the 3 named bads below the floor but false-flags 4 known event-date
bars). A real second witness needs a second vendor pre-2016 or sub-5m granularity, neither
held. Lead decides whether any residual action (for example accepting the 4 known false
positives to recover 3 named bads) is worth taking; nothing landed.

## What

Todo 594's `isolated_wick` rule flags a wick of at least 2.5x the body
(`threshold.bar_scrub.isolated_wick.min_ratio`) in a neighbourhood spanning under 1.5x. Below the
ratio floor, the 1d band 2.0x to 2.5x with a narrow neighbourhood (span < 1.5) still holds bad
prints (IWM 2009-12-23 high 112.03 on a 62.69 body, CSCO 2007-02-14 high 54.10 on 27.49, LNG
2005-09-01 high 78.10 on 39.91) mixed with real crash days (2008-09-18/19/29, 2008-10-10,
2015-08-24, 2020-03-16) and low-priced names. Ratio and span alone cannot separate them: the
ratio axis is a continuum here and real events sit at the same spans as bad prints.

## Next

A different discriminator for this band, for example:
- agreement with a second vendor's bar on the same session (Alpaca SIP from 2016, the raw
  `ohlcv_raw` rows of another kind, Yahoo's daily range);
- the 5m path within the day: a real intraday low leaves a run of 5m bars near it, a bad print
  is one bar (or none, when the 5m tape never saw it).

Measure the discriminator on the band below before seeding any rule, then extend the scrub.

## The band (1d, measured 2026-11-05, 60 bars)

Class is a first pass from the date and price level, not a verdict: "bad print" means a liquid
name with an isolated wick on an ordinary day; "market-event day" needs the second witness;
2010-05-06 bars are already covered by `busted_trade_window` when beyond 60%.

| date | symbol | source | open | high | low | close | ratio | span | served | class |
|---|---|---|---|---|---|---|---|---|---|---|
flash crash (busted_trade_window covers)                  7
| 2000-12-20 | ZD | ibkr/named | 0.48 | 0.52 | 0.24 | 0.48 | 2.00 | 1.444 | yes | low-priced or fallback name: plausibly real |
| 2004-09-14 | STLD | ibkr/named | 9.25 | 9.28 | 4 | 9.21 | 2.30 | 1.047 | yes | bad print (liquid name, isolated) |
| 2004-10-28 | PNW | ibkr/named | 42.8 | 86.08 | 42.16 | 42.69 | 2.01 | 1.020 | yes | bad print (liquid name, isolated) |
| 2004-11-17 | MBWM | ibkr/named | 36.51 | 36.82 | 14.99 | 36.81 | 2.44 | 1.027 | yes | bad print (liquid name, isolated) |
| 2004-12-30 | TPR | ibkr/named | 28.6 | 28.7 | 13.615 | 28.415 | 2.09 | 1.023 | yes | bad print (liquid name, isolated) |
| 2005-04-14 | ULH | ibkr/named | 18.78 | 18.78 | 8.69 | 17.86 | 2.06 | 1.089 | yes | bad print (liquid name, isolated) |
| 2005-04-20 | WHR | ibkr/named | 64.64 | 129.28 | 61.24 | 61.7 | 2.00 | 1.088 | yes | bad print (liquid name, isolated) |
| 2005-08-12 | AMZN | ibkr/named | 2.23 | 4.95 | 2.2 | 2.21 | 2.22 | 1.037 | yes | low-priced or fallback name: plausibly real |
| 2005-12-12 | COKE | ibkr/named | 4.58 | 4.66 | 1.89 | 4.56 | 2.41 | 1.031 | yes | low-priced or fallback name: plausibly real |
| 2006-04-27 | VSEC | ibkr/named | 9 | 9 | 3.75 | 8.13 | 2.17 | 1.222 | yes | bad print (liquid name, isolated) |
| 2006-05-08 | EWL | ibkr/named | 27.07 | 55.26 | 22.68 | 22.75 | 2.04 | 1.204 | yes | bad print (liquid name, isolated) |
| 2006-06-15 | IWM | ibkr/named | 68.05 | 69.97 | 33.36 | 69.74 | 2.04 | 1.048 | yes | bad print (liquid name, isolated) |
| 2006-07-18 | INTC | ibkr/named | 17.93 | 18.27 | 7.95 | 18.2 | 2.26 | 1.055 | yes | bad print (liquid name, isolated) |
| 2006-12-15 | LH | ibkr/named | 61.88 | 132.34 | 61.68 | 61.81 | 2.14 | 1.010 | yes | bad print (liquid name, isolated) |
| 2007-02-27 | BIO | ibkr/named | 70.73 | 151.3 | 67.04 | 71.75 | 2.11 | 1.094 | yes | bad print (liquid name, isolated) |
| 2007-04-18 | MDLZ | ibkr/named | 21.59 | 47.55 | 21.04 | 21.13 | 2.20 | 1.025 | yes | bad print (liquid name, isolated) |
| 2007-04-27 | T | ibkr/named | 29.31 | 63.34 | 29.07 | 29.17 | 2.16 | 1.026 | yes | bad print (liquid name, isolated) |
| 2007-07-19 | AMT | ibkr/named | 43.91 | 45.28 | 21.8 | 45.13 | 2.01 | 1.054 | yes | bad print (liquid name, isolated) |
| 2007-07-26 | AXON | ibkr/named | 14.27 | 30 | 13.52 | 14.05 | 2.10 | 1.115 | yes | bad print (liquid name, isolated) |
| 2007-07-31 | D | ibkr/named | 42.38 | 98.9 | 41.83 | 42.1 | 2.33 | 1.054 | yes | bad print (liquid name, isolated) |
| 2007-08-07 | LNG | ibkr/named | 32.51 | 89.28 | 32.09 | 35.76 | 2.50 | 1.189 | yes | bad print (liquid name, isolated) |
| 2007-08-15 | NVR | ibkr/named | 567 | 1138 | 535.99 | 542.57 | 2.01 | 1.154 | yes | bad print (liquid name, isolated) |
| 2007-08-17 | EWW | ibkr/named | 54.06 | 116.16 | 52.84 | 54.75 | 2.12 | 1.174 | yes | bad print (liquid name, isolated) |
| 2007-09-10 | EOG | ibkr/named | 34.9 | 84.9 | 34.21 | 35.22 | 2.41 | 1.036 | yes | bad print (liquid name, isolated) |
| 2007-09-10 | FUL | ibkr/named | 26.81 | 63.2 | 26.2 | 26.92 | 2.35 | 1.039 | yes | bad print (liquid name, isolated) |
| 2007-09-25 | SLB | ibkr/named | 103.27 | 105 | 42.85 | 104.66 | 2.41 | 1.057 | yes | bad print (liquid name, isolated) |
| 2007-11-30 | BIL | ibkr/named | 91.98 | 223.72 | 91.84 | 91.9 | 2.43 | 1.004 | yes | bad print (liquid name, isolated) |
| 2007-11-30 | MTG | ibkr/named | 23.16 | 48.5 | 23.16 | 23.67 | 2.05 | 1.211 | yes | bad print (liquid name, isolated) |
| 2008-01-04 | XLE | ibkr/named | 39.75 | 89.08 | 38.75 | 38.75 | 2.24 | 1.059 | yes | bad print (liquid name, isolated) |
| 2008-02-25 | EXC | ibkr/named | 56.03 | 56.35 | 26.25 | 55.81 | 2.13 | 1.038 | yes | bad print (liquid name, isolated) |
| 2008-09-18 | STT | ibkr/named | 66.08 | 68.7 | 29.09 | 59 | 2.03 | 1.262 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | ADSK | ibkr/named | 35.13 | 37.45 | 15.06 | 35.71 | 2.33 | 1.153 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | AMAT | ibkr/named | 16.44 | 16.44 | 7.17 | 15.9 | 2.22 | 1.075 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | AMGN | ibkr/named | 61.44 | 63 | 27 | 59.97 | 2.22 | 1.098 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | CINF | ibkr/named | 34.84 | 34.84 | 13.68 | 33.6 | 2.46 | 1.318 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | CMCSA | ibkr/named | 9.85 | 9.98 | 4.31 | 9.7 | 2.25 | 1.080 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-19 | COST | ibkr/named | 70.75 | 71 | 30.7 | 66.09 | 2.15 | 1.101 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-29 | ACGL | ibkr/named | 8.4 | 8.4 | 3.67 | 7.94 | 2.16 | 1.122 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-29 | R | ibkr/named | 60.18 | 131.99 | 58.02 | 58.18 | 2.19 | 1.066 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-29 | STRL | ibkr/named | 16.98 | 17.31 | 7.7 | 16.16 | 2.10 | 1.160 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-29 | WSBF | ibkr/named | 9.26 | 9.43 | 4.24 | 8.59 | 2.03 | 1.109 | yes | market-event day: real or bad, needs a second witness |
| 2008-09-29 | YORW | ibkr/named | 13.75 | 13.75 | 6.22 | 12.49 | 2.01 | 1.123 | yes | market-event day: real or bad, needs a second witness |
| 2008-10-10 | MYRG | ibkr/named | 10.92 | 10.92 | 5 | 10.14 | 2.03 | 1.209 | yes | market-event day: real or bad, needs a second witness |
| 2008-12-04 | SIRI | ibkr/named | 1.7 | 2.2 | 0.8 | 1.6 | 2.00 | 1.267 | yes | low-priced or fallback name: plausibly real |
| 2009-02-20 | GSAT | ibkr/named | 3.15 | 6.6 | 2.85 | 3.15 | 2.10 | 1.316 | yes | low-priced or fallback name: plausibly real |
| 2010-05-06 | ACN | ibkr/named | 41.94 | 42.3 | 17.74 | 41.09 | 2.32 | 1.063 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | BRO | ibkr/named | 9.85 | 9.93 | 4.02 | 9.49 | 2.36 | 1.067 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | EPI | ibkr/named | 22.26 | 22.42 | 10 | 21.51 | 2.15 | 1.062 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | G | ibkr/named | 16.31 | 16.55 | 6.67 | 15.94 | 2.39 | 1.085 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | EXLS | ibkr/named | 3.25 | 3.4 | 1.48 | 3.18 | 2.15 | 1.088 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | EZA | ibkr/named | 56.01 | 56.76 | 23 | 53.88 | 2.34 | 1.076 | yes | flash crash (busted_trade_window covers) |
| 2010-05-06 | IJR | ibkr/named | 15.3 | 15.49 | 6.83 | 14.88 | 2.18 | 1.091 | yes | flash crash (busted_trade_window covers) |
| 2012-08-13 | BMNR | ibkr/named | 120 | 120 | 60 | 120 | 2.00 | 1.200 | yes | bad print (liquid name, isolated) |
| 2013-05-07 | FRHC | ibkr/named | 0.42 | 0.5 | 0.205 | 0.4375 | 2.05 | 1.482 | yes | low-priced or fallback name: plausibly real |
| 2013-05-23 | AEP | ibkr/named | 48.18 | 48.54 | 22.28 | 48.28 | 2.16 | 1.047 | yes | bad print (liquid name, isolated) |
| 2014-05-09 | FRHC | ibkr/named | 0.21 | 0.4225 | 0.1875 | 0.2 | 2.01 | 1.200 | yes | low-priced or fallback name: plausibly real |
| 2015-08-24 | KKR | ibkr/named | 17.73 | 19.43 | 8 | 18.69 | 2.22 | 1.130 | yes | market-event day: real or bad, needs a second witness |
| 2016-07-20 | FUBO | ibkr/fallback | 720.724 | 1081.09 | 360.362 | 1081.09 | 2.00 | 1.500 | yes | low-priced or fallback name: plausibly real |
| 2019-04-22 | DFTX | ibkr/fallback | 6 | 15.5999 | 6 | 6.612 | 2.36 | 1.378 | yes | low-priced or fallback name: plausibly real |
| 2020-03-16 | KTOS | alpaca/sip_rth | 11.71 | 11.89 | 5 | 11.05 | 2.21 | 1.355 | yes | market-event day: real or bad, needs a second witness |

## Closure 2026-11-13

Closed 2026-11-13 (lead): Superseded by the owner ruling of 2026-11-13 (todo 600): the wide 1d wicks were judged on the IBKR-era canonical, and the second witness this todo sought was IBKR or Alpaca against itself. Canonical 1d becomes the Massive day file (official prints); any wick still wide there surfaces through the nightly D7 wick checks after step 7 and gets its own todo then.
