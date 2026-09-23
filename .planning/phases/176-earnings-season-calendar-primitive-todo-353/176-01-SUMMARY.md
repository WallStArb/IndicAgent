---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: 01
subsystem: research
tags: [ic-measurement, bh-fdr, spearman, psycopg3, sql-injection-guard, statistics]

# Dependency graph
requires: []
provides:
  - "Tested pure earnings-season window classifier (days_since_quarter_end/is_earnings_season) that later plans' production implementation is checked against"
  - "SQL identifier allow-list + psycopg.sql.Identifier composition pattern for future analysis scripts"
  - "Live-measured A1_VERDICT=CONFIRMED for up_vol_body_diff (1d), reproducing the origin todo's numbers on the corrected window"
  - "Live-measured SWEEP_VERDICT=CONFIRMED, SWEEP_SURVIVORS (31/57 features) -- the D-01a gate token plans 176-04/176-05/176-06 read"
affects: [176-04, 176-05, 176-06, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "psycopg 3 sql.SQL(...).format(sql.Identifier(...)) for operator-influenced column names, with an allow-list built from dataclasses.fields() -- never f-string SQL"
    - "pg_stat_activity contention pre-check before any corpus-wide query against feature_vectors, with pid != pg_backend_pid() to avoid self-matching"
    - "Sample-size-weighted Fisher-z pooling across symbols before a two-sample IC-difference test, feeding exactly one apply_bh_fdr call over a fixed-size family"

key-files:
  created:
    - scripts/analysis/earnings_season_conditional_ic_reverification.py
    - tests/unit/scripts/test_earnings_season_window.py
    - .planning/phases/176-earnings-season-calendar-primitive-todo-353/176-EVIDENCE-A1.md
  modified:
    - .planning/phases/176-earnings-season-calendar-primitive-todo-353/176-RESEARCH.md

key-decisions:
  - "1d timeframe treated as the canonical/gating measurement for both A1_VERDICT and SWEEP_VERDICT (matches D-04's own primary-effect re-verification timeframe and the origin todo's unqualified numbers); 1h measured and reported as supporting evidence only, not a second competing verdict"
  - "SWEEP_VERDICT=CONFIRMED (not just WEAKER carve-out): 31/57 features cleared BH-FDR + breadth, including up_vol_body_diff itself -- gate decision is PROCEED for plans 176-04/176-05/176-06"
  - "B2 sufficient-N threshold set to 30 rows per partition per symbol, reusing this project's existing sample_size >= 30 setup_performance convention rather than inventing a new threshold"

patterns-established:
  - "Pattern: exactly-one-token documents (A1_VERDICT=/SWEEP_VERDICT=/SWEEP_SURVIVORS=) separate the literal machine-checkable token line from all descriptive prose references to it, so a grep -c check for 'exactly one' occurrence stays meaningful even when a document discusses multiple measurement runs"

requirements-completed: [ES-08]

# Metrics
duration: 18min
completed: 2026-09-23
---

# Phase 176 Plan 01: Assumption A1 Re-verification + Family Sweep Summary

**Live re-measured up_vol_body_diff's earnings-season IC effect on the corrected 14-42-day window (A1_VERDICT=CONFIRMED, reproducing the origin todo's numbers) and extended it to a full 57-feature BH-FDR-corrected vol/volume family sweep with a breadth test, producing SWEEP_VERDICT=CONFIRMED (31 survivors) -- the D-01a gate token that clears plans 176-04/176-05/176-06 to proceed.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-09-23T11:08:11Z
- **Completed:** 2026-09-23T11:25:41Z
- **Tasks:** 3
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments

- A tested, reusable pure-Python window classifier (`days_since_quarter_end`/`is_earnings_season`) exists for later plans' production implementation to be diffed against, with 27 passing unit tests covering every boundary case in the plan (day 13/14/42/43, quarter-end day, year-boundary crossing, leap year).
- Two independent SQL-identifier-safety mechanisms are in place and unit-tested: allow-list membership (`_validated_identifier`, built by construction from `dataclasses.fields(FeatureVector)`) plus `psycopg.sql.Identifier` composition -- verified zero f-string SQL construction anywhere in the script.
- Assumption A1 is no longer an open, unverified claim: live-measured `A1_VERDICT=CONFIRMED` on 1d (ratio 1.94x, n=300,546/629,965), closely reproducing the origin todo's reported second-finding numbers.
- The full 57-feature vol/volume family was swept with the multiple-comparisons denominator fixed in source before measurement, `apply_bh_fdr` called exactly once, and a breadth test (B2 sign-agreement, B3 five-symbol jackknife) applied to every FDR survivor -- `SWEEP_VERDICT=CONFIRMED`, 31/57 features broad and significant, including `up_vol_body_diff` itself.
- Found and fixed a real bug in the contention guard during live execution (see Deviations) before any measurement ran against it.

## Task Commits

Each task was committed atomically:

