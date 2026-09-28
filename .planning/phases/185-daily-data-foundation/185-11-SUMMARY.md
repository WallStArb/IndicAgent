---
phase: 185-daily-data-foundation
plan: 11
subsystem: bars
tags: [d2b, derived-grid, archive, digest, single-writer-guard]

# Dependency graph
requires: [185-01, 185-04, 185-06]
provides:
  - production/migrations/383_derived_grid.sql (applied live: ohlcv_intraday_raw_archive hypertable, bar_content_digest + bar_content_digest_current, append-only triggers, bar_derivation_writer grants, both APR seeds)
  - services/bar_derivation.py (BarDerivation(BaseBatch), --stage grid: per-symbol archive-verify-delete-insert, --changed-only, dry-run default, --exclude-symbols-file lane guard)
  - src/intelligence/bars/sources.py (SOURCE_DERIVED_5M, GRID_RULE_VERSION grid-v1, GRID_TIMEFRAMES)
  - production/systemd/indicagent-bar-derivation.service (Type=oneshot, no timer; plan 12 chains it)
  - tests/unit/test_market_data_ohlcv_writer_boundary.py (single-writer CI guard: bar_derivation.py the only PERMANENT raw-table writer)
affects: [185-12, 185-17, 185-18, 186-D-23/D-24]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Archive with INSERT ... ON CONFLICT DO NOTHING, then LEFT JOIN count/value/volume checksum verify inside the same transaction: rerun-safe after a partial archive, and nothing leaves market_data_ohlcv unverified"
    - "Dry-run default on any rewrite pass; --apply is the explicit opt-in and opens the provenance batch row"

key-files:
  created:
    - production/migrations/383_derived_grid.sql
    - src/intelligence/bars/sources.py
    - services/bar_derivation.py
    - production/systemd/indicagent-bar-derivation.service
    - tests/unit/services/test_bar_derivation_grid.py
    - tests/unit/test_market_data_ohlcv_writer_boundary.py
    - tests/unit/test_derived_grid_migration_contract.py
  modified:
    - services/service_auditor.py
    - tests/unit/test_market_data_ohlcv_boundary.py

key-decisions:
  - "Write method segment_delete_copy per 185-01 measurements c/d (90,575-111,180 rows/s, 0 chunks decompressed); recorded in the migration header and the infra.bar_derivation.grid_write_method APR key, and the code refuses any other value"
  - "Digest input is values plus flag state of the kept (non-quarantined) 5m bars; derived 15m/1h digests use the constituent rule unions; the rule version is recorded beside, never an input (D-07)"
  - "Dry-run opens no bar_derivation_batch row, so the no-live-rewrite acceptance check (completed stage='grid' count 0) holds by construction until plan 12"

patterns-established:
  - "Timeframe-scoped PERMANENT/TEMPORARY reasons on every raw-table writer in the new CI guard; each TEMPORARY names the plan that retires it"

requirements-completed: [D-02, D-07, D-15]

# Metrics
duration: about 3 h across an executor run plus a compaction continuation
completed: 2026-09-28
---

# Plan 185-11: D2b writer, archive, digest table, single-writer CI summary

**Schema live and the writer tested end to end on fakes; no live data touched (zero completed grid batches), so plan 12 runs the rewrite against a fenced single-writer surface**

## Task commits
1. **Task 1: migration 383 applied live + sources.py + contract test** - `b199d01dc`
2. **Task 2 RED: grid unit tests (swept into a parallel session's docs commit)** - `db021babf`
3. **Task 2 GREEN: BarDerivation, systemd unit, registry, both boundary guards** - `060af4f26`, wording follow-up `6d83321ff`

**Plan metadata:** this commit

## Acceptance criteria
- All listed tests pass: 17/17 in the verify set (8 grid, 4 migration contract incl. reuse, 3 read boundary, 2 writer boundary), full tests/unit/ green
- `grep -n "bar-derivation" services/service_auditor.py`: `_DAG_ORDER` line 120 and `_ONESHOT_UNITS` line 221
- Reviewed write statements in services/bar_derivation.py: exactly one `DELETE FROM market_data_ohlcv` (the per-symbol 15m/1h segment, line 124, after archive + checksum verify), the derived `INSERT INTO market_data_ohlcv`, and the `bar_quality_flag` constituent-flag upsert; the batch UPDATE lives in the pre-existing bar_derivation_batch.close_batch. Nothing else writes
- No live data rewritten: `select count(*) from bar_derivation_batch where stage='grid' and status='completed'` returns 0 (dry-run opens no batch row at all)

## Deviations from plan
- The RED test file was swept into the parallel 186 session's docs commit `db021babf` (shared-checkout stage sweep, 415 lines). Per the coordinator's instruction it counts as the RED commit; the complete GREEN version landed in `060af4f26`
- The plan's verify path `tests/unit/test_service_auditor_registry_integrity.py` does not exist; the registry integrity test lives at `tests/unit/services/test_service_auditor_registry_integrity.py` and that one was run
- Archive INSERT uses ON CONFLICT DO NOTHING plus a LEFT JOIN count/value/volume checksum compare (plan sketched a plain INSERT ... SELECT + count check): a rerun after a partial archive still verifies correctly instead of double-failing on the PK
- `execute()` returns the totals dict: BaseBatch.__init__ calls setup_service_logging, which replaces structlog's capture config mid-test, so the tests assert on the return value instead of captured logs
- D-31's nightly-race systemctl guard is deliberately not implemented here: plan 11 creates no timer, and the guard belongs to plan 12's chaining design where the race exists
- Migration apply iteration: `timescaledb.compress_segmentby` must be `'symbol, timeframe'` (no parens) on this TimescaleDB build; fixed in file and contract test, re-applied clean
- Follow-up commit `6d83321ff` aligned the writer allow-list reasons with the plan's exact retirement scoping (15m/1h until plan 12, 1d until plan 18, feature-factory 186-06/186-25 note)

## Issues encountered
- A test row left in the archive while verifying the append-only triggers live had to be removed with `SET session_replication_role = replica` (DISABLE TRIGGER is not supported on hypertables with columnstore); archive count back to 0
- The happy-path test needed the fixture's informational flag folded into its digest oracle (values plus flag state), which is the D-07 contract working as designed

## User setup required
None. The systemd unit is created but deliberately not installed/enabled (plan 12 owns the live run and the nightly chaining).

## Next phase readiness
- Plan 12 runs the universe rewrite (`systemctl start indicagent-bar-derivation` or the CLI with --apply), stops 15m/1h gap detection, and chains the unit from the nightly backfill (D-31 race guard lands there)
- The lane guard (--exclude-symbols-file) is ready for plan 12's coordination with the todo 449 backfill campaign
- Phase 186's revision detection reads bar_content_digest_current, now live with the append-only fence

## Self-Check: PASSED

All 8 created/modified files exist on disk; all 4 cited commits (b199d01dc, db021babf, 060af4f26, 6d83321ff) present in git log.

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-28*
