---
phase: 166-frame-execution-recalibration
plan: 02
subsystem: alpha-scoring
tags: [ensemble-ic-engine, apr-calibration, alpha-frames, config-service, timescaledb, python]

# Dependency graph
requires:
  - phase: 166-01
    provides: migration 253 (alpha.frame.stop_atr_mult/target_r_multiple per-(regime,tf) key namespace + alpha.ensemble_ic.stop_mae_percentile/target_mfe_percentile/stop_target_min_qualifying_symbols selection-criterion APR keys), diagnosis confirming the current global 1.5/2.0 scalars are systematically too wide
  - phase: 142B
    provides: alpha_frames hypertable (counterfactual_mae/mfe/stop_atr_mult/status columns), CounterfactualTracker exit-status literals
  - phase: 142A
    provides: EnsembleICEngine + _calibrate_hold_max_bars (the CR-02 champion-gate dispatch pattern this plan mirrors)
provides:
  - "_select_stop_target_from_excursions() -- pure per-symbol selection function (services/ensemble_ic_engine.py)"
  - "EnsembleICEngine._calibrate_stop_target() -- async orchestration writing per-(regime,tf) alpha.frame.stop_atr_mult/target_r_multiple keys"
  - CR-02 champion-weight_version gate now covers the scalar candidate identically to hold_max_bars
  - EnsembleICConfig extended with stop_mae_percentile/target_mfe_percentile/stop_target_min_qualifying_symbols fields
affects: [166-04, 166-05, 166-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Uncensored-subpopulation percentile calibration for a distance/reward-ratio parameter, reading a DIFFERENT source table (alpha_frames) than the orchestrating engine's own corpus (alpha_ensemble_ic) -- the results param scopes eligible symbols, a fresh weight_epoch+bar_ts-filtered query supplies the actual excursion data"
    - "Same-file sibling-function port: _calibrate_hold_max_bars' grouping/median/CR-02/skip-if-empty STRUCTURE reused verbatim; only the selection criterion and data source differ (Finding 1/Pitfall 1)"

key-files:
  created:
    - tests/unit/test_ensemble_ic_stop_target_calibration.py
  modified:
    - services/ensemble_ic_engine.py

key-decisions:
  - "_calibrate_stop_target() queries alpha_frames directly (weight_epoch=weight_version, bar_ts<oos_start, symbol=ANY(eligible_symbols)) rather than reading counterfactual data off the results param passed to _calibrate_hold_max_bars -- the alpha_ensemble_ic corpus rows genuinely carry no counterfactual_mae/mfe columns; results still scopes WHICH symbols are eligible (skip is_pooled), consistent with the plan's 'same STRUCTURE, different DATA SOURCE' framing"
  - "stop_target_min_qualifying_symbols (migration 253, default 3) is wired as the per-symbol per-status minimum FRAME count (min_frames) inside _select_stop_target_from_excursions, per the plan's explicit Task 1 instruction -- despite the migration's own description naming it a per-cell minimum-qualifying-SYMBOLS floor. No second cell-level qualifying-symbol-count gate exists; a cell writes on ANY non-zero count of qualifying symbols, exactly mirroring _calibrate_hold_max_bars' 'zero qualifying symbols is the only skip condition' contract and this plan's own must_haves truth"
  - "stop and target components are tracked as INDEPENDENT per-cell medians (a symbol may qualify for one and not the other, since closed_target and closed_max_hold are disjoint frame subpopulations) -- n_written counts each component's key write separately"

patterns-established:
  - "Pattern: when a calibration function's orchestrating corpus (the IC engine's own results) lacks the data a new selection criterion needs, scope eligibility from that corpus but fetch the actual data from its true source table with an explicit in-sample + champion-weight_epoch filter -- do not force-fit unrelated data through the existing results shape"

requirements-completed: [D-01b, D-02, D-03]

# Metrics
duration: ~40min
completed: 2026-07-23
---

# Phase 166 Plan 02: Scalar Candidate (stop_atr_mult/target_r_multiple Calibration) Summary

**Built `_calibrate_stop_target()`, the champion-gated sibling of EIC-02's `_calibrate_hold_max_bars()`, deriving per-(regime,tf) `stop_atr_mult`/`target_r_multiple` from `alpha_frames`' uncensored closed_target-MAE/closed_max_hold-MFE excursion percentiles instead of copying the IC-decay-walk (which has no distance/reward-ratio analog).**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-07-23T12:21:15Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (1 modified, 1 created)

## Accomplishments

- **Task 1:** Added `_select_stop_target_from_excursions()` -- a pure module-level function selecting `(stop_atr_mult, target_r_multiple)` for one symbol's `(symbol, tf, regime)` group from `alpha_frames` excursion data. Stop placement uses the `stop_mae_percentile`-th percentile of ATR-rescaled MAE among `closed_target` frames only (uncensored -- these frames never touched the stop); target placement uses the `target_mfe_percentile`-th percentile of R-unit MFE among `closed_max_hold` frames only (uncensored -- never touched stop or target). `closed_stop` frames are excluded from the stop distribution (right-censored, todo 088 alignment); `closed_ic_decay` frames excluded from both. Extended `EnsembleICConfig.from_apr` with the three migration-253-seeded selection params.
- **Task 2:** Added `EnsembleICEngine._calibrate_stop_target()`, mirroring `_calibrate_hold_max_bars`' grouping/median/skip-if-empty structure but querying `alpha_frames` directly (scoped to the champion `weight_epoch`, in-sample `bar_ts < oos_start`, and the symbols this run's `results` corpus actually measured) since the source table for counterfactual excursions differs from the IC engine's own corpus. Wired into the identical CR-02 champion-`weight_version` dispatch block as `_calibrate_hold_max_bars` -- fires only when `weight_version == champion_weight_version`, otherwise logs `ensemble_ic.stop_target_calibration_skipped`.

