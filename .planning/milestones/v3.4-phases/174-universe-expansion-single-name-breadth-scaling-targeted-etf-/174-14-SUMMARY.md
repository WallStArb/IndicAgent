---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 14
subsystem: analysis
tags: [correlation-structure, pca, effective-breadth, pre-registration, gate, pandas, numpy]

# Dependency graph
requires: []
provides:
  - "scripts/analysis/universe_expansion_correlation_structure_check.py -- committed, re-runnable correlation-structure diagnostic (pairwise correlation, PC variance share, n_eff, regime-conditioned)"
  - "evaluate_d10_gate() -- D-10's pre-registered pilot gate as code, with both thresholds as literal, non-APR constants, before any pilot data exists"
  - "residualize_against_factor() -- generic single-factor OLS residualization, reported-only SPY view, structurally never wired into the gate"
affects: [174-11-ic-engine-scale-measurement, 174-12-full-scale-down-cap-draw]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-function-core / I/O-shell split for a one-shot analysis script (correlation_structure/evaluate_d10_gate/residualize_against_factor pure, everything else in main() as the shell) -- matches this phase's established DB-batching and accumulate-then-log-once conventions."
    - "Pre-registered gate as literal module constants with an explicit non-APR justification comment, not a config_state key -- distinct from this project's default APR-everything rule; the exemption itself is documented inline."

key-files:
  created:
    - scripts/analysis/universe_expansion_correlation_structure_check.py
    - tests/unit/scripts/test_universe_expansion_correlation_structure_check.py
  modified: []

key-decisions:
  - "D-10's thresholds (_D10_GATE_UNCONDITIONAL_MAX=0.10, _D10_GATE_HIGH_BEAR_MAX=0.30) and the coverage constant (_MIN_DAILY_COVERAGE=0.95) are literal module constants, not APR keys -- an explicit non-APR justification comment is in the code, since APR's default-everything rule would otherwise apply."
  - "evaluate_d10_gate() takes dict-shaped correlation_structure() results (or None) rather than raw floats, so a missing/None regime result fails closed with a named reason instead of requiring the caller to pre-extract a float that might not exist."

requirements-completed: [D-10]

# Metrics
duration: 25min
completed: 2026-09-15
---

# Phase 174 Plan 14: Correlation-structure diagnostic + D-10 pre-registered gate Summary

**Committed, unit-tested Python script that reproduces the published single-name-book correlation baseline exactly and encodes D-10's two pilot-gate thresholds as literal, pre-registered code constants.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-09-15T20:45:00Z
- **Completed:** 2026-09-15T21:10:31Z
- **Tasks:** 2 completed
- **Files modified:** 2 (both new)

## Accomplishments
- Turned the ad-hoc analysis behind `docs/research/phase174-single-name-book-correlation-structure-2026-09-15.md` into committed, re-runnable code (`scripts/analysis/universe_expansion_correlation_structure_check.py`), structured as three pure statistics/gate/residualization functions around a thin DB-fetch/print/JSON-output shell.
- Verified the script reproduces the published baseline **exactly** when run against `--tag single_name_equity` against the live corpus (see Reproduction Tables below) -- no methodological divergence found, no tolerance widening needed.
- Encoded D-10's two pre-registered thresholds (unconditional avg pairwise corr <= 0.10, `high_bear`-conditioned <= 0.30) as literal, non-APR module constants, evaluated by `evaluate_d10_gate()`, with a distinct process exit code (0 pass / 2 gate-failed / 1 error) so a caller cannot misread a failing gate as either a pass or an infrastructure problem.
- Added a reported-only SPY-residualized view (`residualize_against_factor()`) for interpretability, with a structural test (case 15) proving no code path can ever feed a residualized number into the gate.
- 17 unit tests against synthetic data with analytically known answers, covering all 5 statistics scenarios, all 7 gate boundary scenarios, and both residualization scenarios from the plan. Full `tests/unit/` suite (10k+ tests) stays green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the diagnostic and reproduce the published baseline** - `ec84788fb` (feat)
2. **Task 2: Unit coverage for the statistics and both gate thresholds** - `d81cf63b8` (test)

**Plan metadata:** committed alongside this SUMMARY.

## Files Created/Modified
- `scripts/analysis/universe_expansion_correlation_structure_check.py` - correlation-structure diagnostic: `correlation_structure()`, `evaluate_d10_gate()`, `residualize_against_factor()` (pure functions) plus cohort resolution (`--tag`/`--symbols`/`--symbols-file`), batched daily-close fetch from `market_data_ohlcv_tradeable`, coverage filter, `market_regimes` join, raw + SPY-residualized table printing, `--json-out`, `--gate` exit-code contract.
- `tests/unit/scripts/test_universe_expansion_correlation_structure_check.py` - 17 synthetic-data test cases, zero DB/network.

## Decisions Made
- **D-10 thresholds and the coverage constant are literal, non-APR constants** (rather than `config_state` keys): a pre-registered gate's entire epistemic value comes from being immutable after the result is seen, and an APR key is by construction editable at runtime from a psql prompt with no commit or reviewable diff. This is a deliberate, documented exception to CLAUDE.md's default APR-everything rule -- the code comment cites D-10's own wording ("fixed here before any pilot data exists -- not adjustable after seeing the result").
- **`evaluate_d10_gate()` accepts `correlation_structure()`-shaped dicts (or `None`), not raw floats** -- this makes "the regime produced no data" a first-class, fail-closed input shape (`None`) rather than requiring every caller to remember to check for a missing key before calling the gate.
- **1d cell-count coverage denominator = the union of all fetched trading dates across the cohort**, not a fixed calendar-day count -- matches the baseline document's method exactly and is what let the reproduction match to 4 decimal places.

