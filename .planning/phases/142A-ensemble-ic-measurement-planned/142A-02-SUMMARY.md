---
phase: 142A-ensemble-ic-measurement-planned
plan: 02

subsystem: database, batch-compute, ops-tooling
tags: [asyncpg, config-service, apr, markdown-reporting, ensemble-ic]

requires:
  - phase: 142A-01
    provides: alpha_ensemble_ic hypertable + EnsembleICEngine (EIC-01/EIC-03)
provides:
  - EIC-02 IC decay curve -> alpha.frame.hold_max_bars.<regime>.<tf> APR calibration
  - EIC-04 phase gate evaluation script (PASS/FAIL, APR threshold, latest-run scoped)
  - EIC-05 gate-failure diagnosis script (4-section markdown report)
affects: [142B]

tech-stack:
  added: []
  patterns:
    - "Post-write calibration phase composed onto an existing BaseBatch execute() (EIC-02 runs after the serial INSERT, same invocation, same pool)"
    - "Latest-run scoping via scored_at = max(scored_at) instead of a rolling NOW()-INTERVAL window, for deterministic gate/diagnosis on manual reruns"
    - "Dual significance+sufficiency gate (passes_fdr AND reliable) before any cell may set a load-bearing execution parameter"

key-files:
  created:
    - scripts/ops/alpha/ops_ensemble_ic_gate.py
    - scripts/ops/alpha/ops_ensemble_ic_diagnosis.py
    - tests/unit/test_ensemble_ic_decay.py
    - tests/unit/test_ensemble_ic_gate.py
  modified:
    - services/ensemble_ic_engine.py

key-decisions:
  - "EIC-02 aggregates per-symbol hold_bars to a per-(regime, tf) APR key via MEDIAN across qualifying (passes_fdr=true AND reliable=true) symbols only -- unqualified symbols are excluded from the group entirely, not down-weighted, so a noisy or low-N cell can never move a load-bearing hold_bars value even indirectly via the median."
  - "is_pooled=true rows are excluded from the EIC-02 per-symbol grouping -- hold_max_bars is a per-symbol execution parameter; the POOLED row is a diagnostic aggregate, not a tradable cell."
  - "A (regime, tf) pair with zero qualifying symbols is left unwritten (no config_service.set call) rather than defaulted -- the prior APR value (migration seed or earlier calibration) remains authoritative until a future run qualifies."
  - "EIC-04/EIC-05 both scope to scored_at = max(scored_at) rather than a rolling time window, matching the D-142A-R2 pinned-per-run vintage semantics from Plan 01 -- guarantees one deterministic verdict per invocation regardless of manual reruns."
  - "EIC-05 Section 2 uses percentile_cont(0.5) WITHIN GROUP for the per-symbol median ci_lower (review finding #2 fix) and filters feature_ic_scores.regime_scope = 'cross_sectional' when the column exists (Phase 141.1 RSCOPE-01), with a documented unfiltered fallback."

patterns-established:
  - "Ops diagnostic scripts (EIC-05) always exit 0 regardless of findings -- diagnosis is informational; only the paired gate script (EIC-04) carries a pass/fail exit code."

requirements-completed: [EIC-02, EIC-04, EIC-05]

duration: ~40min
completed: 2026-07-02
---

# Phase 142A Plan 02: EIC-02 Calibration + EIC-04 Gate + EIC-05 Diagnosis Summary

**IC-decay-curve calibration of 36 alpha.frame.hold_max_bars APR keys wired into EnsembleICEngine.execute(), plus a paired EIC-04 PASS/FAIL phase-gate script and an EIC-05 4-section root-cause diagnosis script, both scoped to the deterministic latest alpha_ensemble_ic run vintage.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-07-02T18:00:00Z (approx, first read of plan context)
- **Completed:** 2026-07-02T18:27:35Z
- **Tasks:** 3/3 completed
- **Files modified:** 4 created, 1 modified

## Accomplishments

