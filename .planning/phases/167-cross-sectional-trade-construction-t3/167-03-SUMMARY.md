---
phase: 167-cross-sectional-trade-construction-t3
plan: 03
subsystem: infra
tags: [asyncpg, timescaledb, batch, incremental-watermark, crash-recovery]

requires:
  - phase: 167-cross-sectional-trade-construction-t3
    provides: "construction_spreads hypertable + APR keys (Plan 01), pure construction primitives decile_legs/spread_from_legs/one_way_turnover/net_spread_by_cost_bps/validate_construction_config (Plan 02)"
provides:
  - "CrossSectionalSpreadTracker(BaseBatch) oneshot service with incremental watermark, streaming server-side cursor panel scan, chunked idempotent persistence, and --backfill CLI"
  - "Durable per-run CorpusManifest summary at .planning/corpus_manifests/cross_sectional_spread_tracker.json"
  - "Proven crash-recovery: a run interrupted after a partial chunk write recovers to a byte-identical table on the next incremental invocation, with no special recovery flag"
affects: [167-04, 167-05, 167-06]

tech-stack:
  added: []
  patterns:
    - "execute() / _execute_inner(pool, manifest) split mirroring counterfactual_tracker.py"
    - "Two fixed panel SQL strings (_PANEL_SQL_BACKFILL / _PANEL_SQL_INCREMENTAL) resolved once at import from a static template, never runtime string interpolation of caller-supplied values"
    - "Watermark and prior-leg turnover seed both derive exclusively from committed construction_spreads rows -- crash recovery requires no in-memory state"

key-files:
  created: [tests/integration/test_cross_sectional_spread_tracker.py]
  modified: [services/cross_sectional_spread_tracker.py]

key-decisions:
  - "No systemd timer, no service_auditor._DAG_ORDER registration -- manual/on-demand only per Plan 03 design decision 1 (matches alpha_scorer.py/counterfactual_tracker.py/tag_calibrator.py precedent; a construction that hasn't cleared its own Validation Gates does not earn scheduled infrastructure)"
  - "No ProcessPoolExecutor -- one sequential ORDER BY bar_ts ASC pass with a cross-sectional reduction at each bar; the turnover chain is strictly sequential, no per-symbol independence to exploit"
  - "ON CONFLICT (construction_name, tf, bar_ts) DO NOTHING, never DO UPDATE -- persisted rows are an immutable measurement record; a construction change bumps compute_version and truncates via infrastructure_truncate_derived_tables.sh instead of rewriting in place"

patterns-established:
  - "Crash-simulation integration test: delete a contiguous tail of already-persisted rows, re-run in incremental mode with no special flag, assert the recovered rows are byte-identical column-for-column to an uninterrupted reference run -- not merely a row-count check"

requirements-completed:
  - "TCL-MD-1: Minimal Design step 1 - input (ctf_momentum conviction vector)"
  - "TCL-MD-5: Minimal Design step 5 - rebalance rule (per-bar, D-03 exact replica)"
  - "TCL-MD-6: Minimal Design step 6 - portfolio-level measurement persistence"
  - "D-03: rebalance every bar, no cost-floor-gated rebalance-on-change"
  - "D-04: tf=15m, full active equity universe only"
  - "RESEARCH Pattern 1: incremental watermark, not full-corpus rescan"
  - "RESEARCH Pattern 2: turnover seeded from the last PERSISTED leg membership"
  - "REVIEW-H1 (Codex): crash recovery across a partially-written run must be proven by test, not only by design"
  - "REVIEW-M3 (Codex): manual runs need a durable structured summary artifact, not only log lines"