## Deviations from Plan

None - plan executed exactly as written. The one candidate deviation was cosmetic: the acceptance criteria's literal-substring greps (`config_state|ConfigService` returning 0, `rankdata(X, axis=0)` citation) required two small wording adjustments to explanatory comments/docstring prose so the reasoning stayed accurate while satisfying the exact grep patterns -- no functional code change, folded into Task 1's commit rather than tracked as a separate deviation.

## Issues Encountered
- Initial version of unit test case 15 (residualized-value-never-feeds-the-gate structural guard) used a broad "any line containing both `evaluate_d10_gate` and `resid`" check, which false-positived on the module's own docstring prose (a sentence mentioning both `evaluate_d10_gate()` and "SPY-residualized" in the same line, `resid` being a substring of "residualized"). Fixed before committing by scoping the guard to actual `evaluate_d10_gate(...)` call-site arguments via regex extraction, matching the plan's own acceptance-criteria grep pattern (`evaluate_d10_gate(residual`) more precisely than a bare pairwise substring check would have.
- This worktree had no local `.venv` (worktrees don't carry Python virtualenvs); ran all verification via the main checkout's `.venv` at `/home/bg/dev/indicagent/.venv` with its `bin/` prepended to `PATH` for the pre-commit hook's ruff/black checks. No code impact, noted per the project's known worktree-venv gotcha.

## Reproduction Tables

Ran `.venv/bin/python scripts/analysis/universe_expansion_correlation_structure_check.py --tag single_name_equity --json-out ...` against the live corpus. Cohort: 128 `single_name_equity`-tagged symbols, 117 retained after the 95%-coverage filter, dropped list matches the baseline exactly: `BNTX, COIN, CRWD, CTVA, DOCS, DOW, GEV, LIN, ODFL, RVMD, UBER`.

### Raw pairwise daily-return correlation (published baseline vs. reproduced)

| Regime | N | Published Avg | Reproduced Avg | Published n_eff | Reproduced n_eff |
|---|---|---|---|---|---|
| unconditional | 117 | 0.3164 | 0.3164 | 3.10 | 3.10 |
| high_bear | 117 | 0.4789 | 0.4789 | 2.07 | 2.07 |
| mid_bull | 117 | 0.1423 | 0.1423 | 6.68 | 6.68 |
| low_bull | 117 | 0.1731 | 0.1731 | 5.55 | 5.55 |
| high_bull | 117 | 0.3020 | 0.3020 | 3.25 | 3.25 |
| high_neutral | 117 | 0.2030 | 0.2030 | 4.77 | 4.77 |
| mid_bear | 117 | 0.3213 | 0.3213 | 3.06 | 3.06 |
| mid_neutral | 117 | 0.2061 | 0.2061 | 4.70 | 4.70 |
| low_neutral | 117 | 0.1985 | 0.1985 | 4.87 | 4.87 |
| low_bear | 117 | 0.3111 | 0.3111 | 3.15 | 3.15 |

Every regime row reproduced to 4 decimal places -- an exact match, not merely "within tolerance." PC1 share (unconditional): published 33.50%, reproduced 33.50%.

### SPY-residualized correlation (measured-during-planning reference vs. reproduced)

| | Reference (planning) | Reproduced | Tolerance | Within? |
|---|---|---|---|---|
| Unconditional avg pairwise corr | 0.0417 | 0.0417 | ±0.01 | yes (exact) |
| `high_bear` avg pairwise corr | 0.0334 | 0.0334 | ±0.01 | yes (exact) |
| Unconditional n_eff | 20.05 | 20.05 | ±2.0 | yes (exact) |
| `high_bear` n_eff | 23.99 | 23.99 | ±2.0 | yes (exact) |
| Mean SPY beta | 0.987 | 0.9870 | ±0.05 | yes (exact) |
| Std SPY beta | 0.366 | 0.3664 | -- | yes |
| Min / Max SPY beta | 0.358 / 2.335 | 0.3584 / 2.3347 | -- | yes |

No methodological divergence was found -- the fill rule, `min_periods`, coverage denominator, and regime-join date-cast timezone handling (the four candidates the plan flagged) all matched the baseline method on the first run.

### D-10 gate evaluated against this baseline (informational, expected to fail)

Running `--gate` against the existing 117-name large/mega-cap book correctly **FAILS** both D-10 thresholds (unconditional 0.3164 > 0.10, `high_bear` 0.4789 > 0.30, exit code 2) -- this is the expected, structural result the gate exists to detect: today's book does not clear D-10, which is exactly why D-10's actual test subject is the down-cap pilot sample (Plan 12), not this baseline.

## Known Stubs

None.

## Threat Flags

None -- this plan introduces only read-only queries against existing tables (`market_data_ohlcv_tradeable`, `market_regimes`, `instrument_tags`), matching the threat model's own disposition list. No new endpoints, auth paths, or schema changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- D-10's gate is implemented and pre-registered in git before any pilot data exists, ready for Plan 12's actual pilot run to call it with `--gate --tag <pilot_cohort_tag>` (or `--symbols-file`) once the pilot sample is onboarded and backfilled 1d-only.
- No blockers. The one thing a downstream plan should know: this script's `--gate` evaluation intentionally FAILS when pointed at the existing large/mega-cap book (confirmed above) -- that is correct behavior, not a bug to "fix" before Plan 12 runs it against the actual down-cap pilot cohort.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: scripts/analysis/universe_expansion_correlation_structure_check.py
- FOUND: tests/unit/scripts/test_universe_expansion_correlation_structure_check.py
- FOUND commit: ec84788fb
- FOUND commit: d81cf63b8
