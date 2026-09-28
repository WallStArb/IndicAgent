---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: "04"
subsystem: research-infra
tags: [feature-matrix, cost-hurdle, date-panel, compute-eligibility, asyncpg, promotion]

# Dependency graph
requires:
  - phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope (plan 01)
    provides: summary-card schema and the deletion order this promotion unblocks
provides:
  - scripts/infrastructure/instrument_compute_eligibility_audit.py (COMPUTE_READY_PREDICATE_SQL, COMPUTE_READY_1D_PREDICATE_SQL, load_compute_timeframes) so onboarding SOP stage 8 survives 186-16
  - scripts/research/date_panel.py (Panel, spearman: date-block bootstrap, panel-synchronous shift null)
  - scripts/research/cost_hurdle.py (pre-registered personal-scale cost band as pure functions)
  - scripts/research/feature_matrix.py (fetch_feature_matrix: two-pass asyncpg fetch, no forward_returns join)
affects: [186-16 (scripts/analysis deletion), 186-07 (todo 445 consumer), 186-10/186-14 (fresh IC jobs), onboarding SOP]

# Tech tracking
tech-stack:
  added: []  # no new libraries; numpy/pandas/psycopg/asyncpg/scipy already in use
  patterns:
    - "caller-owned connection with required keyword-only start/end span (lookahead cannot enter by omission)"
    - "keep-mask decoupling: fetch is target-agnostic, survivor selection belongs to the caller's kernel-computed target"
    - "unit-explicit epoch-ns conversion (pandas 3's microsecond default resolution makes bare .asi8 unit-dependent)"

key-files:
  created:
    - scripts/infrastructure/instrument_compute_eligibility_audit.py
    - scripts/research/date_panel.py
    - scripts/research/cost_hurdle.py
    - scripts/research/feature_matrix.py
    - tests/unit/scripts/test_research_cost_hurdle.py
    - tests/unit/scripts/test_research_feature_matrix.py
  modified:
    - scripts/infrastructure/universe_expansion_promote_compute_eligible.py
    - tests/unit/scripts/test_compute_ready_predicate_apr.py
    - tests/unit/test_date_panel.py (moved to tests/unit/scripts/test_research_date_panel.py)
    - CLAUDE.md (wide-frame rule pointer only)

key-decisions:
  - "cost_hurdle constants stay module constants, not APR keys: they are pre-registered (changing one invalidates every placement) and scripts/ is outside the APR mandate's src/services scope"
  - "fetch_feature_matrix drops the forward_returns join (186-23 drops the table; CLAUDE.md executable-returns rule): the caller computes its target with panel.forward_returns and passes target-is-finite as the keep mask"
  - "NON_FEATURE_COLS omits hmm_duration: that exclusion was combiner-specific; callers opt out via extra_exclude_cols"
  - "migrations 337/341/358 and the schema-baseline fixture cite the old scripts/analysis path in comments; applied and immutable, left as historical citations (186-16 owns the vulture whitelist entry)"
  - "onboarding SOP doc needs no edit: it runs only universe_expansion_promote_compute_eligible.py and never names the audit module (verified lines 175-225)"

patterns-established:
  - "promoted-helper test discipline: exact-equality against the originals via importorskip plus inline-formula assertions so the tests survive 186-16"

requirements-completed: [D-12, R-05, D-02]

# Metrics
duration: 53 min
completed: 2026-09-28
---

# Phase 186 Plan 04: Reusable scripts/analysis helper promotion Summary

**Four surviving pieces of scripts/analysis promoted (compute-eligibility audit to scripts/infrastructure, date panel + pre-registered cost band + two-pass feature-matrix fetch to scripts/research) with the forward_returns join removed and the onboarding promote step repointed, so 186-16 can delete the directory without breaking a live importer.**

## Performance

- **Duration:** 53 min (started 2026-09-28T05:50:54Z, completed 2026-09-28T06:43:33Z)
- **Tasks:** 3 of 3
- **Files modified:** 11 (7 created, 3 modified, 1 test moved)

