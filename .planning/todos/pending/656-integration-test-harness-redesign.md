---
status: pending
priority: P2
filed: 2026-11-22
source: integration harness lane after commit 0ecff0c7a (two sessions killed each other's integration runs; a live-reading test held a six-minute query on production), 2026-11-22
blocked_on: the daily residual run is counted and the lead says go
---

# Integration test harness redesign: an isolated test cluster, a database per session, no test reads production data

Plan 2026-11-23 (`docs/plans/2026-11-23-integration-harness-plan.md`): the order becomes delete (17 functions, phase 1), cluster (task 3, phase 2), baseline (task 4 with 655, phase 3), CI (task 5, phase 4); the test cluster port is 5442, not 5433 (taken by `ssfi-timescaledb`); 655 closes with a rendered scheme and nodes, not a data dump.

Status (2026-11-22): tasks 1 and 2 done (task 2 in 7b05a7284, task 1 in the landing that adds the closure note below); tasks 3 to 5 open.

## Why

`tests/integration/conftest.py` drops and rebuilds one hard-coded database, `indicagent_test`, on the production cluster at every session start (`pg_terminate_backend`, `DROP DATABASE`, baseline restore, replay of migrations above cutoff 576). Three defects follow, each verified in the code on 2026-11-22:

- Two sessions running integration tests kill each other ("terminating connection due to administrator command"): the second session's rebuild terminates the first's backends.
- Every rebuild runs as superuser on the production cluster: its DDL and restore write WAL that streams to the ubuntu2 standby and the WAL archive, and its load competes with live runs for buffers and disk. So every integration run needs a quiet window, which makes honest testing slow.
- Seven files read the live `indicagent` data by hard-coded URL; one held `SELECT DISTINCT rule_version FROM canonical_bar_lineage` on production for more than six minutes. `test_pipeline_flow.py` also sets `os.environ["DATABASE_URL"]` to the live database at import time, which redirects every later `get_settings()` reader in the session (the classification tests among them, which write inside rolled-back transactions) to production.

Outside the live files the suite collects 173 tests: 156 pass, 1 skips, 16 fail, all classification (todo 655: no classification seed in the baseline).

## Decisions

**(a) Per-session database, on a dedicated test cluster.** The fix for contention is isolation, not a better name on the shared cluster. A second Postgres container, `indicagent-testdb`, runs the production image (`production-timescaledb` today; the pinned `timescaledb-ha` tag once todo 654 lands, by referencing the same image), on port 5442 (5433 is taken by the `ssfi-timescaledb` container, 2026-11-23), data on tmpfs, `fsync=off`, `synchronous_commit=off`, `full_page_writes=off`, no archive, no replication, cgroup caps (`cpus: 4`, `mem_limit: 6g`), server-level `statement_timeout = 60s`. It lives in its own compose file and project (`production/docker-compose.testdb.yml`, project `indicagent-testdb`), so no compose command for it can recreate the production database container.
- Naming: one source, `tests/integration/db.py`. `tests/conftest.py` sets `DATABASE_URL` once at import to `postgresql://postgres:postgres@localhost:5442/indicagent_test_<8 hex>` (random per process, so each xdist worker and each session gets its own; the `indicagent_test` prefix keeps the unit-suite live guard in `tests/unit/conftest.py` treating it as non-live). `db.py` reads that env var and exports `TEST_DB_URL`, `TEST_DB_NAME`, `connect()`; every integration file imports from it, none carries a DSN literal.
- Setup cost: a template database `indicagent_tmpl_<hash12>`, where the hash is SHA-256 over the baseline and seed files, the replayed migration files and `db.py` itself. The first session to need a missing template builds it under `pg_advisory_lock` on the test cluster's `postgres` database (concurrent sessions wait, then reuse it), marks it `datistemplate`, `datallowconn = false`. Each session then runs `CREATE DATABASE <name> TEMPLATE indicagent_tmpl_<hash12>`: about a second for a schema-plus-seed database, against a full rebuild per session. Measure both in task 3 and record the numbers here.
- Cleanup: each session holds `pg_advisory_lock(hashtext(<its db name>))` on a maintenance connection for its life and drops its database at teardown. At start it sweeps every `indicagent_test_%` database whose lock it can take with `pg_try_advisory_lock` (the owner's connection is gone, so the owner is dead) and drops it, and drops templates other than the current hash whose `COMMENT ON DATABASE` build stamp is older than 24 hours. The server releases advisory locks when a connection dies, so a crashed session never blocks the sweep; a tmpfs restart simply starts empty.
- Roles are cluster-wide and a schema dump does not create them, so the baseline gains a roles file (`pg_dumpall --roles-only --no-role-passwords`) applied before the schema.

**(b) Live-reading tests: delete six, keep one under a marker.** A test that reads production data is monitoring; the D7 audit (`services/bar_reconciliation_audit.py` over `src/intelligence/bars/integrity_checks.py`) is the monitoring home.

| File | Decision | What replaces it |
|---|---|---|
| `test_pipeline_flow.py` | delete | nothing: phase 107 smoke on retired tables, and its import-time env override is a hazard |
| `test_battery_waivers_have_recorded_runs.py` | delete | `LEGACY_WAIVERS` is empty, so it only skips. A unit tripwire asserts `battery_pass.LEGACY_WAIVERS == {}` with the message that a waiver needs its recorded-run check at the point the runner consumes it (`battery_pass.py` is not edited: it is hashed research code) |
| `test_scrub_pass_live.py` | delete | one-time landing check of phase 185 plan 10, done. The standing invariant (the tradeable view admits no quarantined bar) moves to `test_market_data_ohlcv_tradeable_view.py` on the test database with fixture rows; a dropped quarantine entry is already the audit's `isolated_wick` finding |
| `test_bar_quality_flag_quarantine.py` | delete | one-time check of migration 381. Its view assertions (quarantined bar hidden, flagged-unquarantined bar visible, column contract) move to the same tradeable-view test with fixture rows |
| `test_d2_single_writer_live.py` | delete after mapping | each of its 6 assertions maps to an audit check (`policy_conformance`, `month_digests`/`stale_digest_months`, `recompute_findings`, `split_discontinuities`) or is dropped as obsolete (IBKR identities: canonical no longer selects IBKR). An assertion with no home becomes a pure check in `integrity_checks.py` run by the audit |
| `test_derived_grid_live.py` | delete after mapping | same mapping for its 7 assertions (`grid_parity` and the digest checks); the IBKR SMART comparison is obsolete |
| `test_migration_schema_sync.py` | keep, marker `live_catalog` | the only test allowed a production DSN. Catalog reads only (`pg_catalog`, `information_schema`), on a connection opened with `-c default_transaction_read_only=on -c statement_timeout=30s -c lock_timeout=1s` and `application_name=indicagent-test-live-catalog`. Skipped unless `--live-catalog` is passed; `tools/gate.py` passes it whenever the diff touches `production/migrations/`, which is when the drift it catches can arise. No research-run guard: catalog reads do not contend with a data run |

`test_classification_schema.py` and `test_instrument_classification_coverage.py` already read `get_settings()`, so they run on the test database; their docstrings and `docs/foundation/security-classification-hierarchy.md` still tell readers to run them against the live database with `--noconftest`, which is fixed in task 4.

**(c) Interim lock until (a) lands.** An exclusive `fcntl.flock` on `logs/integration/test_db.lock` in the main checkout, held for the whole pytest session (not only the rebuild: the clash kills running tests, not the rebuild), with a holder note and a waiting message, the `tools/gate.py` parity-lock model. The lock code moves out of `gate.py` into one Ring 0 helper both import. Task 3 deletes the integration use.

**(d) Baseline bump to the migration head, then delete `_LIVE_BUILD_ONLY`.** Regenerate with `scripts/infrastructure/regenerate_integration_baseline.py`, which gains a `classification` seed (`classification_scheme`, `classification_node`, `instrument_classification`, the three tables migration 364 creates) and the roles file. Set the cutoff to the highest applied migration at dump time, empty `_NOT_IN_BASELINE` once 568 and 571-574 are confirmed applied, delete `_LIVE_BUILD_ONLY`, its stub and `test_live_build_only_migrations.py` (605 is then inside the baseline). This closes todo 655.

**CI.** `.github/workflows/ci.yml` runs `tests/unit/` only. After todo 654 the test cluster's image is a public pinned tag, so CI runs the integration suite against it as a service container (`pytest tests/integration -n auto`; `live_catalog` stays off: CI has no production). Before 654, no: building the custom image per CI run is work 654 deletes.

## Sequencing and windows

| Task | Needs from a quiet window |
|---|---|
| 1 delete the live tests | one integration run on the shared cluster (minutes), lead's slot |
| 2 interim lock | none beyond the unit suite; one short integration run |
| 3 test cluster and per-session databases | none on production: the container is separate and capped; starting it is the one host change |
| 4 baseline bump | a production read (`pg_dump --schema-only`, small data dumps): no DDL, no fingerprinted run, no step window; after the residual run is counted |
| 5 CI | after todo 654 lands |

## Non-goals

- The eight unit files that read the live database read-only under todo 494's guard. Separate concern; not here.
- Rewriting the baseline as a from-empty replay (rejected in the conftest docstring; still true).

## Global constraints

- Done-Coding SOP per task: `/simplify`, `/review`, `pytest tests/unit/ -n auto` exit 0, ruff, black, `tools/check_glossary.py`, independent review. Integration gate: `pytest tests/integration -q` exit code, from task 3 on against the per-session database on the test cluster. Judge by exit code, never a tail.
- No integration test, from task 3 on, connects to port 5432 except `test_migration_schema_sync.py` through `db.PRODUCTION_CATALOG_URL`. A unit boundary test enforces it.
- A missing or unreachable test database fails loud; the reachability `pytest.skip` calls in test-database files go.
- Each task is one commit (or a pair), reversible by `git revert`.

## Review focus

1. Two sessions start at once with no template: one builds, the other waits on the advisory lock and reuses it (task 3 test).
2. A session killed with SIGKILL leaves its database: the next session's sweep drops it, and never drops a live session's database (task 3 test, two connections).
3. A worktree whose migrations differ from main: different hash, its own template, main's template untouched (task 3 test).
4. Running `tests/integration` with the test cluster down: one loud error naming the container and the compose command, not 170 errors or skips (task 3 test).
5. `--live-catalog` passed while production is busy: the 30 s timeout and 1 s lock timeout fail the test loud rather than wait (task 1 test asserts the connection options).

---

### Task 1: Delete the live-reading tests; keep the schema sync behind `live_catalog`

End state: no integration file reads production data; the tradeable-view invariants run on the test database; `test_migration_schema_sync.py` runs only with `--live-catalog`.

Scope:
- [x] Delete `test_pipeline_flow.py`, `test_battery_waivers_have_recorded_runs.py`, `test_scrub_pass_live.py`, `test_bar_quality_flag_quarantine.py`.
- [x] Map each assertion of `test_d2_single_writer_live.py` and `test_derived_grid_live.py` to an audit check or "obsolete (IBKR)"; write the map into this todo's fix note; add a pure check plus unit test for any assertion with no home; then delete both files.
- [x] Extend `test_market_data_ohlcv_tradeable_view.py`: `test_quarantined_bar_is_hidden`, `test_flagged_unquarantined_bar_is_visible`, `test_view_column_contract` (insert fixture rows in a rolled-back transaction).
- [x] `tests/unit/research/test_battery_pass.py::test_legacy_waivers_stay_empty` asserting `LEGACY_WAIVERS == {}`.
- [x] Register `live_catalog` in `pytest.ini`; add the `--live-catalog` option and skip hook to `tests/integration/conftest.py`; open the production connection in the schema sync test with the options in decision (b).
- [x] `tools/gate.py`: add `--live-catalog tests/integration/test_migration_schema_sync.py` to the plan when a changed path is under `production/migrations/`; unit test in `tests/unit/tools/` for the classification.

TDD: write the three view tests and the gate classification test, see them fail, implement, see them pass.
Gates: unit suite exit 0; `pytest tests/integration/test_market_data_ohlcv_tradeable_view.py` exit 0; `grep -rln "5432/indicagent\"" tests/integration` lists only the schema sync test; independent review of the assertion map.
Rollback: `git revert`; nothing outside the repo changed.

### Task 2: Interim cross-session lock

End state: a second integration session waits, naming the holder, instead of killing the first.

Scope:
- [ ] Move `parity_lock` from `tools/gate.py` to `src/core/file_lock.py` as `exclusive_file_lock(path: Path, note: str, *, timeout: float, poll: float) -> Iterator[None]` (context manager); `gate.py` imports it.
- [ ] `tests/integration/conftest.py`: `migrated_test_database` becomes a yield fixture holding `exclusive_file_lock(<main checkout>/logs/integration/test_db.lock, ...)` for the session, timeout 2 h as a module constant (test harness code, outside the APR scope of `src/` and `services/`).
- [ ] Unit tests in `tests/unit/core/test_file_lock.py`: second holder waits and gets in after release; timeout raises naming the holder note; a dead holder's lock is free (flock released on close).

TDD as listed. Gates: unit suite exit 0; two concurrent `pytest tests/integration/test_ucr_fk_indexes.py` runs both exit 0 (one waits). Rollback: `git revert`.

### Task 3: Test cluster, per-session database from a template

End state: `pytest tests/integration` on any session or worktree runs on its own database on `indicagent-testdb`, set up in about a second when the template exists, with no connection to port 5432 except the schema sync test.

Scope:
- [ ] `production/docker-compose.testdb.yml` (service `testdb`, project `indicagent-testdb`, image as decision (a), port 5442, tmpfs, the settings and caps listed); runbook lines in `docs/operations/operations-infrastructure.md` (start, stop, it is disposable).
- [ ] `tests/integration/db.py`: `TEST_DB_URL`, `TEST_DB_NAME`, `MAINTENANCE_URL` (5433/postgres), `PRODUCTION_CATALOG_URL`, `connect(*, autocommit: bool = True) -> psycopg.Connection`, `template_hash(paths: Iterable[Path]) -> str`, `ensure_template(hash12: str) -> str`, `create_session_database(template: str, name: str) -> None`, `sweep_stale(prefix: str = "indicagent_test_") -> list[str]`.
- [ ] `tests/conftest.py` sets `DATABASE_URL` from a per-process random suffix on port 5442.
- [ ] `tests/integration/conftest.py`: the build code (baseline, roles file, seeds, replay) runs only inside `ensure_template`; the session fixture sweeps, creates, holds its advisory lock, drops at teardown; the interim file lock from task 2 is removed.
- [ ] Every file in `tests/integration` with a DSN literal or `current_database() == "indicagent_test"` reads `db.py` instead (concept_parent_lineage, oos_start_write_once, ucr_fk_indexes, research_ledger, concept_registry_transition, d2_writer_can_upsert_1d, d2_excludes_test_caller_observations, market_regimes_replace, market_data_ohlcv_tradeable_view, migration_schema_sync, ingress_write_contract, ohlcv_coverage_atomic_write, corpus_rerun_store, ticker_entity_map_install_db, which today creates its own database on the production cluster); their reachability skips go.
- [ ] `tests/unit/test_integration_db_boundary.py`: no file under `tests/integration/` holds `:5432/` or a bare `indicagent_test"` literal, except the allow-listed `db.py`.
- [ ] Integration tests in `tests/integration/test_harness_isolation.py` for review focus items 1 to 4.
- [ ] Record the measured template build time and per-session create time in this todo.

TDD: boundary unit test and the isolation tests first (fail on today's harness), then the code.
Gates: unit suite exit 0; `pytest tests/integration -n 4` exit 0 except the 16 classification failures until task 4 (counted, not tailed); two sessions in parallel both exit 0; `pg_stat_activity` on the production cluster shows no `indicagent_test%` database during the run; independent review.
Rollback: `git revert`, `docker compose -p indicagent-testdb down`; the production cluster is untouched, and dropping the leftover `indicagent_test` there is a separate, later cleanup the lead calls.

### Task 4: Baseline at the migration head, classification seed, delete `_LIVE_BUILD_ONLY`

End state: the integration suite is green on a fresh session database; todo 655 closed.

Scope:
- [ ] `regenerate_integration_baseline.py`: add the `classification` seed and the roles file; unit test of its plan (file list) without a database.
- [ ] Run it in the window (decision table); new fixture files with today's date; delete the 2026-11-05 files.
- [ ] Conftest: point at the new date, set the cutoff, empty `_NOT_IN_BASELINE` after checking `schema_migrations` or equivalent for 568 and 571-574, delete `_LIVE_BUILD_ONLY`, its stub and `test_live_build_only_migrations.py`.
- [ ] Fix the stale docstrings of the two classification test files and the run instructions in `docs/foundation/security-classification-hierarchy.md`; update `docs/reference/gotchas.md` (the baseline-lag section, and the harness model) and `docs/reference/cheatsheet.md` line 83.
- [ ] Close todo 655 in the same commit.

Gates: `pytest tests/integration` exit 0 on a session database (0 failed); `pytest tests/integration --live-catalog -k schema_sync` exit 0 in the window; unit suite exit 0; independent review.
Rollback: `git revert` restores the old fixtures and the 605 exclusion.

### Task 5: CI runs the integration suite (after todo 654)

End state: every push runs the integration suite against the pinned production image in CI.

Scope:
- [ ] `.github/workflows/ci.yml`: an `integration` job with a service container on the pinned `timescaledb-ha` tag, the same server settings as the compose file, `pytest tests/integration -n auto` with the job failing on a non-zero exit.
- [ ] The image tag appears in the compose file and the workflow; a unit test asserts the two are equal, so the CI image cannot drift from the one sessions use.

Gates: the CI job green on a push; a deliberately broken migration on a scratch branch fails it. Rollback: `git revert` of the workflow change.

## Lead rulings (2026-11-22, indicagent-12)

Plan confirmed; execution waits for the daily residual run to be counted and the lead's ping.

- (a) Disposable `indicagent-testdb`: yes. Cap its memory hard (4 GB container limit, small `shared_buffers`), because the first daily launch died to a system-wide OOM. Never co-schedule it with a counted run. The compose file follows the production log caps.
- (b) Delete the six live-reading tests: yes, but each deleted assertion gets a one-line disposition in this todo's closure note before the deletion lands (mapped to a named D7 audit check, moved to the test database, or obsolete with the reason). Keep `test_migration_schema_sync` behind `--live-catalog`.
- (c) Session-long `flock` in `src/core/file_lock.py` (Ring 0), removed when (a) lands.
- (d) Baseline bump: yes, in a quiet window only (no fingerprinted run, no step 7 window); tell the lead before reading production.
- Order change: fix the `test_pipeline_flow` `DATABASE_URL` import side effect first, by deleting it with its disposition note. That deletion is task 1 (highest hazard). CI integration only after todo 654.

## Task 1 closure note: dispositions

Every test function of the six deleted files, one line each. A: a named check of the D7 audit (`services/bar_reconciliation_audit.py`, timer daily 06:00 UTC, over `src/intelligence/bars/integrity_checks.py`) holds it, with the unit test that pins the check. B: moved to the test database or to a pure function with a unit test. C: obsolete, with the reason. Totals: 33 functions, A 10, B 12, C 11 (a mixed row counts under its first letter). Each A and B home below was verified by reading the named code and unit test on 2026-11-22.

| File | Test | Disposition |
|---|---|---|
| test_pipeline_flow.py | test_timescaledb_connectable_sync | C: phase 107 smoke; every integration session connects anyway, and production health is service_auditor's and the nightly audits' |
| test_pipeline_flow.py | test_intelligence_features_has_recent_data_sync | C: `intelligence_features` is a deleted v2.x table; the assertion was `count >= 0` |
| test_pipeline_flow.py | test_signal_ledger_has_recent_data_sync | C: v2.x signal path deleted (phase 185-45); `count >= 0` |
| test_pipeline_flow.py | test_market_data_ohlcv_has_recent_data_sync | C: `count >= 0` asserts nothing; canonical freshness is the audit's `freshness_1d` |
| test_pipeline_flow.py | test_jsonb_not_double_serialized_sync | C: reads the deleted `intelligence_features`; the asyncpg codec rule is in gotchas |
| test_pipeline_flow.py | test_signal_ledger_schema_columns_exist_sync | C: v2.x table; the schema of what exists is `test_migration_schema_sync.py`'s |
| test_pipeline_flow.py | test_intelligence_features_schema_columns_exist_sync | C: v2.x table, as above |
| test_battery_waivers_have_recorded_runs.py | test_every_waiver_row_has_a_recorded_real_run | B: `tests/unit/research/test_battery_pass.py::test_legacy_waivers_stay_empty` (the waiver table is empty, so the old test only skipped; a waiver needs its recorded-run check where the runner consumes it) |
| test_scrub_pass_live.py | test_fixture_sizes_pinned | B: already `tests/unit/bars/test_fixtures_present.py::test_dry_run_report_section_counts` (45/27/1864) |
| test_scrub_pass_live.py | test_all_72_dry_run_keys_quarantined_and_hidden | B: the rule's verdicts on the known answers are `tests/unit/bars/test_scrub_known_answers.py::test_all_45_confirmed_corrupt_rows_quarantined`; hidden-when-quarantined is `test_market_data_ohlcv_tradeable_view.py::test_quarantined_bar_is_hidden`; a wick the view still serves is the audit's `isolated_wick` |
| test_scrub_pass_live.py | test_no_ambiguous_key_is_quarantined | B: `test_scrub_known_answers.py::test_none_of_the_1864_ambiguous_rows_quarantined` |
| test_scrub_pass_live.py | test_15_legacy_1d_keys_quarantined | B: `test_scrub_known_answers.py::test_all_15_legacy_confirmed_corrupt_1d_rows_quarantined_or_recorded` |
| test_scrub_pass_live.py | test_both_timeframes_have_completed_scrub_batches | C: one-time landing record of phase 185 plan 10 |
| test_scrub_pass_live.py | test_integrity_facts_recorded_per_timeframe | C: one-time landing record of phase 185 plan 10 |
| test_scrub_pass_live.py | test_tradeable_view_admits_no_quarantined_bar | B: `test_market_data_ohlcv_tradeable_view.py::test_quarantined_bar_is_hidden` (the anti-join count, on fixture rows) |
| test_bar_quality_flag_quarantine.py | test_legacy_copy_survives_and_no_status_bar_is_visible | B + C: the legacy copy stays protected and quarantining by `services/bar_scrub.py` `_PROTECTED_RULES` (`tests/unit/services/test_bar_scrub.py::test_write_flags_refuses_legacy_rule_in_evaluated_set`, `::test_write_flags_prune_stale_deletes_other_rules_except_legacy`); the status-visibility half is C, `price_sanity_status` is no longer a visibility rule (migration 447) |
| test_bar_quality_flag_quarantine.py | test_quarantined_bars_absent_from_tradeable_view | B: `test_market_data_ohlcv_tradeable_view.py::test_quarantined_bar_is_hidden` |
| test_bar_quality_flag_quarantine.py | test_unquarantined_flagged_bars_still_visible | B: `test_market_data_ohlcv_tradeable_view.py::test_flagged_unquarantined_bar_is_visible` |
| test_bar_quality_flag_quarantine.py | test_dropped_index_gone | C: one-time check that migration 381 applied (an index drop) |
| test_bar_quality_flag_quarantine.py | test_tradeable_view_column_contract | B: `test_market_data_ohlcv_tradeable_view.py::test_view_column_contract` (plus the venue volume null) |
| test_d2_single_writer_live.py | test_the_corpus_holds_only_d2v2_canonical_identities | A: `policy_conformance` (stricter, per date; `tests/unit/bars/test_integrity_checks.py::test_a_contradicting_pair_fails_policy_conformance`, and the d2-v6 case `test_policy_conformance_under_d2v6_accepts_massive_then_alpaca_and_flags_every_ibkr_pair` added here) and `check_stray_sources` (`tests/unit/services/test_bar_reconciliation_audit.py::test_the_retired_vendor_is_a_stray_daily_pair`). The presence half (IBKR pairs must exist) is C: IBKR removed 2026-11-13 |
| test_d2_single_writer_live.py | test_ibkr_named_bars_sit_only_under_an_ibkr_exception_policy_row | A: `policy_conformance`: no d2-v6 row names IBKR, so every IBKR row fails it (the d2-v6 unit test above) |
| test_d2_single_writer_live.py | test_lineage_view_holds_only_the_current_rule_version | A: `stale_digest_months` (`digest_fresh`) fails a month whose digest is not of `RULE_VERSION`; `test_digest_fresh_fails_on_drift_missing_month_or_old_rule_version` |
| test_d2_single_writer_live.py | test_stored_values_equal_derive_daily_for_a_sample_recomputed_from_d1 | A: `recompute_findings` (`canonical_recompute`) over every active name, not a sample; `test_recompute_fails_on_a_changed_extra_or_missing_bar`. The IBKR sample categories are C |
| test_d2_single_writer_live.py | test_digest_covers_every_1d_month_with_bars | A: `month_digests` + `stale_digest_months` (`digest_fresh`) flag a missing month; same unit test |
| test_d2_single_writer_live.py | test_no_scale_break_across_a_split_unless_flagged_pre_split_unrefetched | A: `split_discontinuities` (`split_continuity`), judged against the split product, stricter than the old 2x band; `test_split_continuity_names_an_unadjusted_and_a_double_adjusted_split` |
| test_derived_grid_live.py | test_no_session_has_1h_rows_at_two_minutes | A + B: a foreign 1h row is `stray_vendor_rows` (`test_stray_vendor_rows_fail_per_timeframe`); one anchor per session is `aggregate_session_grid`'s (`tests/unit/bars/test_session_grid.py::test_full_day_grid_shapes`). Stored-row equality: gap 1 below |
| test_derived_grid_live.py | test_derived_symbols_1h_rows_are_derived_and_session_anchored | A + B: `stray_vendor_rows`; anchoring is `test_full_day_grid_shapes`, `test_half_day_grid_shapes`, `test_nyse_sessions_dst_transition_opens`; the delayed open is `tests/unit/bars/test_nyse_sessions_grid_alignment.py` (see correction 1) |
| test_derived_grid_live.py | test_derived_bars_equal_direct_5m_aggregation | B: `test_session_grid.py::test_grid_equals_direct_loop`; stored rows equal to the derivation: `grid_recompute_findings` (gap 1) |
| test_derived_grid_live.py | test_first_1h_open_equals_the_first_5m_open_of_every_session | B: `test_grid_equals_direct_loop`; quarantined 5m are dropped before aggregation (`tests/unit/services/test_bar_derivation_grid.py::test_constituent_flags_list_kept_bar_rules_and_quarantine_excludes`) |
| test_derived_grid_live.py | test_1h_volume_close_and_open_agree_with_ibkr_smart_1d_observations | C: IBKR removed 2026-11-13; canonical 5m holds no IBKR session since the step 7 rebuild (d2-v6, 2026-11-16) |
| test_derived_grid_live.py | test_canonical_grid_holds_derived_rows_only_and_raw_holds_vendor_parity | A + C: canonical half is `stray_vendor_rows` and `check_stray_sources` (`ALLOWED_PAIRS` 15m/1h = the derived pair), the grid stage fails loud on a vendor row (`test_a_stored_vendor_row_fails_the_symbol_loud_and_writes_nothing`), the writer fence `tests/unit/test_market_data_ohlcv_writer_boundary.py`; the raw IBKR parity half is C (Part F deletes those rows) |
| test_derived_grid_live.py | test_digest_current_covers_5m_15m_1h_for_derived_symbols | A: intraday `digest_fresh` (`intraday_month_digests` + `stale_intraday_months`) fails a month with a recompute but no stored digest, per timeframe; the missing-month case is now pinned by `test_bar_reconciliation_audit.py::test_a_missing_stored_digest_fails_only_its_timeframe` (the existing case covered a wrong digest only) |

Gaps:
1. Stored 15m/1h rows equal to the derivation of current 5m: closed in the check library, open in monitoring until todo 657 wires it. `integrity_checks.grid_recompute_findings` (pure, same `write_contract.classify` comparison as `recompute_findings`, identity included), unit test `test_grid_recompute_flags_a_changed_extra_or_missing_bucket`. Intraday `digest_fresh` cannot see this: the grid stage writes the digest from the values it derived (`services/bar_derivation.py`, `_month_digest_rows` over `derived`), not from the rows it stored. Not wired into the audit yet: todo 657.
2. d2-v6 policy conformance: `test_policy_conformance_under_d2v6_accepts_massive_then_alpaca_and_flags_every_ibkr_pair`.

Corrections to the draft map:
1. The late open: the draft said no unit case covers a 09:32 open. One does, and the deleted test's own expectation was stale: `nyse_sessions` floors mcal's 09:32 open on 2006-12-27 to the 09:30 vendor grid (`tests/unit/bars/test_nyse_sessions_grid_alignment.py::test_delayed_open_is_floored_to_the_five_minute_grid`), so the derived grid of that day anchors at 09:30, not :32. Added `test_the_delayed_open_day_derives_its_grid_on_the_vendor_grid` to pin the grid end to end.
2. `judge_name_intraday` lives in `services/bar_reconciliation_audit.py`, not in `integrity_checks.py`.

Follow-up, filed as todo 657: wire a `grid_recompute` verdict per 15m/1h into `judge_name_intraday`. It needs a per-name read of the stored canonical 15m/1h rows (the loader reads 5m and the raw archive only), a field on `_IntradayInputs`, the aggregate over the months `digest_scope` picks, and a new name in `CHECKS_INTRADAY`, which changes the audit's verdict list and every reader of it, in a module a timer imports. More than a few lines and an output-contract change, so it gets its own reviewed change.

Scope notes (both filed in todo 657):
- `CANONICAL_1D_SOURCES` still admits the three IBKR pairs, so `check_stray_sources` would not flag a stray IBKR 1d row (only `policy_conformance` would, and it judges `is_active` names only). After Part F, removing those pairs makes the stray check enforce no IBKR in canonical; separate change.
- `check_daily_vs_intraday` reads IBKR SMART observations, so it is vacuous after Part F; nothing vendor-neutral compares canonical 1d to the canonical 5m aggregate. A successor needs a measured tolerance first.
- `test_migration_schema_sync.py` now runs only with `--live-catalog` (marker `live_catalog`), on a production connection with `default_transaction_read_only=on`, `statement_timeout=30s`, `lock_timeout=1s`, `application_name=indicagent-test-live-catalog`; its three queries read `information_schema` and `pg_catalog` only (`tests/unit/test_live_catalog_schema_sync.py` pins both). `tools/gate.py` adds the `live_catalog` step whenever a path under `production/migrations/` changed, and the step fails unless the test reports `1 passed`.
