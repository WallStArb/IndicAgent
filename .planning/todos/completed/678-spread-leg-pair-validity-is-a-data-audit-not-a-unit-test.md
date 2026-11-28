---
claimable: true
status: completed
objective: O3
priority: P3
filed: 2026-11-26
source: indicagent-8c test hygiene audit (lane O, lead ruling 2026-11-25)
---

# Move the spread_leg pair validity check to an ops audit

## What

`tests/unit/test_spread_leg_pair_validity.py` asserts on production `instrument_tags` rows through the live database, so its result depends on data, not code, and it skips in CI. Recommendation: move the two checks (every `spread_leg` row names a valid pair symbol; pairs are symmetric) into an ops audit script under `scripts/ops/` that writes a report and an `integrity_monitor` row, and keep a unit test of the checking functions on a small seeded in-memory case. Drop the live-DB tests from `tests/unit/` once the audit runs on a timer or in the pre-pilot checklist.

## Done when

The audit exists and has run once with its result recorded here, and the unit tests no longer read the live database.

## Closed 2026-11-28 (claimed and landed by indicagent-03)

`scripts/ops/ops_spread_leg_audit.py` reads the `spread_leg` tags and instruments, prints every missing pair, unknown symbol and non-reciprocal pair, writes one `integrity_monitor` row (`spread_leg_audit`, metric `problems`, threshold 0) and exits 1 on any problem. Its checks are pure and unit-tested on seeded cases in `tests/unit/scripts/test_ops_spread_leg_audit.py`; the live-DB unit test and its write-boundary allow-list entry are deleted. First run 2026-11-28 01:06Z: 54 rows, 0 problems, row written (passed true).