1. **Task 1: Tested pure window classifier + contention-guarded measurement script**
   - `3c31f9f45` test(176-01): add failing test for earnings-season window classifier + identifier guard
   - `c597ff321` feat(176-01): tested pure earnings-season window classifier + contention-guarded measurement script
2. **Task 2: Family-wide vol/volume sweep with BH-FDR and a breadth test**
   - `7f96a3837` test(176-01): add failing test for family-wide vol/volume sweep + breadth test
   - `aa1a66c49` feat(176-01): family-wide vol/volume sweep with BH-FDR and a breadth test
   - `634a75a6f` fix(176-01): contention guard self-matched its own query text every run (deviation, see below)
3. **Task 3: Run both measurements and write the evidence document**
   - `e97a176d7` docs(176-01): run A1 re-verification + family sweep, write evidence doc

_TDD tasks (1 and 2) each have a RED test commit followed by a GREEN feat commit; no REFACTOR commit was needed (implementation was clean on first pass in both cases)._

## Files Created/Modified

- `scripts/analysis/earnings_season_conditional_ic_reverification.py` - Pure window classifier, SQL-identifier-safety guard, contention pre-check, single-feature and `--sweep` measurement modes, verdict-decision helpers
- `tests/unit/scripts/test_earnings_season_window.py` - 27 tests: window-boundary cases, identifier allow-list rejection, family membership/exclusions, sweep-verdict decision, breadth-test (`_is_broad`) cases
- `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-EVIDENCE-A1.md` - Full measurement record: commands run, single-feature result, 57-row sweep table, gate decision, limitations
- `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-RESEARCH.md` - A1 Assumptions Log row corrected with a dated entry recording both verdict tokens (no other section touched)

## Decisions Made

- **1d as the canonical/gating timeframe:** both `A1_VERDICT=` and `SWEEP_VERDICT=` tokens are reported once, attached to the 1d measurement. 1h was also measured (per Task 3's instruction to run both timeframes) and is reported in full as supporting/robustness evidence, but does not carry a second competing set of tokens -- this matches D-04's own primary-effect re-verification, which was itself a 1d measurement, and the origin todo's numbers, which were reported without a timeframe qualifier.
- **B2 sufficient-N threshold = 30 rows/partition/symbol:** reused this project's existing `sample_size >= 30` `setup_performance` promotion-gate convention (CLAUDE.md) rather than deriving a new threshold specifically for this breadth test.
- **Evidence-doc token discipline:** every place the document discusses a token by name without stating its actual value uses the bare name (`A1_VERDICT`, no trailing `=`); the literal `TOKEN=VALUE` form appears exactly once per token, satisfying the plan's "exactly one" acceptance criteria while still letting the document narrate all four measurement runs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Contention guard self-matched its own query text on every invocation**
- **Found during:** Task 3 (first live execution attempt)
- **Issue:** `_CONTENTION_QUERY`'s literal SQL text contains the substrings it searches `pg_stat_activity` for (`feature_vectors`, `autovacuum`). Since the guard's own in-flight `SELECT` is itself an `active` row in `pg_stat_activity` while it executes, the query matched itself -- producing a false `CONTENTION DETECTED` / `A1_VERDICT=BLOCKED` on the very first run, before any genuine contention was checked.
- **Fix:** Added `AND pid != pg_backend_pid()` to `_CONTENTION_QUERY`, excluding the caller's own backend.
- **Files modified:** `scripts/analysis/earnings_season_conditional_ic_reverification.py`
- **Verification:** Re-ran the same `--tf 1d` command after the fix; contention check passed cleanly and the corpus query ran to completion. Full unit suite (`tests/unit/ -q`) still green after the fix.
- **Committed in:** `634a75a6f` (standalone fix commit, before any of the four measurement commands in the evidence doc)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for correctness -- without this fix, the contention guard would have permanently blocked every measurement run, including legitimate ones with zero real contention. No scope creep; the fix is confined to the guard's own query text.

## Issues Encountered

One genuine (non-bug) contention event was also observed and handled correctly by the guard as designed: an active `autovacuum` worker on a `feature_vectors` chunk fired the BLOCKED path on an early attempt (before the self-match bug above was even discovered, on a retry after the first false positive). Retried seconds later once the worker had completed, per the plan's retry-with-growing-delay instruction -- no forcing of the query through contention.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `176-EVIDENCE-A1.md` carries the machine-checkable `SWEEP_VERDICT=CONFIRMED` / `SWEEP_SURVIVORS=` (31 features) tokens plans 176-04, 176-05, and 176-06 read as their pre-execution gate, per D-01a. Decision recorded explicitly: PROCEED.
- The tested pure window classifier (`days_since_quarter_end`/`is_earnings_season`) is available at `scripts/analysis/earnings_season_conditional_ic_reverification.py` for later plans' production `_days_since_quarter_end`/`earnings_season_flag` implementations to be diffed against for correctness.
- No blockers. The full unit test suite (`tests/unit/ -q`) is green with no regressions from this plan's additions.

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*

## Self-Check: PASSED

All claimed files verified present on disk; all six task commits verified present in `git log`.
