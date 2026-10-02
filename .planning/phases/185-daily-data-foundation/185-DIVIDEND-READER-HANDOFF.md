# Dividend reader hand-off: dispute windows become unknown returns (D-23)

For: the phase 183 owner (`src/intelligence/research/` lane)
From: phase 185 plan 21 (2026-10-02)
Status: NOT APPLIED - waiting on the lane owner; nothing in 185 edits the research package

## What exists now

- `dividend_date_dispute` (migration 403): 26 rows on 18 names, each `(symbol,
  first_date, last_date, dates_by_source, fetch_run_id)`, span 1-5 days, both sources'
  dates present. Populated by `dividend_event_writer` whenever reconciliation finds one
  dividend on two dates; both events stand in `dividend_events`.
- Plan 07 already shipped the pure helpers beside the table:
  `src/intelligence/bars/corporate_actions.py::unknown_return_mask(session_dates,
  entry_idx, exit_idx, disputes)` -> boolean mask, True where a return's `[entry, exit]`
  session span intersects `[first_date - 1 session, last_date]`.

## The change to apply in the research reader

`src/intelligence/research/dividends.py` (the total-return reader behind
`panel.total_return`): a session-to-session return whose span crosses a dispute window
is unknown (NaN), not a computed value from either source's dates. Concretely:

1. Load the symbol's disputes alongside its dividend events (same query pattern as the
   coverage read; `dividend_date_dispute` is tiny, at most a few dozen rows per year).
2. Build the return mask with `unknown_return_mask` over the same session calendar the
   reader already uses for return construction.
3. Apply the mask after dividend adjustment, before any consumer sees the series: the
   masked entries follow the `no_fill` convention (NaN, never zero) already used for
   uncovered dividend spans outside `dividend_event_coverage`.

Rationale: inside a dispute window the correct dividend amount is genuinely unknown
(the sources disagree by 1-5 days), so any return spanning it is a guess. Unknown is
the honest value; NaN also keeps the mask consistent with how S0 treats uncovered
dividend days today.

## Tests to add (in the research package's own suite)

1. A return fully inside one dispute window is NaN; a return entirely before or after
   it is unchanged.
2. A return whose entry session is `first_date - 1 session` is masked (the boundary
   case in `unknown_return_mask`'s docstring).
3. A symbol with no disputes produces a byte-identical series to before the change
   (regression guard; the 913 no-dispute names must not move).
4. Masked entries are NaN, not 0.0 (`no_fill`).

## Why a hand-off and not a 185 edit

The phase 183 session owns `src/intelligence/research/`; the lane rule in STATE.md says
nobody else edits it. Plan 21's discipline check (`git diff --quiet
src/intelligence/research/dividends.py`) passed: 185 shipped the table, the writer and
the pure helpers; this reader change is the single remaining consumer.
