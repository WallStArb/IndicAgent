---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "05"
subsystem: database
tags: [postgres, timescaledb, index-hygiene, primary-keys, migrations, performance-baseline]

requires:
  - phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
    provides: plan, research facts (D-36/D-37/D-38, live index and settings measurements)
provides:
  - market_regimes duplicate index dropped (D-36), ~387 MB freed, one btree less per regime write
  - every public table has a PK or a recorded disposition (D-37); drift_monitor dropped
  - reusable read-only D-38 baseline script + committed before-JSON for 186-17
  - work_mem drift cause proven with evidence (R-12)
affects: [186-17 (postgres tuning), 186-11 (ctx_events drop), 186-22 (feature_ic_scores_history and construction_spreads drop)]

tech-stack:
  added: [pyyaml-based compose parsing in scripts/ops/db/ops_pg_settings_baseline.py]
  patterns:
    - "surrogate (id, time) PK over an existing sequence or identity column on hypertables Timescale cannot retrofit with USING INDEX"
    - "compression toggle off/ALTER/on inside one migration transaction for identity columns on columnstore hypertables (no chunk round trip, no VACUUM rule)"

key-files:
  created:
    - production/migrations/384_market_regimes_duplicate_index_drop.sql
    - production/migrations/385_primary_key_inventory.sql
    - scripts/ops/db/ops_pg_settings_baseline.py
    - scripts/ops/db/__init__.py
    - tests/unit/scripts/test_ops_pg_settings_baseline.py
  modified:
    - scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py
    - docs/operations/operations-database.md
    - .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-05-pg-baseline.json (created; the committed baseline)

key-decisions:
  - "uq_transform_graduation was a UNIQUE constraint, not an adoptable index: replaced in one ALTER by an equivalent PRIMARY KEY over the same columns (ON CONFLICT target inference unchanged)"
  - "market_data_ohlcv stays on its unique index as the recorded PK-equivalent exception; A1 re-confirmed on Timescale 2.27.1"
  - "work_mem 8MB vs compose 64MB: the container (created 2026-06-22) predates the 64MB compose edit (48bd250fa, 2026-08-13) and was never recreated, only restarted"

patterns-established:
  - "new-table rule: every new table carries a PK, hypertable PKs include the time column; market_data_ohlcv is the single recorded exception (docs/operations/operations-database.md)"

requirements-completed: [D-36, D-37, D-38, R-12, D-16, D-08]

duration: 4h16m wall (includes ~4h quota pause; ~15m active)
completed: 2026-09-28
---

# Phase 186 Plan 05: Database hygiene Summary

**Duplicate market_regimes index dropped concurrently with EXPLAIN proof, 11 no-PK tables dispositioned (7 PKs added, drift_monitor dropped), and a committed D-38 baseline whose work_mem drift cause is proven: the container predates the compose edit and was never recreated.**

## Performance

- **Duration:** ~15 min active (4h16m wall including the quota pause between Tasks 2 and 3)
- **Started:** 2026-09-28T06:56:14Z
- **Completed:** 2026-09-28T11:11:57Z
- **Tasks:** 3/3
- **Files modified:** 8 (2 migrations, 1 script + package, 1 test file, reset script, ops doc, baseline JSON, this summary)

## Accomplishments
- D-36: `market_regimes_regime_group_tf_ts` (387 MB, idx_scan 31,851,965) dropped via `DROP INDEX CONCURRENTLY`; all four ic_engine query shapes verified equal-or-better on `market_regimes_pkey` before and after
- D-37: every public table now has a PK except `market_data_ohlcv` (recorded unique-index equivalent, A1 confirmed) and the two tables other plans drop (ctx_events 186-11, feature_ic_scores_history 186-22); `drift_monitor` dropped with its reset-script entry removed in the same commit
- D-38/R-12: read-only baseline committed as JSON with a tested re-runnable script; drift cause established from five evidence points; nothing tuned, nothing restarted (StartedAt unchanged 2026-09-24T10:42:17Z)

## Task Commits

1. **Task 1: duplicate market_regimes index drop** - `afbae7ac6` (chore; migration 384 applied live and committed with its apply)
2. **Task 2: PK inventory, drift_monitor drop** - `d46e030f5` (chore; migration 385 applied live and committed with its apply, reset script + ops doc in the same commit)
3. **Task 3: D-38 baseline (TDD)** - `b431655e4` (test, RED) / `a9bbe3f40` (feat, GREEN) / `606004d57` (feat, measurements + compare fixes)

