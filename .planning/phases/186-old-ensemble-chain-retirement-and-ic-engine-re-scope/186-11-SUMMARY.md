---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 11
subsystem: infra
tags: [ctx-writer, retirement, migration, systemd]
requires: [186-01]
provides:
  - indicagent-ctx-writer unit uninstalled; ctx_events and ctx_snapshots dropped (migration 388)
affects: [186-22, 186-19]
key-files:
  created: [production/migrations/388_drop_ctx_tables.sql]
  modified: [services/service_auditor.py, src/core/stream_keys.py, tests/unit/services/test_service_auditor_registry_integrity.py]
decisions:
  - "Migration number 388 (live tail was 387)"
metrics:
  completed: 2026-09-29
---

# Phase 186 Plan 11: ctx-writer retirement summary

The ctx pipeline is gone: the unit is uninstalled from the host, the module and every live reference are deleted, and `ctx_events` and `ctx_snapshots` are dropped by a guarded migration (388) committed with its apply.

## Commits (branch gsd/186-11-ctx-writer-retirement)

- Task 2: 15a452c98 refactor(186-11) retire ctx-writer
- Task 3: 79a59913a feat(186-11) drop ctx_events and ctx_snapshots (migration 388)

## Gates

- Card lint: `pytest tests/unit/test_summary_cards.py` green (41 passed); `cache-ctx-tables.md` lists both tables.
- D-01: `ps aux` for ic_engine, backfill_feature_factory, regime_writer, rebuild, ic_measure returned nothing; STATE.md shows no live or resumable corpus run.
- Pre-drop counts: ctx_events 0, ctx_snapshots 0. Jobs on ctx_events: 1040 policy_compression, 1049 policy_retention.

## D-08 consumer grep dispositions

All live hits matched the plan's list: services/context_writer.py, its test, the unit file, wave3/wave4 targets, service_auditor (2 lines), stream_keys `topic_ctx_snapshot` and its test, FeatureRepository (+4 vulture lines, parity_repository docstring), reset script, dashboard hook, the ten docs. No publisher of `ctx.snapshot` and no new importer. Left as history: migrations 091/095/096/103/140/232 and 385 (comment), tests/integration/fixtures baselines (2026-07-18 and 2026-09-27), docs/plans design doc, docs/research fable docs, summary cards, `.planning`. `src/intelligence/research/runner.py` `ctx.snapshot` is an attribute access (false positive). `docs/operations/operations-database.md:78` (dated PK inventory row "Dropped by 186-11") left as accurate history.

## Migration 388

Applied live with ON_ERROR_STOP, then committed. Post-apply: `to_regclass('ctx_events')` and `to_regclass('ctx_snapshots')` NULL; jobs 1040/1049 gone; `alert.lag.ctx-writer` absent from config_state and config_schema; 1 config_history row `migration_388`; `context_features` still present.

## Host effects

`systemctl disable --now indicagent-ctx-writer`, unit file and wants-link removed, daemon-reload, reset-failed. `list-unit-files | grep ctx-writer` returns 0; no process. Repo wave3/wave4 targets installed into /etc/systemd/system; `systemd-analyze verify indicagent-wave4.target` printed no output (no ctx-writer mention). The Redpanda topic `ctx.snapshot` still exists (1 partition) and was left in place (transport only).

## Verification

- vulture exits 3 identically on untouched main (pre-existing: `src/core/resource_lease.py:263 exc_info`); no hit on touched files.
- mypy-baseline filter reports new violations only in files this plan did not touch (baseline line drift from other sessions); none in stream_keys, parity_repository.
- `pytest tests/unit -q --co` clean; registry, service_auditor and core tests green; full `pytest tests/unit/ -q` green in the worktree (main re-run recorded in the report).

## Deviations

None to plan intent. `/simplify` and `/review` are not invokable from an executor subagent; the diff is deletion-dominated (9 insertions in code files).

## Self-Check: PASSED
