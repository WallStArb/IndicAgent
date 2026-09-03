---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 02
subsystem: intelligence
tags: [concept-registry, fdr, bh-fdr, asyncpg, promotion-gate, ensemble]

# Dependency graph
requires:
  - phase: 160
    provides: ConceptRegistryService 4-table schema, FOR UPDATE row-lock pattern, D-10/D-12/D-15 win-decision machinery in ops_ensemble_weight_compare.py
provides:
  - Fail-closed FDR enforcement inside ConceptRegistryService.record_comparison_outcome (a caller can no longer promote a win it cannot prove survived multiplicity correction)
  - Every REGISTRY: FAILED exit path in ops_ensemble_weight_compare.py returns 1, not 0
  - --challenger-concept existence validation before any registry write
  - Regression test proving L-2's FOR UPDATE lock guarantee
affects: [170-plans-touching-ic_engine-as-a-second-concept-registry-writer, feature_registry-domain-parity-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-closed gate inside the service, not caller convention: a new guard reads a gate column (fdr_required) and blocks unless the caller supplies affirmative proof (fdr_passed=True); None/False both block."
    - "Every automation-facing failure path in an actuator script returns 1, with a scoped comment marking any deliberately-unchanged report-only return 0 paths so the exception is not mistaken for an oversight."

key-files:
  created: []
  modified:
    - src/intelligence/concept_registry_service.py
    - tests/unit/test_concept_registry_service.py
    - scripts/ops/alpha/ops_ensemble_weight_compare.py
    - tests/unit/test_ensemble_weight_compare.py

key-decisions:
  - "L-2 closed by verification, not new code: the existing FOR UPDATE lock held across the single conn.transaction() already provides the CAS guarantee; a second redundant CAS was deliberately not added, per the plan's explicit instruction."
  - "The FDR guard applies to wins only -- a loss is always recorded regardless of fdr_required, so a decaying concept's consecutive-win counter still resets correctly."
  - "fdr_passed is derived from the caller's own run state (bool(p_raw_list) at the Pass-2 apply_bh_fdr call site), not a caller-supplied claim -- the caller cannot lie its way past the guard by passing a hardcoded True."

patterns-established:
  - "GateState-style dataclasses that gate a promotion action: add the new APR/gate-derived field to the dataclass AND the SQL SELECT AND the guard placement comment explaining ordering, in the same commit."

requirements-completed: [L-2, L-3, L-4, L-6]

# Metrics
duration: 5min
completed: 2026-08-04
---

# Phase 170 Plan 02: Concept Registry FDR/Exit-Code/Challenger-Validation Hardening Summary

**Fail-closed BH-FDR enforcement moved from caller convention into `ConceptRegistryService.record_comparison_outcome`, every `ops_ensemble_weight_compare.py` registry failure now exits non-zero, and an unknown `--challenger-concept` is rejected before any write.**

## Performance

- **Duration:** ~5 min (two atomic task commits)
- **Started:** 2026-08-04T10:37:26-04:00 (Task 1 commit)
- **Completed:** 2026-08-04T10:41:48-04:00 (Task 2 commit)
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- `GateState` now carries `fdr_required` (loaded via `_LOAD_CONCEPT_SQL`'s `g.fdr_required`); `decide_comparison_action`/`record_comparison_outcome` gained a keyword-only `fdr_passed: bool | None = None` parameter threaded through to a new `'blocked_fdr_unverified'` guard that fires when `won and state.fdr_required and fdr_passed is not True` -- placed after the evidence-mass floor, before win/loss bookkeeping, so a loss is still always recorded.
- The stale class docstring paragraph claiming "this service never reads `concept_gate.fdr_required`... lives entirely upstream" was deleted and replaced with the inverted, now-true statement.
- L-2 (the read-modify-write CAS question) closed by verification: `test_load_concept_sql_holds_row_lock` asserts `"FOR UPDATE" in _LOAD_CONCEPT_SQL` and `"conn.transaction()" in inspect.getsource(record_comparison_outcome)`. No second CAS was added, per plan instruction.
- `ops_ensemble_weight_compare.py`: every `REGISTRY: FAILED` print now returns 1 (unknown champion, new unknown-challenger check, missing `alpha.concept_registry.*` APR keys, `ConceptNotFoundError`). A new `REGISTRY: BLOCKED` branch handles `decision.action == 'blocked_fdr_unverified'`, also returning 1.
- `--challenger-concept` existence is validated against `concept_registry` before any registry work, symmetric to the pre-existing champion check; the `ConceptNotFoundError` catch remains as defence-in-depth.
- `fdr_correction_applied = bool(p_raw_list)` captured at the Pass-2 `apply_bh_fdr` call site and passed as `fdr_passed=` to `record_comparison_outcome` -- derived from the run's own state, not a caller-supplied claim.
- The three genuinely report-only failure paths that predate the registry block (missing `gate_lookahead`, missing `compare_fdr_alpha`, the `alpha_ensemble_ic` query failure) were deliberately left at `return 0`, with a comment recording why -- per the plan's explicit scope boundary.

## Task Commits

1. **Task 1: Move FDR enforcement inside record_comparison_outcome, fail closed (L-6, L-2)** - `3d65dd1c` (feat)
2. **Task 2: Non-zero exits and challenger-concept validation in ops_ensemble_weight_compare (L-3, L-4)** - `5fc8bc50` (fix)

_No plan-metadata commit in this worktree -- STATE.md/ROADMAP.md are updated centrally by the orchestrator after the wave completes (worktree mode)._

## Files Created/Modified

- `src/intelligence/concept_registry_service.py` - `GateState.fdr_required`, `_LOAD_CONCEPT_SQL` selects `g.fdr_required`, `decide_comparison_action`/`record_comparison_outcome` gain `fdr_passed`, new `'blocked_fdr_unverified'` guard and action-vocabulary docstring entry, L-7 docstring paragraph deleted/replaced, L-2 comment updated recording closure-by-verification
- `tests/unit/test_concept_registry_service.py` - 6 new FDR-guard tests (blocked-on-None, blocked-on-False, allowed-on-True, unaffected-when-not-required, loss-still-recorded, guard-runs-after-evidence-floor) + `test_load_concept_sql_holds_row_lock`; `_state()`/`_row()` fixtures extended with `fdr_required`
- `scripts/ops/alpha/ops_ensemble_weight_compare.py` - challenger-concept existence check (new, returns 1), all `REGISTRY: FAILED`/`ConceptNotFoundError` sites changed from `return 0` to `return 1`, `fdr_correction_applied` captured and passed as `fdr_passed=`, new `REGISTRY: BLOCKED` branch for `blocked_fdr_unverified`, `--challenger-concept` help text updated, scope-boundary comment above the three untouched report-only failure paths
- `tests/unit/test_ensemble_weight_compare.py` - `test_registry_failure_paths_return_nonzero` (scans source for every `REGISTRY: FAILED` line, asserts the next `return` statement within 6 lines is `return 1`)

## Decisions Made

- L-2 is verification, not implementation (per plan): confirmed the existing `FOR UPDATE` lock held across the single `conn.transaction()` already closes the read-modify-write race; codified as a regression test rather than adding a redundant CAS.
- The comment marking the report-only failure paths (missing `gate_lookahead`/`compare_fdr_alpha`/`alpha_ensemble_ic` query error) was worded to avoid the literal substring `"REGISTRY: FAILED"` so it doesn't pollute the grep-based acceptance count or the new `test_registry_failure_paths_return_nonzero` regression test with a comment that has no adjacent `return` statement.

## Deviations from Plan

None - plan executed exactly as written. One environment note below (not a deviation from the plan's task actions, but relevant to the plan's own `<verification>` step 4).

## Issues Encountered

- The plan's `<verification>` step 4 (`python ... --champion v1 --challenger v1 --challenger-concept __definitely_not_a_concept__; echo "exit=$?"` expecting `exit=1`) could not be exercised end-to-end in this dev environment: `alpha_ensemble_ic` is currently empty (confirmed via `SELECT weight_version, count(*) FROM alpha_ensemble_ic GROUP BY weight_version` returning 0 rows), consistent with STATE.md's Tier -1 note that `ensemble_trainer`/`alpha_publisher` have not yet run against the current corpus. The script's existing "no comparable strata" early-return (`return 0`, unchanged by this plan -- report-only, predates the registry path) fires before reaching the challenger-concept check, so the live smoke test can't reach the new code path without seeded `alpha_ensemble_ic` rows. This is a data-availability gap in this environment, not a code defect: the exact code path (`args.challenger_concept` existence check, `return 1` on failure) is covered directly by `test_registry_failure_paths_return_nonzero` and the module-source assertions in Task 2's `<verify>` block, both of which pass. No worktree in this wave has a seeded `alpha_ensemble_ic` corpus to exercise this against; re-verify live once a future `ensemble_ic_engine`/`ensemble_trainer` run populates the table.
- This worktree had no `.venv` (per `feedback_gsd_worktree_venv_missing.md` -- worktrees are never given their own gitignored venv). Created a local symlink `./.venv -> /home/bg/dev/indicagent/.venv` so both the pre-commit hook's ruff/black checks and this session's `pytest`/`ruff`/`black` invocations could resolve the shared toolchain. The symlink is gitignored (`.venv` is in `.gitignore`) and was never staged or committed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `ConceptRegistryService.record_comparison_outcome` is now safe for a second automated caller (e.g. `ic_engine`) to invoke without re-deriving FDR-enforcement discipline itself -- the fail-closed guard is structural, not caller convention.
- `ops_ensemble_weight_compare.py`'s exit codes are now trustworthy for `ops_corpus_pipeline_run.sh`-style automation to gate on.
- No blockers for later phase-170 plans. This plan's scope was deliberately narrow (`domain='ensemble_strategy'` + the generic service only) and did not touch `ic_engine`/`ensemble_trainer` or seed any schema/rows.

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*
