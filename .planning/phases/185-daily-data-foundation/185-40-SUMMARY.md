---
phase: 185-daily-data-foundation
plan: 40
subsystem: data-integrity
tags: [d7, bar_integrity, verdicts, intraday, slot_coverage, grid_parity, coverage_cache, apr]
requires: [185-33, 185-39]
provides:
  - "intraday bar_integrity verdict rows per name with 5m bars: slot_coverage, digest_fresh (5m, 15m, 1h), grid_parity (15m, 1h), stray_vendor_rows (15m, 1h), coverage_cache"
  - "answered_slots, slot_coverage_by_year, grid_parity, rebucket_5m, digest_scope (pure, src/intelligence/bars/integrity_checks.py)"
  - "coverage_cache_drift: fetcher-lock try-lock plus an always-rolled-back rebuild (services/bar_reconciliation_audit.py)"
affects: [185-41, 189-10, 186-26]
key-files:
  created:
    - production/migrations/450_bar_integrity_intraday_apr.sql
    - tests/unit/test_bar_integrity_intraday_apr_migration_contract.py
  modified:
    - services/bar_reconciliation_audit.py
    - src/intelligence/bars/integrity_checks.py
    - tests/unit/bars/test_integrity_checks.py
    - tests/unit/services/test_bar_reconciliation_audit.py
decisions:
  - "grid_parity compares the 5m bars re-aggregated over the vendor archive's own bucket edges, not the stored derived 1h rows: the archive's 1h grid sits on clock hours (09:30 half hour, then 10:00, 11:00) while the derived grid is anchored at :30, so by key the two share only 09:30 and differ there by span (QQQ: 5,112 shared keys, 5,112 mismatches)"
  - "coverage_cache is one verdict per name on subject SYM|5m, as the plan states; a held lock writes no coverage_cache row and the count is in the run log"
  - "digest scope: a name rechecks every month when it has no previous verdict or its previous verdict failed, otherwise the months spanned by changing ohlcv_load rows since the previous report; a full sweep is recorded as an informational digest_full_sweep fact on subject intraday|sweep"
  - "the 5m completeness fact stays (see Deletes)"
metrics:
  completed: 2026-10-07
---

# Phase 185 Plan 40: Intraday verdict report Summary

D7 now writes the five intraday checks for every name holding 5m bars (240 today), in the same `bar_integrity` rows the 1d report uses (`SYM|5m`, `SYM|15m`, `SYM|1h`). The live run wrote 1,440 intraday rows plus one informational sweep fact; the unit suite is green and no verdict was adjusted.

## Commits

- bdb80cc3e: pure slot coverage, grid parity and archive-bucket rebucketing, with tests
- f68610102: migration 450 (applied live with lock_timeout 5s), the D7 intraday report, digest scope, coverage_cache, tests

## Tests

- tests/unit/bars (integrity_checks, gap_plan, session_grid), tests/unit/services/test_bar_reconciliation_audit.py, migration 450 contract, migration number uniqueness, market_data_ohlcv boundary, ohlcv_coverage writer boundary: green.
- `tests/unit/ -q` (full): no failures, only the existing skips. ruff and black clean on the touched files.
- All intraday tests use fakes (a fake asyncpg connection, a fake lock, a fake psycopg connection and cursor); nothing touches live D1 (todo 494). The coverage_cache tests assert that the connection sees only `rollback` then `close`, never `commit`, that the lock is released on success and when the rebuild raises, that a held lock never connects, and that the lock holder is `bar-reconciliation-audit`.

## Live run (2026-10-07 13:30 UTC, by hand, outside the 05:30-06:30 window)

`PYTHONPATH=/home/bg/dev/indicagent .venv/bin/python services/bar_reconciliation_audit.py`, exit 0, 16 min 5 s in total against 5.5 min before this plan: the intraday part added about 8.5 min plus the unchanged 1d part. The fetcher service and timer stayed stopped; the lock was free (skipped 0). First run, so it was a full digest sweep.

| check | pass | fail | seconds |
|---|---|---|---|
| slot_coverage (5m) | 0 | 240 | 62.5 |
| digest_fresh (5m, 15m, 1h; 720 rows) | 720 | 0 | 300.9 |
| grid_parity (15m, 1h; 480 rows) | 349 | 131 | 80.8 |
| stray_vendor_rows (15m, 1h; 480 rows) | 480 | 0 | 0.0 |
| coverage_cache (one per name) | 5 | 235 | 38.7 |

The 1d report in the same run is unchanged from 185-33 (session_coverage 240 fail, unexplained_seam 8, vendor_basis_run 46, the rest zero).

## Findings (named, nothing adjusted)