## Files Created/Modified
- `production/migrations/384_market_regimes_duplicate_index_drop.sql` - the D-36 drop, no BEGIN/COMMIT (CONCURRENTLY), evidence in header
- `production/migrations/385_primary_key_inventory.sql` - D-37 dispositions, PKs, drift_monitor drop, A1 text, compression toggles
- `scripts/ops/db/ops_pg_settings_baseline.py` (+ `__init__.py`) - read-only D-38 capture and drift comparison
- `tests/unit/scripts/test_ops_pg_settings_baseline.py` - 9 unit tests (temp compose files, fake pg_settings rows; no DB, no docker)
- `scripts/infrastructure/backfill/infrastructure_reset_pipeline_data.py` - drift_monitor tuple removed
- `docs/operations/operations-database.md` - "Primary key inventory (D-37, phase 186)" section; drift_monitor removed from the wipe prose
- `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-05-pg-baseline.json` - the before measurement for 186-17

## D-36 evidence (Task 1)

Precondition gate passed: no ic_engine/regime_writer/backfill_feature_factory/cross_sectional_regime/feature_lifecycle process in `ps aux`; zero rows in pg_locks on market_regimes; zero idle-in-transaction sessions.

Index evidence before: `market_regimes_pkey` UNIQUE (regime_group, tf, ts) 400 MB idx_scan 0; `market_regimes_regime_group_tf_ts` btree same columns 387 MB idx_scan 31,851,965. Plain table, ~5.35M rows, 1806 MB total.

D-08 grep (both historical names, repo-wide excluding .venv): `production/migrations/171_market_regimes.sql` (creation), `production/migrations/222_regime_group.sql` (rename), `docs/plans/archive/2026-07-01-cross-sectional-regime-model.md`, `.planning/milestones/v3.1-phases/144-*` (PATTERNS, 01-PLAN), `.planning/phases/186-*/186-05-PLAN.md`, `186-PLAN-OUTLINE.md`, `186-RESEARCH.md`, and the two dated integration baseline dumps (`schema_baseline_2026-07-18.sql`, `schema_baseline_2026-09-27.sql`, left alone). No src/services/scripts code names the index.

EXPLAIN (ANALYZE, BUFFERS) on equity/5m/low_bull (554,177 rows; twe 2025-12-24 05:15Z), plan node + execution time, before -> rolled-back-drop proof -> after apply + ANALYZE:

| Query (ic_engine site) | Before | In-txn drop proof | After |
|---|---|---|---|
| watermark MAX/COUNT/md5 (~1207) | Index Scan `..._regime_group_tf_ts`, 459.0 ms | Index Scan `market_regimes_pkey`, 663.7 ms (1.45x, within 2x gate) | Index Scan `market_regimes_pkey`, 391.2 ms |
| DISTINCT ts subquery (~4554) | Parallel Seq Scan, 312.4 ms | Parallel Seq Scan (same), 244.9 ms | Parallel Seq Scan, 235.3 ms |
| ordered ts prefetch (~4832) | Gather Merge + Parallel Seq Scan, 221.0 ms | same shape, 173.4 ms | same shape, 155.7 ms |
| full group/tf fetch (~6216) | Index Scan `..._regime_group_tf_ts`, 266.4 ms | Index Scan `market_regimes_pkey`, 228.2 ms | Index Scan `market_regimes_pkey`, 208.3 ms |

Acceptance verified live: pg_indexes for market_regimes = `market_regimes_pkey` only; `indisvalid` = t; migration grep counts 1/0.

## D-37 evidence (Task 2)

Inventory re-run matched the 11-table set exactly. Row counts: integrity_monitor 299 (interfaces said 287; its live writer appended rows, disposition unaffected), feature_ic_scores_history 49,568,124 (grew from ~49.3M, dropped by 186-22 anyway), all others as planned (0 rows; transform_graduation plain table).

