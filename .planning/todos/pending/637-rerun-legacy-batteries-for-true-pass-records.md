---
status: pending
priority: P3
filed: 2026-11-18
source: stored battery pass records (todo 635 review, lead ruling 2026-11-18): the legacy families run under a waiver table, not a record
---

# Rerun the legacy E17 batteries so their waivers retire

## What

`runner.static_gate` now requires, for a real or exploration run, a recorded battery pass (`research/battery_passes/`, `battery_pass.require`). Family 1 (four specs), the intraday periodicity family and family 2 have E17 batteries whose passes are ledger prose with no result file, so they have no pass record; under `battery_pass.LEGACY_WAIVERS` (one row per spec input hash, each citing its ledger E17 entry).

## Done when

- Each legacy family's battery is rerun through `scripts/research/e17_null_battery.py` (1,000 simulations per cell, single core, no DB) and bound into a record.
- Its waiver row is deleted; `LEGACY_WAIVERS` is empty.

## Not before

A real run of any of these families. Not on the critical path of the first counted daily family (the daily residual and H-C records come from todos 636 and 635); the first real run of family 1, periodicity or family 2 needs its record first.

## Status 2026-11-24 (todo consolidation pass)

`LEGACY_WAIVERS` has been `{}` since it was created (`battery_pass.py:89`, b522cc3fd), so the waiver-row condition is met. Tier corrected to P3: the next counted families are H-C, 9 and 10.
