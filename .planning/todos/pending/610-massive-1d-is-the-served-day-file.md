---
status: pending
priority: P1
filed: 2026-11-12
source: todo 600 step 6, 8a day-file-against-minute check; reversed by the lead 2026-11-12 after measuring the close convention
---

# Massive 1d is the served day file; the 2003 to 2007 close convention needs a third witness

## Ruling (lead 2026-11-12), reverses this todo's first version

Massive 1d is the served day file (kind sip_flat_agg at 1d, as already loaded). The design's section 3 fallback (build 1d from RTH minute rows when the day close differs from the RTH aggregate on more than 1 percent of names) is rejected: it rested on the guess that extended-hours trades cause the difference. Measured:

- The day-file close is the official consolidated close (the closing-auction print). On liquid names it equals the last regular-hours minute close on 20 to 50 percent, the 16:00 minute bar's open or close on 2 to 42 percent, and neither on 14 percent (2024) to 76 percent (2008) (sampled days 2004 to 2024; script in the lead's scratchpad, to be folded into the runner). In 2012 AAPL and XOM the day close equals the open of the 16:00 bar, which a cut below 16:00 drops. A 1d built from minutes can never reproduce the official close.
- The worker's 8a run: the RTH-built 1d fails against IBKR 1d in every era (return agreement 33 to 96 percent, level 25 to 83 percent), while the served day file agrees with IBKR 1d at 99.9 percent or better on returns from 2014 and 92 to 99 percent in 2008 to 2013.
- Day-file volume carries a different basis: above even the all-hours minute sum (AAPL 2024-06-13: day 97.9M, all-hours minutes 88.6M, RTH 82.4M). That also explains the smooth drift of the IBKR/Massive volume ratio (1.0 in 2003 to 0.5 in 2025). It is a labelled basis (todo 518 mechanism, the volume guard), not a defect.

Consequence: no new 1d build; step 7 uses the loaded day-file 1d raw rows; this todo no longer gates step 7.

## Open: 2003 to 2007 close convention

In 2003 to 2007 the day file disagrees with IBKR 1d at 44 to 50 percent on returns while the RTH-built 1d agrees at 94 to 96 percent in 2006 and 2007, so either IBKR's early close convention or Polygon's early day close differs. It needs a third witness (an exchange-official close source) before those eras feed a daily test; the 8a runner reports them as unresolved, never pass or stop, and they do not block 2008 onward. Until settled, daily tests that cross the 2007/2008 seam must not read cross-era returns from the pre-2008 span.

## Gates

Per-era close-convention table in the 8a runner (informational); the 2003 to 2007 eras reported as unresolved with the candidate witnesses named; a decision recorded here before any daily test reads 2003 to 2007.
