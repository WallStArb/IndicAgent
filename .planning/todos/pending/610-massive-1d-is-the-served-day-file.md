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

## Measured 2026-11-13 (lead, after the r5h 8a run): the pre-2008 dispute is a close definition

120 seeded names per year, share of days where IBKR smart_trades 1d close equals (within 2 bp of the name's median log ratio) the Massive day-file close, and where it equals the close of Massive's last regular-hours 5m bar (15:55 ET, `sip_flat_agg`):

| Year | IBKR = day-file close | IBKR = last RTH 5m close | day file = last RTH 5m |
|---|---|---|---|
| 2006 | 0.307 | 0.808 | 0.338 |
| 2010 | 0.903 | 0.336 | 0.350 |
| 2013 | 0.937 | 0.448 | 0.475 |
| 2018 | 0.987 | 0.591 | 0.598 |

Before about 2008 IBKR's daily close is the last regular-hours trade; from about 2008 it is the official close, which the Massive day file carries in every era. Massive's minute files (a separate product) witness IBKR's early print. Opens agree at the same rate across eras (2006: 82 percent within 2 bp, against 83 to 93 percent in 2010 to 2020), so the dispute is the close field only. IBKR `venue_*` 1d bars are not a usable witness (a per-venue aggregate; they disagree with both sides even in 2018).

Lead ruling 2026-11-13: 2004 to 2007 1d is a close-definition difference, not a defect on either side. The served 1d keeps one definition across the whole span (the official close of the day file); taking IBKR before 2008 would put a definition seam at 2008. The 8a runner gets a definition-witness test (declared in the design doc before code, disclosed as written after the r5h results). 2008 to 2013 is separate: a 6 to 10 percent residual the last-trade convention does not explain; its 1d stop stands until diagnosed.

## Gates

Per-era close-convention table in the 8a runner (informational); the 2003 to 2007 eras reported as unresolved with the candidate witnesses named; a decision recorded here before any daily test reads 2003 to 2007.

## Measured 2026-11-23 (indicagent-fe, read-only): canonical close against Yahoo, 2004 to 2011

Witness: Yahoo `Close` (split-adjusted, not dividend-adjusted), the official close. Sample: 120 names with membership rows in each of 2005, 2006 and 2007, ordered by sha256("610" + symbol); 63 had Yahoo history (the other 57 are dead or delisted names Yahoo no longer serves, so the sample is survivor-biased and says nothing about them). Statistic per name-year: share of days whose canonical-to-Yahoo log ratio is within 2 bp of that name-year's median (the median absorbs the level of split adjustment). About 15,800 days per year.

| Year | Names | Mean share within 2 bp | Name-years below 90 percent |
|---|---|---|---|
| 2004 | 62 | 0.982 | 3.2 percent |
| 2005 | 63 | 0.997 | 0 |
| 2006 | 63 | 0.997 | 0 |
| 2007 | 63 | 0.972 | 11.1 percent (7 names, 84 to 89 percent) |
| 2008 | 63 | 0.981 | 4.8 percent |
| 2009 | 63 | 0.977 | 3.2 percent |
| 2010 | 63 | 0.993 | 1.6 percent |
| 2011 | 63 | 0.988 | 1.6 percent |

- The canonical Massive close is the official close in 2005 and 2006 at 99.7 percent, as in the control years; there is no 2003-to-2007 seam against Yahoo. The earlier IBKR dispute is IBKR's last-trade close (ruling 2026-11-13), not a canonical defect.
- 2007 is lower in 7 of 63 names (FFIN, STRL, FELE, MGRC, CMCO, CSCO, RRGB; 84 to 89 percent). Not diagnosed; at n = 63 this is a disclosure, not a finding.
- Scope C name-years in 2003 to 2007: 13,427 of 100,805 (13.3 percent). The measured disagreement rate (a name-year below 90 percent) is 0 percent in 2005 and 2006 and 11.1 percent in 2007 in the sample, so at most about 0.4 percent of scope C name-years (2007: 3,294 of 100,805, times 11.1 percent) are touched in the sample's reading.
- The 143 names with no Massive before their first day are holes (todo 632), not a close-convention question: canonical has no close there to compare.
- Second witness (tape plus a vendor) was not run; Yahoo alone is the one witness here, and the rule treats a Yahoo-only call as the incumbent-defect floor, not a defect finding.

Proposal for the lead (no rule is needed on this evidence): record the 2005 to 2007 closes as the official close, agreeing with Yahoo, and let family 9's 2005 to 2007 inputs read canonical as is; disclose the 2007 residual (7 of 63 sampled names below 90 percent) with the sample size. Re-open only if the 2007 residual grows on a larger sample.
