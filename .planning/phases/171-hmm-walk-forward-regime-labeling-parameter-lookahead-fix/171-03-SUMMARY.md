---
phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix
plan: 03
subsystem: database
tags: [timescaledb, psycopg, regime-labeling, data-integrity, provenance, ops-tooling]

# Dependency graph
requires: []
provides:
  - "scripts/ops/corpus/ops_regime_null_out_and_verify.py -- 3-mode checked-in tool: null-out, verify-post-null, verify-post-relabel"
  - "REQ-3 provenance check demonstrated to fail on a known-dirty live cell (SPY/1d) before being trusted"
  - "cache/regime_null_out_manifest.json resumability convention for plans 171-05/171-06"
  - "cache/regime_relabel_provenance_report.json machine-readable evidence format for plans 171-05/171-06"
affects: [171-05, 171-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-cell (symbol, tf) blanket UPDATE with atomic tmp+rename manifest resumability, mirroring state_manager.py's checkpoint idiom"
    - "Single serial psycopg connection, never ProcessPoolExecutor, for a write path against a compressed TimescaleDB hypertable"
    - "Column-ownership single source of truth: SET/WHERE clauses built from REGIME_WRITER_OWNED_COLUMN_NAMES, never hand-typed"

key-files:
  created:
    - scripts/ops/corpus/ops_regime_null_out_and_verify.py
    - tests/unit/scripts/test_ops_regime_null_out_and_verify.py
  modified: []

key-decisions:
  - "Split Task 1 (null-out) and Task 2 (verify modes) into two atomic commits even though both land in the same two files, per task_commit_protocol -- Task 1's main() stubs the two verify modes with NotImplementedError, Task 2 replaces the stubs with real dispatch"
  - "Added D-06 job_completed_total{job,status} emission (init_otel_providers + JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics) matching the nearest sibling mutation script (ops_stale_k3_hmm_fields_cleanup.py), even though the plan's <action> text didn't call it out explicitly -- CLAUDE.md's OTel Health Contract mandates this for oneshot jobs"
  - "Added explicit print() dry-run/banner output alongside structlog logging -- structlog in this project is file-only (no console handler), so 'prints a per-cell plan' from the plan's acceptance criteria required literal stdout output, matching ops_stale_k3_hmm_fields_cleanup.py's own print()+structlog dual-output convention"
  - "--tf choices restricted to the 4 known timeframes (5m/15m/1h/1d) -- not explicitly required by the plan, but prevents a typo'd tf from producing a silent no-op cell (Rule 2, missing validation)"

requirements-completed: [REQ-3]

duration: 3min
completed: 2026-08-08
---

# Phase 171 Plan 03: Regime NULL-Out and Provenance Verification Tool Summary

**Checked-in `ops_regime_null_out_and_verify.py` (3 modes: null-out, verify-post-null, verify-post-relabel) that enforces the walk-forward HMM path's own unenforced single-method-provenance precondition on `feature_vectors`' 8 regime-writer-owned columns, demonstrated live to correctly FAIL on SPY/1d's currently-mixed-provenance data.**

## Performance

- **Duration:** 3 min (commit-to-commit; wall time including research/context-gathering was longer)
- **Started:** 2026-08-08T02:31:44-04:00 (Task 1 commit)
- **Completed:** 2026-08-08T02:33:58-04:00 (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 2 (both created)

## Accomplishments

- Built the single checked-in tool this phase's walk-forward rollout (plans 171-05/171-06) cannot safely run without: RESEARCH.md's Critical Finding proved a bare `regime_writer.py --refit` against the current corpus would silently blend the retired full-history-fit method's stale values with fresh walk-forward labels in the warmup-prefix bars of every relabeled cell.
- `--mode null-out`: per-(symbol, tf) blanket UPDATE nulling all 8 `REGIME_WRITER_OWNED_COLUMN_NAMES` columns, one cell at a time on a single serial connection, proving its own post-condition (zero non-NULL owned columns remain) before advancing an atomic tmp+rename manifest. A cell that fails its post-condition is marked `failed` and logged, but does not abort the run — the remaining scope still gets processed.
- `--mode verify-post-null` and `--mode verify-post-relabel`: read-only re-checks. The relabel-provenance check asserts, per cell, that the count of rows before the earliest labeled bar is at least that tf's `initial_warmup_bars` (read live from `config_state`, falling back loudly to `_WALK_FORWARD_DEFAULT_PARAMS` only when the APR key is missing) — proving no stale pre-fix value survived in the warmup prefix.
- Demonstrated the acceptance criterion's required negative control live: `--symbols SPY --tf 1d --mode verify-post-relabel` correctly FAILs (SPY/1d currently carries 4,795 old-method-labeled rows with `rows_before_first_label=0`, far short of 1d's 504-bar warmup floor) — proving the check has teeth before plans 171-05/171-06 trust a PASS from it.
- Writes `cache/regime_relabel_provenance_report.json` (one record per cell: symbol, tf, labeled_rows, first_labeled_bar_ts, rows_before_first_label, initial_warmup_bars, verdict) as the machine-readable completion evidence those plans will attach.

## Task Commits

Each task was committed atomically:

1. **Task 1: Chunked per-cell NULL-out with manifest resumability** - `289cbf71` (feat)
2. **Task 2: Post-relabel provenance verification modes** - `9d5cf222` (feat)

_Both tasks had `tdd="true"`; tests were written and verified green alongside each task's implementation in the same commit (not split into separate RED/GREEN commits, since this is `type="execute"` at the plan level, not `type="tdd"` — the plan-level TDD gate enforcement in execute-plan.md applies only to `type: tdd` plans)._

## Files Created/Modified

- `scripts/ops/corpus/ops_regime_null_out_and_verify.py` - 3-mode ops tool (null-out / verify-post-null / verify-post-relabel), 331 lines
- `tests/unit/scripts/test_ops_regime_null_out_and_verify.py` - 13 unit tests using a scripted fake psycopg connection/cursor double (no live DB)

## Decisions Made

- **Task split across two commits from one holistic implementation.** The plan's Task 2 explicitly says the two verify modes may either be stubbed with `NotImplementedError` in Task 1 or built directly against the same argparse surface in Task 2 "if Task 2 has not landed." Since both tasks landed in the same session, I reconstructed a genuine Task-1-only slice (verify modes stubbed) for the first commit, then layered Task 2's real implementations on top for the second commit — preserving per-task atomicity per `task_commit_protocol` rather than a single combined commit.
- **D-06 OTel job-completion signal added** (`init_otel_providers`, `JOB_COMPLETED_TOTAL.add(1, {"job": ..., "status": ...})`, `flush_and_shutdown_metrics()`). CLAUDE.md's OTel Health Contract mandates `job_completed_total{job, status}` for oneshot jobs; the nearest same-purpose sibling script (`ops_stale_k3_hmm_fields_cleanup.py`, which also mutates regime-owned columns) already follows this pattern. Not explicitly called out in the plan's `<action>` text, but matches the project's own established convention for this exact class of script (Rule 2).
- **Explicit `print()` output alongside structlog.** `setup_service_logging()` in this codebase is file-only (`RotatingFileHandler`, no console handler) — the acceptance criterion "prints a per-cell plan" would not literally hold with structlog-only output. Added `print()` calls for the dry-run per-cell plan/summary and the `REQ-3 PROVENANCE: PASS/FAIL` banner, mirroring `ops_stale_k3_hmm_fields_cleanup.py`'s established dual-output convention (structlog for the machine-readable audit trail, `print()` for the human-facing report).
- **`--tf` choices restricted** to the four known timeframes (`5m 15m 1h 1d`) rather than left open. Not required by the plan text, but a typo'd `--tf` value would otherwise silently process a cell that matches zero rows rather than erroring — minor Rule 2 addition.

## Deviations from Plan

None of the above are corrections to the plan's design — all are small, in-scope additions (OTel signal, print-vs-log clarification, CLI validation) consistent with this project's established conventions for the exact class of script this plan builds. No Rule 4 (architectural) deviations occurred.

## Issues Encountered

- Regime NULL-out module-level `setup_service_logging("logs/regime_null_out_and_verify.log")` loses the race to `services.regime_writer`'s own module-level `setup_service_logging("logs/regime_writer.log")` call, since importing `_WALK_FORWARD_DEFAULT_PARAMS` from that module runs its module-level code first and `setup_service_logging`'s "first call wins" idempotency guard then silently routes this script's structlog output to `logs/regime_writer.log` instead of its own dedicated log file. Purely cosmetic (log routing only, zero effect on correctness or the data-integrity guarantees this plan enforces) and caused by `regime_writer.py`'s own pre-existing import-time side effect, not this plan's code — left as-is per the scope-boundary rule (only fix issues directly caused by this task's own changes). Worth a follow-up todo if `regime_writer.py`'s import-time logging setup is ever revisited.
- This worktree had no `.venv` (per project convention — gitignored, not copied into GSD worktrees). Ran `ruff`/`black`/`pytest` via the main repo's `/home/bg/dev/indicagent/.venv/bin/` binaries directly, and exported that `bin/` onto `PATH` for the pre-commit hook's own `ruff`/`black` checks to resolve.

## User Setup Required

None - no external service configuration required. This script requires DB connectivity (`Settings().database_url`) at runtime, already configured project-wide.

## Next Phase Readiness

- The tool is fully built, unit-tested (13 tests, all green), lint-clean, and live-verified against the real `feature_vectors` corpus (dry-run and both verify modes exercised against SPY/1d with the exact expected results).
- `tests/unit/` full suite (not just this plan's tests) is green — wave merge gate satisfied.
- `git status --short` shows zero changes to `feature_vectors` data from this plan (only dry-run and read-only verify modes were exercised against the live DB; `--mode null-out` in non-dry-run form was never invoked against the live corpus in this plan, exactly as the plan's own `<verification>` section requires — "this plan builds the tool only; plans 171-05 and 171-06 run it against real data").
- Plans 171-05 and 171-06 can now use `--mode null-out` (pilot scope, then full 231×4tf rollout) followed by `--mode verify-post-relabel` as their own completion evidence, attaching `cache/regime_relabel_provenance_report.json`.

---
*Phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix*
*Completed: 2026-08-08*