- **slot_coverage, 240 of 240 fail.** The worst year is 2026 for 186 names: the live 5m feed has no bars after about 2026-09-29 (SPY 2026 0.9948, QQQ 0.9738 with 5 missing sessions), so the current year sits under 0.995 for most names until 189-10's fetch fills it. Of the other 54 names the worst year is 2006-2020 (single-day holes such as SPY 2006-12-27, 78 slots). Names whose worst year is below 0.5 are a short first or last year: ABBV 0.022, RSPU 0.203, BTAL 0.398, BLK/CCJ/COP/CRM/CVS/DHI/DUK/ECL/ELV/EMR 0.458, and a few at 0.46 to 0.49. 54 names have exactly one failing year; 123 have two; the maximum is 16.
- **grid_parity, 131 failing (name, timeframe) cells: 59 on 15m, 72 on 1h; 52 of the 131 have an OHLC mismatch, the rest are volume only.** Over all failing cells: 15m has 1,536,904 volume-only buckets and 15,311 with a price difference; 1h has 507,001 and 8,180. The volume-only differences are mostly 1 to 2 shares (vendor rounding; BHP 85,939 of 131,128 buckets differ by 1 to 2 shares, prices equal), with large ones on ETFs (CWB, DBA, DBB, DBC up to 80,734 shares). The price differences concentrate in CTVA (10,259 15m and 4,515 1h buckets; no volume difference, so a price-basis difference, to be traced to the 2019 spin) and GE (4,590 and 2,973), then DBA, DBB, DBC, CWB, EDV, IEF, PFF, SHY, TLT, XLC, XLRE and others in the tens to low hundreds, plus one-bucket cases (MSFT 2026-08-06 14:15 close and volume, ODFL, VUG, XBI and similar). The spec's "15m must match exactly" is zero-tolerance, so volume rounding makes the report fail; whether volume deserves a stated tolerance is a design decision for the owner (the rule stays a definition in code until then). Names are in `bar_integrity.grid_parity_mismatches` in logs/bar_reconciliation_audit.log.
- **coverage_cache, 235 of 240 fail, all real ledger drift.** A diagnostic run (same rebuild, rolled back) shows 235 of the drifting series are `1d` (latest_timestamp two sessions behind the stored bars: the Tradier daily load advanced 1d bars on 2026-10-05 and 10-06 and nothing refreshed the 1d ledger, because only the fetcher calls `refresh_1d_bounds`, and it is stopped), 7 are `1h` and 3 are `15m` (row_count or earliest differ from the rebuild). It clears when the fetcher resumes or an operator runs `--rebuild-coverage`; this plan does neither.
- **digest_fresh and stray_vendor_rows: zero failures.** All 240 names hold fresh 5m, 15m and 1h digests, and no vendor 15m/1h row remains in market_data_ohlcv for them.

## Deviations from plan

### Auto-fixed and design calls

**1. [Rule 1 - Bug] grid_parity compares re-aggregated 5m, not the stored derived 1h rows**
- Found during: Task 2 live measurement before the full run.
- Issue: by key, stored derived 1h rows and the archive's 1h rows share only the 09:30 bucket and differ there by span (derived 09:30-10:30, vendor 09:30-10:00); the plan's literal comparison would fail every name for a grid reason, not a data reason, and a pass-on-nothing alternative would be a silent wrong answer.
- Fix: `rebucket_5m` re-aggregates the 5m bars over each archive bucket's own span (to the next clock boundary of the timeframe), counting only buckets with every constituent; `grid_parity` then compares on shared keys as specified. 15m uses the same path (the stored derived 15m equals it; QQQ 132,007 shared, 0 mismatches). This is a recorded design call; the archive stays the independent measurement.
- Files: src/intelligence/bars/integrity_checks.py, services/bar_reconciliation_audit.py. Commits bdb80cc3e, f68610102.

**2. [Rule 3 - Blocking] Duplicate test names in the migration contract file**
- Found during: first commit attempt (pre-commit check 6).
- Fix: two tests renamed with `intraday` in the name. No behavior change.

**3. Migration number.** 450 was free (`ls production/migrations` shows 449, then 453 and 454); the filename stands.

### Run note

The first live attempt failed instantly with `ModuleNotFoundError: No module named 'scripts'`: the unit sets `PYTHONPATH` to the repo, my shell did not. The import of the fetcher lock from `scripts/` is the plan's instruction (read-only, namespace package); services/bar_auditor documents that services do not import from scripts as a convention, and no CI test forbids it. Run with the unit's PYTHONPATH.

## Deletes

The plan asked to compare D7's window-only grid completeness fact with slot_coverage on one name and delete the old fact if equal. Measured on SPY and QQQ: the old 5m cell for 2026 is identical to slot_coverage's 2026 value (SPY 14,820 of 14,898 = 0.9948; QQQ 14,508 of 14,898 = 0.9738), and a unit test pins the equality of the two arithmetics. Both stay: the old fact also judges 15m and 1h for the whole `compute` universe (including the names that hold only vendor 15m/1h and have no 5m yet), feeds the pooled `COMPLETENESS_SHARE` gauge and the masked-slot check, and has no equivalent in the new report. Deleting only its 5m cells would split one fact in two for no gain; revisit when 185-42 retires the vendor 15m/1h rows.

## Known limits

- coverage_cache cannot see a ledger row for a series with no bars and no requests: the rebuild does not touch it, so the diff is empty. The check docstring says so.
- The digest scope reads "previous report" as the previous verdict's `evaluated_at`; a load committed between the audit's reads and its write is picked up by the weekly sweep at the latest.
- Every digest recompute reads the name's full 5m series even when the scope is small, because grid_parity needs it anyway; the first-run sweep cost 301 s for digests. A scoped run is cheaper only in the hashing.

## Known Stubs

None.

## Threat Flags

None. coverage_cache takes the existing fetcher advisory lock and runs `SET LOCAL ROLE bar_derivation_writer` for the rolled-back rebuild; it adds no commit path to `ohlcv_coverage` (T-185-40-03 asserted in tests). No table, script or APR key beyond migration 450.

## Not touched

STATE.md and ROADMAP.md were not edited (shared checkout, scratch-then-copy rule); the orchestrator updates them. The ledger doc, ideas doc, evidence/, 189 deferred-items.md, `_history_fetch_item.py`, the fetch queue, the coverage writer and the fetcher were not touched.

## Self-Check: PASSED

- Files found: production/migrations/450_bar_integrity_intraday_apr.sql, tests/unit/test_bar_integrity_intraday_apr_migration_contract.py, services/bar_reconciliation_audit.py, src/intelligence/bars/integrity_checks.py.
- Commits found: bdb80cc3e, f68610102.
- Live rows: 1,440 intraday verdict rows in integrity_monitor from the run.
