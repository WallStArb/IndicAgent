# The 2.0-2.5x wick band has no second witness in the vendor's own tape

Author: Claude (todo 595 measurement lane, 2026-11-09)
Informed by: `.planning/todos/pending/595-wide-wicks-2x-to-2-5x-need-a-second-witness.md`;
todo 594 (`isolated_wick` rule, commit aff4f022c); `docs/research/scrub-historical-pass.md` for format.

Status: measurement complete, proposal at the end. No rule landed from this lane; scripts
stayed in scratch.

## Band enumeration (the denominator)

594's multiplicative wick ratio, larger of `high / max(open, close)` and
`min(open, close) / low`, on `market_data_ohlcv_tradeable` 1d, ratio in [2.0, 2.5] with
neighbourhood span under 1.5 (adjacent traded bars plus the body): 60 bars, reproducing the
todo 595 table exactly (60 of 60 printed rows matched, 0 extra, 0 missing). Full list with
OHLC, ratio, span, side, vendor is in the todo table; this note does not repeat it.

The three named bad prints sit below the floor: IWM 2009-12-23 ratio 1.774, CSCO 2007-02-14
1.968, LNG 2005-09-01 1.957. The band's 2.0 floor misses them; they are measured alongside
the band below and counted in the extension cost.

Labels are the todo 595 classes, taken as ground truth for this note: 29 bad prints,
15 market-event bars (2008-09-18/19/29, 2008-10-10, 2015-08-24, 2020-03-16), 7 flash-crash
bars (2010-05-06, already quarantined by `busted_trade_window`), 9 low-priced or fallback
rows left unlabeled.

## Witness A: the day's 5m path

Measured on the canonical tradeable 5m view, scoped to days where bars exist; absence of
bars is recorded as no-verdict, never as a verdict. Coverage: 34 of 60 band days have any
5m bar (bad 18/29, event 9/15, flash 5/7, low-priced 2/9); all uncovered days are pre-2016
fallback or pre-backfill eras. Days with bars carry 57-81 bars, the ~78-bar RTH grid plus
some after-hours.

Result: on every covered day, both classes, the 5m path contains the 1d extreme exactly
(traversal 1.0), touched in exactly one 5m bar. At the outer 10% of the wick: 33 of 34
covered days show run 1, SIRI 2008-12-04 shows 2. Widening the band to 25% and 50% of the
wick changes nothing: median run 1 in every class, maxima 2 in mixed classes (BIL bad and
ACGL event at 50%). The todo's picture, a real low leaving a run of 5m bars near it, is
not what the tape holds; a real crash extreme on these days is as much a one-bar spike as
a bad print.

The extreme 5m bars also share shape across classes: open and close sit near the body side
of the bar while the extreme is an internal wick. Bad prints: close position within the
bar's range 0.000-0.009 from the body end on 12 of 18 (LH, MDLZ, T, AXON, D, LNG, NVR,
EWW, FUL, BIL upper; IWM, AMT, EXC, SLB lower at 0.94-1.0). Real events: ADSK, AMAT, AMGN,
CINF, CMCSA, COST, ACGL, KTOS all 0.85-1.0, the same V-spike. Time of day overlaps too:
all six 2008-09-19 extremes print in the opening 13:30 UTC bar, but 8 of 18 bad prints
also print 13:30-14:45 and AEP 2013-05-23 exactly at 13:30.

Raw check: the fake extremes are real rows of the vendor tape, not daily-only artifacts.
IWM 2006-06-15 20:05 UTC 5m (low 33.36, open 69.81, close 69.77) exists in `ohlcv_raw` and
in canonical; ACN's flash low 17.74 likewise. Canonical 1d, canonical 5m and raw 5m all
derive from the same vendor tape, so no aggregation of that tape can testify against a
print it served.

