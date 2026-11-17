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

## Lead ruling 2026-11-16

Not a D4, D5 or Part F gate: the D4 rerun and D5 proceed as scripted. Scope items 1 and 2 run after `PARTD4 DONE` inside the
A3 split sweep window (witness first, then the `--apply-massive` record and reselect for CLBK; ATRO on its witness alone).
Scope item 3 (the gate on lone breaks) is decided with the todo 592 owner before the first counted test.

## Scope 3 design: the gate is on the sweep output (draft 2026-11-17, indicagent-ca)

Rule: `ops_split_calendar_audit --sweep --witness massive --strict --dispositions <csv>` exits 3 when a
break with a row verdict (`unrecorded_split`, `inseries_rescale`, `junction_rescale`) on an active name has
no current `corporate_action` row within 30 days of it and no line in the dispositions list (symbol, date,
reason, evidence; `operator_list` format). `real_move` and `reported` stay disclosed, never gated.

Why the sweep and not D7: the sweep already classifies breaks and runs about 70 s (2026-11-13 run); D7 is a
77 minute audit whose modules timers import, so a new required check there waits for a quiet window and
reclassifies every name's verdict. Revisit D7 only if a break class the sweep cannot see matters.

Calibration, written before any run: no new tunable. The break size (|ln step| > 0.4), the lone-day cut (at
most 20 names step), the scale tolerance and the 30 day window are the sweep's frozen constants, and the
recorded-row window is the same 30 days. Expected result on the rebuilt canonical before any record: CLBK
unresolved, the A3 2026-11-13 rows (CENT, GSAT recorded; HSIC, TMUS IBKR-era junctions) gone with the
switch. A name that stays unresolved is fixed by a recorded row or a dispositions line with its witness,
never by changing a constant.

Known blind spot: a break below ln 0.4 (ATRO, ratio 1.2) is outside the sweep by definition; price cannot
separate it from a move, so it stays a filing-witness item (scope 1) and is not gated.

Landing: `scripts/` only, imported by no timer or service, so it needs no quiet window.

Known limits of the gate (review 2026-11-17, accepted): a recorded row of any type or factor within 30 days
counts as the explanation (a loose match; a factor check waits for a case that needs it); breaks on inactive
names are not counted; the witness failing on a name makes `--strict` fail (`witness_error`), never pass.

## Sweep gate parameters (recorded 2026-11-16, before any run of the gate)

`ops_split_calendar_audit --sweep --strict` is the scope 3 gate on the sweep output. Its frozen constants, all reused from the classifier and written here before the first run, no new tunable:

- Explanation window: a break is explained by a current `corporate_action` row within 30 days of it (`_SWEEP_CALENDAR_WINDOW`), and only when the row's factor is the break's own scale: `|ln(factor) + step| <= 0.1` (`_SWEEP_SCALE_TOL`; a split drops the close by 1/factor, a reverse split lifts it). The "no row of any type within 15 days" wording above was the evidence for CLBK only, not the gate's window.
- Active-only: only names with `instruments.is_active` are gated, as the Gates section says ("an active name"). Inactive names, including the stage 2 inactive rows, are swept and written to the CSV but never fail the gate.
- Gated breaks: the rescale verdicts (`junction_rescale`, `inseries_rescale`, `unrecorded_split`) and every `reported` break (the witness cannot decide, the ATRO shape), unless an operator disposition (symbol, date, reason, evidence) rules it. A witness error always fails `--strict`.
- An empty read never passes: no active names or no lone breaks read fails, and `--strict` refuses `--symbols`. The unresolved breaks are written beside `--out` as `<out stem>_unresolved.csv` and printed on failure; disposition lines that match no break are reported.