## Task Commits

Each task was committed atomically:

1. **Task 1: `_select_stop_target_from_excursions()` pure selection function** - `3727eb2c` (test)
2. **Task 2: `_calibrate_stop_target()` method + CR-02 champion-gate wiring** - `ebbc559b` (feat)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode -- orchestrator handles final merge)

## Files Created/Modified

- `services/ensemble_ic_engine.py` - Added `_STOP_TARGET_FETCH_SQL`, `_select_stop_target_from_excursions()`, `EnsembleICEngine._calibrate_stop_target()`, extended `EnsembleICConfig` with 3 new fields, wired the CR-02 dispatch to call both calibration functions under the same champion gate.
- `tests/unit/test_ensemble_ic_stop_target_calibration.py` - 12 unit tests: 8 for the pure selection function (percentile correctness, closed_stop/closed_ic_decay exclusion, min_frames floor, NaN/inf filtering, no decay_threshold/lookahead reference) + 4 for the async orchestration (grouping/median-across-symbols, zero-qualifying-cell skip, is_pooled exclusion, CR-02 dispatch source-level assertion).

## Decisions Made

- `_calibrate_stop_target()` reads `alpha_frames` via its own query rather than extracting counterfactual data from the `results` param `_calibrate_hold_max_bars` also receives -- the `alpha_ensemble_ic` corpus rows built by this engine's own worker functions carry no `counterfactual_mae`/`mfe` columns (confirmed via full-file grep before implementing: zero pre-existing references to `counterfactual`/`alpha_frames` in `ensemble_ic_engine.py`). `results` still governs eligibility scope (skip `is_pooled`, restrict to symbols this run measured); the query adds its own `bar_ts < oos_start` in-sample filter since `alpha_frames` (unlike `results`) is not already scoped to this run's corpus.
- `stop_target_min_qualifying_symbols` (migration 253) is used as `min_frames` (the per-symbol minimum finite-observation floor) per the plan's explicit Task 1 instruction, despite the migration's description framing it as a per-cell minimum-qualifying-symbols floor. No additional cell-level "N qualifying symbols" gate was added beyond the existing "zero qualifying symbols = skip" contract -- this exactly matches the plan's own must_haves truth ("A (regime,tf) cell with zero qualifying symbols is skipped entirely") and `_calibrate_hold_max_bars`' precedent (any non-zero count of qualifying symbols writes a median).
- Stop and target are tracked as fully independent per-(regime,tf) aggregations -- a symbol contributing a valid stop value need not also contribute a valid target value (the two source subpopulations, `closed_target` and `closed_max_hold`, are disjoint by construction).

## Deviations from Plan

### Auto-fixed Issues

None -- both tasks' `<action>` text left genuine implementation-detail latitude (the exact data-flow for `_calibrate_stop_target()`'s counterfactual data source was not fully specified in the literal 4-parameter signature quoted in the plan text) rather than describing a bug or gap. Resolved via direct investigation of the live schema (`alpha_frames` columns, `alpha_frame_writer.py`'s `weight_epoch` tag-through, `EnsembleICEngine._execute_inner`'s in-scope `weight_version`/`oos_start` variables) before implementing -- documented above as a Decision Made, not a deviation, since no plan requirement was violated (the function's signature was extended with `weight_version`/`oos_start` params beyond the plan's illustrative 4-param list, which is necessary for correct in-sample/champion-epoch scoping and was always going to be available at the real call site inside the CR-02 dispatch block).

---

**Total deviations:** 0
**Impact on plan:** None. Both tasks executed per their `<action>`/`<verify>`/`<acceptance_criteria>` text; the signature extension is an implementation necessity consistent with the plan's own IN-SAMPLE-ONLY/CR-02 requirements, not a scope change.

## Issues Encountered

None. Full unit suite (`tests/unit/ -q`) green throughout both tasks; ruff and black clean on every commit.

## User Setup Required

None -- no external service configuration required. Migration 253's APR keys (166-01) already provide the runtime configuration surface; the first live `weight_version == champion` `EnsembleICEngine` run will populate the per-(regime,tf) `alpha.frame.stop_atr_mult`/`target_r_multiple` keys this plan's code writes.

## Next Phase Readiness

- Plan 166-03 (structural candidate Part 1) is independent of this plan's code (different files: `alpha_frame_writer.py` extension + new `structural_confluence.py` module) and remains blocked on Phase 163 execution per 166-01's `NULL_PENDING_163` finding -- unaffected by this plan.
- Plan 166-04/166-05/166-06 (validation gate, wiring, scoring) can rely on `alpha.frame.stop_atr_mult.<regime>.<tf>`/`target_r_multiple.<regime>.<tf>` keys existing in `config_state` once a champion-`weight_version` `EnsembleICEngine` run executes against real `alpha_frames` data -- the calibration mechanism itself is code-complete and unit-tested, but has not yet been run against live data in this plan's scope (that's an ops-run/later-plan concern, matching 166-01's diagnosis-only precedent).
- No blockers introduced. Full unit suite remains green post-merge.

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*
