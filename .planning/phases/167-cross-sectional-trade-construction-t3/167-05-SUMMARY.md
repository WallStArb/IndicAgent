---
phase: 167-cross-sectional-trade-construction-t3
plan: 05
subsystem: infra
tags: [numpy, lstsq, bootstrap, validation-gate, attribution]

requires:
  - phase: 167-cross-sectional-trade-construction-t3
    provides: "construction_spreads hypertable + APR keys (Plan 01), pure construction primitives (Plan 02), CrossSectionalSpreadTracker write path (Plan 03), evaluate_spread_gate/frame_gate_passes reuse/write_verdict_artifact/--evaluate-gate mode (Plan 04)"
provides:
  - "static_tilt_weights: time-averaged net leg exposure per symbol -- the static bucket membership benchmark"
  - "static_tilt_series: counterfactual buy-and-hold-average-exposure return series, with structural alignment guards"
  - "attribution_verdict: single-regressor spread-vs-static-tilt decomposition; residual gated through counterfactual_tracker.frame_gate_passes verbatim, no new bootstrap"
  - "--evaluate-attribution CLI mode / _run_evaluate_attribution: read-only per-scale + binding Gate 2 verdict, JSON verdict artifact including the static weight vector"
  - "Argparse mutual exclusion across --backfill / --evaluate-gate / --evaluate-attribution"
affects: [167-06]

tech-stack:
  added: []
  patterns:
    - "Single-regressor OLS via numpy.linalg.lstsq (design matrix [static, ones]) instead of a per-symbol dummy regression -- avoids overfitting with as many regressors as universe symbols"
    - "Residual = spread - beta*static, intercept deliberately NOT subtracted -- the intercept is the forecast's constant excess return and is exactly what the gate tests"
    - "Structural alignment guard (_assert_strictly_increasing_unique) shared by static_tilt_series and attribution_verdict -- raises on any duplicate or non-monotonic bar key rather than trusting sorted-input ordering"
    - "Four parallel regression sequences built in one ordered pass over the sorted bar_ts intersection of two independently-fetched sources, so they cannot drift relative to each other by construction"

key-files:
  created: []
  modified:
    - services/cross_sectional_spread_tracker.py
    - tests/unit/test_cross_sectional_spread_tracker.py

key-decisions:
  - "Static bucket membership = each symbol's time-averaged net leg membership over the evaluation window: w_s = (n_bars_long_s - n_bars_short_s) / n_bars. Deliberately carries no timing information -- that is the entire point of the benchmark."
  - "The benchmark is ONE collapsed returns series (sum_s w_s * r_s,t), never 80 per-symbol dummy regressors -- avoids a scalar-dependent-variable regression with as many regressors as the universe."
  - "Gate 2 gates on the RESIDUAL, not static_r2 alone: gate2_passes = residual_passes AND NOT static_dominates. Proven un-satisfiable by low R-squared alone via test case C."
  - "static_dominates = static_r2 > alpha.construction.attribution_max_static_r2 (seeded 0.50 by Plan 01) -- the literal reading of the design doc's 'if a fixed membership explains most of it.'"
  - "No statsmodels, no BH-FDR, no second bootstrap -- numpy.linalg.lstsq for the OLS fit, counterfactual_tracker.frame_gate_passes reused verbatim on the residual series."
  - "Both lookahead scales get independent verdicts; gate2_passes_overall requires BOTH scales' gate2_passes to be true (design decision 7)."
  - "The static-tilt benchmark is retrospective and time-averaged by construction (computed from the SAME window whose returns it explains) -- benchmark_kind is a literal returned field on every verdict, PASS and FAIL alike, and the PASS verdict_text is worded 'not explained by a static tilt,' never 'loads on' or 'is caused by' the forecast."

requirements-completed:
  - "TCL-VG-2: Validation Gate 2 - attribution honesty; spread P&L must load on the forecast, not a static factor tilt"
  - "RESEARCH Open Question 1: Gate 2 scoped and implemented as new work (no prior implementation existed anywhere in this codebase)"
  - "RESEARCH Assumption A5: a construction that is a disguised static factor tilt now fails Gate 2, proven by a unit test built to construct exactly that case"
  - "RESEARCH Todo 185 assessment: no per-entity demeaning primitive added -- ranking already differences out any within-bar-constant per-symbol term"
  - "REVIEW-H3 (Codex): the static-tilt benchmark's retrospective, non-causal nature is a first-class field (benchmark_kind) and caveat string (interpretation_caveat), never only prose"
  - "REVIEW-S3 (Codex): the regression fails loudly (ValueError) on misaligned series, duplicate timestamps, or non-unique bar keys, at two independent layers"
  - "REVIEW-H4 (Codex): the Gate 2 verdict lands in a machine-readable JSON artifact via write_verdict_artifact, not only logs and prose"

