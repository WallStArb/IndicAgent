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

## Result and gate (2026-11-18)

The battery landed (`null_battery_seasonality.py`). H-C does not register or run until `s1.json` shows SIZE HOLDS for the S1 cell, and both results (the seven non-S1 cells, which held, and the S1 cell) are recorded with the E23 entry. A real run is now refused by `runner.static_gate` unless a battery pass record for the family's inputs and the battery's current code exists under `research/battery_passes/` (`battery_pass.require`); the record is bound from the driver JSON of both parts when the S1 cell finishes.
