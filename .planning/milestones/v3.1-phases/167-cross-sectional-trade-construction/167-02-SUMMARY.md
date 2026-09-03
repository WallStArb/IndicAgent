---
phase: 167-cross-sectional-trade-construction
plan: 02
subsystem: alpha
tags: [pure-functions, unit-tests, cross-sectional, decile-spread, cost-hurdle, apr-validation]

# Dependency graph
requires:
  - phase: 167-01
    provides: schema/APR keys/glossary entries this module's constants and future orchestration reference
provides:
  - "services/cross_sectional_spread_tracker.py: decile_legs, spread_from_legs, one_way_turnover, net_spread_by_cost_bps, validate_construction_config"
  - "tests/unit/test_cross_sectional_spread_tracker.py: 6 tests covering decile split, tied/missing feature values, run-boundary turnover, cost sweep, config validation, flat-weight guard"
affects: [167-03, 167-04, 167-05, 167-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-function construction primitives with no DB/Kafka I/O, unit-testable against the proof script's own ranking mechanic"
    - "Deterministic (feature_value, symbol) tie-break, recorded in the docstring as an intentional reproducibility divergence from the cross_sectional_relative_value proof script"
    - "None (not 0.0) as the explicit uncomputable-turnover sentinel at run boundaries"

key-files:
  created:
    - services/cross_sectional_spread_tracker.py
    - tests/unit/test_cross_sectional_spread_tracker.py
  modified: []

key-decisions:
  - "Flat equal-weight legs, no vol-scaling — built exactly what cross_sectional_relative_value's proof script measured, not the design doc's aspirational vol-scaled version (Pitfall 1)"
  - "Deterministic (feature_value, symbol) ascending tie-break in decile_legs, recorded as an intentional reproducibility divergence from the cross_sectional_relative_value script's row-order-dependent pandas sort_values tie order"
  - "one_way_turnover returns None, never 0.0, when both prior legs are empty (no predecessor bar) — Pitfall 4's named symptom is a turnover of exactly 0.0/1.0 at every run boundary"
  - "A None or non-finite feature value raises ValueError naming the offending symbol rather than being sorted — Python's tuple sort on NaN is non-transitive and silently produces an arbitrary split"
  - "net_spread_by_cost_bps computes every cost tier live from realized turnover every run (D-05), and never reads the directional-trade cost-hurdle APR key (different mechanism, Pitfall 5)"

patterns-established:
  - "Pattern: pure construction primitives isolated before any BaseBatch/DB machinery exists, so equivalence to a proof script can be asserted directly in a unit test"

requirements-completed:
  - "TCL-MD-2"
  - "TCL-MD-3"
  - "TCL-MD-4"
  - "D-01"
  - "D-02"
  - "D-05"
  - "CLAUDE-APR"
  - "REVIEW-H2"
  - "REVIEW-M2"

# Metrics
duration: 20min
completed: 2026-07-27
---

# Phase 167 Plan 02: Cross-Sectional Spread Tracker Module Skeleton Summary

**Five pure construction primitives (decile split, dollar-neutral spread, leg turnover, live cost-hurdle sweep, APR range validation) productionizing cross_sectional_relative_value's proven ranking mechanic, with a deterministic tie-break and a loud non-finite-value guard the proof script never needed.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-27T04:01:00Z
- **Completed:** 2026-07-27T04:21:45Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments

- `services/cross_sectional_spread_tracker.py` — five importable, ruff-clean, DB-free pure
  functions: `decile_legs`, `spread_from_legs`, `one_way_turnover`, `net_spread_by_cost_bps`,
  `validate_construction_config`. Module constants `_TF`, `_FEATURE`, `_CONSTRUCTION_NAME`
  match the plan's `<interfaces>` exactly; `_DEFAULT_BOOTSTRAP_RANDOM_STATE` is imported from
  `services.counterfactual_tracker`, never redefined.
- `tests/unit/test_cross_sectional_spread_tracker.py` — 6 named tests (`test_decile_split`,
  `test_decile_split_tied_and_missing_values`, `test_turnover_across_run_boundary`,
  `test_cost_hurdle_sweep`, `test_config_validation`, `test_spread_is_flat_equal_weight`), all
  passing, no live DB. Full `tests/unit/` suite (664 tests, 3 pre-existing skips unrelated to
  this plan) remains green.
- The Codex-review tied/missing-value edge case (167-REVIEWS.md's "Genuinely open" item 1) is
  now explicit and tested: a tie straddling the exact short-leg cut resolves identically across
  three input orderings (as-given, reversed, seeded shuffle), and a `None`/NaN/+-inf feature
  value raises `ValueError` naming the offending symbol instead of silently corrupting the sort.

## Exact Function Signatures Shipped

These are the contracts Plans 03/04/05 import directly — reproduced verbatim here per the
plan's `<output>` instruction:

```python
def decile_legs(
    ranked_symbols: Sequence[str],
    feature_values: Sequence[float],
    decile_fraction: float,
) -> tuple[list[str], list[str]] | None: ...

def spread_from_legs(
    returns_by_symbol: Mapping[str, float | None],
    long_leg: Sequence[str],
    short_leg: Sequence[str],
) -> float | None: ...

def one_way_turnover(
    prev_long: frozenset[str],
    prev_short: frozenset[str],
    cur_long: frozenset[str],
    cur_short: frozenset[str],
) -> float | None: ...

def net_spread_by_cost_bps(
    gross_spread: float | None,
    turnover: float | None,
    cost_bps: Sequence[int],
) -> dict[str, float] | None: ...

def validate_construction_config(
    decile_fraction: float,
    cost_bps: Sequence[int],
    null_shuffles: int,
    attribution_max_static_r2: float,
) -> None: ...
```

Module constants: `_TF = "15m"`, `_FEATURE = "ctf_momentum"`,
`_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"`.

## Intentional Divergences from the cross_sectional_relative_value Proof Script (for Plan 06 Task 3's write-up)

Two divergences are recorded here, in the module docstring, and in the function docstrings
that own them — Plan 06 Task 3 must enumerate both in the research write-up:

1. **Deterministic `(feature_value, symbol)` tie-break** (design decision 2). The cross_sectional_relative_value script
   ranks via pandas `sort_values(feature_col)` alone, whose tie order depends on input row
   order — acceptable for a one-off script, unacceptable for a persisted, reproducible table.
   The judgment that exact ties are effectively measure-zero rests on `ctf_momentum` being a
   continuous z-scored feature; it would need re-examination before this machinery ever ranks
   a discrete or heavily-quantized feature. Recorded by Codex review as MEDIUM.
2. **Missing/non-finite feature values raise `ValueError`** (design decision 5). The cross_sectional_relative_value script
   never guards against this because its SQL already filters `ctf_momentum IS NOT NULL`; this
   module adds the guard anyway because "should never fire" is exactly the condition worth
   asserting, and because Plan 04's shuffled null re-forms legs from permuted values on a
   separate code path where the same silent-corruption risk exists. Recorded by Codex review
   as HIGH.

Neither divergence changes what cross_sectional_relative_value measured — both are pinned by test and documented as
divergences from the proof script's exact behavior, not silent implementation choices.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create the module skeleton with the pure construction primitives** - `0c1572a4` (feat)
2. **Task 2: Unit tests for the construction primitives, including tied and missing feature values** - `2907396a` (test)

## Files Created/Modified

- `services/cross_sectional_spread_tracker.py` — five pure construction primitives + three
  module constants; no DB, no I/O, no class yet
- `tests/unit/test_cross_sectional_spread_tracker.py` — 6 unit tests, no live DB

## Decisions Made

None beyond what the plan's `<design_decisions>` block already specified — followed the plan
as written, including the two intentional divergences documented above (both were plan
requirements, not deviations discovered during execution).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reworded two docstring mentions of the forbidden cost-hurdle APR key to satisfy the plan's own literal-grep acceptance criterion**

- **Found during:** Task 1 (module skeleton) — running the plan's stated acceptance-criteria
  grep after the initial draft.
- **Issue:** The plan's acceptance criteria require
  `grep -v '^#' services/cross_sectional_spread_tracker.py | grep -c 'alpha.quant.cost_hurdle'`
  to return 0 (Pitfall 5: this module must never read that key from executable code). The
  module docstring and `net_spread_by_cost_bps`'s docstring both explained the divergence by
  naming the literal key `alpha.quant.cost_hurdle.<tf>` in prose, which the grep (correctly,
  since it only excludes `^#` comment lines, not triple-quoted docstrings) counted as 2
  matches.
- **Fix:** Reworded both mentions to describe the same key by its namespace/attribute parts
  (`alpha.quant` namespace, `cost_hurdle` + `.<tf>` suffix) instead of the exact contiguous
  dotted string, preserving the documentation intent without matching the literal grep pattern.
- **Files modified:** `services/cross_sectional_spread_tracker.py`
- **Verification:** `grep -v '^#' services/cross_sectional_spread_tracker.py | grep -c 'alpha.quant.cost_hurdle'` returns 0; re-ran the full Task 1 verification command, still passes.
- **Committed in:** `0c1572a4` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/wording fix to satisfy a stated acceptance criterion)
**Impact on plan:** No functional change — this is a docstring wording fix, not a change to any
function's behavior. No scope creep.

## Issues Encountered

None. The worktree's `.venv` was absent (a known GSD worktree gotcha), so `ruff`/`black`/
`pytest` were invoked via `/home/bg/dev/indicagent/.venv/bin/` (main repo's venv, shared
filesystem) and via `PATH` export for the pre-commit hook's own tool-discovery step.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03's `BaseBatch` orchestration service can import these five functions directly and
  build thin persistence/CLI logic over already-proven, already-tested math.
- Plan 04 (shuffled-ranking null) and Plan 05 (attribution) both depend on `decile_legs`'
  non-finite guard existing on the permuted-feature code path — confirmed present and tested.
- No blockers. All four plan-level verification commands pass:
  `pytest tests/unit/test_cross_sectional_spread_tracker.py -x -q` (6 passed),
  `pytest tests/unit/ -q` (green, no regression),
  `ruff check services/cross_sectional_spread_tracker.py` (exits 0),
  `black --check services/cross_sectional_spread_tracker.py tests/unit/test_cross_sectional_spread_tracker.py` (exits 0).

---
*Phase: 167-cross-sectional-trade-construction*
*Completed: 2026-07-27*

## Self-Check: PASSED

- FOUND: services/cross_sectional_spread_tracker.py
- FOUND: tests/unit/test_cross_sectional_spread_tracker.py
- FOUND: .planning/milestones/v3.1-phases/167-cross-sectional-trade-construction/167-02-SUMMARY.md
- FOUND: 0c1572a4 (Task 1 commit)
- FOUND: 2907396a (Task 2 commit)
- FOUND: d0062c60 (SUMMARY.md commit)