duration: ~35min
completed: 2026-07-27
---

# Phase 167 Plan 05: Validation Gate 2 (Attribution Honesty) Summary

**Single-regressor decomposition of the realized cross-sectional spread against a retrospective, time-averaged static leg-membership benchmark, with the residual gated through the identical day-clustered bootstrap Gate 1 uses -- exposed as a fourth, read-only `--evaluate-attribution` CLI mode.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3
- **Files modified:** 2 (both extended, none created)

## Accomplishments
- `static_tilt_weights` implemented: per-symbol time-averaged net leg exposure `w_s = (n_bars_long_s - n_bars_short_s) / n_bars`, raising `ValueError` on empty input rather than returning a silently-empty (and misleadingly clean-passing) weight vector.
- `static_tilt_series` implemented: the counterfactual buy-and-hold-average-exposure return series, with a structural duplicate/non-monotonic bar-key guard shared with `attribution_verdict`.
- `attribution_verdict` implemented: single-regressor `spread = alpha + beta*static + eps` OLS fit via `numpy.linalg.lstsq`, `static_r2` computed with a `SS_tot == 0` divide-by-zero guard, residual computed as `spread - beta*static` (intercept deliberately retained, never subtracted), residual gated through `counterfactual_tracker.frame_gate_passes` verbatim -- zero new bootstrap machinery. Returns the literal `benchmark_kind = "retrospective_time_averaged_membership"` on every call.
- `--evaluate-attribution` CLI mode (`_run_evaluate_attribution`) added: fetches OOS leg-membership + gross-spread rows and the raw panel via a plain `asyncpg.connect` (no pool, no writes, no D-06), builds the four regression sequences (`spread_values`, `static_values`, `cluster_ids`, `bar_keys`) from the sorted intersection of both sources' `bar_ts` sets in one ordered pass, computes a per-scale `attribution_verdict`, and logs the binding overall verdict with an explicit `interpretation_caveat`. Writes a JSON verdict artifact via Plan 04's `write_verdict_artifact`, unchanged.
- `--backfill` / `--evaluate-gate` / `--evaluate-attribution` are now a single `argparse` mutually exclusive group -- an operator cannot request a write pass and a read-only gate in the same invocation.
- Five new unit tests (17 total in the file): the static-weight arithmetic, all three Gate 2 outcomes (pure static tilt FAILS, independent P&L PASSES, low-R-squared-but-no-residual FAILS), the alignment guards at both layers, and a targeted regression test proving the residual mean equals the retained intercept, never zero.

## Exact Log Field Names, Verdict Artifact Contract, and the Three verdict_text Outcomes

Recorded here verbatim per this plan's `<output>` instruction -- Plan 06 transcribes the live verdict and this caveat into `docs/research/trade-construction-layer.md`.

**Log events emitted by `_run_evaluate_attribution` (structlog, `cross_sectional_spread_tracker.*` namespace):**
- `cross_sectional_spread_tracker.attribution_intersection` -- one line per scale (`fast`, `slow`), logged BEFORE the regression so a shrinking intersection is visible rather than silent. Fields: `scale`, `n_attribution_rows`, `n_panel_bars`, `n_intersection`.
- `cross_sectional_spread_tracker.attribution_verdict` -- one line per scale, `segment="oos"`. Fields: `scale`, `segment`, `max_static_r2`, plus every key of `attribution_verdict`'s returned dict (`beta`, `intercept`, `static_r2`, `static_dominates`, `n_bars`, `n_clusters`, `residual_ci_lower`, `residual_ci_upper`, `residual_passes`, `gate2_passes`, `benchmark_kind`).
- `cross_sectional_spread_tracker.gate2_summary` -- one line, the binding verdict. Fields: `gate2_passes_overall`, `fast_static_r2`, `slow_static_r2`, `fast_residual_ci_lower`, `slow_residual_ci_lower`, `benchmark_kind`, `verdict_text`, `interpretation_caveat`.
- `cross_sectional_spread_tracker.gate2_verdict_artifact_written` -- one line. Field: `artifact_path`.

**Verdict artifact path convention (reused from Plan 04, unchanged):** `logs/construction_verdicts/gate2_{YYYYmmddTHHMMSSZ}.json` (UTC, never overwritten) plus `logs/construction_verdicts/gate2_latest.json` (always the most recent run).