D-08 grep hits per table (src/services/scripts/tests/production/systemd/production/grafana/docs, migrations + baseline dumps excluded):
- **ctx_events**: services/context_writer.py (writer, named columns), reset-script list, canonical-truth-registry doc, tests -> no change, 186-11 drops
- **feature_ic_scores_history**: services/ic_engine.py ~1423/~1460 (old-chain INSERTs), test_summary_cards -> no change, 186-22 drops
- **market_data_ohlcv**: bar_writer + backfill_feature_factory + bar_derivation/bar_auditor/bar_scrub + many readers (boundary allow-lists), ops scripts, docs -> kept, unique-index PK equivalent
- **dlq_events**: services/dlq_writer.py (named columns), reset preserved-list, service_auditor DAG comment, systemd unit (loaded, inactive, disabled) -> PK (id, routed_at)
- **integrity_monitor**: src/core/integrity_monitor.py (both INSERT styles name columns), live readers feature_lifecycle/forward_return_writer/vocabulary_drift + ops scripts -> PK (id, evaluated_at)
- **drift_monitor**: ONLY infrastructure_reset_pipeline_data.py line ~66 list entry, plus operations-database.md prose (updated in this commit) -> DROPPED
- **alpha_multiplier_shadow**: dormant I8 (src/core/ai/lineage.py, alpha prompts, kafka topic setup), reset list, promotion-protocol doc -> id IDENTITY + PK (id, ts)
- **service_health_events**: service_auditor.py INSERT (named columns) -> id IDENTITY + PK (id, ts)
- **signal_lineage**: lineage_writer.py INSERT (named columns, ON CONFLICT DO NOTHING; unit `indicagent-lineage-writer` active), alpha_swarm, ai_stats route, tests -> id IDENTITY + PK (id, ts)
- **signal_transform_log**: transform_recorder.py INSERT (named columns), graduation_analyzer -> id IDENTITY + PK (id, ts)
- **transform_graduation**: repository UPSERT ON CONFLICT (transform_id, transform_version, segment_key), graduation_writer/analyzer -> PK over those columns

A1 probe (scratch hypertable, BEGIN/ROLLBACK): `ERROR: hypertables do not support adding a constraint using an existing index` - exactly as expected; the conditional branch (probe succeeds -> separate SOP plan + todo) did NOT trigger. Scratch table cleaned up by the rollback.

Timescale 2.27.1 rejections observed live: `ADD COLUMN ... GENERATED ... AS IDENTITY` on columnstore-enabled hypertables -> "cannot add column with constraints to a hypertable that has columnstore enabled"; the four identity tables therefore toggled compression off/on inside the migration with the exact prior settings (segmentby symbol/service/segment_key, orderby ts DESC NULLS FIRST; verified identical after apply; WARNING "column id should be used for segmenting or ordering" is expected and harmless). No chunk compressed or decompressed (0 chunks on all four); vacuum-check test passes.

Post-apply acceptance verified live: no-PK set = `ctx_events,feature_ic_scores_history,market_data_ohlcv`; `to_regclass('drift_monitor') is null` = t; 7 new PK constraints; reset-script grep 0; "Primary key inventory" doc count 1.

## D-38 / R-12 evidence (Task 3)

Measurement context: no batch job running (ps aux gate re-run); iostat -x 1 30 on nvme0n1 (the only physical disk; dm-0 above it): avg r/s 23.7, w/s 10.9, w_await 4.63 ms, %util 0.89 (idle). Cumulative since stats_reset: buffer hit 98.83%, 55,517 temp files, 1,011 GB temp bytes - the spill evidence against work_mem 8 MB. Current top spiller in pg_stat_statements is this plan's own Task 1 EXPLAIN (4,371 blocks written / 3 calls); the durable spillers are in the committed JSON.

Drift diagnosis, each point recorded:
- (a) `docker inspect` .Config.Cmd ends `-c work_mem=8MB` - the running command line, not the compose 64MB
- (b) container Created 2026-06-22; the commit introducing work_mem=64MB is `48bd250fa` (2026-08-13) - the container PREDATES the edit by ~7 weeks; StartedAt 2026-09-24 is a restart, which reuses the old Cmd
- (c) compose project config_files label = `/home/bg/dev/indicagent/production/docker-compose.yml`, and `production/docker-compose*.yml` matches exactly that one file - no other compose file, no override
- (d) pg_settings work_mem: setting 8192 kB, source `command line`, sourcefile NULL - not ALTER SYSTEM, not postgresql.conf
- (e) pg_db_role_setting: only statement_timeout=30min (role postgres) and idle_in_transaction_session_timeout/idle_session_timeout=60min (db indicagent) - no work_mem override anywhere

**Stated cause (evidence-backed):** the timescaledb container was created 2026-06-22 with work_mem=8MB in its command line; the compose edit to 64MB (48bd250fa, 2026-08-13) was never followed by `docker compose up -d` (recreate), and plain restarts/reboots reuse the recorded Cmd. The research hypothesis is confirmed.