## Accomplishments
- The onboarding SOP's promote step imports the audit from `scripts/infrastructure/` (code byte-identical below the docstring; predicate SQL text unchanged, so migration 341's inline copy still matches)
- `scripts/research/date_panel.py` promoted code-identical with its test moved and repointed
- `scripts/research/cost_hurdle.py` deduplicates both personal_cost_hurdle scripts into pure functions + pre-registered constants; bit-identical to the originals on identical inputs
- `scripts/research/feature_matrix.py` generalizes `fetch_training_matrix`: no target join, caller-supplied keep mask, required keyword-only span, caller-owned connection, session-scoped work_mem
- CLAUDE.md wide-frame rule now points at `fetch_feature_matrix`; nothing under `scripts/analysis/` or `src/intelligence/research/` was touched

## Task Commits

Each task was committed atomically (TDD tasks: RED verified before implementation, single commit per task as the plan's action blocks specify):

1. **Task 1: promote compute-eligibility audit to scripts/infrastructure** - `edd14b42c` (refactor)
2. **Task 2: promote date panel and cost band to scripts/research** - `c4d68172c` (feat)
3. **Task 3: promote two-pass feature matrix fetch + CLAUDE.md repoint** - `01519f701` (feat)

## Files Created/Modified
- `scripts/infrastructure/instrument_compute_eligibility_audit.py` - copied from scripts/analysis with a move note in the docstring only; exports both predicate constants and load_compute_timeframes
- `scripts/infrastructure/universe_expansion_promote_compute_eligible.py` - import, docstring and comment repointed at scripts.infrastructure
- `scripts/research/date_panel.py` - date-block bootstrap + panel-synchronous shift null (code-identical from `from __future__` down)
- `scripts/research/cost_hurdle.py` - corwin_schultz_daily, estimate_cs_spreads, rank_turnover, one_way_cost, annual_drag, ic_min + 10 pre-registered constants
- `scripts/research/feature_matrix.py` - NON_FEATURE_COLS, select_feature_columns, FeatureMatrix, fetch_feature_matrix
- `tests/unit/scripts/test_research_date_panel.py` - moved from tests/unit/test_date_panel.py, import repointed
- `tests/unit/scripts/test_research_cost_hurdle.py` - 12 tests: exact equality vs originals (importorskip) + inline formulas + fake-connection estimate_cs_spreads + subprocess import isolation
- `tests/unit/scripts/test_research_feature_matrix.py` - 17 fake-connection tests incl. SQL-shape, span, keep-mask, both RuntimeError paths
- `tests/unit/scripts/test_compute_ready_predicate_apr.py` - import repointed
- `CLAUDE.md` - one pointer in the wide-frame rule

## Decisions Made
- See key-decisions; all follow the plan's action blocks. The SOP no-edit finding and the migrations-as-historical-citations decisions are recorded there per the plan's verification requirements.

## D-08 consumer grep outputs (plan verification requirement)

Grep 1, real imports of the four helpers outside scripts/analysis/ (run from the worktree
root; every hit is either in the plan's context list or inside scripts/analysis/ itself,
which dies in 186-16):

- `scripts/infrastructure/universe_expansion_promote_compute_eligible.py:34` (repointed in Task 1)
- `tests/unit/scripts/test_compute_ready_predicate_apr.py:15` (repointed in Task 1)
- `tests/unit/test_date_panel.py:5` (moved + repointed in Task 2)
- `tests/unit/test_nonlinear_interaction_combiner_shared.py:20` and `tests/unit/test_extreme_volume_divergence_track1.py:6` (test scripts 186-16 deletes; left as-is by design)
- 20 further hits, all `^scripts/analysis/` internal importers of `_nonlinear_interaction_combiner_shared` / `personal_cost_hurdle` / `_date_panel`, deleted by 186-16

Grep 2, textual mentions outside scripts/analysis/ (all classified, none are imports):

- `CLAUDE.md:157` - repointed in Task 3
- `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`, `docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`, `docs/plans/2026-09-26-unified-research-to-production-design.md`, `docs/research/{data-edge-source-thesis,ic-engine-short-horizon-cell-deletion-prereg,measurement-nonlinear-interaction-combiner}.md` - historical research/provenance citations; pre-registration text must keep citing the path it was pre-registered at
- `production/migrations/{337,341,358}*.sql` and `tests/integration/fixtures/schema_baseline_2026-09-27.sql` - applied, immutable DDL comments citing the old path; historical citations by decision
- `scripts/infrastructure/universe_expansion_stratified_sourcing.py:69` - a comment noting IBKR client 48 was the personal_cost_hurdle one-off; not an import, no edit needed
- `tools/vulture_whitelist.py:999` - 186-16's job per the plan
- the promote script, the three repointed tests, and scripts/analysis/ internals already covered above

No importer outside the context list appeared; execution proceeded per the plan.

## Cost-hurdle: deliberately NOT promoted

- `_live_quote_ratios` and the `/tmp` live-quote cache (IBKR client 48 top-of-book validation): R-13 forbids phase 186 from starting IBKR jobs; the validation verdict (CS estimator FAILED the [0.5, 3.0] band, live 1.4bp median is the anchor) is already recorded in the pre-registration doc and in `LIVE_SPREAD_ANCHOR`
- `_fetch_ranks` (both variants), `_bars_per_trading_day`, `_lookahead_bars_for_tf`, `_measured_ic_at`: they read `feature_vectors` / `feature_ic_scores` shapes this phase replaces (186-24/186-28)
- both `main()`s and the sensitivity-table printers: presentation tied to the old tables; git history keeps them
- `_HORIZONS`, `_VALIDATION_SYMBOLS`, `_TFS`, `_TURNOVER_FEATURE`: run-specific configuration of the dead mains, not band math

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] epoch-ns conversions made unit-explicit in feature_matrix.py**
- **Found during:** Task 3 (GREEN phase)
- **Issue:** pandas 3.0.1's default datetime resolution is microseconds and `DatetimeIndex.asi8` returns the index's own unit, so the original's bare `.asi8` pattern is NOT epoch-ns on the installed pandas; the plan's own contract ("bar_ts as int64 epoch-ns" into `keep`, row-for-row pass-2 assertion, UTC meta reconstruction) would silently see another unit and meta would land in 1970
- **Fix:** `_epoch_ns()` helper (`to_numpy(dtype="datetime64[ns]").astype(int64)`), the same conversion for the pass-2 assertion, and int64 -> `datetime64[ns]` for meta reconstruction; documented in the module docstring
- **Files modified:** scripts/research/feature_matrix.py
- **Verification:** test_fetch_keep_receives_pass1_key_arrays asserts dtype int64; happy-path test asserts meta bar_ts equals the source timestamps in UTC
- **Committed in:** 01519f701

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** Meets the plan's stated epoch-ns contract rather than the literal original code; no scope change. Note: the original's meta reconstruction has the same unit bug on pandas 3, but the original is dead code that 186-16 deletes, so it was not touched (D-02/scope boundary).