- `_select_hold_bars_from_decay()` in `services/ensemble_ic_engine.py`: pure function walking the canonical `[fast, mid, slow, extended]` scale order for one `(symbol, tf, regime)` group's IC decay curve, gating on BOTH `passes_fdr=true` AND `reliable=true` before any cell participates (review finding #6) — a cell failing either gate is excluded entirely, never down-weighted.
- `EnsembleICEngine.execute()` extended with a post-write calibration phase (`_calibrate_hold_max_bars`): groups the just-written rows by `(symbol, tf, regime)` (excluding `is_pooled=true`), calls the decay selector per group, aggregates to a per-`(regime, tf)` `alpha.frame.hold_max_bars.<regime>.<tf>` APR key via the MEDIAN across qualifying symbols, and writes via `ConfigService.set` with a reason string documenting the qualifying-symbol count and `decay_threshold`. Pairs with zero qualifying symbols are left unwritten.
- `scripts/ops/alpha/ops_ensemble_ic_gate.py` (EIC-04): reads `min_qualifying_fraction` and `gate_lookahead` from `config_state`, runs the qualifying-cell-fraction SQL scoped to `scored_at = max(scored_at)`, prints a markdown PASS/FAIL verdict, exit code 0/1. `_evaluate_gate` is a pure importable helper guarding `n_total=0` without a `ZeroDivisionError`.
- `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` (EIC-05): 4-section markdown report (N-per-cell / pooled-vs-per-symbol IC gap / TF breakdown / regime coverage), all sections scoped to the same latest-run vintage; Section 2 uses `percentile_cont(0.5) WITHIN GROUP` for a true per-symbol median `ci_lower` (fixes the review-flagged `max(CASE...)` bug) and filters `feature_ic_scores.regime_scope = 'cross_sectional'` when present. Loud `WARNING` line if `min_obs_per_regime` is missing from APR (never a silent default). Always exits 0 (informational).
- 2 new unit test files (12 tests total: 8 for the decay selector including noise-exclusion and low-N-exclusion cases, 4 for the gate fraction helper).

## Task Commits

1. **Task 1: EIC-02 — IC decay curve to hold_max_bars APR calibration** - `cd6706e4` (feat)
2. **Task 2: EIC-04 — Phase gate evaluation script** - `12b44106` (feat)
3. **Task 3: EIC-05 — Gate failure diagnosis script** - `18045f5d` (feat)

_Note: Tasks 1 and 2 (tdd="true") followed RED-then-GREEN internally — new tests were written and confirmed failing (ImportError / ModuleNotFoundError) before the corresponding implementation was added, then committed together as the task's atomic unit per the plan's task boundaries._

## Files Created/Modified

- `services/ensemble_ic_engine.py` - added `_select_hold_bars_from_decay()` (pure decay-curve selector) and `EnsembleICEngine._calibrate_hold_max_bars()` (post-write APR calibration phase), wired into `execute()`
- `scripts/ops/alpha/ops_ensemble_ic_gate.py` - EIC-04 phase-gate script (new file, new `scripts/ops/alpha/` directory)
- `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` - EIC-05 diagnosis script
- `tests/unit/test_ensemble_ic_decay.py` - 8 tests for `_select_hold_bars_from_decay`
- `tests/unit/test_ensemble_ic_gate.py` - 4 tests for `_evaluate_gate`

## Decisions Made

- Excluded `is_pooled=true` rows from the EIC-02 per-symbol grouping before calling the decay selector — `hold_max_bars` governs real per-symbol position holds; the POOLED row is a diagnostic aggregate and including it in the median would let a non-tradable row skew a load-bearing execution parameter. This is a plan-consistent interpretation (the plan's `<action>` groups "by (symbol, tf, regime)" for the per-symbol calibration step, and POOLED is not a real symbol whose hold_bars would ever be applied to a live position).
- Followed the plan's explicit correction of RESEARCH.md's code sketch: `ConfigService.set` (not `set_async`), and the decay-crossing value is the PRECEDING qualifying scale's `lookahead_bars` (not the failing scale's).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Prose reference to `NOW() - INTERVAL` in gate-script docstring/comments tripped the plan's own literal-absence grep**

- **Found during:** Task 2 acceptance verification
- **Issue:** The plan's acceptance criteria require `grep -c "NOW() - INTERVAL" scripts/ops/alpha/ops_ensemble_ic_gate.py` to return 0 (review finding #4 — no rolling window). The module docstring and an inline comment both described *what NOT to do* using the literal string `NOW() - INTERVAL`, which the grep cannot distinguish from actual usage.
- **Fix:** Reworded both prose references to describe the same concept ("a rolling time-window subtraction from the current instant") without the literal string, matching the same pattern Plan 01 hit and resolved for `datetime.now(UTC)` in `ensemble_ic_engine.py`.
- **Files modified:** `scripts/ops/alpha/ops_ensemble_ic_gate.py`
- **Verification:** `grep -c "NOW() - INTERVAL" scripts/ops/alpha/ops_ensemble_ic_gate.py` now returns 0; `grep -c "max(scored_at)"` still returns 2 (the actual SQL usage, unaffected by the wording change).
- **Committed in:** `12b44106` (Task 2 commit)

