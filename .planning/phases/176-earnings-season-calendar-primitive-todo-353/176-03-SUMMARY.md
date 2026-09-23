---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: "03"
subsystem: intelligence
tags: [feature-factory, apr, feature-vectors, calendar-primitive]

# Dependency graph
requires:
  - phase: 176-02
    provides: "feature_vectors.earnings_season_flag/days_since_quarter_end columns (migration 350), APR keys, concept_registry genesis rows"
provides:
  - "_days_since_quarter_end/_earnings_season_flag pure functions in feature_factory.py"
  - "FeatureVector.earnings_season_flag/days_since_quarter_end dataclass fields (300 total)"
  - "_EARNINGS_SEASON_FIELD_NAMES persistence slice, appended LAST (309 columns total)"
  - "Both fields wired on compute()/compute_batch()/_cold_start_vector() and both production APR prewarm paths"
affects: [176-04, 176-05, 176-06, 176-07, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Calendar primitive reuse discipline: _earnings_season_flag calls _days_since_quarter_end internally, mirroring _quad_witching_flag calling _opex_flag"
    - "Optional config parameter threaded into a previously-config-less helper (_cold_start_vector) for a single new field, defaulting to a neutral fallback when absent"

key-files:
  created: []
  modified:
    - src/intelligence/feature_factory.py
    - src/intelligence/schemas.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/intelligence/test_feature_factory_batch_parity.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/test_canary_predictors.py
    - tests/unit/test_feature_factory.py

key-decisions:
  - "Deferred the two field-to-group dict entries from Task 1 to Task 2's atomic commit: adding them before the dataclass fields existed would have broken test_feature_vector_domain_complete's 1:1 parity invariant (FEATURE_VECTOR_DOMAIN keys must exactly equal FeatureVector's field names) at the Task 1 commit boundary"
  - "_days_since_quarter_end deliberately does not reuse _QUARTER_LENGTH_DAYS (91.25, the 30-day-per-month approximation _quarter_position uses) -- true calendar-day counting keeps the two fields at the measured 0.935 correlation rather than making them collinear"
  - "_cold_start_vector gained an Optional config parameter (not required) so its one existing caller and any future zero-bar caller still work without config; earnings_season_flag falls back to 0.0 when config is None even if bar_ts is available"

requirements-completed: [ES-01, ES-02, ES-03]

# Metrics
duration: 30min
completed: 2026-09-23
---

# Phase 176 Plan 03: Earnings-Season Calendar Primitive Compute Wiring Summary

**Two new tier-1 calendar primitives (`earnings_season_flag`, `days_since_quarter_end`) computed from `bar_ts` alone via APR-driven window boundaries, wired through every FeatureVector construction site with zero positional-index drift on the other 307 existing columns.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-09-23T07:29:00-04:00 (worktree base correction)
- **Completed:** 2026-09-23T07:50:50-04:00
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- `_days_since_quarter_end(bar_ts)` and `_earnings_season_flag(bar_ts, config)` added to `feature_factory.py`, both pure functions, both APR-driven (no hardcoded 14/42 window literals), both boundary-tested including the reuse-discipline regression test
- `FeatureVector` gained two non-nullable float fields (300 total, up from 298), declared as one contiguous run so the derived persistence slice covers exactly this block
- `feature_vector_persistence.py`'s `_ALL_COLUMN_NAMES` now derives 309 columns (up from 307), with the two new fields appended LAST — every pre-existing column keeps its exact positional SQL parameter index
- All five `FeatureVector` construction sites wired: `_build_feature_vector`'s signature + `_guard()` body, `compute()`'s call site, both `compute_batch()` touch points, and `_cold_start_vector` (gained an Optional `config` param)
- Both production APR prewarm paths (`feature_vector_pipeline.py` live path, `backfill_feature_factory.py` batch path) resolve the window boundaries from the same APR keys with identical defaults
- Batch-parity test proves `compute()` and `compute_batch()` agree on both new fields at an in-window, an out-of-window, and a quarter-end boundary timestamp

## Task Commits

Each task was committed atomically:

1. **Task 1: Pure calendar functions + APR config fields + group registration** - `eab944c74` (feat)
2. **Task 2: ATOMIC — schema fields + every construction site + persistence slice + fixtures** - `1413c2b06` (feat)
3. **Task 3: APR prewarm wiring on both production paths + batch parity** - `967e0968f` (feat)

_Note: no TDD RED/GREEN split — this plan's `tdd="true"` tasks wrote behavior tests inline with implementation per the plan's own task structure, not a strict test-first/test-after split._

## Files Created/Modified
- `src/intelligence/feature_factory.py` - Two new pure calendar functions, two new `FeatureFactoryConfig` fields (defaulted, matching `canary_rng_seed`'s convention), field-to-group dict entries, all five construction-site updates, `_cold_start_vector`'s new `config` param
- `src/intelligence/schemas.py` - `FeatureVector.earnings_season_flag`/`days_since_quarter_end` fields, docstring extension log entry, field-count updates (298→300)
- `src/intelligence/features/feature_vector_persistence.py` - `_EARNINGS_SEASON_FIELD_NAMES` derived slice, appended LAST in `_ALL_COLUMN_NAMES` and the params-building generator, module docstring extension log entry (307→309 columns)
- `services/feature_vector_pipeline.py` - Two APR seed-list entries, two `FeatureFactoryConfig(...)` construction kwargs (live path)
- `services/backfill_feature_factory.py` - Two `cfg.get_sync` construction kwargs (batch path)
- `tests/unit/intelligence/test_feature_factory_p7.py` - Boundary tests for both new functions, field-to-group parity test count bump
- `tests/unit/intelligence/test_feature_factory_batch_parity.py` - New batch-parity test (3 parametrized timestamp cases); two pre-existing direct `_build_feature_vector(...)` calls needed the 2 new required kwargs
- `tests/unit/services/test_feature_vector_writer_column_mapping.py` - New sentinel fields, new no-shift positional-index test, all `len(params) == 307` assertions bumped to 309
- `tests/unit/services/test_feature_vector_writer.py` - New sentinel fixture fields, 3 hardcoded 307-count assertions bumped to 309
- `tests/unit/services/test_backfill_feature_factory.py` - New sentinel fixture fields, 307-count assertion bumped to 309
- `tests/unit/test_canary_predictors.py` - Two hardcoded `dataclasses.fields(FeatureVector)` count assertions (298) bumped to 300, with the `ic_engine.py` alignment-gate rationale comment preserved
- `tests/unit/test_feature_factory.py` - One hardcoded field-count assertion (298) bumped to 300

## Decisions Made
See `key-decisions` in frontmatter above.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Deferred field-to-group dict entries from Task 1 to Task 2**
- **Found during:** Task 1, running the full `test_feature_factory_p7.py` suite per its acceptance criteria
- **Issue:** The plan's Task 1 action block assigns the two `FEATURE_VECTOR_DOMAIN` dict entries (`"earnings_season_flag": "calendar"`, `"days_since_quarter_end": "calendar"`) to Task 1, alongside the pure functions and config fields. But `test_feature_vector_domain_complete` asserts `set(FEATURE_VECTOR_DOMAIN.keys()) == fv_fields` (an exact 1:1 parity invariant between the field-to-group dict and `FeatureVector`'s actual dataclass fields). Adding the two dict entries in Task 1 — before the dataclass fields exist (they land in Task 2's atomic commit) — broke that invariant at the Task 1 commit boundary, contradicting Task 1's own acceptance criterion that the full test file must pass.
- **Fix:** Moved the two `FEATURE_VECTOR_DOMAIN` entries into Task 2's commit, landing them in the same atomic commit as the dataclass fields. This preserves the parity invariant at every commit boundary, consistent with the plan's own Pitfall 4 philosophy (schema + all dependents must land atomically) applied to this closely related invariant that the plan's task boundaries hadn't accounted for.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `test_feature_factory_p7.py -x -q` green after Task 1's commit; `test_feature_vector_domain_complete` green after Task 2's commit
- **Committed in:** `eab944c74` (deferral, Task 1), `1413c2b06` (actual addition, Task 2)

**2. [Rule 1 - Bug] Fixed hardcoded field-count assertions rippling from the 298→300 schema change**
- **Found during:** Task 2, running `pytest tests/unit/ -q` per its acceptance criteria
- **Issue:** Six test files elsewhere in the suite (not listed in Task 2's `<files>` block) hardcode `FeatureVector`'s field count (298) or the persisted column count (307), either as a bare assertion or embedded in a docstring's running arithmetic. The 298→300 dataclass change and 307→309 persistence-slice change broke all of them at collection/run time, and two `test_feature_factory_batch_parity.py` tests call `_build_feature_vector(...)` directly with a full kwargs set, hitting a `TypeError: missing 2 required keyword-only arguments` since the two new fields have no default (Pitfall 4).
- **Fix:** Updated every hardcoded count (`test_canary_predictors.py`, `test_feature_factory.py`, `test_feature_vector_writer_column_mapping.py`, `test_feature_vector_writer.py`, `test_backfill_feature_factory.py`) from 298→300 / 307→309, and added the two new required kwargs to both direct `_build_feature_vector(...)` call sites in `test_feature_factory_batch_parity.py`. One of the six files (`test_canary_predictors.py`) carries a load-bearing comment noting `ic_engine.py`'s alignment gate compares this exact count against a live `concept_registry(domain='feature')` row count — migration 350 (176-02, already merged) seeds exactly 2 new rows there, so the count stays in sync.
- **Files modified:** `tests/unit/intelligence/test_feature_factory_batch_parity.py`, `tests/unit/test_canary_predictors.py`, `tests/unit/test_feature_factory.py`, `tests/unit/services/test_feature_vector_writer_column_mapping.py`, `tests/unit/services/test_feature_vector_writer.py`, `tests/unit/services/test_backfill_feature_factory.py`
- **Verification:** `pytest tests/unit/ -q` exits 0 with zero collection errors, zero failures
- **Committed in:** `1413c2b06` (Task 2 commit — same atomic commit as the schema change that caused the ripple, per Pitfall 4's own logic: these fixes are mechanically required by that exact change, not separate scope)

**3. [Rule 1 - Bug, tooling] Symlinked worktree `.venv` to the main repo's**
- **Found during:** Task 1, first commit attempt
- **Issue:** The pre-commit hook's ruff/black checks look for `${REPO_ROOT}/.venv/bin/{ruff,black}` where `REPO_ROOT` resolves to the worktree root. Worktrees don't get their own `.venv` (a known GSD worktree gotcha), so both checks reported "not found" and blocked the commit.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-ac10ab1bdc125839c/.venv`. `.venv` is gitignored, so this is a local-only convenience symlink with no git-tracked effect.
- **Files modified:** none (symlink outside git tracking)
- **Verification:** Pre-commit hook's ruff/black checks passed on the next commit attempt
- **Committed in:** N/A (not a git-tracked change)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bug fixes required by the plan's own atomic-commit logic applied consistently, 1 Rule 1 tooling fix)
**Impact on plan:** All three deviations were mechanically required consequences of the plan's own Task 2 atomicity requirement (Pitfall 4) — none represent scope creep or design changes. No `<threat_model>` mitigations were skipped; no architectural changes were made.

## Issues Encountered
- Worktree HEAD at spawn time was an ancestor of the expected base commit (branched before wave 1's merge commits landed on `main`) rather than exactly at it — resolved per the standard `<worktree_branch_check>` `git reset --hard` correction before any work began. No commits were lost; this worktree had no prior commits of its own.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both primitives are computed and persisted on all three code paths (live, batch, cold-start), with zero positional-index drift on the 307 pre-existing columns and full APR coverage on both production entrypoints
- 176-04/05/06 (the conditioning workstream, gated per STATE.md's D-01a amendment on 176-01's extended sweep result) can now read real `earnings_season_flag`/`days_since_quarter_end` values once 176-07's corpus backfill runs — this plan does not backfill existing rows, it only wires new-row compute going forward
- No blockers for 176-04 through 176-08

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*
