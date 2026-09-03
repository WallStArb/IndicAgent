---
phase: 165-swing-fib-trend-structure-primitives
plan: 03
subsystem: intelligence
tags: [feature-factory, swing-momentum, fibonacci-zones, apr, mutation-testing, nullability]

# Dependency graph
requires:
  - phase: 165-swing-fib-trend-structure-primitives
    provides: "Plan 02's _compute_swing_structure() shared find_peaks/find_troughs pass and its in-memory swing_high_price/swing_low_price/swing_high_indices/swing_low_indices/n_bars intermediates -- this plan's fibonacci helper consumes swing_high_price/swing_low_price directly (D-05)"
provides:
  - "_compute_swing_momentum(): 8 FeatureVector fields off its own self-contained confirm-window extreme detector (_detect_swing_extremes/_dedup_swing_extremes, D-06 Finding B), no atr_val parameter (ATR cancels exactly out of every consuming ratio), two archived implementation-vs-docstring bugs fixed rather than ported"
  - "_compute_fib_zones(): 4 FeatureVector fields consuming Plan 02's swing_high_price/swing_low_price directly, the archived cross-plugin fallback deleted outright (D-05), not reimplemented"
  - "_SWING_MOMENTUM_FALLBACK/_FIB_FALLBACK all-None fallback dicts (D-01), mutation-verified"
  - "tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py: 12 new tests appended (module now has 20 total, shared by Plan 04)"
