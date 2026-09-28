---
phase: 185-daily-data-foundation
plan: 07
subsystem: bars
tags: [d24-seam-audit, d21-splits, d23-disputed-dates, d17-venue-study, preregistration, pure-functions]

# Dependency graph
requires: [185-01]
provides:
  - src/intelligence/bars/seams.py: Seam + find_seams (constant-ratio run detection over stored vs fresh closes, APR-supplied rel_tol/min_run, no defaults)
  - src/intelligence/bars/corporate_actions.py: SplitInference + infer_split (rational p/q snap, p and q <= 50), DisputedDate + disputed_dates + unknown_return_mask (the D-23 conservative dispute rule)
  - src/intelligence/bars/venue_study.py: NameEvaluation + VenueStudyResult + evaluate_name + evaluate_study (D-17 statistics judged against the pre-registration)
  - config/bars/venue_study_preregistration.json: the committed D3 pre-registration (selection rule, seed 185017, windows, routes, both criteria, verdict, effect)
affects: [185-13, 185-15, 185-22, 186]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Greedy constant-ratio runs: a day joins a run only if the run's max/min ratio spread stays within rel_tol, so a 0.3 percent daily drift can never accumulate into a seam the way an adjacent-days-only test would allow"
    - "Pre-registration before code: the thresholds file is committed alone first, so git log -1 --format=%cI on it is the tamper-evidence plan 13 checks against its first study request"

key-files:
  created:
    - src/intelligence/bars/seams.py
    - src/intelligence/bars/corporate_actions.py
    - src/intelligence/bars/venue_study.py
    - config/bars/venue_study_preregistration.json
    - tests/unit/bars/test_seams.py
    - tests/unit/bars/test_corporate_actions.py
    - tests/unit/bars/test_venue_study.py
  modified: []

key-decisions:
  - "Pre-registration commit ac36ad099 touches only config/bars/venue_study_preregistration.json and predates every line of venue_study code (T-185-07-01); registered_at is its commit date 2026-09-28T02:17:04Z"
  - "Seam semantics fixed in the docstring: run end = corporate-action date (last day on the old scale), factor = run median ratio, band width = max/min - 1 <= rel_tol, per-day differs-from-1 beyond rel_tol; runs are greedy left-to-right and non-overlapping"
  - "infer_split refuses a snap to 1/1 (p == q) and any gap beyond ratio_snap_tol: both leave the seam unexplained (None) rather than recording a fake split (T-185-07-02)"
  - "The disputed span reaches one session below first_date because a return entered at the session before the earliest possible ex-date already spans the event (drop between that close and the next open); the pair shape is exactly Reconciliation.near_misses so the D5 writer feeds it directly (T-185-07-03)"
  - "Missing venue days count against both criteria, never dropped; listing venue 'has the most volume' means strictly greater than every other route present that day; a wholly absent listing venue reports 0.0 shares"
  - "NASDAQ primaryExchange normalizes to the ISLAND routing code inside evaluate_name (mirror of ibkr.py's _VENUE_ALIASES; the pure module must not import the provider)"
  - "evaluate_study's structural gates (min_names, min_per_venue per selected venue) force passed False with reason strings; the pre-registered verdict formula applies to a structurally valid study"
  - "_MAX_SPLIT_TERMS = 50 stays a module constant: it is the plan interface's definitional bound separating real split ratios from arbitrary rationals, not an operator tunable"

patterns-established:
  - "Tests load the committed pre-registration JSON instead of restating thresholds, so code and pre-registered numbers cannot drift apart silently"

requirements-completed: [D-17, D-21, D-23, D-24]

# Metrics
duration: about 0.5 h including context read and self-review
completed: 2026-09-28
---

# Plan 185-07: seams, splits, disputed dates and the D3 pre-registration summary

