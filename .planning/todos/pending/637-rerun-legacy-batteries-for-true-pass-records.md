---
status: pending
priority: P3
filed: 2026-11-18
source: stored battery pass records (todo 635 review, lead ruling 2026-11-18): the legacy families run under a waiver table, not a record
---

# Rerun the legacy E17 batteries so their waivers retire

## What

`runner.static_gate` now requires, for a real or exploration run, a recorded battery pass (`research/battery_passes/`, `battery_pass.require`). Family 1 (four specs), the intraday periodicity family and family 2 have recorded real runs whose E17 batteries passed, but the evidence is ledger prose with no result file, so they run under `battery_pass.LEGACY_WAIVERS` (one row per spec input hash, each citing its ledger E17 entry).

## Done when

- Each legacy family's battery is rerun through `scripts/research/e17_null_battery.py` (1,000 simulations per cell, single core, no DB) and bound into a record.
- Its waiver row is deleted; `LEGACY_WAIVERS` is empty.

## Not before

The cores are free. Not on the critical path: the waivers keep every recorded family runnable until then, and an amended or new spec never gets a waiver.
