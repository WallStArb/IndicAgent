---
status: pending
priority: P3
filed: 2026-11-26
source: indicagent-8c test hygiene audit (lane O, lead ruling 2026-11-25)
---

# Move the spread_leg pair validity check to an ops audit

## What

`tests/unit/test_spread_leg_pair_validity.py` asserts on production `instrument_tags` rows through the live database, so its result depends on data, not code, and it skips in CI. Recommendation: move the two checks (every `spread_leg` row names a valid pair symbol; pairs are symmetric) into an ops audit script under `scripts/ops/` that writes a report and an `integrity_monitor` row, and keep a unit test of the checking functions on a small seeded in-memory case. Drop the live-DB tests from `tests/unit/` once the audit runs on a timer or in the pre-pilot checklist.

## Done when

The audit exists and has run once with its result recorded here, and the unit tests no longer read the live database.
