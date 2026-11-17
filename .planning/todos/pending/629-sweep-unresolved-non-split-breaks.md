---
status: pending
priority: P1
filed: 2026-11-17
source: A3 sweep run 2026-11-17 (ops_split_calendar_audit --sweep --strict --witness yahoo, exit 3: 1,529 active names, 634 lone breaks, 72 unresolved, 0 recorded_unapplied, 0 double adjusted, 0 witness errors; the unresolved list is the run's _unresolved.csv)
---

# Sweep: unresolved breaks that are not clean ratios, rescale verdicts, and reused tickers

## What

Unresolved breaks whose size is not a simple split ratio (spin-offs and distributions leave a level step at an
arbitrary ratio; large positive steps are reverse splits or a different security under the same ticker), plus
the sweep's rescale verdicts. Two rows carry `unrecorded_split` (NESR 2024-10-22, SW 2016-05-16) and two
`inseries_rescale` (APTV 2017-12-05, PNR 2018-05-01), which the sweep reads as a scale error in canonical.
SNX 2020-12-02 is the day after the Concentrix spin-off already in `config/corporate_actions/spin_off_exclusions.csv`
(2020-12-01): the break needs its disposition at the break date.

- ACVA 2025-11-06 (-0.47, reported)
- APTV 2017-12-05 (-1.26, inseries_rescale)
- BAX 2015-07-01 (-0.59, reported)
- CNO 2008-09-17 (-0.55, single_bar_reversal)
- DD 2025-11-03 (-0.86, reported)
- EBAY 2015-07-20 (-0.84, reported)
- ECHO 2008-01-02 (+0.55, reported)
- ENOV 2022-04-05 (+0.59, reported)
- ENSG 2014-06-03 (-0.48, reported)
- EQT 2018-11-13 (-0.62, reported)
- FAF 2010-06-02 (-0.82, reported)
- GSAT 2014-04-21 (+1.90, reported)
- HLT 2017-01-04 (+0.75, reported)
- HON 2026-06-15 (-0.66, reported)
- MDU 2024-11-01 (-0.65, reported)
- MSI 2011-01-04 (+1.47, reported)
- NESR 2024-10-22 (+1.27, unrecorded_split)
- NI 2015-07-02 (-0.98, reported)
- OII 2020-03-10 (-0.58, reported)
- PMTS 2021-08-05 (+3.14, reported)
- PNR 2018-05-01 (-0.41, inseries_rescale)
- POWI 2006-10-30 (+0.45, reported)
- ROKU 2017-11-09 (+0.44, reported)
- RTX 2020-04-03 (-1.24, reported)
- SIRI 2009-02-11 (-0.73, reported)
- SLM 2014-05-01 (-1.05, reported)
- SMCI 2020-01-14 (+0.55, reported)
- SNEX 2020-07-06 (+0.47, reported)
- SNX 2020-12-02 (-0.74, reported)
- SPXC 2015-09-28 (-1.53, reported)
- SSB 2004-03-09 (+1.33, reported)
- SVRA 2016-02-10 (-0.59, reported)
- SVRA 2016-09-21 (-1.57, reported)
- SW 2016-05-16 (-1.86, unrecorded_split)
- THRM 2012-06-13 (+2.02, reported)
- UAMY 2020-10-08 (+0.63, reported)
- UNIT 2025-08-04 (+0.50, reported)
- VIAV 2015-08-04 (-0.56, reported)
- XPO 2021-08-02 (-0.50, reported)
- XPO 2022-11-01 (-0.46, reported)

Reused tickers (todo 624 owns the mechanism, the pit ticker map): SN reads two breaks, the 2018-12-06 end of the
earlier issuer's bars and the 2023-07-31 start of SharkNinja.

- SN 2018-12-06 (-0.55, reported)
- SN 2023-07-31 (+4.76, reported)

## Requirement first (Musk step 1)

A spin-off or distribution is a real price event for the holder, never a split row (`spin_off_exclusions.csv`);
the sweep needs only a disposition (symbol, break date, reason, evidence URL). Decide per row: a disposition,
a split row through `--apply-rows`, or an identity fix under todo 624 (reused ticker, large positive steps).

## Scope

1. Classify each row with a non-price witness (filing or exchange notice), batched by event type.
2. Write dispositions to `config/corporate_actions/sweep_dispositions.csv`, split rows through the operator
   path, and hand the reused-ticker rows to todo 624.
3. The two `inseries_rescale` and two `unrecorded_split` rows first: the sweep reads them as scale errors in
   canonical that research would read as fabricated returns.

## Gates

The sweep lists none of these rows unresolved after one rerun; no `recorded_unapplied` or
`recorded_double_adjusted` row appears; unit suite exit code.
