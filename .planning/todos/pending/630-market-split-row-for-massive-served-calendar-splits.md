---
status: pending
priority: P1
filed: 2026-11-17
source: todo 628 evidence pass (indicagent-55, 2026-11-17): no sanctioned writer exists for a calendar-listed market split on a Massive-served series
---

# No writer records a market split that the Yahoo calendar lists and Massive's reference lacks

## What

Eleven of the 20 breaks in todo 628 are real forward splits: Yahoo's split calendar lists the split on the break
day (read-only `ops_split_calendar_audit --audit --symbols ...`), canonical (Massive, served unadjusted) steps by
the full ratio (`canonical_step` within 0.015 of `-ln(calendar_factor)`), and the incumbent routes (IBKR, Alpaca)
read adjusted (route step 0.0). The audit gives each `route_conflict`, which by design writes no row, and Massive's
reference holds no event for most of them. Result: no row exists, so selection and the daily rule leave canonical
unrescaled and research reads a fabricated return.

| name | ratio | last old-scale session | Massive reference event |
| --- | --- | --- | --- |
| XHE, XHS, XSW, XTN | 2:1 | 2015-09-10 | none |
| ALK | 2:1 | 2014-07-09 | none (2012-03-16 only) |
| PENG | 2:1 | 2022-02-01 | none |
| AAON | 3:2 | 2013-07-02 | massive_only 2013-07-02, tape_conflict, pending lead ruling |
| ROL | 3:2 | 2018-12-10 | massive_only 2018-12-10, tape_conflict, pending lead ruling |
| MDU | 3:2 | 2003-10-29 and 2006-07-26 | none |
| MGEE | 3:2 | 2014-02-07 | none |

Why no existing path takes them: `--apply-rows` writes a todo 592 operator row (`detail.rows_file`), which
`is_market_split` excludes, so it never rescales Massive. `--apply-massive` re-judges a Massive proposed line
(tape `tape_step`, cited reference pages), and these are `tape_conflict` or absent. `--apply` needs a `confirmed`
audit verdict and a calendar_audit row must name rescalable routes (`bar_derivation.split_rescale_routes`
raises on none; RESCALABLE_SERIES holds IBKR and Alpaca only).

## Requirement first (Musk step 1)

Is the calendar plus the series evidence enough to record a market split? The incumbents already carry these
splits adjusted (route steps 0.0) and Massive is served unadjusted: that is exactly the event class
`massive_reference` means ("a market split the incumbents already carry adjusted"), without Massive's page. Decide
between (a) a new split source `calendar_market` (CHECK constraint, `SPLIT_SOURCES`, market fact, no routes, the
audit writes it for `route_conflict` rows whose canonical vendor is Massive and whose incumbents read adjusted),
or (b) `--apply-massive` accepting a hand-ruled tape verdict for the two Massive-reference cases (AAON, ROL) and
(a) for the rest. Recommendation: (a) for all, one writer, the evidence in `detail` (calendar date and factor,
canonical step, route steps, audit file digest); AAON and ROL then close their pending rulings.

## Scope

1. Ruling on the mechanism (the lead).
2. The new source: migration (CHECK), `SPLIT_SOURCES`, `is_market_split`, the daily rule and `bar_derivation.split_record`
   (no routes, rescales Massive, stales nothing), `ops_split_calendar_audit` verdict and insert path, tests.
3. A rows file for the eleven rows above, dry run, apply, reselect 1d, 5m and the grid for the ten names.

## Gates

The sweep lists none of the eleven; `split_continuity` passes for each; selection `--compare` shows real
differences only on the ten names; unit suite exit code; independent review. The audit and `bar_selection` are
imported by timers: a quiet window.
