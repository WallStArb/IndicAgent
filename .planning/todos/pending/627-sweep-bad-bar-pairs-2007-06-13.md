---
status: pending
priority: P2
filed: 2026-11-17
source: A3 sweep run 2026-11-17 (ops_split_calendar_audit --sweep --strict --witness yahoo, exit 3: 1,529 active names, 634 lone breaks, 72 unresolved, 0 recorded_unapplied, 0 double adjusted, 0 witness errors; the unresolved list is the run's _unresolved.csv)
---

# Sweep: five one-day reversal pairs on 2007-06-13 and 2007-06-14

## What

Five names show a single_bar_reversal on 2007-06-13 and an equal and opposite step on 2007-06-14 (step sizes
0.62 to 2.23 in log terms). A one-bar excursion that returns the next day, on the same two dates across five
names, reads as one bad bar per name on the same day (a vendor day-file defect), not a split. The sweep gates
every single_bar_reversal until the bar is listed in `config/corporate_actions/operator_bad_bars.csv`
(`operator_bad_bar` quarantine).

- ACGL 2007-06-13 (-1.03, single_bar_reversal)
- ACGL 2007-06-14 (+1.03, reported)
- ACTG 2007-06-13 (+0.66, single_bar_reversal)
- ACTG 2007-06-14 (-0.62, reported)
- IDXX 2007-06-13 (-1.21, single_bar_reversal)
- IDXX 2007-06-14 (+1.23, reported)
- SHEN 2007-06-13 (-0.62, single_bar_reversal)
- SHEN 2007-06-14 (+0.63, reported)
- SIRI 2007-06-13 (+2.23, single_bar_reversal)
- SIRI 2007-06-14 (-2.23, reported)

## Requirement first (Musk step 1)

Measure the class first: how many names carry a bar on 2007-06-13 that disagrees with its neighbours (every
name, not only the five the sweep read), which raw vendor served each, and whether the defect is in Massive's
archive file for that day. If it is the file, fix by class (one quarantine rule for the day), not five rows.

## Scope

1. Read-only measurement of the class on 2007-06-13 (names, vendors, steps).
2. List the bars in `operator_bad_bars.csv` with the evidence, or add a day rule; reselect nothing until decided.
3. Rerun the sweep once; these rows leave the unresolved list.

## Gates

The sweep lists none of these ten rows; the D7 verdict set is unchanged except through the listing; unit suite exit code.