**Verdict artifact top-level payload keys:** `gate2_passes_overall` (bool), `verdict_by_scale` (dict keyed `"fast"`/`"slow"`, each the full `attribution_verdict` return dict), `max_static_r2` (float, the threshold in force), `static_tilt_weights` (dict, symbol -> weight -- the single most useful field for a later reader trying to understand WHAT the tilt was), `oos_start` (str), `n_oos_rows` (int), `n_oos_day_clusters` (int), `benchmark_kind` (str, always `"retrospective_time_averaged_membership"`), `interpretation_caveat` (str, verbatim below), `compute_version` (str), `verdict_text` (str, the three-way per-scale distinction joined with `" | "`).

**The three `verdict_text` outcomes, in the design doc's own terms (produced per scale by `_attribution_verdict_text`, joined `" | "` across both scales):**

1. **PASS** -- `gate2_passes` is `True`: *"{scale}: PASS -- the residual clears zero at 95% CI (ci_lower=...) and a fixed membership does not explain most of the spread (static_r2=...); the P&L is not explained by a static tilt"*. Wording is deliberately limited to "not explained by a static tilt" -- it never claims the P&L is caused by or loads on the forecast (design decision 8; a `grep -c "loads on the forecast"` acceptance criterion enforces this at zero matches).
2. **FAIL, static tilt** -- `static_dominates` is `True`: *"{scale}: FAIL, static tilt -- a fixed membership explains static_r2=... of the spread, above the configured ceiling, so the 'forecast' is a factor exposure in disguise (edge thesis T4); cap expectations accordingly"*.
3. **FAIL, no residual** -- `static_dominates` is `False` but `residual_passes` is `False`: *"{scale}: FAIL, no residual -- after removing the static component nothing survives at 95% CI (residual_ci_lower=...)"*.

**The exact `interpretation_caveat` wording (module constant `_ATTRIBUTION_INTERPRETATION_CAVEAT`, carried verbatim into both the `gate2_summary` log line and the verdict artifact):**

> "The static-tilt benchmark is a retrospective, time-averaged summary of realized leg membership over the same window whose returns it is used to explain, not a live or causal decomposition of the strategy's mechanism. A surviving residual therefore falsifies the static-tilt explanation without establishing what does explain the return."

**The binding Gate 2 pass rule (design decision 7, single source of truth):** `gate2_passes_overall` is `True` iff BOTH the `fast` and `slow` scales' `gate2_passes` are `True`.

## Task Commits

1. **Task 1: Implement the attribution-honesty pure functions** - `bb049f98` (feat)
2. **Task 2: Wire the --evaluate-attribution read-only CLI mode and its verdict artifact** - `634b48f3` (feat)
3. **Task 3: Unit tests for attribution honesty, including a deliberately failing construction** - `9a14a7f8` (test)

**Plan metadata:** orchestrator's responsibility per this plan's worktree execution mode (STATE.md/ROADMAP.md not touched by this agent).

## Files Created/Modified
- `services/cross_sectional_spread_tracker.py` - added `static_tilt_weights`, `_assert_strictly_increasing_unique`, `static_tilt_series`, `attribution_verdict`, `_ATTRIBUTION_ROWS_SQL`, `_ATTRIBUTION_INTERPRETATION_CAVEAT`, `_attribution_verdict_text`, `_run_evaluate_attribution`, and the `--evaluate-attribution` CLI flag (now part of a mutually exclusive argparse group with `--backfill`/`--evaluate-gate`) on top of Plans 02-04's construction primitives, write path, and Gate 1 evaluation core.
- `tests/unit/test_cross_sectional_spread_tracker.py` - added `test_static_tilt_weights`, `test_attribution_honesty`, `test_attribution_verdict_rejects_misaligned_series`, `test_static_tilt_series_rejects_duplicate_bars`, `test_attribution_intercept_is_not_subtracted_from_residual` (12 prior tests from Plans 02/04 unchanged, still passing; 17 total).

