---
phase: 167-cross-sectional-trade-construction-t3
plan: 04
subsystem: infra
tags: [asyncpg, timescaledb, batch, bootstrap, scipy, validation-gate]

requires:
  - phase: 167-cross-sectional-trade-construction-t3
    provides: "construction_spreads hypertable + APR keys (Plan 01), pure construction primitives decile_legs/spread_from_legs/net_spread_by_cost_bps (Plan 02), CrossSectionalSpreadTracker write path with incremental watermark (Plan 03)"
provides:
  - "mean_gross_spread_over_bars: the single shared per-draw reduction used by BOTH the observed measurement and every shuffled-null draw"
  - "shuffled_ranking_null_p: live within-bar-only permutation null with a runtime eligible-bar-count parity guard"
  - "evaluate_spread_gate: reuses counterfactual_tracker.evaluate_frame_gate verbatim, renames tf/regime/n_frames to scale/cost_bps/n_bars"
  - "write_verdict_artifact: strict-JSON timestamped + _latest verdict artifact under logs/construction_verdicts/, NaN/inf coerced to null, never overwrites a prior run"
  - "--evaluate-gate CLI mode / _run_evaluate_gate: read-only eight-cell OOS verdict grid, binding Gate 1 pass/fail, labeled in_sample_diagnostic segment"
affects: [167-05, 167-06]

tech-stack:
  added: []
  patterns:
    - "Single shared reduction function (mean_gross_spread_over_bars) called by both the observed pass and every null draw, so observed-vs-null comparability is structural, not asserted"
    - "Runtime eligible-bar-count parity guard: shuffled_ranking_null_p raises if its own draws diverge in eligible-bar count; _run_evaluate_gate raises if the null's count differs from the observed pass's count"
    - "alpha_scorer.py's SHAPE CONSTRAINT rename pattern: evaluate_frame_gate's 2-tuple group_key output (tf/regime) renamed to the caller's actual semantics (scale/cost_bps) rather than reimplementing the bootstrap"
    - "Strict-JSON verdict artifact: non-finite floats coerced to null before json.dumps(allow_nan=False), timestamped filename never overwritten, _latest.json mirrors the most recent run"

key-files:
  created: []
  modified:
    - services/cross_sectional_spread_tracker.py
    - tests/unit/test_cross_sectional_spread_tracker.py

key-decisions:
  - "Gate 1 evaluates the OOS window with bar_ts >= alpha.validation.oos_start (design decision 1) -- the OPPOSITE direction of counterfactual_tracker's FRAME-04 in-sample exit gate, which uses <. The module's sole `<` comparison against bar_ts is the in-sample diagnostic query, verified by grep in acceptance criteria."
  - "The binding Gate 1 pass rule (single source of truth, reproduced verbatim by Plan 06 in trade-construction-layer.md): Gate 1 passes iff, at max(cost_bps) (the most conservative tier), BOTH the fast and slow cells have passes is True, AND both scales' null_p is strictly below 0.05."
  - "The in-sample segment is logged with segment='in_sample_diagnostic' and is never fed into gate1_passes -- it exists solely to make the T3 script's full-2006-2026-history published numbers comparable to the OOS verdict."
  - "No second bootstrap implementation: evaluate_spread_gate delegates 100% of the day-clustered bootstrap machinery to counterfactual_tracker.evaluate_frame_gate/frame_gate_passes. An acceptance-criteria grep for 'scipy.stats import bootstrap|def frame_gate_passes|def _bca|BCa' (including the literal substring 'BCa' anywhere in the file, even in prose) returns 0."
  - "The shuffled-ranking null is recomputed live from the raw feature/return panel every run via _GATE_PANEL_SQL -- never derived from persisted construction_spreads rows, since a permutation of the ranking produces different legs than what was persisted."

requirements-completed:
  - "TCL-VG-1: Validation Gate 1 - net-of-cost spread Sharpe > 0 at 95% bootstrap CI, beats the shuffled-ranking null"
  - "TCL-MD-6: Minimal Design step 6 - portfolio-level measurement vs. benchmarks"
  - "D-05: cost-hurdle computed live, verdict reported per cost tier"
  - "RESEARCH Pattern 3: --evaluate-gate as a separate read-only CLI mode"
  - "RESEARCH Todo 186 assessment: reuse frame_gate_passes day-clustered bootstrap, do NOT build a new cross-sectional block bootstrap"
  - "REVIEW-H2 (Codex): the shuffled null must have defined, tested behavior for tied values and bars with too few eligible symbols"
  - "REVIEW-S2 (Codex): the null universe must preserve universe size, decile rounding, and symbol eligibility exactly"
  - "REVIEW-H4/L1 (Codex): capture a machine-readable verdict artifact, so the docs are not the only record of what happened"