**2. [Rule 3 - Blocking] Worktree missing `.venv` symlink for pre-commit hook's ruff/black resolution**

- **Found during:** First commit attempt (Task 1)
- **Issue:** The repo's pre-commit hook resolves `${REPO_ROOT}/.venv/bin/ruff` and `${REPO_ROOT}/.venv/bin/black` (falling back to `which`, which was also empty in this shell). The git worktree has no local `.venv` — it lives only in the main repo checkout — so both lint/format checks were BLOCKED, not skipped, failing the commit.
- **Fix:** Created a symlink `${WORKTREE_ROOT}/.venv -> /home/bg/dev/indicagent/.venv` so the pre-commit hook's existing resolution logic finds the real ruff/black binaries. `.venv` is gitignored (confirmed via `git check-ignore -v .venv`), so the symlink itself is never staged or committed — it only affects the local worktree filesystem for hook resolution.
- **Files modified:** none tracked by git (symlink only, gitignored)
- **Verification:** All three task commits subsequently ran `[4/8] Ruff lint check... All checks passed!` and `[5/8] Black format check... OK Black format applied` for real (not skipped), and `PASSED: All pre-commit checks passed`.
- **Committed in:** N/A (environment-only fix, not a tracked file change)

---

**Total deviations:** 2 auto-fixed (2 Rule 3 blocking-issue fixes)
**Impact on plan:** Both are mechanical/environmental corrections with zero change to the plan's design intent (EIC-02/EIC-04/EIC-05 methodology, SQL, APR keys, or gating logic). No scope creep.

## Issues Encountered

- The full `pytest tests/unit/ -q` suite (5423 tests after this plan's additions) takes ~10 minutes to run, dominated by HMM/regime-writer numeric tests — consistent with Plan 01's note. Ran it twice in the background (once after Task 1, once after all 3 tasks + pre-commit hook auto-formatting) to confirm no regressions.
- Confirmed the same 33 pre-existing test failures documented in Plan 01's `deferred-items.md` (all in `test_fetch_htf_bars.py`, `test_roll_batch.py`, `test_run_historical_pipeline.py`, `test_regime_writer.py` (both copies), `test_causal_hmm_decoding.py`) reappeared identically in both runs — zero new failures introduced by this plan's changes, zero failures resolved (out of scope, not touched). Final counts: 5390 passed, 33 failed (pre-existing), 41 skipped.
- An unrelated modified file, `.planning/corpus_manifests/alpha_publisher.json`, appeared in `git status` throughout this session (a different process/agent's manifest write against the shared DB, timestamped after this plan started). Left untouched and uncommitted per the scope boundary rule — not related to any of this plan's 3 tasks.

## User Setup Required

None — no external service configuration required. Both ops scripts (`ops_ensemble_ic_gate.py`, `ops_ensemble_ic_diagnosis.py`) correctly handle the empty-`alpha_ensemble_ic`-table case (gate exits 1 with a clear "no IC rows yet" message; diagnosis exits 0 with the same message) since `EnsembleICEngine` has not yet been run against live data (blocked on the Phase B corpus re-run per Plan 01's summary — unchanged by this plan).

## Next Phase Readiness

- Phase 142A is now feature-complete: EIC-01 (Plan 01, IC measurement), EIC-02 (this plan, hold_max_bars calibration), EIC-03 (Plan 01, walk-forward stability), EIC-04 (this plan, phase gate), EIC-05 (this plan, diagnosis) are all implemented and unit-tested.
- Phase 142B (frame simulation) remains deliberately unplanned until `EIC-04` passes on real Phase B data — running `EnsembleICEngine` once, then `ops_ensemble_ic_gate.py`, is the next live-data action, not part of this plan's scope (both scripts were explicitly verified only against the empty-table path per the plan's `<verification>` section — "Live execution of the gate/diagnosis scripts is BLOCKED until Plan 01 runs against Phase B data").
- The `.venv` symlink deviation is worktree-local only; it does not need to persist or be replicated anywhere — the orchestrator's merge back to `main` will not include it (gitignored).

---
*Phase: 142A-ensemble-ic-measurement-planned*
*Completed: 2026-07-02*

## Self-Check: PASSED

All created files verified present on disk; all 3 task commits (cd6706e4, 12b44106, 18045f5d) verified present in git log.
