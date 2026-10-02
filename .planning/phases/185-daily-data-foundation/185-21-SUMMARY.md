---
phase: 185-daily-data-foundation
plan: 21
subsystem: dividends
tags: [d5, dividend-route, d1, disputes, ibkr]
requires: [185-07, 185-15]
provides:
  - IBKR dividend events derived from D1 observations (no IBKR contact, no lease)
  - dividend_date_dispute (migration 403): near misses recorded, not rolled back
  - validation report with a stated verdict; reader hand-off to phase 183
affects: [185-22, 185-23, phase 183 reader]
key-files:
  created:
    - production/migrations/403_dividend_date_dispute.sql
    - tests/integration/test_dividend_d1_route_live.py
    - docs/research/ibkr-dividend-route-validation.md
    - .planning/phases/185-daily-data-foundation/185-DIVIDEND-READER-HANDOFF.md
  modified:
    - services/dividend_event_writer.py
    - tests/unit/services/test_dividend_event_writer.py
decisions:
  - "IBKR rows are not usable alone for research: sub-cent re-basing artifacts on low-yield ETFs (XLU 20 of 59 events over ten years) and one missed real quarterly (XLU 2020-03-23). Yahoo stays reference; IBKR is the D5 cross-check."
  - "The 8 vanished-guard names keep their stored interim rows (rolled back loudly); deletion plus re-derivation is a deferred item, not a plan-21 scope rider."
metrics:
  tasks: 2
  completed: 2026-10-02
---

# Phase 185 Plan 21: D5 IBKR dividend route from D1, date disputes Summary

The IBKR dividend route now derives entirely from D1's stored observations, near misses
become dispute records instead of symbol rollbacks, and the route is validated on known
dividends with a stated verdict.

## Results

- Task 1 (8bfa7109e): `_derive`'s IBKR branch reads the paired TRADES and ADJUSTED_LAST
  closes `ohlcv_observation` holds for one `fetch_run_id` (route SMART; cross-run rows
  and duplicate bar_dates refused by the new pure `d1_close_series`); the writer never
  contacts IBKR, and the lease allow-list entry is gone. Near misses go through plan 07's
  `disputed_dates` into `dividend_date_dispute` (migration 403, span CHECK 1-5 days,
  first recording wins) inside the same per-symbol transaction. Pure functions untouched
  (`git diff --quiet src/intelligence/research/dividends.py` clean; no line inside
  join_adjustment_pairs, derive_ibkr_events, reconcile, vanished_ex_dates changed).
  Writer tests 99 green.
- Task 2 (e81bd28e2): run over all names from plan 15's paired run
  `c9b625b5-5fc4-4656-8b49-06fd93062123`: 932 considered, 921 derived, 45,248 events
  (45,876 stored ibkr rows), 26 disputes on 18 names (the exact pre-registered count),
  414 yield disagreements, 1,714/1,914 ibkr/yahoo holes. Validation: JPM 40/40, KO 40/40
  over ten years; XLU 39/40 (2020-03-23 missed; 20 sub-cent artifacts); NVR 2004 nothing.
  Full unit suite rc=0. Report: `docs/research/ibkr-dividend-route-validation.md`.

## Verdict (D-22)

IBKR rows usable alone for research: no. Yahoo remains the reference (owner-approved,
todo 428); the D1-derived IBKR set is the independent cross-check, exact on material
single-name dividends, with disagreements as dispute records.

## Failures and follow-ups

10 names failed loudly, per-symbol rollback, stored rows untouched: 8 on the
vanished-ex-date guard (interim-era stored rows the D1 series does not reproduce; 16 of
18 sampled dates lack Yahoo corroboration - deferred: delete, rerun), CBC (negative
ADJUSTED_LAST closes in D1, provider defect kept as observations), CLBK (no TRADES in
the run; plan 14 late-name class). All in `deferred-items.md`.

## Deviations

- The executor hit its 5-hour usage limit after Task 1's red-green and the code landed;
  the orchestrator finished inline per the owner's 429 directive: ran the Task 1 gate
  (full suite rc=0), applied migration 403, committed Task 1, then executed Task 2.
- The integration suite is blocked by todo 486 (conftest replay fails on migration 426),
  so the live checks ran via psql and are pinned in
  `tests/integration/test_dividend_d1_route_live.py` for when 486 clears.
- The plan's XLU acceptance ("all quarterlies matched or disputed") is not met by the
  data: reported as the measured 39/40 plus artifacts rather than silently widened.

## Hand-offs

- Reader change (dispute windows become unknown returns): `185-DIVIDEND-READER-HANDOFF.md`,
  for the phase 183 owner.
- 185-22 (nightly overlap split detection) builds on the same D1 pairing SQL pattern.
