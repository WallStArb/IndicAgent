---
status: pending
priority: P2
filed: 2026-09-24
source: found building the Phase 179 S0 snapshot test (feat/179-harness), reproduced 2026-09-24
---

# Integration suite's scratch-DB build fails on migration 322, so every tests/integration/ test errors at setup

## What

`tests/integration/conftest.py`'s session-scoped autouse fixture builds `indicagent_test` by
applying `production/migrations/*.sql` in order. It fails on
`322_timeframe_intraday_hourly_vocabulary_group.sql` line 31:

```
ERROR: insert or update on table "vocabulary_group_member" violates foreign key constraint
"vocabulary_group_member_namespace_code_fkey"
DETAIL: Key (namespace, code)=(timeframe, 1m) is not present in table "controlled_vocabulary".
```

The live DB has the row (applied in a different order or seeded by hand); a fresh build does not.
Because the fixture is autouse, every test under `tests/integration/` errors at setup, so the
integration suite has been giving no signal.

## What to do

1. Find which migration should seed `controlled_vocabulary (timeframe, 1m)` before 322 and
   whether the live DB got it outside a migration (CLAUDE.md: live-applied migrations have no
   forcing function to be committed).
2. Fix forward with a migration or correct the seed order; rebuild `indicagent_test` from
   scratch and run `pytest tests/integration/ -q` to confirm setup passes.
3. Consider a CI job that builds the scratch DB from migrations, so ordering bugs fail loudly.

## Triage 2026-09-26 (backlog review with the owner)

Closed: merged into todo 429 (same broken integration conftest, migration 322 replay).
