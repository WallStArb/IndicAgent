---
id: 486
title: Integration conftest migration replay fails on 426 (unattached chunk dependencies block DROP)
status: done
priority: high
owner: unassigned
created: 2026-10-02
source: phase 185 plan 12 (D-15)
---

# Integration conftest migration replay fails on 426

The `tests/integration/` session fixture (`conftest.py::migrated_test_database`) rebuilds
`indicagent_test` from the pinned baseline (`schema_baseline_2026-09-27.sql`, cutoff 380) and
replays every migration numbered above it. Since 186-22 landed `426_drop_old_chain_tables.sql`,
that replay fails and the whole integration suite errors at fixture setup before any test runs
(discovered running 185-12's D-15 live checks, 2026-10-02):

```
psql:error: ERROR:  table _timescaledb_internal._hyper_88_71343_chunk depends on table ensemble_alpha
HINT:  Use DROP ... CASCADE to drop the dependent objects too.
RuntimeError: applying 426_drop_old_chain_tables.sql failed
```

Root cause: the baseline dump/restore leaves some old-chain hypertable chunks
(`_hyper_88_7134*`, `ensemble_alpha` et al.) as tables that carry an auto `pg_depend` entry on
the parent but are NOT attached partitions in `pg_inherits` (0 of the failing chunk set attached,
81 other links present), so plain `DROP TABLE` refuses where production's live catalog dropped
cleanly. Editing 426 is off the table (applied migrations are immutable); `DROP ... CASCADE` is
not acceptable as migration semantics on production.

Fix per the conftest's own prescribed maintenance ("bump this and regenerate the baseline files
periodically"): regenerate `schema_baseline_*` + the three seed files from current production
(old-chain tables now absent post-426) and raise `_BASELINE_MIGRATION_CUTOFF` to the current
migration head. Verify the full `pytest -m integration` session rebuild goes green, including
`test_migration_schema_sync.py`'s scratch-vs-production diff.

Interim workaround used by 185-12: the D-15 checks were executed directly against the live DB
(test-module assertions invoked over a real psycopg connection).

## Closed 2026-10-03 (plan 185-18)

Baseline regenerated at cutoff 433 (`tests/integration/fixtures/*_2026-10-02.sql`). The schema-only
dump drops pre-cutoff data and restores production's `_compressed_hypertable_N` tables as orphan
stubs, so the fix needed more than a regeneration: a fourth seed (`config_schema` and
`config_state`, wired into `_apply_baseline`), a stub-drop block in the hypertables file, and three
stale tests updated (`get_active_contracts(dimension=)`, `TransitionResult`, the 185-18 fences).
`pytest -m integration` is green apart from four tests that read the live database and are broken
for unrelated reasons: `test_ic_parity_replay` (reads the `forward_returns` table dropped by
186-23) and `test_bar_quality_flag_quarantine` (a migration 381 one-time snapshot compared with
data that moved in 185-12).
