---
phase: 148-alpha-scoring-system-planned
plan: 04
subsystem: analysis-scripts
tags: [oos-gate, execution-proof, apr, bootstrap-ci, regime-stratified, pytest-tdd]

# Dependency graph
requires:
  - phase: 148-01
    provides: gate_evaluations table (write target), alpha.scoring.min_sharpe/max_drawdown_ratio APR keys, Wave 0 RED test stub naming this plan's exact build targets
  - phase: 143.1-08
    provides: champion 143.1-08 pooled/regime-stratified numbers this script adopts (D-06)
provides:
  - scripts/analysis/score03_gate2_execution_eval.py (built, unit-tested, NOT yet run against the live DB)
  - assemble_gate2_evidence() pure evidence-assembly core (importable, exercised directly by tests)
affects: [148-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [atomic transactional check+insert with pre-run snapshot, dry-run full-compute-zero-write escape hatch, regime-stratified companion via evaluate_frame_gate 2-tuple group_key]

key-files:
  created:
    - scripts/analysis/score03_gate2_execution_eval.py
  modified:
    - tests/unit/test_score03_gate2_execution_eval.py

key-decisions:
  - "Imported _max_drawdown/_annualized_sharpe directly from phase143_1_08_shadow_validation.py (implicit namespace package import, same pattern tests/unit/test_oos_holdout_eval.py already uses for scripts.ops.corpus.ops_oos_holdout_eval) rather than copying the WR-03 frozen-edge-case functions verbatim -- single source of truth, zero drift risk."
  - "Result verdict computed strictly from the pooled c1-c5 criteria (all(...) -> 'pass'/'fail'); the regime-stratified companion is a mandatory diagnostic accompaniment (D-07) that explains WHY the pooled verdict landed where it did, not a second input into the pass/fail boolean -- matches 143.1-08-SHADOW-VALIDATION.md's own separation of pooled criteria 1/3/4 from regime-stratified 2/7."
  - "Deliberately kept the literal words 'gate_id' and 'FRAME-04' off the same source line everywhere in the script (module docstring, comments, provenance string) -- the plan's own acceptance criteria grep for a same-line 'gate_id.*FRAME-04' pattern to catch an accidental second gate_id assignment; phrased explanatory text to avoid a false-positive trip on that check while still documenting the D-08 same-gate relationship in prose."

patterns-established:
  - "Async-mock async-context-manager pattern for asyncpg Pool.acquire()/Connection.transaction() tests: both are plain (non-async) methods returning an async CM object, so the outer .acquire/.transaction attribute must be a MagicMock (sync call) whose return_value implements __aenter__/__aexit__ as AsyncMocks -- an AsyncMock on .acquire itself makes the call return an unawaited coroutine, which breaks `async with`."

requirements-completed: [SCORE-03]

# Metrics
duration: ~55min
completed: 2026-07-22
---

# Phase 148 Plan 04: SCORE-03 Gate 2 Execution-Proof Scorer Summary

**Built and unit-tested the standalone one-shot OOS Gate 2 (execution proof) scorer -- champion-only, all 5 SHADOW-REVIEW criteria including the labeled c7_confident_loss proxy for criterion 5, APR-driven c3/c4 thresholds, mandatory regime-stratified companion, --dry-run escape hatch, and an atomic transactional write with a pre-run snapshot -- without running it against the live DB.**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-07-22
- **Tasks:** 1/1 completed
- **Files modified:** 1 created (production script), 1 modified (test file, from Wave 0 RED stub to GREEN)

## Accomplishments

- Built `scripts/analysis/score03_gate2_execution_eval.py`: a standalone one-shot script that queries `alpha_frames` for `weight_epoch='143.1-08-champion'` only (no challenger comparison, per D-06), computes the pooled SHADOW-REVIEW criteria c1 (>=60 OOS days), c2 (day-clustered bootstrap CI lower > 0, via `frame_gate_passes`), c3 (Sharpe > `alpha.scoring.min_sharpe` APR threshold), c4 (max drawdown ratio < `alpha.scoring.max_drawdown_ratio` APR threshold), and c5 (the `c7_confident_loss` short-side confident-loss tail check, explicitly labeled in the evidence as an operational proxy for the literal N/A criterion 5 -- Codex HIGH concern retained per D-06)
- Wired the mandatory regime-stratified companion (D-07) via `evaluate_frame_gate(rows, ..., group_key=lambda row: (row["direction"], row["regime"]), min_clusters=regime_gate_min_clusters)` -- STEP 0 verify-first isolated test (`test_evaluate_frame_gate_direction_regime_groupkey_roundtrip`) confirms the helper's `(dim_a, dim_b)` unpack round-trips a `(direction, regime)` 2-tuple into the returned dict's `tf`/`regime` fields before wiring the production integration
- Extended `phase143_1_08_shadow_validation.py`'s `_load_apr` pattern to also pull `alpha.scoring.min_sharpe` and `alpha.scoring.max_drawdown_ratio` from the same `alpha.scoring.%` fetch, so c3/c4 verdicts are recomputed at the call site from the actual APR values (never `sharpe > 0.5` or `not dd_fails` literals) -- a `/config/parameters` edit to either threshold genuinely moves the verdict
- Implemented `--dry-run`: full computation, printed verdict + regime coverage table, zero writes to `gate_evaluations`, zero look-log append -- lets a developer verify the script reproduces the known 3-of-5-criteria FAIL without consuming the one-shot gate
- Implemented the real (non-dry-run) write path as a single asyncpg transaction: `SELECT count(*) FROM gate_evaluations WHERE gate_id = 'gate2_execution'` re-asserted inside the transaction, raising (and rolling back) if a prior row exists, then one `INSERT`; the look-log entry (run_ts, result, pre-run snapshot) is appended only after commit
- Assembled a pre-run snapshot (`oos_start`, `weight_epoch`, `apr_values_used`, `input_population_row_count`, `fetch_sql_sha256`) embedded in both the evidence jsonb and the look-log entry
- Single `gate_id='gate2_execution'` write target -- verified no `gate_id='FRAME-04'` (or any variant) row type exists anywhere in the new files; the D-08 "same gate" relationship is documented in prose (module docstring, provenance field) without the literal strings `gate_id` and `FRAME-04` ever co-occurring on one source line, satisfying the plan's own grep acceptance gate
- Turned all four Wave 0 RED stub tests GREEN (`test_cites_champion_143_1_08_numbers`, `test_regime_stratified_companion_required`, `test_gate2_dry_run_writes_nothing`, `test_gate2_evidence_payload_shape`) and added three supporting tests (group-key round-trip verify-first, atomic-write + look-log call-shape assertion, run-once refusal) -- 7/7 passing
- Confirmed the script was NOT run for real against the live DB at any point during this plan -- only unit tests (pure-function calls on synthetic rows and mocked asyncpg pool/connection objects) were executed

## Task Commits

Each task was committed atomically:

1. **Task 1: Build score03_gate2_execution_eval.py and turn test_score03_gate2_execution_eval.py GREEN** - `f8fdbb45` (feat)

## Files Created/Modified

- `scripts/analysis/score03_gate2_execution_eval.py` (new, 465 lines) -- the SCORE-03 / Gate 2 execution-proof scorer. Reuses `frame_gate_passes`/`evaluate_frame_gate`/`_DEFAULT_BOOTSTRAP_RANDOM_STATE` from `services/counterfactual_tracker.py` and `_max_drawdown`/`_annualized_sharpe` (imported, not copied) from `scripts/analysis/phase143_1_08_shadow_validation.py`
- `tests/unit/test_score03_gate2_execution_eval.py` (rewritten from Wave 0 stub, 7 test functions) -- all pure/mocked, no DB or Kafka dependency

## Decisions Made

- Imported `_max_drawdown`/`_annualized_sharpe` directly from `phase143_1_08_shadow_validation.py` via Python's implicit namespace package support (no `__init__.py` needed -- the same pattern `tests/unit/test_oos_holdout_eval.py` already relies on for `scripts.ops.corpus.ops_oos_holdout_eval`) rather than copying the WR-03 frozen-edge-case logic verbatim. Single source of truth for these two statistics functions.
- The overall `result` ('pass'/'fail') is computed strictly from the pooled c1-c5 criteria via `all(...)`. The regime-stratified companion is mandatory and always present in the evidence (D-07) but is diagnostic accompaniment explaining *why* the pooled number lands where it does, not a second boolean folded into the pass/fail computation -- this mirrors 143.1-08-SHADOW-VALIDATION.md's own separation of pooled criteria (1, 3, 4) from regime-stratified criteria (2, 7).
- Phrased all module docstring / comment / provenance text so the literal strings `gate_id` and `FRAME-04` never appear on the same source line, satisfying the plan's own `grep -c "gate_id.*FRAME-04" == 0` acceptance check while still documenting the D-08 same-gate relationship in prose elsewhere in the file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] AsyncMock on `pool.acquire`/`conn.transaction` breaks `async with`**
- **Found during:** Task 1, first test run of the two write-path tests
- **Issue:** asyncpg's `Pool.acquire()` and `Connection.transaction()` are plain (non-async) methods that return an async context-manager object directly; mocking `.acquire`/`.transaction` as `AsyncMock` attributes makes calling them return an *unawaited coroutine* instead of the CM object, so `async with pool.acquire() as conn:` raised `TypeError: 'coroutine' object does not support the asynchronous context manager protocol`.
- **Fix:** Added a `_async_cm(return_value)` test helper returning a `MagicMock` (sync call) whose `__aenter__`/`__aexit__` are `AsyncMock`s, and set `mock_pool.acquire = MagicMock(return_value=_async_cm(mock_conn))` / `mock_conn.transaction = MagicMock(return_value=_async_cm(None))` instead of relying on the default `AsyncMock()` behavior for those two attributes.
- **Files modified:** `tests/unit/test_score03_gate2_execution_eval.py`
- **Verification:** Both write-path tests (`test_gate2_real_write_atomic_transaction_and_look_log`, `test_gate2_real_write_refuses_second_run`) pass.
- **Committed in:** `f8fdbb45` (Task 1 commit)

**2. [Rule 3 - Blocking] Symlinked the worktree's missing `.venv` to the main repo's shared venv**
- **Found during:** Task 1 (running pytest/ruff/black)
- **Issue:** This worktree has no `.venv` (gitignored, matching the known project gotcha 148-01 already hit).
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv .venv` -- same fix, same rationale as 148-01's identical deviation entry.
- **Files modified:** none tracked (gitignored symlink)
- **Verification:** `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/black` all resolved and ran.
- **Committed in:** N/A (untracked, gitignored)

**3. [Rule 1 - Bug] Ruff import-sort + black reformatting on first pass**
- **Found during:** Task 1, pre-commit-equivalent lint pass before staging
- **Issue:** `ruff check` flagged un-sorted import blocks in both new/modified files; `black --check` flagged formatting in both.
- **Fix:** `ruff check --fix` then `black` on both files; re-ran the full grep-based acceptance-criteria check afterward (all still passed, including the `group_key=lambda row: (row["direction"], row["regime"])` exact-match grep and the `gate_id.*FRAME-04` zero-match grep) since reformatting can shift line breaks.
- **Files modified:** `scripts/analysis/score03_gate2_execution_eval.py`, `tests/unit/test_score03_gate2_execution_eval.py`
- **Verification:** `ruff check` and `black --check` both clean; all 7 tests still GREEN after reformatting; pre-commit hook passed cleanly on commit.
- **Committed in:** `f8fdbb45` (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 3 - blocking tooling/mocking issues, 1 Rule 1 - lint/format bug), all mechanical, no scope creep.

## Issues Encountered

None beyond the three auto-fixed deviations documented above.

## Known Stubs

None. This plan's own deliverable was to turn the Wave 0 stub GREEN with real logic, which it does -- `assemble_gate2_evidence` performs the full pooled + regime-stratified computation on real input rows, no hardcoded/empty return values.

## Grep Acceptance Gate Verification

All plan-specified acceptance-criteria greps re-verified against the final (post-black) file:
- `143.1-08-champion` present (2 occurrences)
- `gate2_execution` present (3 occurrences)
- `gate_id.*FRAME-04` -- **zero** matches (no second FRAME-04 gate_id anywhere)
- `group_key=lambda row: (row["direction"], row["regime"])` -- exact match present
- `from services.counterfactual_tracker import` present
- `scipy.stats.bootstrap` -- zero matches (no hand-rolled bootstrap)
- `as exc` -- zero matches (CLAUDE.md exception-variable-name rule honored)
- `alpha.scoring.min_sharpe` / `alpha.scoring.max_drawdown_ratio` -- both present (APR-driven thresholds)
- `not dd_fails` -- zero matches (c4 recomputed from the APR ratio, not the baked-in fail flag)
- `sharpe > 0.5` -- zero matches (c3 uses the APR variable, not a hardcoded literal)
- `confident_loss` (10 occurrences) and `c5_proxy_note` (1 occurrence) both present
- `dry.?run` present (9 occurrences)
- transaction/BEGIN pattern present (1 occurrence: `async with conn.transaction():`)
- `snapshot` (7 occurrences) and `sha256` (4 occurrences) both present

## User Setup Required

None -- no external service configuration required. The script itself must NOT be run for real against the live DB until plan 148-05, and only after Gate 1 (per D-02).

## Next Phase Readiness

`scripts/analysis/score03_gate2_execution_eval.py` is built, unit-tested (7/7 GREEN), and verified against every acceptance-criteria grep. It has never been invoked against the live DB in this plan -- `gate_evaluations` still has zero `gate2_execution` rows. Plan 148-05 can now run this script for real (`--dry-run` first for a sanity check, then the real one-shot invocation) once Gate 1 (SCORE-02, plan 148-03, executing in a sibling worktree) has completed. No blockers identified for 148-05.

Full `tests/unit/` suite run: 6 pre-existing failures remain, all in sibling plans' own Wave 0 RED stub files (`test_alpha_scorer.py` -- 148-02 scope, `test_oos_gate1_signal_eval.py` -- 148-03 scope) -- unrelated to this plan and expected to be resolved by those parallel executors, not this one. Zero regressions introduced by this plan's changes.

## Self-Check: PASSED

Both created/modified files verified present on disk (`scripts/analysis/score03_gate2_execution_eval.py`, `tests/unit/test_score03_gate2_execution_eval.py`); task commit (`f8fdbb45`) verified present in `git log`.

---
*Phase: 148-alpha-scoring-system-planned*
*Completed: 2026-07-22*
