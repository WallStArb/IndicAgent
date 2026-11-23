# Integration harness plan: delete first, then isolate, then automate

**Status:** Plan, 2026-11-23, for the lead (indicagent-0b). Docs only: nothing is built, no container is started, no integration test is run. It sequences todos 656 and 655 and corrects three details of 656 found while reading the code.
**Author:** indicagent-d4.
**Inputs:** `.planning/todos/pending/656-integration-test-harness-redesign.md` (tasks 1 and 2 done, 3 to 5 open), `.planning/todos/pending/655-*.md`, `tests/integration/` (29 test files, 175 test functions), `tests/integration/conftest.py`, `docs/reference/gotchas.md`, `docs/foundation/timescaledb-compressed-column-migration.md` (the 768 GB incident).

## 1. What the todo gets right and what changes

The decisions of 656 stand: a separate capped test cluster, a database per session copied from a hashed template, no test reads production data, the schema sync behind `--live-catalog`, CI after 654. Three details change:

1. Port 5433 is taken. `ssfi-timescaledb` (the sibling project's `timescale/timescaledb-ha:pg18` container) publishes `0.0.0.0:5433`, read from `docker ps` and `ss -ltn` on 2026-11-23. A test cluster on 5433 would fail to start or, worse, collide silently on a restart order. The plan uses 5442 (nothing listens on 5434 to 5499) and a startup check that the port is free before the compose file runs.
2. The Musk order is not followed by the todo's task order. Tasks 3 and 4 build machinery (a cluster, templates, a baseline bump) for 175 tests of which 17 should not exist. Deleting them first shrinks task 4 (655) and removes work from the template.
3. 655's classification seed does not need a data dump. The scheme and nodes are deterministic code (`src/config/classification_seed.py`, `render_seed_sql`, data module `NODES`). The 16 failing tests need a scheme and nodes, and the five coverage tests that need per-instrument assignments are monitors that should be deleted (section 2).

## 2. Musk steps applied to the 29 test files

Counts are test functions (a parametrized function counts once), 175 in total.

Step 1, is the requirement real? A test is real if it fails when production code or a migration breaks and cannot be replaced by a unit test or by a monitor that already runs.

| Category | Functions | Files | Disposition |
| --- | --- | --- | --- |
| Deleted-system remnants | 9 | `test_bar_aggregator_session_boundary` (1), `test_dividend_d1_route_live` (5), `test_live_build_only_migrations` (3) | delete |
| Live-data monitors | 7 | `test_instrument_classification_coverage` (5 of 6), `test_instrument_registry` (2 of 3) | delete |
| Redundant | 1 | `test_feature_vectors_schema::test_table_is_empty` | delete |
| Live catalog, kept | 1 | `test_migration_schema_sync` | keep behind `--live-catalog` |
| True integration | 157 | the other 24 files | keep, move to the per-session database |

Why each deletion holds:

- `test_bar_aggregator_session_boundary` connects to Kafka on `localhost:19092`, catches every failure by printing and returning, and asserts nothing: it cannot fail. The streaming path is dormant (CLAUDE.md, data flow).
- `test_dividend_d1_route_live` validates stored state after one named IBKR fetch run (`--fetch-run-id c9b625b5...`) against production. IBKR is removed (owner 2026-11-13) and the file reads a hard-coded live URL. A dividend monitor, if wanted, belongs to the dividend reconciliation audit, not to the test suite.
- `test_live_build_only_migrations` exists only to prove that `conftest._LIVE_BUILD_ONLY` hides no coverage. It is deleted together with that list in the baseline phase (section 4, phase 3), never before: deleting it first would leave the exclusion unverified.
- `test_instrument_classification_coverage`: `test_every_active_instrument_has_a_current_row`, `test_source_refs`, `test_no_history_before_build_date`, `test_depth` and `test_active_contract_sectors_come_from_classification` measure how complete the classification of the current universe is. That is a property of production data, already carried by `src/config/classification_coverage.py` (monitor type `classification_coverage`). Run on a test database they would test the seed, not the code. `test_classification_service_round_trip` is a real service test and stays.
- `test_instrument_registry`: `test_get_active_contracts_returns_nonzero` and `test_all_required_symbols_present` assert that the instruments table holds SPY, which is seed content. `test_trigger_installed` checks a migration's trigger on the schema and stays.
- `test_feature_vectors_schema::test_table_is_empty` asserts that a freshly built database has no rows in a table, which is a fact about the harness.

Step 2, delete. The 17 functions above (9 + 7 + 1). The requirement behind each is either met by an existing monitor or not real.

Step 3, simplify. After the deletions: no test carries a DSN literal (nine test files carry a `localhost:5432` DSN literal today, besides the conftest and the catalog test; they import one `db.py`), no test skips on an unreachable database (a missing test cluster fails once, loudly), and `test_ticker_entity_map_install_db.py` stops creating its own throwaway database on port 5432 and takes a database from the per-session fixture.

Step 4, accelerate. The template database (`CREATE DATABASE ... TEMPLATE`) replaces a rebuild per session. Measure before relying on it (phase 2).

Step 5, automate. CI runs the integration suite against the pinned image after todo 654 (phase 4). Nothing earlier is automated: automating a suite that contains monitors would only run the monitors faster.

## 3. Failure modes and gates

| Failure mode | Guard | Gate |
| --- | --- | --- |
| A test touches the live database | The test cluster is the only DSN source (`tests/integration/db.py`); a unit test fails if any file under `tests/integration/` holds `:5432/` or a bare `indicagent_test"` literal outside `db.py` and the allow-listed catalog test; `tests/unit/conftest.py` keeps treating `indicagent_test_*` as non-live | `tests/unit/test_integration_db_boundary.py` exit 0; the catalog test opens its production connection read-only with `statement_timeout` 30 s and `lock_timeout` 1 s (done in task 1) |
| Port clash | Test cluster on 5442, not 5433 (ssfi). The compose start check refuses a busy port and names the holder | `ss -ltn` shows 5442 free before the first start; the runbook line says so |
| Template drift | Template name carries a SHA-256 over the baseline, seeds, replayed migrations, `db.py`, and the server image id and extension versions; a different hash builds its own template; stale templates swept after 24 hours | review focus items 1 to 3 of 656 as tests; one test builds two templates from two worktrees and checks that main's template is untouched |
| Concurrent `CREATE DATABASE` from one template | PostgreSQL takes a lock on the source database while it is copied, and a concurrent copy can fail with "source database is being accessed by other users"; serialize every copy under the same advisory lock that guards the template build | measured in phase 2 with 16 concurrent sessions before the xdist default is set |
| Disk or memory exhaustion (the 768 GB incident was a compressed hypertable column rewrite on production) | The test cluster is tmpfs with an explicit `size=` cap, a cgroup `mem_limit` and `cpus` cap, and no data volume, so it cannot touch the root filesystem; it holds schema and seeds only (the largest fixture is 3 MB), never a production data dump; every ALTER on a compressed hypertable in a replayed migration runs on empty chunks | a unit test refuses a seed or baseline file above 10 MB; `docker inspect` shows `Memory` and `Tmpfs` limits before a session starts; `df /` is unchanged across a full run |
| Leaked per-session databases | Advisory-lock liveness sweep of 656 decision (a), tmpfs restart starts empty | review focus item 2 |
| Cluster down or reachable but wrong | One loud error naming the container and the compose command | review focus item 4 |
| A green run that hides migrations above the baseline cutoff | The baseline bump and the deletion of `_LIVE_BUILD_ONLY` (phase 3); until then `docs/reference/gotchas.md` keeps its warning | unit test that the cutoff equals the highest migration number at dump time |
| Two sessions kill each other's runs | The interim file lock (task 2, done) until per-session databases land; its integration use is deleted in phase 2 | two concurrent runs both exit 0 |

Every phase also carries the Done-Coding SOP: `/simplify`, `/review` as skills, `pytest tests/unit -n auto` exit 0 (`-n 2` while a heavy job holds the slot), ruff, black, `tools/check_glossary.py`.

## 4. Phases

Phase 1, one session, no docker, no integration run, light compute. Delete the 17 functions and the files that empty out (`test_bar_aggregator_session_boundary.py`, `test_dividend_d1_route_live.py`). Keep `test_live_build_only_migrations.py` until phase 3. Edit `test_instrument_registry.py` to the trigger test, `test_instrument_classification_coverage.py` to the round-trip test, `test_feature_vectors_schema.py` to its four schema tests. Fix the stale docstrings of the two classification test files. Before deleting, grep for references (`tools/gate.py`, `docs/`, `pytest.ini`, CI). Gate: unit suite exit 0, `pytest --collect-only tests/integration` collects 158 functions' worth of tests without error (175 less 17), the grep finds no dangling reference (it already finds two documents to update: `docs/research/ibkr-dividend-route-validation.md` names the dividend test and `docs/foundation/security-classification-hierarchy.md` names the classification tests). Reversible by `git revert`.

Phase 2, one session, needs the host free of a heavy job (it starts a container). 656 task 3 with the corrections of section 1: port 5442, tmpfs `size` cap, template hash including the image id, serialized copies, the loud failure when the cluster is down, `db.py`, the boundary unit test, and the isolation tests. Record the measured template build time and per-session create time in the todo, plus the 16-session concurrency result. Gate: `pytest tests/integration` exit 0 against the new cluster, two concurrent runs both exit 0, no production connection (checked by the boundary test and by `pg_stat_activity` on production showing no `indicagent_test_*` application).

Phase 3, one session, needs a quiet production read window (`pg_dump --schema-only`, no DDL). 656 task 4 plus 655: regenerate the baseline at the migration head, add the roles file, seed the classification scheme and nodes from `render_seed_sql` (no per-instrument assignments), delete `_LIVE_BUILD_ONLY`, its stub and `test_live_build_only_migrations.py`, empty `_NOT_IN_BASELINE` after checking 568 and 571 to 574, close 655. Confirm in the phase that the nine `test_classification_schema` functions pass on scheme plus nodes; if one needs assignments, build them in that test as rolled-back fixture rows. Gate: integration suite exit 0 with 0 failures (the 16 classification failures gone).

Phase 4, after todo 654. 656 task 5: a CI `integration` job on the pinned image, with a unit test that the image tag in the compose file equals the one in the workflow.

## 5. Recommended phase 1

Phase 1 as written is small enough for one session: it is pure deletion and docstring edits, touches no research or statistics module, needs no container and no integration run, and it removes 17 of 175 functions and one baseline-exclusion test from the later phases' scope. It can run while the family 9 battery holds the heavy slot, with `-n 2`.

## 6. Open points for the lead

- Port 5442 instead of 5433, because of ssfi.
- Reorder the todo: deletions (phase 1) before the cluster (phase 2) and the baseline (phase 3).
- 655 closes with a rendered scheme and nodes, not a data dump; confirm in phase 3.
- Whether `test_dividend_d1_route_live` wants a replacement monitor in the dividend audit. Recommendation: no, the route it validated no longer exists.
