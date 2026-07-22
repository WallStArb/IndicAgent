---
phase: 148-alpha-scoring-system-planned
plan: 03
subsystem: measurement
tags: [oos-gate, fisher-z-ci, asyncpg, statsmodels, pytest, dry-run, atomic-transaction]

# Dependency graph
requires:
  - phase: 148-01
    provides: gate_evaluations table (write target) + Wave 0 RED test stub naming this plan's exact targets
provides:
  - scripts/ops/corpus/ops_oos_gate1_signal_eval.py (SCORE-02 -- OOS Gate 1 signal-proof scorer, built and unit-tested, NOT yet run for real)
affects: [148-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [dry-run-aware orchestration function separated from argparse main(), atomic check-then-insert transaction for a run-once gate, pre-run integrity snapshot embedded in both evidence jsonb and look-log]

key-files:
  created:
    - scripts/ops/corpus/ops_oos_gate1_signal_eval.py
  modified:
    - tests/unit/test_oos_gate1_signal_eval.py

key-decisions:
  - "Query grain is (symbol, tf, scale) -- no regime stratification for Gate 1 (D-07's regime-stratified companion requirement applies to Gate 2/SCORE-03, not Gate 1)"
  - "Used asyncpg $N placeholders (not psycopg2 %s + ProcessPoolExecutor workers) for the OOS fetch query -- this is a simpler standalone one-shot script, not dispatched through EnsembleICEngine's per-symbol worker pool, so no subprocess indirection is needed"
  - "Exposed _run_gate1() as a dry-run-aware orchestration function independent of argparse's main() specifically so tests can drive the dry-run path and evidence-assembly shape without a real DB or CLI invocation"
  - "Avoided writing the literal substrings 'circular_block_bootstrap' and 'alpha_events' anywhere in the script (including comments/docstrings) so the plan's acceptance-criteria greps for their absence pass unambiguously -- described both concepts in prose instead (e.g. 'the newer bootstrap-based CI method', 'the post-emission execution subset')"

patterns-established:
  - "Dry-run-aware orchestration split: a pure-ish async _run_gate1() function does fetch+compute+verdict+evidence and only branches into print-and-return (dry-run) vs write-and-append (real) at the very end -- keeps the full computation identical between both paths, so --dry-run genuinely validates the same logic the real run would execute"

requirements-completed: [SCORE-02]

# Metrics
duration: ~40min
completed: 2026-07-22
---

# Phase 148 Plan 03: OOS Gate 1 (Signal Proof) Scorer Summary

**Built `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`, a standalone one-shot script that measures IC(alpha_score, forward_return_*) on the OOS side of `ensemble_alpha` using the exact Fisher-z CI methodology `ensemble_ic_engine.py` already uses in-sample, with a `--dry-run` escape hatch and an atomic transactional write guarding the run-once gate discipline; four Wave 0 test stubs turned GREEN.**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-07-22
- **Tasks:** 1/1 completed
- **Files modified:** 1 created (production script), 1 modified (test file, Wave 0 stubs filled in)

## Accomplishments

- Built `ops_oos_gate1_signal_eval.py` (545 lines): fetches `ensemble_alpha` OOS rows (`bar_ts >= alpha.validation.oos_start`) joined to `forward_returns` (`return_type = 'executable_open_to_open'`) and `market_regimes`, computes rank-IC + Fisher-z CI + p-value + walk-forward-stability per (symbol, tf, scale) cell, applies one corpus-wide BH-FDR correction, and classifies an overall `pass`/`fail`/`insufficient` verdict
- Methodology lock verified: imports `_fisher_z_ci` from `src.intelligence.statistics.ic_math` and `compute_walk_forward_stable` from `services.ensemble_ic_engine`; the newer bootstrap-based CI helper is never imported or referenced anywhere in the file (source-level test asserts this)
- Population lock verified: reads `ensemble_alpha` (every scored bar), never the post-emission execution subset; that table name never appears in the file
- `--dry-run` flag runs the full fetch/compute/verdict/evidence pipeline and prints the result but performs zero writes to `gate_evaluations` and zero look-log appends -- verified by a test that asserts `pool.acquire`/`pool.execute` are never called and the look-log file is never created
- Real (non-dry-run) write path opens one `asyncpg` transaction that re-asserts `count(*) FROM gate_evaluations WHERE gate_id='gate1_signal'` is still 0 before inserting -- a crash between the check and the write rolls back cleanly; a genuinely-already-run gate raises rather than silently overwriting or accumulating a second verdict row
- Pre-run integrity snapshot (`oos_start`, APR values used, input population row count, fetch-SQL sha256) embedded in both the `evidence` jsonb and the look-log entry (`.planning/gate_look_log.jsonl`, appended only after the write transaction commits)
- `import statsmodels`-family import sits at module top level (not inside a function), so a missing dependency fails loud at load time, not mid-run
- All 4 Wave 0 stub tests (`test_fails_loud_when_oos_start_unset`, `test_uses_fisher_z_ci_methodology`, `test_gate1_dry_run_writes_nothing`, `test_gate1_evidence_payload_shape`) filled in and GREEN

## Task Commits

Each task was committed atomically:

1. **Task 1: Build ops_oos_gate1_signal_eval.py (with --dry-run + atomic write + snapshot) and turn test_oos_gate1_signal_eval.py GREEN** - `cefb7eef` (feat)

## Files Created/Modified

- `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` - SCORE-02: standalone OOS Gate 1 scorer. Key functions: `_read_oos_start` (fail-loud), `_fetch_symbol_tf_rows` (read-only OOS fetch), `_compute_symbol_tf_cells`/`_compute_fold_ics` (pure IC + walk-forward math), `_apply_corpus_fdr`, `_assemble_verdict` (pass/fail/insufficient, never raised), `_build_snapshot`/`_assemble_evidence` (pre-run snapshot embedding), `_write_gate_result` (atomic check+INSERT transaction), `_append_gate_look_log`, `_run_gate1` (dry-run-aware orchestration), `main` (argparse entrypoint). Not yet run for real -- that is plan 148-05's deliverable.
- `tests/unit/test_oos_gate1_signal_eval.py` - Filled all four Wave 0 stubs: fail-loud oos_start guard (mocked `asyncpg.Pool`), Fisher-z-CI-not-bootstrap source-level assertion, dry-run-writes-nothing (mocked pool + tmp_path look-log, asserts zero write calls and the look-log file is never created), evidence payload exact-key-set assertion (`{cells, oos_start, snapshot, verdict}` and snapshot's `{oos_start, apr_values_used, input_population_row_count, fetch_sql_sha256}`)

## Decisions Made

- Query grain is (symbol, tf, scale) with no regime stratification -- Gate 1 answers the pooled "is there signal at all" question; the regime-stratified companion requirement (D-07) is scoped to Gate 2/SCORE-03, not this plan.
- Adapted the fetch query to asyncpg `$N` placeholders rather than copying the psycopg2 `%s` + `ProcessPoolExecutor`-worker dispatch shape `_WORKER_FETCH_SQL` uses in `ensemble_ic_engine.py` -- this script is a simpler standalone one-shot, not dispatched through that engine's per-symbol worker pool, so the subprocess indirection isn't needed. Table, join shape, and the `return_type = 'executable_open_to_open'` filter are all copied verbatim; only the OOS-direction predicate and the placeholder style changed.
- Exposed `_run_gate1()` as a dry-run-aware orchestration function separate from `main()`'s argparse handling specifically so unit tests can drive the dry-run path and the evidence-assembly shape directly against a mocked pool, with no real DB or CLI invocation required.
- Deliberately avoided writing the literal substrings `circular_block_bootstrap` and `alpha_events` anywhere in the production file (including comments/docstrings), since the plan's acceptance criteria grep for their absence across the whole file, not just executable code -- described both concepts in prose instead ("the newer bootstrap-based CI method", "the post-emission execution subset").

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed a redundant/awkward duplicate test during self-review**
- **Found during:** Task 1, before the first commit attempt
- **Issue:** An early draft of `test_fails_loud_when_oos_start_unset` used a `asyncio.get_event_loop().run_until_complete(...)` sync wrapper (deprecated pattern, and redundant given this project's `asyncio_mode = auto` pytest config) alongside a second, near-identical `test_fails_loud_when_oos_start_unset_async` test.
- **Fix:** Collapsed to a single clean `@pytest.mark.asyncio async def test_fails_loud_when_oos_start_unset(...)` test, matching the plan's exact required function name and the analog file's (`test_oos_holdout_eval.py`) test shape.
- **Files modified:** `tests/unit/test_oos_gate1_signal_eval.py`
- **Verification:** Re-ran `pytest tests/unit/test_oos_gate1_signal_eval.py -v` -- exactly 4 tests collected and passed (no duplicate-name collision, matching the plan's 4 required stub names)
- **Committed in:** `cefb7eef` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking, self-caught during drafting before any commit, no pre-commit hook rejection involved)
**Impact on plan:** Purely mechanical test-authoring cleanup; no change to any production logic, test assertion intent, or the four required test names.

## Issues Encountered

None beyond the one auto-fixed self-review cleanup documented above. `black` reformatted the production file once (long-line wrapping); re-verified all acceptance-criteria greps still passed after reformatting, since a multi-line reflow could in principle have broken a single-line grep pattern -- it did not.

## Known Stubs

None. This plan's own deliverable was always "build and unit-test the script, do not run it for real" (per the plan's own `<done>` criterion) -- that is not a stub, it is the plan's explicit scope boundary. No hardcoded empty values or placeholder UI/data paths were introduced; the script's real (non-dry-run) execution path is fully implemented, just deliberately not invoked against the live DB in this plan.

## User Setup Required

None - no external service configuration required. The script reads DSN/credentials from `Settings()`, matching the existing `ops_oos_holdout_eval.py` and `ensemble_ic_engine.py` pattern already live in the codebase.

## Next Phase Readiness

`scripts/ops/corpus/ops_oos_gate1_signal_eval.py` is built, unit-tested (4/4 GREEN), and verified against every acceptance-criteria grep in the plan (Fisher-z present, bootstrap-based-CI absent, `ensemble_alpha` present/execution-subset absent, executable-return filter present, OOS-direction predicate present, no write to the in-sample table, `--dry-run`/transaction/snapshot/sha256/statsmodels-import all present, no `as exc` usage). Not yet run against the live DB -- that real one-shot invocation, and the resulting verdict, is plan 148-05's deliverable. No blockers identified for that plan; this script's `--dry-run` flag is available for any pre-148-05 developer-time sanity check without consuming the one-shot gate.

## Self-Check: PASSED

Verified `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` exists on disk (545 lines). Verified
commit `cefb7eef` present in `git log --oneline`. Verified `tests/unit/test_oos_gate1_signal_eval.py`
collects and passes 4/4 (`pytest tests/unit/test_oos_gate1_signal_eval.py -v`). Verified full
`tests/unit/` suite shows zero regressions attributable to this plan (the 6 remaining failures
in the suite are pre-existing Wave 0 RED stubs from sibling plans 148-02/148-04, executing
concurrently in separate worktrees, not this plan's scope).

---
*Phase: 148-alpha-scoring-system-planned*
*Completed: 2026-07-22*