Second vendor: exists only from 2016 and only agrees because both vendors aggregate the
same consolidated tape. KTOS 2020-03-16: alpaca, ibkr and tradier all hold low 5 (real,
consistent with its class). DFTX 2019-04-22: ibkr high 15.5999 and tradier 15.6 agree, so
cross-vendor agreement does not even imply the print is good. FUBO 2016-07-20 has a single
vendor and no witness at all.

## Witness B: next-day confirmation

Next traded 1d bar, all 60 band rows plus the 3 named:

| cut | bad (29) | event (15) | flash (7) | low-priced (9) |
|---|---|---|---|---|
| trades through the wick extreme | 0 | 0 | 0 | 0 |
| trades through the day's close | 28 | 14 | 7 | 7 |
| wick-zone overlap, median / max | 0.015 / 0.333 | 0.058 / 0.164 | 0.039 / 0.067 | 0.011 / 0.500 |
| revisit within 5 sessions | 1 | 0 | 0 | 2 |

No cut separates. No bar in any class revisits its extreme the next day, so the
rejection arm is empty for both classes; the continuation arm fires on nearly everything.
Zone overlap ranges overlap between bad and event. The 5-session revisit is inverted: the
only labeled bad that gets revisited is BMNR 2012-08-13, and no event is.

## Confusion matrix on the labeled band (56 rows: 29 bad + 22 real + 5 unlabeled)

Best candidate cut from each witness family, evaluated on days where the witness exists:

| rule | true real | false real (bad flagged real) | no verdict |
|---|---|---|---|
| A: 5m touches extreme (run >= 1) | 14 of 14 covered real | 18 of 18 covered bad | 8 real, 11 bad |
| A: 5m lingers, run >= 2 in outer 10% | 0 of 14 | 0 of 18 (fires on nothing) | as above |
| B: next day trades through the extreme | 0 of 22 | 0 of 29 (fires on nothing) | 0 |
| B: next day trades through the close | 21 of 22 | 28 of 29 | 1 real, 1 bad |

Witness A as specified inverts: the tape always touches, so it clears every bad print it
can see. Tightening to run >= 2 discards everything. Witness B's rejection arm is empty
and its continuation arm does not separate. No threshold on either witness produces a
usable quadrant.

## Proposal

No scrub rule lands for the 2.0-2.5 band from this evidence, and the 2.5 floor of
`isolated_wick` should stay. The band's mixture is real: 2008, 2015-08-24 and 2020-03-16
crash bars sit at the same ratios, spans, 5m shapes and next-day behaviour as the bad
prints, because both come off the same vendor tape at the same granularity.

- Do nothing on ratio/span: 0 real bars falsely quarantined, 32 known bad prints remain
  served (29 band + IWM 2009-12-23, CSCO 2007-02-14, LNG 2005-09-01 below the floor).
- Extending the floor to 1.75 (span < 1.5) was measured: 44 additional rows. It captures
  the 3 named bads but also flags 4 known real event-date bars (IWM and TRMB 2008-09-19
  upper, ERIE 2008-10-10, HCA 2015-08-24) with no witness to save them. Rejected.
- A real second witness needs an independent tape: a second vendor's consolidated 1d
  before 2016 (not held; Alpaca starts 2016) or sub-5m granularity (not held). The
  DFTX case shows even cross-vendor agreement is weak evidence, since both vendors
  redistribute the same consolidated feed; treat second-vendor agreement as necessary,
  never sufficient, if it is ever used.

## Notes for the follow-on

- The six 2008-09-19 extremes and the five 2010-05-06 flash extremes all print in single
  opening or mid-session 5m bars with bad-print shape. Their lows are opening-auction or
  busted-window prints on the same tape; whether those specific lows are good is exactly
  the question this lane could not answer, and `busted_trade_window` plus the known-event
  labels remain the only handles.
- Failure-mode accounting for this pass: 26 of 60 band days have no 5m bars (recorded as
  no verdict, never inferred); band membership counted against the full traded universe,
  not current names (the 60 span 2000-2025 and include dead tickers DFTX, FRHC-era names);
  no rule was seeded and no data table written.
