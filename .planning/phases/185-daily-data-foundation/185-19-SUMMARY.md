---
phase: 185-daily-data-foundation
plan: 19
subsystem: bars
tags: [d3, d4, venue-fallback, empty-history, d1]
requires: [185-13, 185-18]
provides:
  - provider never returns venue bars for storage; venue answers reach D1 through on_observation only
  - migration 404 retiring infra.ibkr.venue_fallback.store_bars (value false, read only to log retirement)
  - confirmed_empty_spans (pure rule in gap_plan) and reconcile_empty_history (D1-backed, 1d)
  - pipeline reconciles each symbol's 1d empty-history row after the D1 flush
  - live D3/D4 checks and the moved-name "Recovery applied" record
affects: [185-20, 189-04]
key-files:
  created:
    - production/migrations/404_venue_fallback_store_bars_retired.sql
    - tests/unit/scripts/test_empty_history_from_d1.py
    - tests/integration/test_d3_d4_live.py
  modified:
    - src/providers/ibkr.py
    - src/providers/base.py
    - src/intelligence/bars/gap_plan.py
    - scripts/infrastructure/backfill/_empty_history.py
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
    - docs/research/moved-name-inventory.md
decisions:
  - The venue route alias map (ISLAND to NASDAQ) moves to providers/base.py as VENUE_ROUTE_ALIASES so the provider's venue walk and the reconcile share one definition.
  - Confirmation counts only no_data requests with a window_start, within one fetch run; the primary venue is read from that run's SMART request and not required.
  - reconcile_empty_history takes an optional symbols scope; the pipeline passes the one symbol it just flushed, the one-time pass over all rows passes none.
  - The live test fails loudly if venue_bars_1d is ever true: the moved-name seam and volume checks are not written until the study passes, rather than shipping an unexercised branch.
metrics:
  tasks: 2
  completed: 2026-10-03
---

# Phase 185 Plan 19: D3 rebase and D4 from recorded answers Summary

Venue choice now belongs to D2 and 1d empty history is a derived fact. The study failed both
criteria, so no venue bar became canonical: the 39 moved names keep their pre-move history as
venue observations in D1, stored and unused.

## Results

- Provider: `_fetch_pre_move_history` returns no bars whatever `_VENUE_FALLBACK_STORE_BARS`
  holds; a true value logs `ibkr.venue_fallback_store_bars_retired`. Migration 404 marks the key
  retired (applied live and committed together). One existing test changed: the one that asserted
  the highest-volume venue's bars were returned and persisted with the switch on
  (`test_keeps_highest_volume_venue_for_the_head`, replaced by `test_venue_bars_are_never_returned_whatever_the_retired_switch`, parametrized over the switch).
- D4: a 1d span is empty only when SMART and every former venue except the primary answered
  no_data in one fetch run (pure rule, 6 tests; confirmed spans and reconcile over a fake connection, 11 tests; pipeline wiring, 1 test).
- Live reconcile over all rows: 115 considered, 26 kept, 89 deleted, 0 inserted, 0 extended.
  The 89 predate D1 capture, so no recorded answer confirms them; their pre-listing spans are
  asked again at each name's next 1d fetch (about 12 requests per name, roughly 1,000 in all).
- Baseline before any step: 0 stored `ibkr_venue` 1d rows, 0 tradeable rows with venue volume;
  both unchanged. No daily batch applied venue bars.

## Deviations

- Migration 404 was free as reserved; 409 and 434 belong to other phases.
- The plan's Task 2 venue-gate-true branch (seam and volume checks for moved names) is not
  implemented; `test_venue_bars_never_became_canonical_while_the_gate_is_false` fails with that
  instruction if the gate is ever turned on.

## Open

- The 89 re-asks add roughly three hours of lease time behind the todo 449 lane and the
  wave 2 onboarding fetch; they happen at each name's next 1d fetch, not in one burst.
