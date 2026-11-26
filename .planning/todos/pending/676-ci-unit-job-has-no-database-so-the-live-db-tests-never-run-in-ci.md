---
status: pending
priority: P2
filed: 2026-11-26
source: indicagent-8c test hygiene audit (lane O, lead ruling 2026-11-25)
---

# CI has no database: the live-DB unit tests never run there

## What

The unit job in `.github/workflows/ci.yml` runs `pytest tests/unit/ -n auto` with no Postgres, so every test marked `requires_db` skips in CI and runs only on the host. About 55 tests are affected: `test_bar_source_policy_retirement.py` (15, the append-only trigger on a TEMP copy of `bar_source_policy`), `services/test_bar_derivation_policy_change_sql.py` (11), `core/test_resource_lease.py` (10), `scripts/test_fetcher_lock.py` (about 10), `services/test_ohlcv_raw_bulk_live.py` (7 or more), `test_canonical_bar_lineage_massive_migration_contract.py` (3), `services/test_bar_derivation_stage_lock.py` (1). A push that breaks one of them passes CI. Interim (landed with this todo): the `requires_db` marker on those tests, and a skip count by reason in the CI job (annotation "unit test skips").

## Design

A `timescale/timescaledb` service container on the unit job (credentials postgres/postgres, database `indicagent`, port 5432, matching the tests' `_LIVE_DB_DSN`), then one step that bootstraps the schema by replaying `production/migrations/*.sql` in order, then the existing pytest step. Recommendation: replay the migrations (one source of truth, and it tests them as a side effect), not a schema dump that can drift. The image must match production's extension set (TimescaleDB, pgvector; todo 654 moves the host to the Debian `timescaledb-ha` image, so pick the CI image after that decision).

## Cost and risks

About 600 migrations replayed on an empty database: the time is not measured (estimate a few minutes, which is added to every unit run; cache the bootstrapped data directory keyed on the migrations hash if it is more than about 3 minutes). Some migrations assume production data or compressed chunks and will fail on an empty database; the first step is to replay them locally on a scratch database and list the failures, which decides whether a baseline snapshot plus the recent migrations is needed. The tests' conftest guard already forces live connections read-only.

## Done when

The replay succeeds in CI, the `requires_db` tests run there with zero skips for "PostgreSQL not reachable" (the annotation shows it), and the job time is recorded here.

Related: [679](679-ci-skips-eleven-tests-that-read-untracked-data.md) (the other CI skips, untracked data).

## Probe state 2026-11-26 (indicagent-26)

The `db-tests` job (`.github/workflows/ci.yml`, non-gating) builds `production/Dockerfile.timescaledb`, loads `tests/integration/fixtures/schema_baseline_2026-11-05.sql` and its hypertables file, creates the two grant roles, loads the instrument and config seeds and replays migrations 560 and up: 91 live-DB tests pass, about 70 s for the job. Replaying all 605 migrations on an empty database does not work (159 files fail, 24 s: the v2.x history assumes tables that no longer exist), so the baseline is the base.

Two replayed migrations fail, and the gate will tolerate exactly these two:
- `575_feature_ic_scores_one_name.sql`: the baseline already holds the renamed table `feature_ic_scores` (migration 575's result), so `ALTER TABLE feature_ic_scores_v2 RENAME` fails on `feature_ic_scores_v2 does not exist`. The replay starts at 560 only because the baseline lacks the `split_factor_product` function that 568 creates and 588 uses; the baseline and the migration numbers overlap, so the overlap re-runs 575 on a database that already has its result.
- `605_universe_membership_reset_for_rebuild.sql`: a production-data guard (it refuses unless `universe_membership` holds 858,454 rows over 278 month-ends), expected to fail on an empty database.

Exit condition: dump a new dated schema baseline at the current migration head (`pg_dump --schema-only`, with the hypertables file), replay only migrations numbered after it, and the 575 entry disappears; 605 stays tolerated until its guard is skipped by a documented marker. At that point the tolerated list is 605 alone, or empty.
