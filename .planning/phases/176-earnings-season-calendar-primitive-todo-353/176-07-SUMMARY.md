---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: 07
subsystem: corpus-pipeline
tags: [feature_vectors, migration-351, backfill, timescaledb-compression, earnings_season]

# Dependency graph
requires:
  - phase: 176-02
    provides: "migration 350: earnings_season_flag / days_since_quarter_end columns (NULL on existing rows) and the feature.earnings_season.start_days/end_days APR seeds"
  - phase: 176-03
    provides: "new-row compute of both columns; the Python window logic the SQL mirrors"
  - phase: 176-01
    provides: "independently tested pure days_since_quarter_end / is_earnings_season used as the agreement reference"
provides:
  - "Both columns populated on all 108,639,338 pre-existing feature_vectors rows (0 NULL, 0 rows still differing from the SQL definition)"
  - "production/migrations/351_earnings_season_backfill.sql: scoped two-column UPDATE inside the documented compressed-hypertable round trip"
  - "176-RECOMPUTE-LOG.md COVERED_SCOPE manifest: 233 symbols x 4 tfs, 932 pairs, bar_ts through 2026-09-18 19:55 UTC"
affects: [176-04, 176-06, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotency proven by counting the UPDATE's own WHERE predicate with pg_temp copies of the helpers, instead of re-running a migration whose step 1 decompresses the whole table"

key-files:
  created:
    - production/migrations/351_earnings_season_backfill.sql
    - tests/unit/test_earnings_season_backfill_contract.py
    - .planning/phases/176-earnings-season-calendar-primitive-todo-353/176-RECOMPUTE-LOG.md
  modified: []

key-decisions:
  - "Whole-table form, not batched (Task 1: 540 GB free vs 193 GB gate; measured worst-case floor ~232 GB)"
  - "Idempotency checked by predicate count, not a full re-run (the re-run would decompress ~154 GB for a no-op)"
  - "The 3 uncompressed 2026 chunks are left to the columnstore policy (inside compress_after = 6 mons)"

requirements-completed: [ES-07]

# Metrics
duration: "unknown (original run telemetry lost to a power-loss reboot)"
completed: 2026-09-23
---

# Phase 176 Plan 07: Earnings-season corpus backfill summary

**Migration 351 populated `earnings_season_flag` and `days_since_quarter_end` on all 108.6M pre-existing `feature_vectors` rows with a two-column UPDATE; a power loss cut the recompress step, which was completed in recovery, and every verification passes.**

## Performance

- **Original run:** started ~14:00 UTC 2026-09-23 after the Task 1 pre-flight; the UPDATE transaction committed; a site power outage rebooted the server (~17:40 UTC) mid-recompress. Elapsed time, rows-updated output and the in-run disk trajectory were written to `/tmp` and lost.
- **Recovery:** 18:07-18:37 UTC (recompress + two bare VACUUMs, concurrent session indicagent-62). Free disk 413 GB -> 518 GB.
- **Verification scan:** 21:03:38-21:15:45 UTC (12m07s, full table, one grouped pass).

## Accomplishments

- 0 NULL rows in either column out of 108,639,338; row count identical to the Task 1 baseline.
- 0 rows satisfy the migration's own `IS DISTINCT FROM` predicate, so a re-run would update nothing.
- 100% coverage on all 932 (symbol, tf) pairs; the flag takes both values in every pair.
- 20/20 sampled rows agree with 176-01's pure Python classifier across 18 distinct quarters, including a quarter-end day and a Dec 30 day.
- In-season fraction 0.325-0.328 on every tf (expected ~0.319, band 0.25-0.40).
- The fully-NULL `regime` symbol set (BIL, EMLC, ETHA, IBIT, VIXY) matches the pre-migration `regime_coverage_auditor` run exactly.
- COVERED_SCOPE manifest written for 176-08.

## Task Commits

1. **Task 1 RED: contract test** - `519e3cd70` (test)
2. **Task 1 GREEN: migration 351 + pre-flight evidence** - `50a2729bd` (feat)
3. **Worktree merge to main** - `995841b6d`
4. **Tasks 2-3: recovery record, verification, COVERED_SCOPE** - committed with this summary (docs)

## Files Created/Modified

- `production/migrations/351_earnings_season_backfill.sql` - APR guard, decompress, scoped two-column UPDATE, recompress, bare VACUUM
- `tests/unit/test_earnings_season_backfill_contract.py` - 8 source-level assertions including the two-assignment SET-list parse
- `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-RECOMPUTE-LOG.md` - pre-flight, recovery record, verification, COVERED_SCOPE, per-symbol appendix

## Decisions Made

See key-decisions in the frontmatter; the reasoning for each is in the RECOMPUTE-LOG.

## Deviations from Plan

### 1. Power loss during step 3

- **Found during:** Task 2 (external event)
- **Issue:** the server rebooted after the UPDATE committed and before recompress/VACUUM finished; 37/86 chunks left uncompressed.
- **Fix:** recompress via the columnstore policy plus manual `compress_chunk()`, then two bare `VACUUM feature_vectors;` (indicagent-62, 18:07-18:37 UTC).
- **Impact:** the plan's cost measurement (elapsed seconds, rows-updated, in-run disk trajectory) is lost. The round trip's cost stays unmeasured.

### 2. Idempotency by predicate count

- **Issue:** the plan calls a re-run "cheap", but step 1 decompresses every chunk (~154 GB of heap) before the no-op UPDATE.
- **Fix:** counted rows matching the UPDATE's WHERE predicate with `pg_temp` copies of the helper functions: 0.
- **Impact:** the same claim, without a second full round trip.

### 3. 3 uncompressed chunks instead of 0

- **Issue:** the acceptance criterion expects 0 uncompressed chunks.
- **Reason:** the three 2026 chunks sit inside `compress_after = 6 mons`, so the columnstore policy leaves them uncompressed and the live writer targets the newest one. This is the policy's steady state.

## Issues Encountered

- `regime_volatility` is fully NULL for BIL, EMLC, ETHA, VIXY and VRP. There is no pre-run snapshot of this column; the SET-list contract test proves this migration could not have touched it. 176-04's per-symbol sub-cells for those symbols will be empty.

## User Setup Required

None.

## Known Stubs

None.

## Threat Flags

T-176-07-02 (disk exhaustion): the in-run disk trajectory was lost, so the 20 GB abort line cannot be shown to have held. Postgres restarted cleanly with no ENOSPC, and 413 GB was free when recovery started.

## Next Phase Readiness

- 176-08 can consume COVERED_SCOPE directly. Its pre-flight should re-check `count(*) WHERE earnings_season_flag IS NULL` = 0, since rows written after this snapshot depend on 176-03's live compute path.
- 176-08's corpus IC run is sequenced after indicagent-62's `fix/174-code-review` ic_engine changes (both change code_content_key, so one recompute absorbs both).

## Self-Check: PASSED

- `176-RECOMPUTE-LOG.md` contains COVERED_SCOPE; `count(DISTINCT earnings_season_flag)` = 2 (plan verify command printed OK)
- `.venv/bin/pytest tests/unit/ -q` exited 0 on main at `995841b6d`
- Migration file and contract test present on main
