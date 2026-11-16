---
status: pending
priority: P1
filed: 2026-11-16
source: step 7 D4 follow-up; independent level-break test of the 15 massive_only events on active names (lead ruling pending a filing witness)
---

# Unrecorded level breaks (CLBK, ATRO) and D7 split_continuity blind to them

## What

D7 `split_continuity` judges only the effective dates of recorded splits (and route seams), so a level
break with no corporate_action row is invisible to it. The test of the 15 Massive-only events on active
instruments (2026-11-16) found two such names:

- CLBK 2026-07-21 (Massive ratio 2.2): canonical close 24.50 to 11.08 (step 0.4522 against 1/2.2 = 0.4545),
  5m overnight 0.4461, volume 16.8M to 57.5M. Canonical, Alpaca and Massive raw all show the same unadjusted
  step; Alpaca did not restate history. No row of any type within 15 days. The bars are tradeable and the
  bar_quality_flag rules that fire are not in `threshold.bar_scrub.quarantine_rules`, so research would read
  a fabricated -54.8% return. Probably a share exchange (conversion) event.
- ATRO 2026-06-15 (ratio 1.2): ambiguous; price cannot separate a 1.2 split from a -5.4% move, volume shows
  no 1.2x, Alpaca did not restate. Needs a filing.

Cleared: ETHA, DD, AMCR, AGL, FUBO (recorded reverse splits, continuous); SCCO's four 0.5 to 1.2% events are
dividends, not splits (never record); CBSH, SITM, SNDK, VIXM fall after the data end.

## Scope

1. A non-price witness per name (SEC filing or exchange notice): event type, ratio, effective date.
2. If CLBK is a share exchange at 2.2: record a split row (last old-scale session 2026-07-20, factor 2.2)
   through the redate-capable `--apply-massive` path after D4 passes, reselect the name (1d, 5m, grid), and
   confirm D7 sees it continuous. ATRO is ruled on its witness alone.
3. Close the class: an unrecorded level break must reach a gate, not only the A3 sweep (a D7 check or a gate
   on the sweep output, decided with the todo 592 owner).

## Gates

The next D4 run is green with the row recorded; the A3 sweep lists no unexplained lone break on an active
name; recorded rows carry the witness in `detail`.
