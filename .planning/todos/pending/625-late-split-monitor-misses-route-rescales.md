---
status: in_review
priority: P1
filed: 2026-11-17
source: independent review of bd278686c (route-named split rows rescale non-Massive winners in selection)
---

# split_horizon_fresh does not cover route rescales

## What

Selection now divides a non-Massive winner by every split row that names its (vendor, kind) in
`detail.unadjusted_routes` (bd278686c; CLBK 2026-07-20 over Alpaca sip_rth 5m). The late-split monitor
`split_horizon_fresh` still reads only `sip_flat_adj` bars and ignores `unadjusted_routes`
(`services/bar_reconciliation_audit.py` `_SELECT_SPLIT_ROWS_SQL` and the 5m inputs,
`src/intelligence/bars/integrity_checks.py` `split_horizon_stale`). A route row recorded after a series'
last selection therefore leaves that series on the old scale with no verdict: CLBK stood stepped
(24.465 to 10.915) after the row was applied and 1d was continuous, and no D7 check noticed.

## Requirement first (Musk step 1)

The check exists so a split recorded after a selection cannot leave canonical stale unseen. A route row is
the same event class, so the check covers it or the class stays open. Reuse selection's own row reader
(`bar_selection.read_split_rows`, which now returns `routes`) so the monitor and the writer cannot
disagree on which rows count; no second SQL.

## Scope

1. The 5m inputs read every canonical 5m bar whose raw (vendor, kind) a known row names, with the raw close;
   `split_horizon_stale` counts bars whose canonical close is not exactly raw close divided by the same
   scale selection applies (`routed_splits_known_at`), as it does for Massive.
2. The audit's split rows come from `read_split_rows` semantics (market_fact and routes), one definition.
3. Tests, including the CLBK-before-reselect case (a route row recorded, the series not reselected: fails)
   and after the reselect (passes), a name with no route row unchanged, and Massive unchanged.

## Gates

D7 `split_horizon_fresh` fails CLBK on the pre-reselect shape and passes after; no other name's verdict
changes (the full 5m verdict set before and after); unit suite exit code; independent review. The 06:00Z
audit timer imports the module, so it lands in a quiet window.

## Built 2026-11-17

`split_rescale.split_row` is the one definition of a split row (market fact and routes) for selection and the audit; `integrity_checks.routed_horizon_stale` counts canonical bars of a route-named series that are not raw close over the routed scale, added to the `split_horizon_fresh` count in `judge_name_intraday`. Live read-only check at the build: CLBK, UHAL and SPY 0 stale. Lands in a quiet window (the 06:00Z audit imports it); the todo closes with the landing.