**The seam audit, split inference and the disputed-date rule are decided by tested pure functions (synthetic 2:1, 1:8 and 20:1 found at the right date; MRNA/ALMS event shapes and drift produce none), and the D3 venue study is pre-registered in its own git commit before any study code or fetch exists**

## Performance
- **Duration:** about 0.5 h (task 1 RED/GREEN, prereg commit, task 2 RED/GREEN, self-review refactor)
- **Completed:** 2026-09-28
- **Tasks:** 2

## Acceptance verified
- tests/unit/bars/ green (103 tests total: 10 seams, 10 corporate actions, 10 venue study, 73 prior); full `.venv/bin/pytest tests/unit/ -q` green (2 pre-existing unrelated skips)
- `grep -nE "def find_seams\(.*=|rel_tol: float =|min_run: int =" src/intelligence/bars/seams.py` returns nothing (no defaulted thresholds; rel_tol/min_run/ratio_snap_tol arrive from APR via plans 15 and 22)
- `git log --oneline -- config/bars/venue_study_preregistration.json` shows exactly one commit (ac36ad099) touching only that file; the JSON carries version, registered_at, rationale, selection (seed 185017, min_names 30, min_per_venue 8), windows, routes, criterion_a, criterion_b, verdict and effect; `min_names >= 30` asserted
- No asyncpg/psycopg/ConfigService/os.environ in any new module; services/dividend_event_writer.py, src/intelligence/research/ and src/intelligence/statistics/ byte-identical
- No migration this plan (185-07 owns none; the threshold.seam.* APR keys belong to plans 15 and 22)

## Task commits
1. **Task 1 RED: seam, split and disputed-date behaviors** - `8c35ef5d8`
2. **Task 1 GREEN: find_seams + infer_split + disputed dates** - `6dc241d78`
3. **Task 2 pre-registration (own commit, before the code)** - `ac36ad099`
4. **Task 2 RED: venue study behaviors** - `a93df1703`
5. **Task 2 GREEN: evaluate_name + evaluate_study** - `551eb6d63`
6. **Self-review cleanup: named listing volume in the max scan** - `7799bf6a8`

**Plan metadata:** this commit

## Deviations from plan
- find_seams additionally raises ValueError on non-finite or non-positive closes and on rel_tol <= 0 or min_run < 1 (the interface names only the length mismatch): a zero close would make the ratio silently inf/NaN and invent or hide a seam. unknown_return_mask likewise validates calendar sortedness, index bounds and array lengths (a wrong calendar would silently mark the wrong returns)
- infer_split excludes the p == q candidate: a factor that snaps to 1 is not a split, so the seam stays unexplained instead of producing a zero-effect kind
- The venue alias table is mirrored as a two-entry module constant rather than imported from src/providers/ibkr.py, keeping the module pure (no ib_async anywhere near it); documented as a mirror
- The 0.3 percent daily drift no-seam behavior depends on rel_tol/min_run passed by the caller; the test pins rel_tol 0.01 and min_run 5, the values the audit is expected to seed

## Issues encountered
- None.

## User setup required
None.

## Next phase readiness
- Plan 13 (D3 study fetch) loads config/bars/venue_study_preregistration.json, applies the selection rule (sha256(seed||symbol) ascending over eligible names), fetches SMART plus the five venue routes, and judges with evaluate_name/evaluate_study per timeframe; it must refuse to run if the prereg commit's %cI postdates its first request's requested_at
- Plans 15/22 call find_seams then infer_split with threshold.seam.rel_tol / min_run / ratio_snap_tol from APR (they own seeding those keys); unexplained seams flow to the D7 audit's unexplained-seams fact
- The D5 writer (plan 22) feeds reconcile().near_misses pairs straight into disputed_dates; the research reader consumes unknown_return_mask so no return crossing a dispute reaches a target

## Self-Check: PASSED
All seven key files present on disk; all six task commits found in git log; prereg commit ac36ad099 touches only the JSON file.

---
*Phase: 185-daily-data-foundation*
*Completed: 2026-09-28*
