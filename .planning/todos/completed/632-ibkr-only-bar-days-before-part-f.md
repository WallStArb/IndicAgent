---
status: completed
priority: P1
filed: 2026-11-17
source: A3 triage (todo 629) found canonical coverage holes that only IBKR raw fills; Part F deletes that raw
---

# IBKR raw holds 1d bar-days that canonical lacks, ahead of the Part F delete

## What

The 629 triage found four names (GSAT 2014, NESR, PMTS, SMCI) whose canonical series has a multi-month hole where IBKR
raw has real bars. A read-only count on 2026-11-17 (overstated, corrected to 359,919 real holes below): 451,735 distinct (symbol, day) 1d IBKR bars with volume, on or
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

## Classification measured 2026-11-23 (indicagent-fe, read-only)

Input: the local export (451,735 distinct symbol-days with volume, 385 names). Each day was looked up in canonical 1d by calendar date (`timestamp::date`), then classed against Massive raw 1d. Scope C is the name-years with any `universe_membership` row. Reads chunked at 200 names, single connection.

| Class | Days | Names | In scope C |
|---|---|---|---|
| Present in canonical by calendar date (not a hole) | 91,816 | 46 | 88,260 |
| Before the name's first Massive day | 341,638 | 323 | 6,876 (143 names) |
| Hole inside the name's Massive span | 4,829 | 46 | 908 (15 names) |
| Massive row exists, canonical has none | 6,080 | 2 | 0 |
| No Massive data for the name | 7,372 | 5 | 0 |

- The 91,816 are an export artifact: the export keyed on exact timestamp, and early canonical rows sit at 00:00Z (IBKR convention) while Massive rows sit at 05:00Z. Real holes are 359,919 days, not 451,735.
- Scope C touched: 7,784 real hole days, 0.74 percent of the 1,054,675 observations (canonical 1,046,891 plus holes) in those name-years.
- Before-first-Massive-day (6,876 in C): IBKR starts earlier than Massive for the name (symbol change or vendor coverage start); 47 names carry 60 or more days, 31 carry 5 or fewer. Largest runs are partial years (WPC 2012, UAL 2010, ACN 2009, each about 180 days).
- Inside-span holes (908 in C): five names hold 60 or more days (NESR 355, PMTS 148, SMCI 97, MPWR 80, GSAT 74); the other ten are small. These are the named 629 holes plus MPWR.
- Massive-row-not-selected (6,080, 2 names) lies outside scope C.
- Not measured: why Massive lacks the early days of the 143 names (needs a per-name vendor look), and 5m.

Recommendation: disclose, no build. The panel absorbs the missing days as NaN under `no_fill`, 0.74 percent of scope C is below the materiality bar (owner 2026-11-20), and filling from the export would overrule the Massive yardstick. Closing this todo on the disclosure plus the correction of the 451,735 figure is the lead's call.

## Closure 2026-11-23 (lead ruling, disclose, no build)

The first-version count of 451,735 bar-days was wrong: 91,816 of them are in canonical by calendar date (timestamp convention). The corrected hole count is 359,919 days. Classes: before the first Massive day 341,638 (6,876 in scope C); inside the Massive span 4,829 (908 in C); Massive row present, no canonical row 6,080 (0 in C); no Massive data for the name 7,372 (0 in C). Scope C is touched on 7,784 days, 0.74 percent of its observations. Reasons for disclosure: the panel absorbs the days as NaN under `no_fill`, the share is below the materiality bar (owner 2026-11-20), and filling from the export would overrule the Massive yardstick. Open question 1 (Part F) was moot (Part F closed); the per-name reason Massive starts later for the 143 names is not chased.