duration: ~65min (interrupted by a Claude Code session-limit reset mid-run; orchestrator completed Task 2's commit and this summary inline after Task 1 had already landed)
completed: 2026-07-27
---

# Phase 167 Plan 03: CrossSectionalSpreadTracker Service Summary

**BaseBatch oneshot with a streaming server-side-cursor panel scan, chunked idempotent inserts, and crash recovery proven byte-identical by a dedicated integration test -- the direct answer to Codex's HIGH review concern.**

## Performance

- **Duration:** ~65 min (Task 1 executed and committed by the wave-2 executor agent; that agent hit a Claude Code session-limit mid-Task-2 after writing and locally verifying the integration test file but before committing -- the orchestrator picked up from the uncommitted worktree state, re-ran the full verification suite, and completed Task 2's commit and this summary)
- **Tasks:** 2/2
- **Files modified:** 2 (1 created, 1 extended)

## Accomplishments
- `CrossSectionalSpreadTracker(BaseBatch)` implemented: `job_name = "cross-sectional-spread-tracker"`, `compute_version = "1.0.0"`, incremental watermark resolution, prior-leg seeding from committed state only, streaming cursor scan (`prefetch=itersize`), chunked `ON CONFLICT ... DO NOTHING` writes, and a `--backfill` CLI.
- Durable `CorpusManifest` per-run summary carrying `mode`, `watermark`, `prior_leg_seed_bar_ts`, `n_panel_rows`, `n_bars_processed`, `n_bars_skipped_degenerate`, `turnover_mean`, `turnover_median`.
- Four integration tests against `indicagent_test`, all passing: one-row-per-bar with exactly one NULL-turnover row, incremental watermark scoping (manifest confirms `n_bars_processed == 2` on the second run, not 4), idempotent re-runs, and tail-truncation crash recovery verified column-for-column against an uninterrupted reference run.

## Task Commits

1. **Task 1: Implement CrossSectionalSpreadTracker with incremental watermark and chunked persistence** - `c4c103d4` (feat) -- landed by the wave-2 executor agent before its session-limit interruption
2. **Task 2: Integration tests for watermark scoping, run-boundary turnover, idempotency, and crash recovery** - `7267a41a` (test) -- test file was already written and locally verified passing by the interrupted executor agent; orchestrator re-verified the full plan verification suite (ruff, black, unit suite, integration suite, migration-schema-sync) before committing

**Plan metadata:** this commit (docs: plan summary)

## Files Created/Modified
- `services/cross_sectional_spread_tracker.py` - added `_PANEL_SQL_TEMPLATE`/`_PANEL_SQL_BACKFILL`/`_PANEL_SQL_INCREMENTAL`, `CrossSectionalSpreadTracker(BaseBatch)`, and the `argparse` CLI entrypoint on top of Plan 02's pure functions
- `tests/integration/test_cross_sectional_spread_tracker.py` - four tests: `test_cross_sectional_spread_backfill_writes_one_row_per_bar`, `test_cross_sectional_spread_incremental_watermark_scoping`, `test_cross_sectional_spread_rerun_is_idempotent`, `test_cross_sectional_spread_recovers_from_interrupted_run`

## Decisions Made
- Followed the plan's design decisions as specified: no systemd timer/DAG registration (decision 1), streaming cursor over a full-corpus DataFrame (decision 2), `DO NOTHING` over `DO UPDATE` (decision 3), no worker pool (decision 4), commit-only-derived crash recovery (decision 5), `CorpusManifest` as the durable run artifact (decision 6).
- The integration test's own manifest write (from running the 4-bar synthetic-panel test suite locally, `n_panel_rows: 24`) was deliberately **not committed** to `.planning/corpus_manifests/cross_sectional_spread_tracker.json` -- checked git history for the other tracked manifest files in that directory (`counterfactual_tracker.json`, `alpha_frame_writer.json`, etc.) and confirmed they are committed only by real production-corpus run plans, never by test execution. Plan 06 ("run the construction for real") will produce and commit the genuine manifest.

## Deviations from Plan

None in the delivered code or tests - Task 1 and Task 2 were implemented and verified exactly as specified. One process deviation, not a plan deviation:

### Process note: session-limit interruption mid-Task-2

The wave-2 executor agent implemented and committed Task 1 (`c4c103d4`), then wrote `tests/integration/test_cross_sectional_spread_tracker.py`, ran it, confirmed "All 4 tests pass" in its final message, and was then terminated by a Claude Code session-limit boundary before running the acceptance-criteria checklist or committing Task 2. No code or test content was lost -- the file existed uncommitted in the worktree exactly as the agent left it. The orchestrator resumed directly in that worktree: re-ran `ruff`/`black`/`pytest tests/unit/`/`pytest tests/integration/ -k cross_sectional_spread`/`test_migration_schema_sync.py` from scratch (not trusting the interrupted agent's self-report), confirmed all pass, deleted the test-run's manifest artifact (see Decisions Made), and committed Task 2. A `.venv` symlink to the primary checkout's `.venv` was added to the worktree so the pre-commit hook's ruff/black checks could run (worktrees do not inherit gitignored directories).

## Issues Encountered
- Worktree pre-commit hook initially failed with "ruff not found" / "black not found" because git worktrees don't include gitignored paths like `.venv`. Fixed by symlinking `.venv` into the worktree to the primary checkout's `.venv` rather than bypassing hooks.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `CrossSectionalSpreadTracker` is ready for Plan 04 to add a `--evaluate-gate` CLI mode reading from `construction_spreads`.
- No real corpus run has happened yet -- the table is empty in live `indicagent`. Plan 06 performs the first real `--backfill` run.

---
*Phase: 167-cross-sectional-trade-construction-t3*
*Completed: 2026-07-27*