## Issues Encountered

- Branch-point collection break from the concurrent 185 session: db021babf (the coordinator's docs commit) accidentally includes `tests/unit/services/test_bar_derivation_grid.py` without its module `services/bar_derivation.py` (which landed afterwards in 060af4f26, "feat(185-11)"). This is the shared-index sweep the dispatch warns about, caught by the 186-04 executor's collection gate. On the branch, full-suite gates ran with `--ignore=tests/unit/services/test_bar_derivation_grid.py` (7075 passed, 0 failed, 2 pre-existing unrelated skips); the ungated collection and full suite pass again on merged main, where the module exists.
- Ruff E741 (`l` variable) and import-order fixes in new test files were applied at pre-commit; black reformats folded into the task commits. One AC adjustment: the feature_matrix docstring initially contained the literal "ALTER SYSTEM" in prose, tripping the `grep -c "ALTER SYSTEM"` acceptance gate (count must be 0); reworded to "never any server-level configuration statement".

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 186-16 can delete `scripts/analysis/` (except the sleeve config closure) without breaking the onboarding promote step or any test outside the files it deletes: the promote script, its APR test and the date-panel test now import from the promoted locations, and the promoted cost/feature modules never read `forward_returns`, `feature_ic_scores` or the old chain
- 186-07 (todo 445) and the fresh IC jobs get `scripts/research/feature_matrix.py` as their fetch layer
- Coordinator relay: db021babf's stray 185 test file should be acknowledged in the 185 lane's bookkeeping (nothing to fix - the module landed in 060af4f26 on main; only the historical commit is odd)

---
*Phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope*
*Completed: 2026-09-28*

## Self-Check: PASSED

All key files exist on disk; all three task commits (edd14b42c, c4d68172c, 01519f701) found; every task acceptance criterion and every plan-level verification command re-run green (see Issues Encountered for the branch-point collection note).
