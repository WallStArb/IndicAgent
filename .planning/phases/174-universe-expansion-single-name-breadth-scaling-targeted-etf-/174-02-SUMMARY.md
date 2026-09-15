---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 02
subsystem: database
tags: [postgresql, timescaledb, instrument-governance, apr, structlog]

# Dependency graph
requires: []
provides:
  - "instruments.compute_eligible / instruments.live_tradeable columns, both NOT NULL, both COMMENT ON COLUMN documented"
  - "measured (not assumed) compute_eligible=true default for all 231 existing rows"
  - "COMPUTE_READY_PREDICATE_SQL, the canonical all-four-timeframes compute-readiness predicate"
  - "scripts/analysis/instrument_compute_eligibility_audit.py, reusable per-symbol history-depth audit"
affects: [174-06, 174-10, 174-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "LATERAL ORDER BY ... LIMIT 1 endpoint lookups (batched via unnest + CROSS JOIN LATERAL) for index-driven min/max timestamp queries against a hypertable, letting TimescaleDB's ChunkAppend early-stop instead of aggregating the full partition"
    - "Counted aggregate (= 4) all-four-timeframes predicate, never a bare EXISTS, exported as a single reusable SQL string constant for cross-plan reuse"

key-files:
  created:
    - scripts/analysis/instrument_compute_eligibility_audit.py
    - production/migrations/337_instruments_governance_split.sql
  modified: []

key-decisions:
  - "compute_eligible=true for all 231 existing is_active=true rows, backed by a measured audit (not an assumption) -- every active symbol has non-zero market_data_ohlcv_tradeable rows and a fetch_complete backfill_status row in all four timeframes (5m/15m/1h/1d)"
  - "live_tradeable=false for all rows -- honest default, not a regression, since nothing reads this column yet and live IBKR streaming is confirmed dormant"
  - "is_active left completely untouched (name, semantics, all 37 call sites) -- the 3-way split is purely additive"
  - "No symbols needed calling out as demotion candidates in the migration header, since the audit found zero missing-timeframe or zero-row active symbols"

patterns-established:
  - "Instrument governance schema split (D-07): is_active (backfill-eligible) / compute_eligible / live_tradeable, replacing a single conflated boolean -- Plan 06 will extend get_active_contracts() with a dimension= parameter reading this schema"

requirements-completed: [D-07a]

# Metrics
duration: 20min
completed: 2026-09-15
---

# Phase 174 Plan 02: Instrument Governance Schema Split Summary

**Migration 337 splits `instruments.is_active` into a 3-way backfill/compute/live-tradeable governance model, with the `compute_eligible=true` default for all 231 existing rows justified by a measured, index-driven per-symbol history-depth audit rather than an assumption.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-15T08:26:44-04:00 (worktree base commit)
- **Completed:** 2026-09-15T08:39:26-04:00
- **Tasks:** 2/2 completed
- **Files modified:** 2 created (1 script, 1 migration)

## Accomplishments

- Built `scripts/analysis/instrument_compute_eligibility_audit.py`, an index-driven audit that measures, per `is_active=true` instrument, whether all four timeframes (5m/15m/1h/1d) have non-zero `market_data_ohlcv_tradeable` rows and a `fetch_complete` `backfill_status` row.
- Ran the audit against the live 231-symbol active universe: **all 231 symbols clear the bar** (`n_active=231, n_with_all_four_tfs=231, n_missing_any_tf=0, n_zero_rows=0`), completing in 4.1s (well under the 5-minute budget).
- Exported `COMPUTE_READY_PREDICATE_SQL`, the canonical all-four-timeframes promotion predicate, for Plans 10 and 12 to reuse verbatim rather than re-deriving.
- Shipped migration 337: additive `compute_eligible`/`live_tradeable` columns on `instruments`, both `NOT NULL`, both documented via `COMMENT ON COLUMN`, applied live and verified idempotent on re-run.
- Confirmed zero behavior change: `is_active` untouched, `compute_eligible=true` for every currently-active row (measured, not assumed), `live_tradeable=false` for all 231 rows, full `tests/unit/` suite green (0 failures) after the migration landed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Measure whether is_active=true really means compute-ready** - `6436daa95` (feat)
2. **Task 2: Migration 337 -- additive compute_eligible/live_tradeable columns** - `8c1435869` (feat)

**Plan metadata:** this SUMMARY's own commit (docs: complete plan)

## Files Created/Modified

- `scripts/analysis/instrument_compute_eligibility_audit.py` - Read-only, index-driven per-symbol audit of history depth across all four timeframes; exports `COMPUTE_READY_PREDICATE_SQL`
- `production/migrations/337_instruments_governance_split.sql` - Additive `ALTER TABLE instruments ADD COLUMN compute_eligible/live_tradeable`, explicit backfill `UPDATE`, three `COMMENT ON COLUMN` statements documenting the 3-way split in the schema itself

## EXPLAIN (ANALYZE, BUFFERS) verification (Task 1 acceptance criterion)

Verified interactively before committing to the query shape (not baked into the script, per the plan's "before committing to the shape" instruction):

- **Count query** (`GROUP BY symbol, timeframe` over a 25-symbol/4-timeframe batch): plan is `Bitmap Index Scan on <chunk>_idx_ohlcv_symbol_tf_time` / `Index Scan Backward using <chunk>_idx_ohlcv_symbol_tf_time` per chunk under a `Parallel Append` -- **no `Seq Scan` node appears anywhere in the plan**. ~380ms actual time for one 25-symbol batch (231 symbols / 25 ≈ 10 batches total).
- **Endpoint lookup query** (`unnest(symbols) CROSS JOIN unnest(timeframes) CROSS JOIN LATERAL (... ORDER BY timestamp ASC/DESC LIMIT 1)` for min/max per pair): plan is `Nested Loop` over `Custom Scan (ChunkAppend)` with `Hypertables excluded during runtime` and per-chunk `Index Scan`/`Index Scan Backward` nodes that report `(never executed)` for chunks after the first match -- ChunkAppend's ordered early-stop behavior confirmed live. Execution time 6-15ms per 25-symbol/4-timeframe batch (buffers all shared-hit, zero disk reads once warm); dominant cost is planning time (~220-260ms per batch, driven by the 258-chunk plan tree), not execution.
- Both query shapes were adopted directly in the shipped script (`_fetch_row_counts`, `_fetch_endpoints`).
- Total wall-clock for the full script run against the live 231-symbol universe: **4.1s** (measured via the script's own `time.time()` instrumentation, confirmed externally with `time python ...`).

## Decisions Made

- **`compute_eligible=true` default for all 231 existing rows** -- backed by the Task 1 audit's measured finding (zero missing-timeframe, zero zero-row active symbols), not an assumption. This makes the new column's default behaviorally identical to today's implicit `is_active`-only gate for every one of the ~37 existing `get_active_contracts()`-adjacent call sites (Plan 06's regression test will assert this formally when it adds the `dimension=` parameter).
- **`live_tradeable=false` for every row** -- correct today (live IBKR streaming confirmed dormant per root `CLAUDE.md`, no ≤80-symbol whitelist has ever been chosen), not a placeholder pending a future decision.
- **No symbols listed as demotion candidates in the migration header** -- the plan's conditional instruction ("if any symbol has zero rows in every timeframe, list those symbols explicitly...") did not trigger, since the audit found none. Documented as a measured non-finding rather than silently omitted.
- **`is_active` left completely untouched** -- no rename, no semantic change, matching the plan's explicit instruction and RESEARCH.md's anti-pattern warning against touching the 37 existing call sites.

## Deviations from Plan

None - plan executed exactly as written. One environment fix was required and is not a deviation from the plan's scope: the worktree spawned without its own `.venv` (a known, previously-documented gotcha for this project's worktree-based execution), which blocked the pre-commit hook's ruff/black checks. Fixed by symlinking `.venv` in the worktree to the main repo's `.venv` (`ln -s /home/bg/dev/indicagent/.venv .venv`) -- a read-only, non-destructive link, no code or migration content affected.

## Issues Encountered

None beyond the `.venv` symlink noted above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Migration 337 is live, committed, and idempotent -- `instruments.compute_eligible`/`instruments.live_tradeable` are ready for Plan 06 to consume via `get_active_contracts(dimension=)`.
- `COMPUTE_READY_PREDICATE_SQL` is exported and stable for Plans 10 and 12 to import verbatim when gating the promotion of newly onboarded (Russell 3000 sample / ETF gap-fill) symbols from `compute_eligible=false` to `true`.
- No blockers. The audit script is reusable as-is for any future re-verification of the active universe's history depth (e.g. after the Russell 3000 sample lands).

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: scripts/analysis/instrument_compute_eligibility_audit.py
- FOUND: production/migrations/337_instruments_governance_split.sql
- FOUND: commit 6436daa95
- FOUND: commit 8c1435869