A2 facts for 186-17: dynamic_shared_memory_type = posix (source: configuration file /var/lib/postgresql/18/docker/postgresql.conf) -> dynamic segments use /dev/shm, which is 512.0M inside the container (HostConfig.ShmSize 536870912, compose shm_size '512m'; 9.1M used).

**186-17 recommendation (stated, not applied):** the drift fix is itself the first tuning step - recreate the container so the already-reviewed compose work_mem=64MB takes effect, then re-take this baseline with the same script and check the top spillers' temp_blks_written per call falls. shared_buffers ~25% of host RAM after ssfi-timescaledb's footprint (host 29.47 GiB total, ssfi measured at only 95.7 MiB, MemAvailable 20.6 GiB) lands around 7 GB (current 3 GB, effective_cache_size 17 GB); with posix DSM on a 512 MB /dev/shm, watch /dev/shm usage after any work_mem rise and consider raising shm_size in the same change window. Recreate only with no batch job running (SOP).

## Decisions Made
- transform_graduation: constraint-for-PK swap in one ALTER (see Deviations) instead of the plan's literal `USING INDEX`, which Postgres rejects for a constraint-owned index
- The four identity-column hypertables keep their exact compression settings; the toggle is recorded in the migration header per table
- construction_spreads_name_tf_idx recorded as moot in migration 384's header (186-22 drops the table)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] transform_graduation PK could not use ADD CONSTRAINT ... USING INDEX**
- **Found during:** Task 2 dry run
- **Issue:** `uq_transform_graduation` is a UNIQUE constraint (contype 'u'), not a bare adoptable index: "index ... is already associated with a constraint"
- **Fix:** one ALTER drops the unique constraint and adds `transform_graduation_pkey PRIMARY KEY (transform_id, transform_version, segment_key)` - same columns, strict upgrade, ON CONFLICT inference unchanged; table empty and plain, dry-run first
- **Files modified:** production/migrations/385_primary_key_inventory.sql
- **Verification:** post-apply constraintdef check; repository UPSERT target infers the PK
- **Committed in:** d46e030f5

**2. [Rule 1 - Bug] baseline compare flagged knowable settings as unknown, and bare compose numbers missed native-unit semantics**
- **Found during:** Task 3 live run (the plan's own "never write results before running" discipline)
- **Issue:** fetch covered only _TRACKED_SETTINGS so compose-only keys (max_connections etc.) read as "unknown"; and wal_buffers=8192 compared unequal to itself because the compose side lacked the 8kB native unit
- **Fix:** fetch the union of tracked + compose keys; interpret bare numeric compose values in the running setting's native unit; two new regression tests
- **Files modified:** scripts/ops/db/ops_pg_settings_baseline.py, tests/unit/scripts/test_ops_pg_settings_baseline.py
- **Verification:** 9/9 tests; live run now reports only the true drift (work_mem)
- **Committed in:** 606004d57

**3. [Process] Task 3 commit structure: RED/GREEN/measurement instead of one commit**
- The plan marks Task 3 tdd="true" but names a single commit message; the TDD gate (test commit, then feat commit) takes precedence. Three commits: b431655e4, a9bbe3f40, 606004d57.

---

**Total deviations:** 3 (1 blocker auto-fix, 1 bug auto-fix, 1 process note)
**Impact on plan:** All preserve reviewed intent; no scope creep, no acceptance criterion loosened.

## Issues Encountered
- Quota exhaustion paused execution between Tasks 2 and 3 (~4h wall); resumed cleanly, no rework needed.
- integrity_monitor 287 -> 299 rows and feature_ic_scores_history growth between planning and execution (live writers); dispositions unaffected, recorded above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 186-17 can proceed: baseline JSON + script committed, drift cause known (recreate, not just restart, applies compose settings), A2 confirmed (posix / /dev/shm 512 MB)
- 186-11 and 186-22 own the remaining two no-PK tables; migration 384's header records construction_spreads as moot for 186-22
- Workload note: the market_regimes EXPLAINs in pg_stat_statements are this plan's own diagnostics, not production load

## Self-Check: PASSED

- All created/modified files exist on the branch (migrations 384/385, script, tests, reset script, ops doc, baseline JSON)
- Commits afbae7ac6, d46e030f5, b431655e4, a9bbe3f40, 606004d57 present on gsd/186-05-db-hygiene
- Plan verification block re-run: single index on market_regimes; no-PK set as expected; both named test files green (10 passed); tests/unit collects; baseline JSON keys validated; container StartedAt unchanged