duration: ~75min
completed: 2026-07-27
---

# Phase 167 Plan 04: Validation Gate 1 Evaluation Core Summary

**A read-only `--evaluate-gate` CLI mode computing an eight-cell OOS verdict grid (2 scales x 4 cost tiers) via `frame_gate_passes` reused verbatim, plus a live shuffled-ranking null whose eligible-bar set is provably identical to the observed measurement, plus a strict-JSON, never-overwritten verdict artifact.**

## Performance

- **Duration:** ~75 min
- **Tasks:** 2/2
- **Files modified:** 2 (both extended, none created)

## Accomplishments
- `mean_gross_spread_over_bars` implemented as the SINGLE shared reduction called by both the observed pass and every shuffled-null draw -- eliminates any possibility of the two being computed over different bar sets by construction, not by convention.
- `shuffled_ranking_null_p` implemented with a within-bar-only permutation (symbol list, universe size, and return mapping carried through untouched) and a runtime `ValueError` guard if the eligible-bar count diverges across draws.
- `evaluate_spread_gate` delegates 100% of the day-clustered bootstrap to `counterfactual_tracker.evaluate_frame_gate`, applying `alpha_scorer.py`'s established SHAPE CONSTRAINT rename pattern (`tf`->`scale`, `regime`->`cost_bps`, `n_frames`->`n_bars`).
- `write_verdict_artifact` persists the full Gate verdict as strict, timestamped JSON (`{verdict_name}_{YYYYmmddTHHMMSSZ}.json` + `{verdict_name}_latest.json`), coercing NaN/inf to `null` and never overwriting a prior run's timestamped file.
- `_run_evaluate_gate` + `--evaluate-gate` CLI flag: fetches the OOS `construction_spreads` rows, computes the eight-cell grid, computes the live shuffled null per scale (asserting null/observed eligible-bar parity), computes the binding Gate 1 verdict, fetches and logs the in-sample diagnostic segment, and writes the full payload via `write_verdict_artifact`. Zero database writes; the only filesystem side effect is the verdict artifact.
- Twelve unit tests (6 new, Plan 02's original 6 preserved) cover the eight-cell grid and field rename, the two-tuple `group_key` contract, a null check proven capable of both passing and failing, within-bar-only permutation (verified via a `numpy.random.default_rng` recording proxy, since `Generator` is an immutable C-extension type), observed-vs-null eligible-bar parity under a degenerate bar and two tied bars (with the internal parity guard proven live via monkeypatch, not merely assumed), and the strict-JSON accumulating verdict artifact.

## Exact Log Event Names, Verdict Artifact Contract, and the Binding Gate 1 Rule

Recorded here verbatim per this plan's `<output>` instruction -- Plan 05 reuses `write_verdict_artifact` for the Gate 2 verdict and Plan 06 reads the artifact and transcribes the rule into `trade-construction-layer.md`.

**Log events emitted by `_run_evaluate_gate` (structlog, `cross_sectional_spread_tracker.*` namespace):**
- `cross_sectional_spread_tracker.gate_verdict` -- one line per (scale, cost_bps) cell, for BOTH the OOS grid (`segment="oos"`) and the in-sample diagnostic grid (`segment="in_sample_diagnostic"`). Fields: `segment`, `scale`, `cost_bps`, `n_bars`, `n_clusters`, `ci_lower`, `ci_upper`, `passes`, `coverage`.
- `cross_sectional_spread_tracker.null_check` -- one line per scale (`fast`, `slow`). Fields: `scale`, `null_p`, `null_mean`, `null_std`, `n_shuffles`, `n_eligible_bars`.
- `cross_sectional_spread_tracker.gate1_summary` -- one line, the binding verdict. Fields: `gate1_passes`, `binding_cost_bps`, `fast_ci_lower`, `fast_ci_upper`, `fast_n_bars`, `fast_n_clusters`, `slow_ci_lower`, `slow_ci_upper`, `slow_n_bars`, `slow_n_clusters`, `fast_null_p`, `slow_null_p`, `verdict_text`.
- `cross_sectional_spread_tracker.gate1_verdict_artifact_written` -- one line. Field: `artifact_path`.

**Verdict artifact path convention:** `logs/construction_verdicts/gate1_{YYYYmmddTHHMMSSZ}.json` (UTC, never overwritten -- the record accumulates) plus `logs/construction_verdicts/gate1_latest.json` (always the most recent run).

**Verdict artifact top-level payload keys:** `gate1_passes` (bool), `binding_cost_bps` (int), `verdict_text` (str, the three-way per-scale distinction), `oos_grid` (list of 8 verdict dicts), `in_sample_diagnostic_grid` (list of 8 verdict dicts, NEVER part of the pass/fail decision), `null_by_scale` (dict keyed `"fast"`/`"slow"`, each with `null_p`/`null_mean`/`null_std`/`n_shuffles`/`n_eligible_bars`/`observed_mean_gross_spread`), `oos_start` (str), `n_oos_rows` (int), `n_oos_day_clusters` (int), `apr` (dict of every APR value in force: `decile_fraction`, `cost_hurdle_bps_round_trip`, `null_shuffles`, `attribution_max_static_r2`, and the four `alpha.scoring.*` bootstrap parameters), `compute_version` (str).

**The binding Gate 1 pass rule, stated once as the single source of truth (design decision 3, verbatim):**

> Gate 1 passes iff, at `max(cost_bps)`, BOTH the `fast` and `slow` cells have `passes is True`, AND both scales' `null_p` is strictly below `0.05`.

## Task Commits

1. **Task 1: Implement the Gate 1 evaluation core, the live shuffled null, the verdict artifact, and the --evaluate-gate mode** - `b8c8ea67` (feat)
2. **Task 2: Unit tests for the Gate 1 grouping core, the shuffled null's edge cases, and the verdict artifact** - `0b5ac943` (test)

**Plan metadata:** this commit (docs: plan summary)

## Files Created/Modified
- `services/cross_sectional_spread_tracker.py` - added `mean_gross_spread_over_bars`, `shuffled_ranking_null_p`, `evaluate_spread_gate`, `_coerce_non_finite`, `write_verdict_artifact`, `_GATE_ROWS_SQL`/`_GATE_ROWS_IN_SAMPLE_SQL`/`_GATE_PANEL_SQL`, `_flatten_gate_rows`, `_build_panel_by_bar`, `_gate1_verdict_text`, `_run_evaluate_gate`, and the `--evaluate-gate` CLI flag/dispatch on top of Plan 02/03's construction primitives and write path.
- `tests/unit/test_cross_sectional_spread_tracker.py` - added `test_evaluate_gate`, `test_evaluate_gate_group_key_is_a_two_tuple`, `test_shuffled_ranking_null`, `test_shuffled_null_permutes_within_bar_only`, `test_shuffled_null_ties_and_degenerate_bars`, `test_verdict_artifact_is_strict_json` (Plan 02's original 6 tests unchanged, still passing).

## Decisions Made
- Followed the plan's design decisions as specified: OOS direction is `>=` (decision 1), in-sample segment is a labeled diagnostic never fed into the verdict (decision 2), binding tier is `max(cost_bps)` requiring both scales to pass AND both nulls to clear (decision 3), the null is recomputed live every run rather than cached (decision 4), no second bootstrap implementation (decision 5), the null universe is defined structurally via one shared reduction function rather than by assertion (decision 6), the full verdict is persisted as strict JSON before any human reads it (decision 7).
- `shuffled_ranking_null_p`'s docstring documents that calling it once per scale with the SAME seed (`bootstrap_random_state`) naturally reproduces the identical sequence of within-bar permutations for both scales "for free," since the permutation depends only on each bar's symbol count and the RNG draw sequence, not on which return column is being tested -- satisfying the T3 script's efficiency lesson (generate the permutation draws once, reuse across scales) within the plan's fixed public interface, which has no hook for passing precomputed draws explicitly.
- `_run_evaluate_gate` fetches the OOS gate rows, the raw panel, AND the in-sample diagnostic rows all within the same open `asyncpg.connect` before closing the connection (rather than opening a second connection later), since the in-sample fetch needs the same `oos_start` value and there is no reason to hold two connections open.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed the literal substring "BCa" from a Task 1 docstring to satisfy the "no second bootstrap implementation" acceptance grep**
- **Found during:** Task 1 verification (acceptance criteria grep pass)
- **Issue:** `evaluate_spread_gate`'s docstring originally said "delegates the day-clustered BCa/CLT bootstrap to `counterfactual_tracker.evaluate_frame_gate` VERBATIM" -- prose intended to describe delegation, but the acceptance criterion `grep -c "scipy.stats import bootstrap\|def frame_gate_passes\|def _bca\|BCa" services/cross_sectional_spread_tracker.py` returns 0 is a literal substring check with no distinction between "implements BCa" and "mentions BCa while explaining it delegates to code that implements BCa." The docstring's own true statement caused a false-positive match.
- **Fix:** Reworded to "delegates the day-clustered block-bootstrap machinery (the small-cluster-count / large-cluster-count method switch documented on `frame_gate_passes`) to `counterfactual_tracker.evaluate_frame_gate` VERBATIM" -- same meaning, no literal "BCa" substring anywhere in the file.
- **Files modified:** `services/cross_sectional_spread_tracker.py`
- **Verification:** `grep -c "scipy.stats import bootstrap\|def frame_gate_passes\|def _bca\|BCa" services/cross_sectional_spread_tracker.py` now returns 0.
- **Committed in:** `b8c8ea67` (Task 1 commit)

**2. [Rule 1 - Bug] `numpy.random.Generator.permutation` cannot be monkeypatched directly (immutable C-extension type)**
- **Found during:** Task 2, writing `test_shuffled_null_permutes_within_bar_only`
- **Issue:** The first implementation attempted `monkeypatch.setattr(np.random.Generator, "permutation", recording_permutation)`, which raised `TypeError: cannot set 'permutation' attribute of immutable type 'numpy.random._generator.Generator'` -- `Generator` is a C-extension type whose methods cannot be reassigned at the class level.
- **Fix:** Wrapped `numpy.random.default_rng` itself (a plain Python function, mutable at the module-attribute level) in a recording proxy object exposing a `.permutation()` method that records the call and delegates to a real `Generator` instance. `services.cross_sectional_spread_tracker` looks up `np.random.default_rng` dynamically at call time via the shared `numpy.random` submodule object, so the monkeypatch is visible to production code without any change to `cross_sectional_spread_tracker.py` itself.
- **Files modified:** `tests/unit/test_cross_sectional_spread_tracker.py`
- **Verification:** `test_shuffled_null_permutes_within_bar_only` passes, correctly asserting each permutation call's input array is exactly one bar's own feature-value set.
- **Committed in:** `0b5ac943` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bug fixes, both caught during this plan's own verification/test-writing, neither touching production logic beyond a docstring wording change)
**Impact on plan:** No scope creep. Deviation 1 is a wording-only fix (no logic change). Deviation 2 is a test-implementation-only fix (no production code change); the property it verifies (within-bar-only permutation) was already correctly implemented in Task 1 and is unaffected.

## Issues Encountered
- The pre-commit hook's ruff/black checks initially require `.venv` in the worktree; the symlink from Plan 03's process note (`.venv -> /home/bg/dev/indicagent/.venv`) was re-created at the start of this session per the same established pattern.
- Running `tests/integration/ -k cross_sectional_spread -m integration` as part of verification wrote a fresh, uncommitted `.planning/corpus_manifests/cross_sectional_spread_tracker.json` test-run manifest. Per Plan 03's summary decision (test-run manifests are never committed -- only real production-corpus runs commit that file), this was left untracked and NOT staged into either task commit.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `--evaluate-gate` is fully implemented and unit-tested, but has never been run against the live corpus -- `construction_spreads` is still empty in live `indicagent` as of this plan (Plan 06 performs the first real `--backfill` run per Plan 03's summary).
- Plan 05 can reuse `write_verdict_artifact` unchanged for the Gate 2 verdict artifact.
- Plan 06 should reproduce the binding Gate 1 pass rule (quoted verbatim above) into `trade-construction-layer.md`, and can read `logs/construction_verdicts/gate1_latest.json` once a real `--evaluate-gate` run has occurred.

---
*Phase: 167-cross-sectional-trade-construction-t3*
*Completed: 2026-07-27*

## Self-Check: PASSED
- FOUND: commit b8c8ea67 (Task 1)
- FOUND: commit 0b5ac943 (Task 2)
- FOUND: services/cross_sectional_spread_tracker.py
- FOUND: tests/unit/test_cross_sectional_spread_tracker.py
