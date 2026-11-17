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

## Scope 3 design: the gate is on the sweep output (draft 2026-11-16, indicagent-ca; parameters revised 2026-11-16)

Rule: `ops_split_calendar_audit --sweep --witness massive --strict --dispositions <csv>` exits 3 on any condition in "Sweep gate parameters" below. It never changes a constant to pass.

Why the sweep and not D7: the sweep already classifies breaks and runs about 70 s (2026-11-13 run); D7 is a
77 minute audit whose modules timers import, so a new required check there waits for a quiet window and
reclassifies every name's verdict. Revisit D7 only if a break class the sweep cannot see matters.

Known blind spot: a break below ln 0.4 (ATRO, ratio 1.2) is outside the sweep by definition; price cannot
separate it from a move, so it stays a filing-witness item (scope 1) and is not gated.

Landing: `scripts/` only, imported by no timer or service, so it needs no quiet window.

## Sweep gate parameters (frozen 2026-11-16, before any run of the gate)

`--strict` reuses the classifier's constants and adds none: break size |ln step| > 0.4, lone-day cut at most 20 names, scale tolerance 0.1 (`_SWEEP_SCALE_TOL`), calendar window 30 days (`_SWEEP_CALENDAR_WINDOW`). A name that stays unresolved is fixed by a disposition with its witness, never by changing a constant. Expected result on the rebuilt canonical before any record: CLBK unresolved.

- Canonical is what the sweep reads, so a break it finds is still in canonical. A current `corporate_action` row within 30 days of the break whose factor is the break's own scale (`|ln(factor) + step| <= 0.1`; a split drops the close by 1/factor, a reverse split lifts it) does not resolve it: it relabels it `recorded_unapplied` (D7 "unadjusted": the row is recorded and canonical still steps by -log f; reselect it), and a row of size `|ln(factor) - step| <= 0.1` relabels it `recorded_double_adjusted` (D7 "double_adjusted"). Only an operator disposition (symbol, date, reason, evidence) rules either class, or the break leaving canonical. The "no row of any type within 15 days" wording in the CLBK evidence above was evidence for that name only, not the gate's window.
- Gated breaks: the rescale verdicts (`junction_rescale`, `inseries_rescale`, `unrecorded_split`), every `reported` break (the witness cannot decide or bracket), and every `single_bar_reversal`. A single-bar reversal in canonical is a one-bar scale error the `operator_bad_bars` quarantine has not taken out of the tradeable view (the quarantine removes the bar and the break); a (symbol, break date) on that list relabels it `recorded_unapplied`. `real_move` is not gated (two witnesses carry the step). A witness error always fails `--strict`.
- Active-only: only names with `instruments.is_active` are gated, as the Gates section says ("an active name"). Inactive names, including the stage 2 inactive rows, are swept and written to the CSV but never fail the gate.
- An empty read never passes: no active names or no lone breaks read fails, `--strict` refuses `--symbols`, and a missing count raises.
- Crowded days: a day on which more than 20 names step beyond the break size has no lone break, so the sweep cannot see its names. `--strict` counts and prints them and fails unless the date is on the frozen market-wide list. Measured on canonical 2026-11-16 (read-only, before any gate run) there is one: 2020-03-09 (22 names, the March 2020 crash day), which is the whole list (`_MARKET_WIDE_DATES`). A date is added only by a dated amendment here. Names on a listed day are not examined by the gate (known limit).
- Output: the unresolved breaks are written beside `--out` as `<out stem>_unresolved.csv` and printed on failure; disposition lines that match no break are reported, not failed.
