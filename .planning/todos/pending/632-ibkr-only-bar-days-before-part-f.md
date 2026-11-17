---
status: pending
priority: P1
filed: 2026-11-17
source: A3 triage (todo 629) found canonical coverage holes that only IBKR raw fills; Part F deletes that raw
---

# IBKR raw holds 1d bar-days that canonical lacks, ahead of the Part F delete

## What

The 629 triage found four names (GSAT 2014, NESR, PMTS, SMCI) whose canonical series has a multi-month hole where IBKR
raw has real bars. A read-only count on 2026-11-17: 451,735 distinct (symbol, day) 1d IBKR bars with volume, on or
after 2003-09-10, in 385 active names, exist in no canonical row (about 30,000 to 37,000 a year to 2015, 1,000 to
6,000 a year since). Part F deletes all IBKR raw from 2003-09-10 with no export (owner 2026-11-13).

## Done

A gzip CSV export of every IBKR 1d raw row not in canonical (713,025 rows including kind variants) is at
`/home/bg/archive/ibkr_raw_1d_only_2026_11_17/` (SHA256 file beside it). It is a local copy only; the owner's no-export
ruling stands for everything else.

## Open

1. Owner: confirm Part F proceeds with this export in hand (recommended), or hold Part F to fill the holes first.
2. Why canonical lacks these days (Massive coverage hole, zero-volume policy, or pre-listing history under a reused
   ticker) by class, before the first counted test: a hole inside a name's live history is a no_fill gap in research.
3. 5m was not exported: IBKR 5m carries extended-hours bars that canonical holds out by policy, so a bar-count of
   differences is not a coverage measure.
