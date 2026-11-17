---
status: in_review
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

## Measured 2026-11-17 (indicagent-55, read-only)

Class: one Massive day-file defect on 2007-06-13, in one vendor. The Massive `sip_flat` 1d row of that day carries a
shared bad print in sixteen names: low 22.29 in fourteen (close also 25.55 in eight: ACGL, ACTG, IDCC, IDXX, SHEN,
SIGI, SIRI, SLAB; high or open 25.55 for ACTG and SIRI; low 22.29 only for ADBE, ADSK, AMZN, FCFS, FCNCA, LKQ,
LRCX, POOL). The same constants appear in no other Massive 1d row of any day (a scan of every date for four or more
names sharing a low under 0.6 of the close, and of shared closes under 0.6 or over 1.6 of the open, finds only this
day). IBKR smart_trades is clean for each name that day (low over close 0.96 to 0.99 against Massive's 0.11 to 0.54 on
the eight whose range is visibly off) and Massive reads normally on 2007-06-12 and 2007-06-14, so the defect is that
day's Massive file, not canonical's processing. Canonical carries all sixteen bars (Massive is primary); the sweep
sees five (step above 0.4: ACGL, ACTG, IDXX, SHEN, SIRI, each with an equal and opposite step the next day), IDCC, SIGI
and SLAB sit below its threshold, and the other eight carry a wrong low only. `vol_scaled_jump` flags seven but is not a
quarantine rule. None of the sixteen was in `operator_bad_bars.csv`.

Prepared (not applied): sixteen `operator_bad_bars.csv` rows (the whole bar is quarantined, the evidence cites this
todo). Finding on the way: `--quarantine-unconfirmed` refused the whole list since the step 7 rebuild, because 109 of
the 131 earlier listed bars (APLD, BMNR, RCAT, FRHC, IDR and others, plus SIRI 2002 and SNEX 2002) exist only in IBKR
raw now (Massive starts later for those names or begins 2003-09-10). A listed bar raw holds but canonical does not is
counted as moot; a bar in no series still raises. Dry run on the audit of the sixteen: 39 bars would be quarantined, 109
moot. The quarantine rewrites each rule's flags globally, so applying it also rewrites the 38 stored earlier bars.
Gates: unit suite exit code, `tools/gate.py`.
