---
status: in_review
priority: P1
filed: 2026-11-17
source: todo 629 triage (c2ed64b58): seven real splits no writer can record
---

# Operator rows line for a Massive-route split (calendar_market), combined factor explicit

## What

Seven sweep breaks are real splits of a Massive-served series (ENOV 2022-03-21 and 2022-04-05, HLT 2017-01-04, HON 2026-06-15,
MSI 2011-01-04, MDU 2003-10-30 and 2006-07-27). `--apply-rows` raised "no rescalable 1d series" for `massive/sip_flat`, and
`--apply-market` needs a Yahoo calendar factor that is a recognised ratio plus an incumbent witness; Yahoo lists ENOV, HLT,
MSI and HON as a combined factor (reverse split times distribution) and MDU has no incumbent. Without a row the strict A3 sweep
gate fails, and a disposition alone would hide the unrecorded split.

## Requirement first (Musk step 1)

The filing is the witness the calendar cannot be. A split is a market fact; a `calendar_market` row means exactly what a
`massive_reference` row means (rescales Massive, stales and rescales nothing else), so the writer needs no new rule branch. The
combined factor is never one step: the row carries the filing's split ratio alone, and the distribution part stays a real move
that keeps its own disposition line.

## Built

`--apply-rows` accepts a line whose only route is `massive/sip_flat` (mixing it with an incumbent route raises) and writes a
`calendar_market` row with `detail.canonical_route`, no `unadjusted_routes`. Optional column `calendar_factor` (Yahoo's combined
factor) lands in `detail` with `residual_factor = calendar_factor / factor` as evidence only. At apply time, after the existing-row
guard (so a re-apply skips, an incumbent route correction nearby never blocks), each line is re-judged on the writing connection:
the factor is a recognised split ratio under the APR (0.581 as one step is refused), Massive's raw 1d series serves the span, and
canonical's stored step from the effective date to the next session, less `calendar_adjusted_step`, reads `unadjusted` against
`-log(ratio)` (a canonical already rescaled, or a wrong factor, fails, so no double scaling). `--commit` is refused unless
`calendar_market` is in `SPLIT_SOURCES`.

Example line (columns symbol, effective_date, factor, unadjusted_routes, calendar_adjusted_step, reason, evidence, calendar_factor):

```
ENOV,2022-04-04,0.333333333333,massive/sip_flat,0.047553,1-for-3 reverse split after the ESAB distribution,<filing url>,0.581
```

## Scope

1. Writer and tests: done (`scripts/ops/bars/ops_split_calendar_audit.py`, `tests/unit/scripts/test_ops_split_calendar_audit.py`).
2. Lead, after review: build the rows file for the seven cases (HLT's `calendar_adjusted_step` in the 629 draft is prose, it needs
   a number; HLT's spin-off-adjusted Alpaca bars are todo 624), dry run, apply, reselect 1d, 5m and the grid for the names, then land
   the distribution dispositions in the same commit and run the A3 sweep once.

## Gates

Unit suite exit code; independent review; the sweep lists none of the seven after the apply; `ops_selection_gate --compare`
differs only on the seven names. The audit is imported by timers: quiet window.
