---
phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s
plan: 02
subsystem: alpha (IC engine)
tags: [ic-engine, significance-testing, broadcast-features, concept-registry, vulture, ci-enforcement]

# Dependency graph
requires:
  - phase: none (wave 1, no depends_on)
    provides: n/a
provides:
  - "ic_engine.py with the bespoke CONTEXT_FEATURES daily-cadence significance path deleted (D-01)"
  - "A CI-enforced regression test guarding against reintroducing a hand-maintained broadcast frozenset"
  - "Two filed, ranked follow-up todos (354, 355) capturing the deletion's downstream consequences"
affects: [173-03, 173-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Executable pre-deletion gate: a live DB query proving zero dependent rows exist, run in the
       same execution that performs the deletion, hard-stopping on any nonzero result -- not a
       planning-time note."
    - "Source-introspection regression test (inspect.getsource + string-absence assertions) as the
       CI enforcement mechanism against a specific named anti-pattern reintroducing itself."

key-files:
  created:
    - .planning/todos/pending/354-context-features-intraday-autocorrelation-per-symbol-pooled-cell.md
    - .planning/todos/pending/355-context-features-writer-orphaned-after-phase-173.md
  modified:
    - services/ic_engine.py
    - tests/unit/test_ic_engine_compute_split.py
    - tests/unit/test_hac_ic_sharpe.py
    - tests/unit/test_ic_engine_dual_write_symbol_hmm.py
    - tests/unit/test_ic_engine_fingerprint.py
    - tests/unit/test_ic_engine_lifecycle_hook.py
    - .planning/todos/PRIORITIES.md

key-decisions:
  - "Pre-deletion gate query (feature_ic_scores WHERE regime_label_source='context_features')
     returned 0 at 2026-08-25T16:02:30Z, in this execution -- deletion proceeded as authorized."
  - "min_obs_daily removed from _COMPUTATIONAL_CONFIG_FIELDS, deliberately moving apr_snapshot_key
     and invalidating every cell fingerprint corpus-wide -- intended, not a fingerprint bug."
  - "APR key alpha.ic.min_obs_daily_features left in config_schema/config_state untouched -- an
     unread key is harmless; no migration filed to delete it."
  - "354/355 filed at the next free numbers (352 was the actual highest pending/completed number
     at execution time, not 353 as the plan's planning-time snapshot stated) -- re-verified live
     per the plan's own instruction before filing."

patterns-established:
  - "Source-introspection regression test naming: test_<function>_has_no_<retired_mechanism>_path,
     asserting absence of every retired symbol string (not just the primary one) so a partial
     reintroduction (e.g. just the config field, without the frozenset) still trips CI."

requirements-completed: [D-01]

duration: 25min
completed: 2026-08-25
---

# Phase 173 Plan 02: Delete CONTEXT_FEATURES Daily-Cadence Significance Path Summary

**Deleted `ic_engine.py`'s bespoke `CONTEXT_FEATURES` daily-cadence significance path (231
redundant per-symbol tests of the same macro time series) after a live pre-deletion gate proved
zero dependent rows existed, added a CI-enforced regression test, and filed the two downstream
consequences as ranked todos.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-08-25T16:02:30Z (pre-deletion gate query)
- **Completed:** 2026-08-25T16:12:51Z
- **Tasks:** 2/2 completed
- **Files modified:** 7 (1 created directory entries: 2 new todo files)

## Accomplishments

- Executable pre-deletion gate ran first, in this execution: `SELECT count(*) FROM
  feature_ic_scores WHERE regime_label_source='context_features'` returned **0** at
  **2026-08-25T16:02:30Z**, authorizing the deletion per the plan's Step 0 protocol.
- Removed the entire daily-cadence significance block inside `_compute_symbol_tf` (the
  `context_features`-table query, `min_obs_daily`/`n_scales` locals, `cf_cluster_id = 10000 +
  cf_idx` assignment, and all downstream IC/bootstrap/walk-forward/row-assembly logic for that
  block) -- 232 lines removed in one surgical cut, bounded exactly by the per-regime-cell loop
  above (kept) and the BH-FDR cluster-representative selection below (kept).
- Removed the `CONTEXT_FEATURES` frozenset and its now-false 11-line "KNOWN GAP (todo 270)"
  comment paragraph.