## Decisions Made
Followed the plan's design decisions as specified: static bucket membership as time-averaged net leg exposure (decision 1), one collapsed benchmark series rather than per-symbol dummies (decision 2), gate on the residual with the intercept retained (decision 3), `static_dominates` threshold as the literal `> 0.50` reading of "most" (decision 4), `numpy.linalg.lstsq` with no statsmodels/BH-FDR dependency (decision 5), no todo-185 per-entity demeaning primitive (decision 6), both lookahead scales required to pass for the binding verdict (decision 7), `benchmark_kind`/`interpretation_caveat` as first-class fields distinguishing a falsification-only test from a causal one (decision 8), and structural (not trusted) alignment validation at two independent layers (decision 9).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reworded a Task 1 docstring to avoid the literal substring "apply_bh_fdr" tripping the acceptance-criteria grep**
- **Found during:** Task 1 verification (acceptance criteria grep pass)
- **Issue:** `attribution_verdict`'s docstring originally named `apply_bh_fdr` by name while explaining it is NOT needed here (a true statement about delegation-avoidance), but the acceptance criterion `grep -c "statsmodels\|apply_bh_fdr" services/cross_sectional_spread_tracker.py` returns 0 is a literal substring check with no distinction between "uses apply_bh_fdr" and "mentions apply_bh_fdr while explaining it is not used." Same class of false-positive Plan 04 hit with "BCa".
- **Fix:** Reworded to reference "`src/intelligence/statistics/ic_math.py`'s FDR helper" instead of the literal function name -- same meaning, no literal "apply_bh_fdr" substring anywhere in the file.
- **Files modified:** `services/cross_sectional_spread_tracker.py`
- **Verification:** `grep -c "statsmodels\|apply_bh_fdr" services/cross_sectional_spread_tracker.py` returns 0.
- **Committed in:** `bb049f98` (Task 1 commit)

**2. [Rule 1 - Bug] Reworded a Task 2 docstring to avoid the literal phrase "loads on the forecast" tripping the acceptance-criteria grep**
- **Found during:** Task 2 verification (acceptance criteria grep pass)
- **Issue:** `_attribution_verdict_text`'s docstring originally quoted the FORBIDDEN phrase itself ("never that it 'loads on the forecast'") while explaining the constraint the PASS wording must satisfy -- the acceptance criterion `grep -c "loads on the forecast" services/cross_sectional_spread_tracker.py` returns 0 is a literal substring check that cannot distinguish "asserts the phrase" from "forbids the phrase while explaining why."
- **Fix:** Reworded to "never that it is caused by or attributable to the forecast" -- same meaning (design decision 8's asymmetry), no literal "loads on the forecast" substring anywhere in the file. The actual PASS verdict text (the string a human would read) never contained the forbidden phrase in the first place; this was a docstring-only wording fix.
- **Files modified:** `services/cross_sectional_spread_tracker.py`
- **Verification:** `grep -c "loads on the forecast" services/cross_sectional_spread_tracker.py` returns 0.
- **Committed in:** `634b48f3` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1, both docstring-wording-only fixes to satisfy literal-substring acceptance grep, neither touching runtime logic)
**Impact on plan:** No scope creep. Both deviations are wording-only fixes matching the same pattern Plan 04 already established (its "BCa" docstring fix) -- literal-substring acceptance criteria checking for absence of a phrase will also match that phrase appearing inside an explanation of its absence.

## Issues Encountered
- Running `tests/integration/ -k cross_sectional_spread -m integration` as part of verification wrote a fresh, uncommitted `.planning/corpus_manifests/cross_sectional_spread_tracker.json` test-run manifest. Per Plan 03/04's established decision (test-run manifests are never committed -- only real production-corpus runs commit that file), this was left untracked and NOT staged into any task commit.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All four CLI modes (`--backfill`, incremental default, `--evaluate-gate`, `--evaluate-attribution`) are implemented, unit-tested, and mutually exclusive where required -- Phase 167's complete CLI surface per this plan's `<interfaces>` block.
- `--evaluate-attribution` has never been run against the live corpus -- `construction_spreads` is still empty in live `indicagent` as of this plan (Plan 06 performs the first real `--backfill` run, then both `--evaluate-gate` and `--evaluate-attribution`).
- Plan 06 should transcribe the exact `gate2_summary` log fields, the verdict artifact's top-level payload keys, the three `verdict_text` outcomes, and the `interpretation_caveat` wording (all recorded verbatim above) into `docs/research/trade-construction-layer.md`, alongside the live verdict once a real `--evaluate-attribution` run has occurred.
- Plan 06 Task 3 (per this plan's threat register, T-167-23) must carry the same `benchmark_kind`/`interpretation_caveat` distinction into the research doc -- do not let "the residual survives" get transcribed as "the forecast caused the P&L."

---
*Phase: 167-cross-sectional-trade-construction-t3*
*Completed: 2026-07-27*

## Self-Check: PASSED
- FOUND: commit bb049f98 (Task 1)
- FOUND: commit 634b48f3 (Task 2)
- FOUND: commit 9a14a7f8 (Task 3)
- FOUND: services/cross_sectional_spread_tracker.py
- FOUND: tests/unit/test_cross_sectional_spread_tracker.py
