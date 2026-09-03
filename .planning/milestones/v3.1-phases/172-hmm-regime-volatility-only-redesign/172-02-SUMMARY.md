---
phase: 172-hmm-regime-volatility-only-redesign
plan: 02
subsystem: database
tags: [postgresql, timescaledb, apr, cvr, hmm, regime, schema-migration, asyncpg]

# Dependency graph
requires: []
provides:
  - "migration 307: 8 new feature_vectors columns (regime_volatility family), 4 alpha.hmm_volatility.* APR key pairs, 3-code regime_volatility CVR namespace"
  - "REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES: Ring 1 column-ownership tuple in feature_vector_persistence.py, unioned into _EXTERNALLY_OWNED_COLUMN_NAMES"
  - "ensemble_trainer._META_COLS excludes the new 8-column family from the training feature matrix"
  - "VocabularyDriftAuditor audits the regime_volatility namespace via a bounded, $1-parametrized query"
affects: [172-03, 172-04, 172-05, 172-06, 172-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ring 1 column-ownership single-source-of-truth (copy of REGIME_WRITER_OWNED_COLUMN_NAMES pattern) for a brand-new column family, applied before any compute path writes to it"
    - "APR provenance-tag discipline ([rca_analysis] citing 171-FINAL-VERDICT.md sections) for a deliberately-not-inherited window default (vol_of_vol_window=60, not 20)"
    - "Column-agnostic pure function generalized by outright rename (extract_regime_hmm_codes -> extract_regime_codes) instead of a parallel duplicate, verified single-referrer via grep before renaming"

key-files:
  created:
    - production/migrations/307_regime_volatility_schema_apr_cvr.sql
    - tests/unit/test_feature_vector_persistence_column_ownership.py
    - tests/unit/test_ensemble_trainer_meta_cols.py
    - .planning/todos/pending/287-legacy-regime-probability-columns-leak-into-ensemble-training-matrix.md
  modified:
    - src/intelligence/features/feature_vector_persistence.py
    - services/ensemble_trainer.py
    - src/config/vocabulary_drift.py
    - tests/unit/test_vocabulary_drift_audit.py

key-decisions:
  - "vol_of_vol_window defaults to 60, not the composite model's inherited 20 -- 171-FINAL-VERDICT.md section 6 found this column's real-vs-null margin thin at 20 and solid from 60 up; deliberately not repointing feature.hmm.obs_vol_of_vol_window"
  - "No alpha.hmm_volatility.walk_forward.enabled gate key -- regime_volatility has no legacy corpus to protect, unlike migration 292's default-false gate for the existing regime column; the walk-forward path runs unconditionally"
  - "regime_volatility is a NEW CVR namespace, not a repoint of regime_hmm -- different taxonomy entirely, regime_hmm's rows describe the composite/trend label set being retired"
  - "extract_regime_hmm_codes renamed outright to extract_regime_codes (no alias) -- grep confirmed it was referenced only inside vocabulary_drift.py and its own test file"

requirements-completed: [REQ-1]

# Metrics
duration: 25min
completed: 2026-08-09
---

# Phase 172 Plan 02: Schema/APR/CVR Foundation Summary

**Migration 307 lands the `regime_volatility` schema/APR/CVR foundation and closes both silent-corruption paths (upsert NULL-out, training-matrix leak) that open the instant the new columns exist, before any compute path writes to them.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-09T06:47:00-04:00 (approx, worktree setup)
- **Completed:** 2026-08-09T07:03:19-04:00
- **Tasks:** 3/3 completed
- **Files modified:** 8 (4 created, 4 modified, excluding the SUMMARY itself)

## Accomplishments

- Migration 307 applied and verified idempotent (re-run produced zero row-count change,
  `NOTICE: column already exists, skipping` on every `ADD COLUMN`, `INSERT 0 0` on every
  APR/CVR block): 8 new `feature_vectors` columns, 4 `alpha.hmm_volatility.*` APR key pairs, 3
  `regime_volatility` CVR codes, legacy `regime_hmm` namespace and `regime` column untouched.
- `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` (Ring 1, `feature_vector_persistence.py`) unioned
  into `_EXTERNALLY_OWNED_COLUMN_NAMES`, so `FEATURE_VECTOR_UPSERT_SQL`'s `DO UPDATE SET` can
  never reference the new family -- the exact 2026-07-30 NULL-out incident class, closed before
  any compute path exists to trigger it.
- `ensemble_trainer._get_feature_columns`'s `_META_COLS` imports the same tuple, excluding all 8
  new columns from the training feature matrix so a NULL is never silently imputed to `0.0`.
- `VocabularyDriftAuditor` now audits `regime_volatility` via a `$1`-bound, `<> ''`-filtered
  query mirroring the existing `regime_hmm` entry; `assert_namespace_coverage` recognizes the
  namespace migration 307 seeds.
- 3 new/extended test files, each carrying at least one assertion manually verified to go red
  when its corresponding exclusion is dropped (verified live during authoring, not just
  asserted in a docstring).
- Filed todo 287 (pre-existing, out-of-scope gap: 4/8 legacy `regime` family columns are not
  excluded from the ensemble training matrix today).

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 307, regime_volatility schema plus APR keys plus CVR namespace** -
   `92b65581` (feat)
2. **Task 2: Ring 1 column ownership and the ensemble_trainer training-matrix exclusion** -
   `bd96d64d` (feat, tdd)
3. **Task 3: Register regime_volatility with the vocabulary drift auditor** - `56e0e02c`
   (feat, tdd)

_Note: all three tasks are `type="auto"`; Tasks 2 and 3 carry `tdd="true"` but landed as single
feat commits each (tests + implementation authored together, verified red/green by manual
temporary reversion rather than separate RED/GREEN commits -- see Deviations)._

## Files Created/Modified

- `production/migrations/307_regime_volatility_schema_apr_cvr.sql` - 8 new `feature_vectors`
  columns, 4 `alpha.hmm_volatility.*` APR key pairs, 3-code `regime_volatility` CVR namespace;
  applied and confirmed idempotent
- `src/intelligence/features/feature_vector_persistence.py` -
  `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES` tuple + exclusion union
- `services/ensemble_trainer.py` - `_META_COLS` imports and excludes the new tuple
- `src/config/vocabulary_drift.py` - `regime_volatility` namespace entry;
  `extract_regime_hmm_codes` renamed to `extract_regime_codes`
- `tests/unit/test_feature_vector_persistence_column_ownership.py` - new: tuple shape, exclusion
  from `DO UPDATE SET`, exclusion from `_EXTERNALLY_OWNED_COLUMN_NAMES`, disjointness from the
  legacy family
- `tests/unit/test_ensemble_trainer_meta_cols.py` - new: `_get_feature_columns` excludes the new
  family, ordinary feature columns and pre-existing exclusions survive/remain excluded
- `tests/unit/test_vocabulary_drift_audit.py` - extended: `regime_volatility` query shape,
  T-161-02 no-hardcoded-interval check, coverage pass/raise cases, renamed-function coverage
- `.planning/todos/pending/287-legacy-regime-probability-columns-leak-into-ensemble-training-matrix.md` -
  new, filed per Task 2's explicit instruction

## Decisions Made

- **`vol_of_vol_window` defaults to 60, not 20**: 171-FINAL-VERDICT.md section 6 explicitly
  flags the 20-bar window (used everywhere else in the Phase 171 investigation) as having a thin
  real-vs-null margin, solid from 60 up. Inheriting `feature.hmm.obs_vol_of_vol_window`'s value
  of 20 unexamined would have repeated 172-RESEARCH.md's named Pitfall 1.
- **No `alpha.hmm_volatility.walk_forward.enabled` gate**: unlike migration 292's default-false
  gate (which protects an existing live column from being changed by landing new code),
  `regime_volatility` has no legacy corpus — the walk-forward path is unconditional.
- **New CVR namespace, not a `regime_hmm` repoint**: `regime_volatility`'s `calm`/`elevated`/
  `turbulent` vocabulary is an entirely different taxonomy from `regime_hmm`'s 5-label
  trend-flavored set being retired; conflating them would corrupt the phased-cutover design.
- **`extract_regime_hmm_codes` renamed outright, no alias**: grep across `src/`, `services/`,
  `scripts/`, `tests/` confirmed the symbol was referenced only inside `vocabulary_drift.py` and
  its own test file, satisfying the plan's stated condition for a clean rename over an aliased
  extension.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked worktree `.venv` to the main repo's `.venv`**
- **Found during:** Task 2 commit (first `git commit` attempt)
- **Issue:** This worktree has no `.venv` directory (a known GSD worktree gotcha — the worktree
  is a separate checkout with no independently-provisioned virtualenv). The mandatory
  pre-commit hook (`.githooks/pre-commit`) looks for `ruff`/`black` at
  `${REPO_ROOT}/.venv/bin/{ruff,black}` (falling back to `PATH`, which also had neither
  installed) and blocked the commit with "ruff not found" / "black not found" — a tooling gap,
  not a real lint/format violation (both tools had already been run manually against the main
  repo's `.venv` and reported clean).
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv <worktree>/.venv` — points the worktree at the
  already-installed main-repo virtualenv, installing nothing new. `.venv` is gitignored, so the
  symlink is invisible to git and does not appear in any commit.
- **Files modified:** none tracked (symlink is gitignored)
- **Verification:** subsequent `git commit` ran the real `ruff check`/`black` via the symlinked
  venv and reported "All checks passed" / "Black format applied" for both remaining task commits.
- **Committed in:** N/A (not a tracked file; the fix is filesystem-only, scoped to this worktree)

**2. [Rule 1 - Bug in test design] Rewrote the primary red-test assertion in Task 2's
first test file to target `_EXTERNALLY_OWNED_COLUMN_NAMES` directly instead of the derived SQL
text**
- **Found during:** Task 2 (manual red/green verification of
  `test_feature_vector_persistence_column_ownership.py`, required by the plan's acceptance
  criteria)
- **Issue:** The first draft's `test_regime_volatility_columns_absent_from_upsert_do_update_set`
  asserted the 8 new columns don't appear in `FEATURE_VECTOR_UPSERT_SQL`'s `DO UPDATE SET` — but
  because these 8 columns are (like 4 of the legacy 8) never added to `_ALL_COLUMN_NAMES` at all,
  that assertion is true "by construction" regardless of whether the union into
  `_EXTERNALLY_OWNED_COLUMN_NAMES` exists. Manually deleting the union and re-running the test
  confirmed it stayed green — it would not have caught a real regression.
- **Fix:** Added `test_regime_volatility_columns_in_externally_owned_set`, which asserts
  membership in `_EXTERNALLY_OWNED_COLUMN_NAMES` directly (the actual mechanism
  `_UPDATE_SET_SQL`'s derivation reads from). Manually deleting the union again confirmed this
  new assertion goes red (`AssertionError: ... member(s) {...} are not in
  _EXTERNALLY_OWNED_COLUMN_NAMES ...`); restored the union and re-confirmed both tests green.
  Kept the original SQL-text assertion too, with a docstring explaining why it alone is
  insufficient — it remains a valid second-layer structural check for if these columns are ever
  added to `_ALL_COLUMN_NAMES` in a future plan.
- **Files modified:** `tests/unit/test_feature_vector_persistence_column_ownership.py`
- **Verification:** manual temporary-reversion red/green cycle, described above; final state
  confirmed via `pytest tests/unit/test_feature_vector_persistence_column_ownership.py -q` (5
  passed).
- **Committed in:** `bd96d64d` (Task 2 commit; the red-test verification itself was never
  committed — the file was restored before staging)

---

**Total deviations:** 2 auto-fixed (1 blocking/tooling, 1 test-design bug caught during the
plan's own mandated red/green verification step)
**Impact on plan:** Neither deviation changed scope. The `.venv` symlink is a worktree-local
tooling fix with zero footprint in the commit history. The test-design fix produced a strictly
stronger regression guard than the plan's literal wording implied, without touching any
production code path.

## Issues Encountered

- Two full `tests/unit/` runs (before and after Task 3's edits) each took longer than the
  120-second foreground command timeout and were moved to background automatically; both
  completed with exit code 0 and only the 2 pre-existing, unrelated skips (an HMM-degeneracy
  skip and a non-caller skip, neither touched by this plan). No new failures, no new skips
  introduced.
- The `SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL` verification the plan
  requests ("record both [counts] in the SUMMARY") was only measured once, post-migration
  (26,791,341). No pre-migration measurement was taken because migration 307 contains no
  statement that reads or writes `feature_vectors.regime` (only `ADD COLUMN IF NOT EXISTS` on 8
  new columns, plus `config_schema`/`config_state`/`controlled_vocabulary` INSERTs) — the count
  is invariant by construction, not merely observed to be unchanged. Same value applies both
  before and after.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Schema/APR/CVR foundation is live: `172-03` (vocabulary-parametrized pure functions) and later
  waves can now reference `alpha.hmm_volatility.*` keys, the `regime_volatility` CVR namespace,
  and the 8 `feature_vectors` columns without any further migration work.
- The column-ownership and training-matrix exclusions are proven in place *before* any compute
  path exists to populate the new columns — `172-04`'s compute+write path can land without
  reopening either silent-corruption question.
- Todo 287 (pre-existing legacy training-matrix leak) is filed and does not block any subsequent
  Phase 172 wave — it describes a gap in the `regime` family this phase deliberately does not
  touch.
- No blockers for `172-03`/`172-04` (both wave 1/2, no dependency on anything this plan left
  incomplete).

---
*Phase: 172-hmm-regime-volatility-only-redesign*
*Completed: 2026-08-09*

## Self-Check: PASSED

All 9 created/modified files confirmed present on disk; all 3 task commit hashes
(`92b65581`, `bd96d64d`, `56e0e02c`) confirmed present in `git log --oneline --all`.