- Removed `min_obs_daily` from `ICEngineConfig`'s field declaration, its APR load
  (`cfg.get_sync("alpha.ic.min_obs_daily_features", 1000)`), and
  `_COMPUTATIONAL_CONFIG_FIELDS` -- deliberately moving `apr_snapshot_key` and invalidating
  every cell fingerprint corpus-wide, which is correct (IC scores change corpus-wide regardless
  of this specific field's removal).
- Rewrote `_compute_cross_sectional_tf`'s docstring "KNOWN GAP" paragraph to describe the target
  broadcast-cell design (Plans 03/04) instead of the retired daily-cadence mechanism, without
  using the literal string `CONTEXT_FEATURES` (needed to satisfy the plan's own
  `grep -c CONTEXT_FEATURES` == 0 acceptance criterion).
- Added `test_compute_symbol_tf_has_no_context_features_daily_path`, a source-introspection
  test mirroring `test_compute_symbol_tf_has_no_db_write_code`'s style. Verified it fails
  (RED) when the string is manually reintroduced into `_compute_symbol_tf` and passes (GREEN)
  against the real post-deletion source, then reverted the manual reintroduction (confirmed
  clean `git diff` on `services/ic_engine.py` afterward).
- Filed `.planning/todos/pending/354-...md` (per-symbol temporal pseudo-replication now exposed
  by the deletion -- explicitly a *different* bug than Phase 173's cross-sectional broadcast
  cell, which does not cover it) and `.planning/todos/pending/355-...md` (`context_features`
  table's writer now has no `ic_engine.py` consumer). Both added to `PRIORITIES.md` (354 → P0,
  355 → P2).

## Task Commits

1. **Task 1: Gate on live row count, then delete the CONTEXT_FEATURES daily-cadence
   significance path** - `490f32b9e` (fix)
2. **Task 2: Add a regression test and file the two follow-up todos this deletion exposes** -
   `ade75a9d7` (test)

_No separate plan-metadata commit -- this SUMMARY and its self-check are the final commit for
this parallel-worktree plan; STATE.md/ROADMAP.md are updated centrally by the orchestrator
after the wave completes._

## Files Created/Modified

- `services/ic_engine.py` - `CONTEXT_FEATURES` daily-cadence path deleted (232-line block +
  frozenset + config field + docstring rewrite); net 265 lines changed (10 insertions, 255
  deletions) across both commits' touches to this file
- `tests/unit/test_ic_engine_compute_split.py` - new
  `test_compute_symbol_tf_has_no_context_features_daily_path`; fixed a pre-existing
  `ICEngineConfig(min_obs_daily=1000, ...)` construction site broken by the field removal
- `tests/unit/test_hac_ic_sharpe.py`,
  `tests/unit/test_ic_engine_dual_write_symbol_hmm.py`,
  `tests/unit/test_ic_engine_fingerprint.py`,
  `tests/unit/test_ic_engine_lifecycle_hook.py` - each had one
  `ICEngineConfig(min_obs_daily=1000, ...)` construction site removed (blocking `TypeError`
  after the field's removal)
- `.planning/todos/pending/354-context-features-intraday-autocorrelation-per-symbol-pooled-cell.md`
  - new todo: per-symbol temporal pseudo-replication exposed by this deletion
- `.planning/todos/pending/355-context-features-writer-orphaned-after-phase-173.md` - new todo:
  `context_features` table's writer is now unowned
- `.planning/todos/PRIORITIES.md` - both new todos added with rationale

## Decisions Made

- **Pre-deletion gate authorized the deletion**: live query at execution time (not the
  planning-time observation) returned 0, per the plan's explicit requirement that "the planning-
  time observation of zero rows does not authorize the deletion; only this run's own observation
  does."
- **Left the APR key row alone**: `alpha.ic.min_obs_daily_features` stays in
  `config_schema`/`config_state` -- no migration filed to delete it, per the plan's explicit
  instruction ("an unread key is harmless and Plan 173-04's follow-up may revisit it").
- **Todo numbers 354/355 confirmed free by live re-check**: the plan's planning-time snapshot
  said the highest number was 353; live `ls .planning/todos/pending/ .planning/todos/completed/`
  at execution time showed the actual highest was 352 (353 was never used) -- 354/355 were free
  either way, no renumbering needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed now-unused `circular_block_bootstrap_ic_serial` import**
- **Found during:** Task 1 (post-deletion vulture check)
- **Issue:** The deleted daily-cadence block was the only caller of
  `circular_block_bootstrap_ic_serial` inside `ic_engine.py`; after deletion, `vulture
  --min-confidence 80` flagged it as an unused import (90% confidence) -- CLAUDE.md requires
  CI-clean dead-code detection.
- **Fix:** Removed `circular_block_bootstrap_ic_serial` from the `ic_math` import list. The
  underlying function is untouched (not deleted from `ic_math.py`) since it may have other
  callers elsewhere in the codebase; only this file's now-dead import was removed.
- **Files modified:** `services/ic_engine.py`
- **Verification:** `vulture services/ic_engine.py --min-confidence 80` no longer flags it;
  remaining 3 vulture findings (lines ~393-405) confirmed pre-existing via `git diff -U0`
  (untouched by this plan's diff hunks) -- out of scope per the SCOPE BOUNDARY rule, not fixed.
- **Committed in:** `490f32b9e` (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed 5 test files constructing `ICEngineConfig(min_obs_daily=...)`**
- **Found during:** Task 1 (running `tests/unit/test_ic_engine_compute_split.py` and the
  broader `-k ic_engine` suite per the plan's acceptance criteria)
- **Issue:** Removing `min_obs_daily` from the `ICEngineConfig` dataclass broke every direct
  `ICEngineConfig(...)` construction site still passing that kwarg -- `TypeError:
  ICEngineConfig.__init__() got an unexpected keyword argument 'min_obs_daily'` in
  `test_ic_engine_compute_split.py`, `test_hac_ic_sharpe.py` (2 sites),
  `test_ic_engine_dual_write_symbol_hmm.py`, `test_ic_engine_fingerprint.py`, and
  `test_ic_engine_lifecycle_hook.py`.
- **Fix:** Removed the `min_obs_daily=1000,` line from each of the 5 files' `ICEngineConfig(...)`
  construction call.
- **Files modified:** `tests/unit/test_ic_engine_compute_split.py`,
  `tests/unit/test_hac_ic_sharpe.py`, `tests/unit/test_ic_engine_dual_write_symbol_hmm.py`,
  `tests/unit/test_ic_engine_fingerprint.py`, `tests/unit/test_ic_engine_lifecycle_hook.py`
- **Verification:** `pytest tests/unit/ -q -k ic_engine` (149 tests) all green after the fix;
  full `pytest tests/unit/ -q` (entire suite) also green.
- **Committed in:** `490f32b9e` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking issues surfaced by running the
plan's own acceptance-criteria commands). No scope creep -- both fixes were required to make
Task 1's explicitly-specified acceptance criteria (full `ic_engine`-scoped test suite green,
vulture clean) actually pass; without them the task could not have been verified complete.

## Issues Encountered

**Acceptance-criteria line-count estimate did not match the actual surgical deletion.** The
plan's acceptance criteria states "`services/ic_engine.py` shrinks by at least 350 lines" and
the objective's prose says "~370 lines." The actual net shrink is 245 lines (255 deletions, 10
insertions for the docstring rewrite) across the file. Root cause: the plan's own `read_first`
section gives the deletion's line-range estimate as "~2801 through ~3163" (362 lines), but the
same section explicitly states the BH-FDR cluster-representative-selection code inside that same
numeric range "must SURVIVE" -- live inspection confirmed roughly 150 of those lines are the
surviving BH-FDR/cluster-representative block, not part of the daily-cadence mechanism at all.
The plan's `<action>` step (a) gives an unambiguous, non-numeric boundary description ("starts at
the comment banner... and ends where the... loop's final `all_results.append({...})` closes and
its enclosing `with short_lived_conn(dsn) as conn:` scope ends") that was followed exactly and
verified against every other acceptance criterion (all `grep -c` checks return 0/nonzero as
specified, full test suite green, vulture clean, `git diff` boundaries manually re-read against
the pre-edit source to confirm no BH-FDR code was touched). Judged the explicit structural
boundary in `<action>` authoritative over the approximate numeric line-range estimate in
`read_first`/the objective's "~370 lines" prose, since deleting further to hit the 350-line
target would require removing code the same plan explicitly marks "must SURVIVE." Not treated
as a Rule 1-4 deviation (no code was wrong, missing, or blocking) -- flagged here for visibility
in case a future reader expects a larger diff and wants to confirm nothing was missed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `services/ic_engine.py` is clean of the retired `CONTEXT_FEATURES` mechanism; Plans 03/04 can
  build the new broadcast-cell design without a lingering second significance-test bug running
  in parallel (D-01's explicit requirement).
- `_compute_cross_sectional_tf`'s docstring already states the target broadcast-cell design in
  present tense, ready for Plans 03/04 to implement against.
- Corpus-wide `feature_ic_scores` fingerprint invalidation is expected and already documented --
  the next full `ic_engine` corpus run will recompute everything regardless of this specific
  change, so no separate "trigger a recompute" follow-up is needed from this plan.
- Two known gaps are filed and ranked (354 P0, 355 P2), not silently left implicit, satisfying
  this plan's `must_haves` truth: "The two consequences of the deletion that this phase does not
  itself fix are captured as filed todos, not left implicit."

---
*Phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s*
*Completed: 2026-08-25*

## Self-Check: PASSED

- FOUND: commit `490f32b9e` (Task 1)
- FOUND: commit `ade75a9d7` (Task 2)
- FOUND: `services/ic_engine.py`
- FOUND: `tests/unit/test_ic_engine_compute_split.py`
- FOUND: `.planning/todos/pending/354-context-features-intraday-autocorrelation-per-symbol-pooled-cell.md`
- FOUND: `.planning/todos/pending/355-context-features-writer-orphaned-after-phase-173.md`
