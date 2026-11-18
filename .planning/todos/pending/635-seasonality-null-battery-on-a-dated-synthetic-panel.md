---
status: pending
priority: P1
filed: 2026-11-18
source: B-S (todo 609): research/specs/seasonality_h5.yaml and seasonality_h5_core.yaml exist, but families/seasonality.py names no NULL_BATTERY
---

# E17 H0 battery for the H-C seasonality family

## What

`runner.static_gate` refuses a family with no E17 H0 battery, so the two H-C specs cannot register or run until one exists
(tested: `test_seasonality_has_no_battery_yet_so_a_run_is_refused_before_the_ledger`). The daily residual battery
(`null_battery_daily_residual.py`) runs members without calendar dates. The H-C battery needs synthetic panels that carry a
session calendar, so the monthly sums and the month labels are the production ones, and the B2 size check (0.05, 0.01 and
0.00167 over 1,000 simulations per cell) for both members and the equal-weight book.

## Done when

- `families/seasonality.NULL_BATTERY` names the battery module; `static_gate` returns its gate.
- The battery's members, params and memory are read from the spec values pinned in `seasonality_h5.yaml` (the test that ties the
  spec to `seasonality.slot_history_sessions` stays).
- Static sizes measured on the dated panel pass the gate; `repro_frozen` bit-identical.

## Why it matters

A precondition of the H-C registration (E23). Without it the family cannot be charged a look.