affects: ["165-04-session-levels"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ratio-based ATR-invariance: a stateless compute helper that only ever consumes amplitude through a same-bar ratio (amps[-1]/mean(amps[-3:])) needs no atr_val parameter at all -- a common positive divisor cancels out exactly, proven at 1e-12 precision rather than assumed"
    - "math.isclose requires rel_tol=0.0 to make abs_tol the binding constraint for O(1)-magnitude values -- the default rel_tol=1e-9 silently dominates a tighter abs_tol=1e-12 bound, found via this plan's own mutation-verification pass"

key-files:
  modified:
    - src/intelligence/feature_factory.py
    - tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py

key-decisions:
  - "Tasks 1+2 (swing momentum compute + fibonacci zones compute, both touching feature_factory.py) committed together as one commit, matching Plan 02's own precedent of collapsing tightly-coupled same-file tasks rather than forcing an artificial hunk-level split; Task 3 (tests) committed separately per the natural file boundary"
  - "struct_accel_bias/swing_amplitude_expanding/in_fib_discount_zone binary-flag assignments required inline '# gradient-exempt' comments to pass the repo's tools/scan_binary_patterns.py pre-commit-adjacent gate -- the existing ALLOWLIST_PATTERNS regex for zone-membership flags ('in_discount') didn't match 'in_fib_discount_zone' due to the inserted '_fib_' substring breaking the match; fixed via the same inline-comment convention already used elsewhere (src/intelligence/trading/cvd_divergence.py) rather than broadening the shared scanner regex (out of this plan's file scope)"
  - "swing velocity/amplitude fields' worked mutation-verification precision bug: math.isclose(b, s, abs_tol=1e-12) without rel_tol=0.0 was NOT actually enforcing 1e-12 precision (default rel_tol=1e-9 dominates for O(1) values) -- caught live during the required mutation-verification pass, fixed in the same task before commit (see Deviations)"

requirements-completed: ["D-01", "D-03", "D-04", "D-05", "D-06", "D-15"]

# Metrics
duration: ~50min
completed: 2026-07-28
---

# Phase 165 Plan 03: Swing Momentum + Fibonacci Zones Summary

**Adds `_compute_swing_momentum()` and `_compute_fib_zones()` to `feature_factory.py`, wired into both `compute()` and `compute_batch()` for 12 of Phase 165's 41 columns (8 swing-momentum + 4 fibonacci), off a self-contained confirm-window extreme detector (D-06 Finding B) and Plan 02's shared swing intermediates (D-05) respectively -- both archived implementation-vs-docstring bugs and the dead ATR divisor fixed rather than ported, mutation-verified.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-07-28
- **Tasks:** 3 (all `type="auto"`, Task 1/2 `tdd="true"`)
- **Files modified:** 2 (1 source, 1 test file)

## Accomplishments
- `_compute_swing_momentum()`: ports `i3_structure/swing_momentum.py`'s amplitude/velocity/energy math over its OWN `_detect_swing_extremes()` confirm-window pass (deliberately NOT the shared `find_peaks`/`find_troughs` pass Plan 02 uses -- D-06 Finding B), reading all nine `feature.swing_momentum.*` APR keys, zero hardcoded magic numbers
- Two archived bugs fixed rather than ported: `amp_mean` now averages the LAST 3 amplitudes (`amps[-3:]`), and `swing_amplitude_expanding` now tests the LAST 3 amplitudes for strict increase -- both match migration 267's binding COMMENT and the archived plugin's own docstring, neither matches what the archived code actually computed
- ATR divisor deleted entirely (no `atr_val`/`close_` parameter): every one of the 8 outputs is derived from a ratio of amplitudes in which a common positive divisor cancels exactly, so the archived ATR-normalize-then-epsilon-guard was a fake-fallback no-op at best and a scale-dependence bug at worst; `test_swing_momentum_atr_invariance` proves this at 1e-12 precision
- `swing_volume_confirmation` (D-15): mean volume over the most recent confirmed swing leg's bar-index span, divided by mean volume over the whole bounded window -- a free column off computation already happening
- `_compute_fib_zones()`: 4 fields consuming Plan 02's `_swing_fields["swing_high_price"]`/`["swing_low_price"]` directly -- the archived `i3.get("swing_high")` cross-plugin fallback is deleted outright (D-05), no rolling-high/low substitute reimplemented; `fib_cluster_fallback_divisor` confirmed referenced nowhere (deliberately dormant, documented at both the field and the use site)
- Zero raw fib price levels persisted (D-04): `fib_236`/`fib_382`/`fib_500`/`fib_618`/`fib_786`/`nearest_fib_level`/`fib_swing_high`/`fib_swing_low` appear nowhere in code; DB query confirms 0 matching `feature_vectors` columns
- Both `compute()` and `compute_batch()` wired for all 12 fields; `compute_batch()` uses a causal pre-slice (`_sm_start = max(0, i - config.swing_momentum_lookback_bars + 1)`) for swing momentum, no new slice needed for fibonacci zones (consumes prices, not arrays)
- 12 new regression tests appended to `test_swing_fib_trend_structure_primitives.py` (module total now 20): non-constant batch, nullability, ATR-invariance, expanding-uses-last-three, velocity-bias numeric encoding (D-03), volume-confirmation free field (D-15), fib-ratio canonical membership, fib ATR-unit distance pin, fib nullability, fib discount-zone boundary flip, live/batch parity, APR-key liveness

## Mutation Check

Three temporary local mutations were applied, tested, and reverted (`git diff --stat` confirmed zero residual diff after all three):

**Mutation 1 -- force both `_compute_swing_momentum()` and `_compute_fib_zones()` to return their fallback dict unconditionally.**
Ran the full test file. Result: 8 of 9 predicted tests failed as expected -- `test_swing_momentum_non_constant_batch`, `test_swing_momentum_atr_invariance`, `test_swing_momentum_expanding_uses_last_three`, `test_swing_momentum_volume_confirmation_free_field`, `test_fib_ratio_is_canonical`, `test_fib_dist_in_atr_units`, `test_fib_discount_zone_boundaries`, `test_swing_momentum_fib_apr_keys_are_live`. `test_swing_momentum_fib_live_batch_parity` did NOT fail -- a correct null result, the same class of finding Plan 02 already documented: `compute()` and `compute_batch()` both call the SAME forced-deterministic function under this mutation, so they trivially agree with each other. Parity's real job (catching a live/batch wiring divergence) is unaffected. `test_swing_momentum_nullability`/`test_fib_nullability_on_degenerate_swing`/`test_swing_momentum_velocity_bias_encoding` also correctly did not fail (they assert all-None/valid-encoding properties that hold trivially true under an all-None forced fallback).

**Mutation 2 -- restore the archived `amplitudes[0] < amplitudes[1] < amplitudes[2]` comparison** (in place of the fixed `amps[-3] < amps[-2] < amps[-1]`).
Ran the full test file. Result: exactly `test_swing_momentum_expanding_uses_last_three` FAILED, proving the test catches the archived-plugin bug shape rather than passing vacuously. All 19 other tests passed.

**Mutation 3 -- restore the archived `+ 1e-9` amplitude-ratio denominator epsilon** (`amps[-1] / (amp_mean + 1e-9)` in place of `amps[-1] / amp_mean`).
First pass with the pre-existing `math.isclose(b, s, abs_tol=1e-12)` assertion: the mutation did NOT cause a failure, despite the actual numeric divergence being ~1.3e-10 (measured directly) -- because `math.isclose`'s default `rel_tol=1e-9` dominates `abs_tol=1e-12` for O(1)-magnitude values, silently masking the intended precision bound. This is a real bug in the test itself, caught by the mutation-verification discipline doing its job. Fixed by adding `rel_tol=0.0` to the assertion (see Deviations below) -- re-ran with the fix in place and Mutation 3 still applied: exactly `test_swing_momentum_atr_invariance` FAILED as required (`swing_amplitude_ratio: base=1.1094889391051463 scaled=1.1094889392325378`, diff ~1.27e-10). Confirmed the CORRECT (unmutated) implementation's cross-scale diff is ~4e-16 (well within `abs_tol=1e-12`), so the fixed assertion has no false-positive risk against real floating-point rounding.

All three mutations reverted; final `git diff` against a pre-mutation backup copy of `feature_factory.py` was empty.

## Task Commits

Each task was committed atomically (Tasks 1+2 share a commit per the file-boundary rationale in Decisions):

1. **Tasks 1+2: `_compute_swing_momentum()` + `_compute_fib_zones()`, wired into `compute()`/`compute_batch()`** - `d54d45ff` (feat)
2. **Task 3: 12 regression tests, mutation-verified** - `fe42f4f1` (test)

## Files Created/Modified
- `src/intelligence/feature_factory.py` - `_SWING_MOMENTUM_FALLBACK`/`_FIB_FALLBACK` (all-None), `_dedup_swing_extremes()`, `_detect_swing_extremes()`, `_compute_swing_momentum()`, `_FIB_RATIOS`, `_compute_fib_zones()`, wired into both `compute()`/`compute_batch()` call sites with the 12 previously-`None` swing-momentum/fib kwargs replaced by real computed values
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` - `_SWING_MOMENTUM_FIELDS`/`_FIB_FIELDS` module-level tuples, 12 new tests, updated module docstring/imports (`dataclasses`, `_compute_fib_zones`, `_compute_swing_momentum`, `_compute_swing_structure`)

## Decisions Made
- Tasks 1+2 committed together (both touch `feature_factory.py` in the same continuous edit pass, same rationale Plan 02 used for its own WIP commit); Task 3 committed separately as the natural file-boundary split
- `# gradient-exempt` inline comments added to three binary-flag assignments (`swing_amplitude_expanding`'s ternary, the `if swing_amplitude_expanding == 1.0` branch, `in_fib_discount_zone`'s ternary) to satisfy `tools/scan_binary_patterns.py` -- these are legitimate categorical/zone-membership flags per the plan's own spec (D-01's "never a plausible-looking number" nullable-discipline is a separate, already-satisfied concern from the binary-pattern scanner's "should this be a continuous gradient" concern), not scoring functions that should be continuous. The existing `in_discount` allowlist regex didn't match `in_fib_discount_zone` due to the inserted `_fib_` substring; fixed via the established inline-comment convention rather than broadening the shared scanner file (out of scope for this plan's `files_modified`)
- Fixed a real precision-check bug in `test_swing_momentum_atr_invariance` mid-mutation-check: `math.isclose(b, s, abs_tol=1e-12)` without `rel_tol=0.0` was not actually enforcing 1e-12 precision. Documented inline in the test with the exact numbers that exposed it

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `math.isclose` default `rel_tol` masked the intended `abs_tol=1e-12` ATR-invariance check**
- **Found during:** Task 3's mandatory mutation-verification pass (Mutation 3)
- **Issue:** `assert math.isclose(b, s, abs_tol=1e-12)` in `test_swing_momentum_atr_invariance` used `math.isclose`'s default `rel_tol=1e-9`, which for O(1)-magnitude values (`swing_amplitude_ratio` ~1.1, `struct_energy` ~0.74) dominates the intended `abs_tol=1e-12` bound (`rel_tol * max(|a|,|b|) ≈ 1.1e-9 >> 1e-12`). The test passed even when the archived `+1e-9` epsilon bug was reintroduced (measured divergence ~1.27e-10), which should have failed a genuine 1e-12 check.
- **Fix:** Added `rel_tol=0.0` to the assertion so `abs_tol=1e-12` is the sole binding constraint. Verified the fix against both the correct implementation (cross-scale diff ~4e-16, passes) and the mutated implementation (diff ~1.27e-10, correctly fails).
- **Files modified:** `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py`
- **Verification:** Re-ran Mutation 3 with the fix in place; `test_swing_momentum_atr_invariance` failed as required. Reverted the mutation; full test file green.
- **Committed in:** `fe42f4f1` (Task 3 commit -- the fix was made before the test file was ever committed, so no separate commit exists for it)

**2. [Rule 3 - Blocking] `tools/scan_binary_patterns.py` gate flagged three legitimate categorical-flag assignments**
- **Found during:** Task 1/2, first attempted `pytest tests/unit/` full-suite run after wiring
- **Issue:** `swing_amplitude_expanding`'s `1.0 if ... else 0.0` ternary, the `if swing_amplitude_expanding == 1.0` branch guard, and `in_fib_discount_zone`'s `1.0 if ... else 0.0` ternary all matched the repo's binary-pattern scanner (`equality_check_continuous_1`/`binary_assignment_1_if_else_0`), which exists to catch scoring functions that should be continuous gradients rather than hard binary cuts. All three are legitimate categorical/zone-membership flags (matching the plan's explicit spec), not scores -- the existing `in_discount` allowlist regex failed to match `in_fib_discount_zone` because of the inserted `_fib_` substring.
- **Fix:** Added inline `# gradient-exempt` comments on all three lines, following the existing convention already used in `src/intelligence/trading/cvd_divergence.py`/`ofi_continuation.py`. Verified black does not reflow the comment away from the flagged line (confirmed by direct re-run).
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `.venv/bin/python tools/scan_binary_patterns.py --json` returns `[]` (zero violations); full `tests/unit/` suite green.
- **Committed in:** `d54d45ff` (Task 1+2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug fix in the test's own precision assertion, 1 Rule 3 blocking-tooling-gate fix)
**Impact on plan:** Both fixes necessary for correctness (the test bug would have let a real regression slip through unnoticed) and for the commit to pass the repo's own pre-commit-adjacent test suite. No scope creep -- both fixes are confined to lines this plan's own work touched.

## Issues Encountered
- The worktree had no `.venv` (a known gotcha per project MEMORY.md -- worktrees spawned without a gitignored `.venv`). Symlinked `.venv` to the main repo's `.venv` (`ln -s /home/bg/dev/indicagent/.venv .venv`) so `ruff`/`black`/`pytest` and the repo's pre-commit hook (which looks for `${REPO_ROOT}/.venv/bin/ruff`) could resolve correctly. This is a local, gitignored, environment-only fix; no tracked files were affected.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 04 (session levels) is independent of this plan's scope -- it builds a new `FeatureCache` session-boundary mutator (D-08/D-09), not touched here
- `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` now has 20 tests across Plans 02-03; Plan 04 appends its own test classes to the same file per the established convention
- 25 of Phase 165's 41 columns now carry real computed values in both live and batch paths (7 swing detection + 6 trend structure from Plan 02, 8 swing momentum + 4 fibonacci from this plan); the remaining 16 (session levels) stay `None` pending Plan 04
- No blockers. Full `tests/unit/` suite green (0 failures, 3 pre-existing unrelated skips), ruff/black clean on every touched file, `tools/scan_binary_patterns.py` clean, mutation-verification discipline satisfied for all three required mutations plus the one that surfaced the test's own precision bug

## Known Stubs
None. 12 of 41 Phase 165 columns now carry real computed values in both live and batch paths; the remaining 16 (session levels: prior-session/overnight/weekly/Asian-session) stay `None` pending Plan 04, per this plan's own scope boundary.

---
*Phase: 165-swing-fib-trend-structure-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

Both key files verified present in the working tree; commits `d54d45ff` and `fe42f4f1` verified present in git log. Mutation-verification was re-run live during SUMMARY authorship (not just recalled from memory): all three required mutations applied, tested, and reverted, with `git diff --stat` confirming zero residual diff after each.
