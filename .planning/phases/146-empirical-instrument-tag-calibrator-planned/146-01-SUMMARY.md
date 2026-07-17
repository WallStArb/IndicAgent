---
phase: 146-empirical-instrument-tag-calibrator
plan: 01
subsystem: database
tags: [postgresql, taxonomy, data-cleanup, tag_vocabulary, instrument_tags, pytest]

# Dependency graph
requires: []
provides:
  - "credit_cycle merged into credit_risk (migration 237) — 8 holders migrated, 0 rows lost"
  - "housing_cycle deleted (self-regression tautology)"
  - "spread_leg evidence contract repaired — 18 rows, all with a structured, symmetric pair"
  - "tests/unit/test_spread_leg_pair_validity.py — CI guard against future spread_leg regressions"
  - "glossary.md documents the credit_cycle banned alias and the T7 category-is-display-only note"
affects: [146-02, 146-03, 146-04, 146-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "spread_leg evidence.pair as string-or-array JSONB, normalized by a shared _normalize_pairs() helper — hub instruments (SPY, FXY, FXE, VYM) legitimately pair against multiple legs, not an arbitrary pick-one simplification"
    - "Live-DB-backed unit test (psycopg2, skip-on-unreachable) for a data-contract check that a filesystem grep cannot express — modeled on test_market_data_ohlcv_boundary.py's allow-list shape but reading DB state instead of source files"

key-files:
  created:
    - production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql
    - tests/unit/test_spread_leg_pair_validity.py
  modified:
    - docs/foundation/glossary.md

key-decisions:
  - "credit_cycle merge required inserting NEW credit_risk rows for 6 symbols (IWM, PFF, XHB, XLF, XLY, XRT) that had credit_cycle but no credit_risk row at all — the plan's 'no weight bump needed' language covered only the HYG/LQD collision case; the other 6 would have silently lost their credit signal without the NOT EXISTS guard already specified in the plan's action text"
  - "spread_leg's evidence.pair is string-or-array JSONB, not always a single string — SPY, FXY, FXE, and VYM are legitimate multi-partner hubs (derived from each partner's own pre-existing `reason` prose); forcing a single pick-one partner would have silently orphaned a pre-existing relationship, violating CLAUDE.md's 'never drop data that could contain signal'"
  - "11 of the 28 original spread_leg rows had non-NULL evidence but NO `pair` key (only free-text `reason` prose) — task 1's acceptance criteria (evidence IS NOT NULL) alone would have missed this; task 2's test explicitly checks for a missing `pair` key, not just NULL evidence, so all 11 were backfilled with a structured pair too"

patterns-established:
  - "Banned-alias glossary section: retired tags get a permanent entry naming the merge/deletion target and the phase/migration that did it, so the exact defect isn't silently reintroduced under the old name"

requirements-completed: [TAG-03]

# Metrics
duration: 25min
completed: 2026-07-17
---

# Phase 146 Plan 01: Wave 0 Taxonomy Cleanup Summary

**Migration 237 merges credit_cycle into credit_risk, deletes the self-regression tautology housing_cycle, and repairs all 28 spread_leg rows to a symmetric, structured evidence.pair contract enforced by a new CI test.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-17T04:10:00-04:00 (approx)
- **Completed:** 2026-07-17T04:14:08-04:00
- **Tasks:** 3/3
- **Files modified:** 3 (1 created SQL migration, 1 created test, 1 modified doc)

## Accomplishments
- Applied migration 237 live against the `indicagent` DB: `credit_cycle` and `housing_cycle` fully retired from both `tag_vocabulary` and `instrument_tags` (verified 0 rows post-migration)
- Repaired `spread_leg`'s evidence contract end-to-end: 28 original rows → 18 remaining, every one with a `pair` key that resolves to a real `instruments.symbol` and reciprocates symmetrically (verified via a new CI test, not just a one-time SQL check)
- Documented both taxonomy changes in `glossary.md` so the retired tags and the category-is-display-only measurement contract are discoverable without re-deriving Phase 146's decisions

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 237 — credit merge, housing_cycle delete, spread_leg evidence backfill** - `a77bf903` (feat)
2. **Task 2: spread_leg pair-validity + symmetry data-contract test** - `e2a8c114` (test)
3. **Task 3: glossary.md — credit_cycle banned alias + T7 category-overlap note** - `657056df` (docs)

_Plan metadata commit is created by the orchestrator after wave merge, not by this worktree agent._

## Files Created/Modified
- `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql` - credit_cycle→credit_risk merge (with a defensive INSERT for the 6 symbols missing a credit_risk row), housing_cycle deletion, spread_leg evidence backfill/insert/delete (18 final rows)
- `tests/unit/test_spread_leg_pair_validity.py` - two live-DB-backed tests: pair-validity (every `pair` resolves to `instruments.symbol`, no missing `pair` key) and symmetry (reciprocal reference check, handles both string and array `pair` shapes)
- `docs/foundation/glossary.md` - "Tag category taxonomy" note (T7: category is display-only, one-factor-series-one-tag collision rule) before the six category definitions; "Banned aliases" section after `macro_driver` documenting `credit_cycle` (merged) and `housing_cycle` (deleted)

## Decisions Made

- **credit_cycle merge's real scope was broader than the plan's headline claim.** The plan's action text said "No credit_risk weight bump is needed — verified live that credit_risk already carries >= credit_cycle's weight on both holders (HYG, LQD)" — true for those two, but 6 of the 8 credit_cycle holders (IWM, PFF, XHB, XLF, XLY, XRT) had no credit_risk row at all. The plan's own defensive-guard instruction ("If any credit_cycle holder lacks a credit_risk row, INSERT ... guard with WHERE NOT EXISTS") already covered this correctly, and the migration implements it as written — flagging here because the plan's summary-level framing undersold how many symbols actually needed the guard to fire (6 of 8, not a rare edge case).
- **spread_leg's `pair` field is string-or-array JSONB**, not always a single string. Four symbols (SPY, FXY, FXE, VYM) are legitimate multi-partner hubs: e.g. SPY is the broad-market leg for both IPO and EZU. A single pick-one string would have forced dropping one of two pre-existing, independently-evidenced relationships to satisfy the symmetry test — instead both partners are preserved as a JSON array, and `_normalize_pairs()` in the test handles both shapes uniformly. This is a data-integrity call (CLAUDE.md: "never drop data that could contain signal"), not a scope expansion — no new table, no new code consumer, same JSONB `evidence` column the plan specified.
- **11 of 28 original spread_leg rows had non-NULL evidence but no `pair` key** — only free-text `reason` prose (e.g. CWB: `{"reason": "CWB/LQD convertible vs straight-credit spread"}`). Task 1's acceptance criteria only checked `evidence IS NULL`, which these rows already satisfied trivially; but Task 2's test (and D-09's actual intent — "evidence->>'pair' resolving to a valid instruments.symbol") requires a structured `pair` key on every row. All 11 were backfilled with `pair` extracted from their own `reason` text via the `||` JSONB merge operator, preserving the original `reason` prose unchanged.
- **The `credit_risk` INSERT SELECT syntax check:** the plan's `weight >= 0.0 AND weight <= 1.0` CHECK constraint required no fixup — every credit_cycle weight being copied to a new credit_risk row was already in `[0.6, 0.9]`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] spread_leg's mechanically-recoverable-pair count was undercounted by the plan's own framing due to hub-node overlap not surfaced in CONTEXT.md/RESEARCH.md**
- **Found during:** Task 1 (writing migration 237)
- **Issue:** CONTEXT.md/RESEARCH.md list "4 mechanically recoverable pairs" (LQD←CWB, TLT←EDV, SPY←IPO/EZU, SCHD←VYM) as if each target symbol reciprocates to exactly one partner. Live evidence-text tracing showed SPY, FXY, FXE, and VYM are each named by more than one other row's `reason` prose (e.g. both IPO and EZU independently name SPY; both FXA and FXE independently name FXY). A naive single-partner backfill would have made the just-added `test_spread_leg_pairs_are_symmetric` test fail for one side of each hub, or silently discarded one of the two pre-existing relationships.
- **Fix:** Implemented `pair` as string-or-array JSONB for the 4 hub nodes (SPY, FXY, FXE, VYM) so both/all partners are preserved and reciprocate correctly; verified full pairwise symmetry by hand before writing the migration (documented in the migration's header comment).
- **Files modified:** `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql`, `tests/unit/test_spread_leg_pair_validity.py`
- **Verification:** `test_spread_leg_pairs_are_symmetric` passes against the live post-migration DB; manual re-derivation of the full 18-row adjacency graph confirmed every edge reciprocates.
- **Committed in:** `a77bf903` (Task 1), `e2a8c114` (Task 2)

**2. [Rule 2 - Missing critical] Added `pair` key to 11 already-evidenced rows that the plan's literal acceptance criteria would have missed**
- **Found during:** Task 1 (writing migration 237)
- **Issue:** Task 1's acceptance criteria ("`evidence IS NULL` returns 0") is satisfiable while still leaving evidence blobs with only a `reason` string and no `pair` key — which would fail Task 2's actual data-contract test (`evidence->>'pair'` resolving to a valid symbol) and defeat D-09's stated purpose.
- **Fix:** Added a `pair` key (via JSONB `||` merge, preserving the existing `reason` text) to all 11 rows that already had non-NULL evidence: CWB, EDV, EZU, FXA, FXE, FXY, IPO, MCHI, SDOG, SPHB, VYM.
- **Files modified:** `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql`
- **Verification:** `test_every_spread_leg_pair_resolves_to_a_valid_symbol` passes; manual `SELECT symbol, evidence FROM instrument_tags WHERE tag='spread_leg'` confirms all 18 remaining rows carry a `pair` key.
- **Committed in:** `a77bf903`

---

**Total deviations:** 2 auto-fixed (1 bug-class undercounted-partner-cardinality fix, 1 missing-critical pair-key backfill)
**Impact on plan:** Both fixes are within D-09's stated scope (repair spread_leg's evidence contract completely, don't fabricate, don't drop data) — no new table, no new code consumer, no schema change. No scope creep.

## Issues Encountered

- **Worktree has no `.venv`** (known GSD worktree risk — see project memory `feedback_gsd_worktree_venv_missing.md`). Resolved by invoking the main repo's `/home/bg/dev/indicagent/.venv/bin/pytest` (and prepending it to `PATH` for the pre-commit hook's ruff/black checks) rather than a local `.venv/bin/pytest`, which does not exist in this worktree.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The `tag_vocabulary`/`instrument_tags` taxonomy is clean: `credit_cycle` and `housing_cycle` are fully retired, `spread_leg` has a sound, CI-enforced evidence contract. Plans 02-05 (Wave 1's schema migration + TagCalibrator service) can now build against a real, deduplicated vocabulary without inheriting these two known defects.
- No blockers. The full `tests/unit/` suite is green (2 pre-existing, unrelated skips only).

---
*Phase: 146-empirical-instrument-tag-calibrator*
*Completed: 2026-07-17*

## Self-Check: PASSED

All claimed files exist (`production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql`,
`tests/unit/test_spread_leg_pair_validity.py`, `docs/foundation/glossary.md`, this SUMMARY.md)
and all claimed commit hashes (`a77bf903`, `e2a8c114`, `657056df`, `c1e317db`) are present in
`git log --oneline --all`.
