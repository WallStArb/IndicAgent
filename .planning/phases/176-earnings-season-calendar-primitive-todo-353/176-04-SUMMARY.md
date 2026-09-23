---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: "04"
subsystem: intelligence
tags: [ic-engine, stratification, apr, calendar-primitive, lifecycle-guard]

# Dependency graph
requires:
  - phase: 176-01
    provides: "D-01a gate evidence: multi-feature BH-FDR sweep with SWEEP_VERDICT=CONFIRMED and non-empty survivors"
  - phase: 176-03
    provides: "feature_vectors.earnings_season_flag column inside FeatureVector's persisted slice"
  - phase: 176-02
    provides: "alpha.ic.earnings_season_conditioned APR key (migration 350) and feature_ic_scores.regime_scope CHECK widening"
provides:
  - "_earnings_season_labels: three-way 1.0/0.0/NaN label mapping (no np.where)"
  - "Third earnings_season stratification pass in _build_regime_passes, APR-gated"
  - "ICEngineConfig.earnings_season_conditioned loaded from alpha.ic.earnings_season_conditioned"
  - "_lifecycle_guard_cells: scope-aware guard selection excluding regime_scope='earnings_season'"
affects: [176-06, 176-07, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stratification pass as a (labels, distinct_labels, resolved_scope) tuple appended in _build_regime_passes, reusing _compute_one_regime_cell verbatim"
    - "Scope-aware guard selection extracted into a pure, DB-free helper (_lifecycle_guard_cells) so the scope contract is unit-pinnable"
    - "New feature column consumed by column index into the already-fetched matrix -- zero fetch-SQL change"

key-files:
  created: []
  modified:
    - services/ic_engine.py
    - tests/unit/services/test_ic_engine.py
    - tests/unit/test_ic_engine_lifecycle_hook.py
    - tests/unit/test_ic_engine_compute_split.py

key-decisions:
  - "Threaded earnings_season_conditioned through the worker args tuple + _compute_symbol_tf only, NOT into _symbol_expected_cells -- the plan's named 'two call sites' are actually the expected-cells mirror and the worker tuple; the mirror writes ic_cell_fingerprints rows whose pass_type CHECK (migration 251) admits only pooled/symbol_hmm/cross_sectional, so tracking earnings cells there would crash the upsert and needs a migration (351, owned by parallel plan 176-07). Corollary: earnings cells are fingerprint-untracked and first-write-final under ON CONFLICT DO NOTHING -- documented at both invalidation DELETEs"
  - "The earnings pass is deliberately NOT gated on the cross_sectional flag: the calendar axis is orthogonal to regime-group routing, and the pass runs on the per-symbol path regardless of which cross-sectional mode is enabled"
  - "Exclusion keys on the regime_scope VALUE, never on the label strings ('in_season'/'off_season' appear nowhere in _lifecycle_guard_cells source, pinned by an inspect.getsource test) -- a future scope carrying the same labels must still route through the guard"
  - "NaN flag values (pre-backfill NULLs) map to None via an explicit three-way mapping, never via a two-way np.where that would fabricate off_season labels (T-176-04-01); partially-backfilled corpora degrade to fewer measured rows"

requirements-completed: [ES-05, ES-06]

# Metrics
duration: 37min
completed: 2026-09-23
---

# Phase 176 Plan 04: Earnings-Season IC Stratification Pass Summary

**APR-gated per-symbol earnings_season IC stratification pass in `_build_regime_passes` with explicit NaN-safe label mapping, plus a scope-aware lifecycle guard that keeps `regime_scope='earnings_season'` measurement rows out of regime-group routing.**

## Performance

- **Duration:** ~37 min
- **Started:** 2026-09-23T13:42:31Z
- **Completed:** 2026-09-23T14:19:24Z
- **Tasks:** 2 (both TDD RED/GREEN)
- **Files modified:** 4

## Gate Record (D-01a)

Executed only after reading `176-EVIDENCE-A1.md`: `SWEEP_VERDICT=CONFIRMED` with 31 non-empty `SWEEP_SURVIVORS` -- PROCEED condition met.

## Accomplishments

- `_earnings_season_labels()` maps the persisted `feature_vectors.earnings_season_flag` column: 1.0 -> in-season, 0.0 -> off-season, everything else (NaN from pre-backfill NULL) -> None; explicit three-way mapping, `np.where` banned by an `inspect.getsource` assertion
- `_build_regime_passes()` appends a third `(labels, distinct_labels, "earnings_season")` pass exactly once, gated on `ICEngineConfig.earnings_season_conditioned` (loaded from APR key `alpha.ic.earnings_season_conditioned`, seed 'true' from migration 350) and skipped with a single info log when the flag column is all-NULL; reuses `_compute_one_regime_cell` verbatim, zero fetch-SQL change (flag read by `_FEATURE_NAMES` column index from the already-materialized matrix)
- Labels sit outside every enabled regime group's tier vocabulary and the calm/elevated/turbulent HMM vocabulary, honoring the LABEL-VOCABULARY-UNIQUENESS INVARIANT (`_REGIME_INSERT_SQL`'s ON CONFLICT key omits regime_scope; todo 391)
- `_lifecycle_guard_cells()` extracted and wired as the Step 3 guard's selection: `feature_status_at_eval == 'active'` AND `regime_scope != 'earnings_season'`; the lifecycle hook's SELECT now fetches `fis.regime_scope` so cell rows carry it (name-keyed dict construction, no positional drift)
- Full in-file `regime_scope` consumer audit completed (table below) with audit comments added at both fingerprint invalidation DELETEs and `_group_cells_for_metrics`
- 15 new DB-free tests (11 pass-construction/label-mapping, 4 guard-exclusion) plus the TDD gate sequence

## Task Commits

Each task committed atomically through the RED/GREEN gates:

1. **Task 1 RED** - `73a27c42f` (test): failing tests for label mapping + pass construction
2. **Task 1 GREEN** - `d047c7606` (feat): earnings_season stratification pass, per-symbol path
3. **Task 2 RED** - `63bc5e4cd` (test): failing tests for lifecycle-guard exclusion
4. **Task 2 GREEN** - `378fb2891` (feat): `_lifecycle_guard_cells` isolation + scope-audit comments
5. **Task 2 fixture ripple** - `88ee5f2f7` (fix): stale fixtures in two adjacent test files (full-suite acceptance)

## Files Created/Modified

- `services/ic_engine.py` - `_EARNINGS_SEASON_FLAG_IDX`, `_earnings_season_labels`, `_build_regime_passes` extension, `ICEngineConfig.earnings_season_conditioned` + loader + APR-key audit entry, `_compute_symbol_tf` param + gated derivation + skip log, worker-args threading, `_lifecycle_guard_cells`, lifecycle SELECT `fis.regime_scope`, guard call-site swap, 3 audit comments
- `tests/unit/services/test_ic_engine.py` - 15 new DB-free tests (label mapping edge cases, pass gating/uniqueness/source assertions, guard exclusion/regression/source assertions)
- `tests/unit/test_ic_engine_lifecycle_hook.py` - fake cursor cols + `_cell` fixture gained `regime_scope` (mirrors the real SELECT contract)
- `tests/unit/test_ic_engine_compute_split.py` - expected-params list gained `earnings_season_conditioned`

## In-File regime_scope Consumer Audit (Task 2 acceptance)

Every `regime_scope` hit in `services/ic_engine.py` that filters or routes on scope, with verdict:

| Location | Consumer | Verdict |
| --- | --- | --- |
| 253 `_resolve_regime_scope` | resolves pooled/cross_sectional tag for row emission | scope-agnostic; the earnings pass bypasses it by passing its scope explicitly in the pass tuple |
| 381/392 cell INSERT SQL | column list + named param, writes the row's own scope | scope-agnostic passthrough |
| 1603 `_FINGERPRINT_INVALIDATE_DELETE_SQL` | filters `regime_scope = %(pass_type)s` | earnings rows can never match (only ever invoked with pooled/symbol_hmm); audit comment added; corollary gap documented (untracked = first-write-final) |
| 1616 `_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL` | hardcodes `'cross_sectional'` | earnings rows can never match; same audit comment |
| 1641-1703 fingerprint/staleness SELECTs | fingerprint freshness reads keyed on pass_type | earnings untracked (needs migration 351, owned by parallel plan 176-07); deferred, not silently ignored |
| 2721/3119/4199/4588 row-emission dicts | stamp the scope value on written rows | scope-agnostic emission |
| 3243-3259 `_group_cells_for_metrics` | groups by (regime, is_pooled, regime_scope) for OTel cell counts | provably scope-agnostic (earnings cell gets its own bucket); audit comment added; metrics only, no decision |
| 3574/3599/3641 `_resolve_regime_scope` call sites | pooled + cross-sectional passes | untouched, no fourth-value exposure |
| 6074 Step 2 material-fail loop | iterates all cell_rows | benign without exclusion: earnings cells carry `COALESCE(ew.weight, 0.0)` standing weight, so `0.0 > decay_materiality_threshold` is always false -- they can never be counted as material fails |
| 5797 `_apply_feature_transitions` (Step 4/5) | aggregates ALL cell_rows by feature_name for demotion/promotion, filtering only on `feature_status_at_eval` | benign today (per-symbol earnings cells never reach this hook: the SELECT pins `symbol='POOLED' AND is_pooled=true`); **176-06 must extend the exclusion here when its POOLED parent-qualified earnings cells enter cell_rows** -- tracked below |
| 5967 `_lifecycle_guard_cells` | the guard selection | exclusion added (this plan) |
| 6031 lifecycle SELECT | fetches `fis.regime_scope` into cell_rows | support change (this plan) |

## Decisions Made

See `key-decisions` in frontmatter above.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's "two `_compute_symbol_tf` call sites" were misidentified; threading skipped intentionally**
- **Found during:** Task 1, pre-implementation trace of the call graph
- **Issue:** The plan directed threading the pass into both `_compute_symbol_tf` call sites (~6615/~6876). Those sites are `_symbol_expected_cells` (the fingerprint expected-cells mirror) and the worker args tuple, not two compute invocations. Threading the earnings pass into `_symbol_expected_cells` would write `ic_cell_fingerprints` rows with `pass_type='earnings_season'`, which migration 251's CHECK constraint rejects -- the upsert would crash every run. Extending the CHECK needs migration 351, already claimed by the parallel plan 176-07 (`351_earnings_season_backfill.sql`); this plan cannot own that number.
- **Fix:** Threaded through the worker args tuple + `_compute_symbol_tf` only (the actual compute path). Documented the corollary at both invalidation DELETEs: earnings cells are fingerprint-untracked, hence first-write-final under ON CONFLICT DO NOTHING, with no staleness detection until a migration extends the pass_type vocabulary.
- **Files modified:** `services/ic_engine.py`
- **Verification:** full unit suite green; targeted tests green
- **Committed in:** `d047c7606`

**2. [Rule 1 - Bug] Stale fixtures in two adjacent test files broke the full-suite acceptance**
- **Found during:** Task 2, running `pytest tests/unit/ -q` per its acceptance criteria
- **Issue:** `test_ic_engine_lifecycle_hook.py`'s fake cursor hardcoded the lifecycle SELECT's column list (no `regime_scope`), so `_lifecycle_guard_cells` raised KeyError on synthetic rows; `test_ic_engine_compute_split.py::test_compute_symbol_tf_return_keys` pinned `_compute_symbol_tf`'s exact parameter list, which Task 1 extended.
- **Fix:** Added `regime_scope` to the fake cursor's cols and the shared `_cell` fixture (mirroring the real SELECT contract), and `earnings_season_conditioned` to the expected-params list with a provenance comment.
- **Files modified:** `tests/unit/test_ic_engine_lifecycle_hook.py`, `tests/unit/test_ic_engine_compute_split.py`
- **Verification:** `pytest tests/unit/ -q` exits 0 (0 failures, 2 pre-existing skips)
- **Committed in:** `88ee5f2f7`

**3. [Rule 1 - tooling] Symlinked worktree `.venv` to the main repo's**
- **Found during:** Task 1, first commit attempt (pre-commit ruff/black hooks need `.venv/bin/` at the worktree root)
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv <worktree>/.venv` (gitignored, local-only). Same fix as 176-03's deviation 3.
- **Committed in:** N/A (not a git-tracked change)

---

**Total deviations:** 3 auto-fixed (2 Rule 1, 1 tooling). No architectural changes; all four `<threat_model>` mitigations applied (T-176-04-01/02/03 mitigate, T-176-04-04/SC accept). No package installs.

## Issues Encountered

- The RED runs fail at collection by design (ImportError for the not-yet-written symbols) -- expected TDD behavior, documented for the gate record.

## Known Stubs

None.

## Deferred Items (for 176-06/176-07 owners)

1. **Fingerprint tracking for earnings cells** needs migration 351's pass_type CHECK extension (176-07 owns the number). Until then earnings cells are first-write-final under ON CONFLICT DO NOTHING -- acceptable for this phase's measurement-only scope, wrong if anything ever promotes them without staleness detection.
2. **`_apply_feature_transitions` (Step 4/5) and the Step 2 loop** operate on all cell_rows. Both are provably benign today (earnings cells cannot reach the hook, and cannot be material fails), but 176-06's POOLED parent-qualified earnings cells WILL reach it -- the same `_lifecycle_guard_cells` exclusion must be applied to Step 4/5's aggregation at that point, and the demotion-fraction semantics of per-feature cells that mix scopes should be decided explicitly then.

## User Setup Required

None.

## Next Phase Readiness

- 176-06 (cross-sectional conditioning) can reuse the pass-tuple pattern and must revisit the two deferred items above
- 176-08 (dashboard/ops surface) can key off `regime_scope='earnings_season'` cells and the `ic_engine.earnings_season_pass_skipped` log event
- No blockers

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: `.planning/phases/176-earnings-season-calendar-primitive-todo-353/176-04-SUMMARY.md`
- FOUND: `73a27c42f` (Task 1 RED)
- FOUND: `d047c7606` (Task 1 GREEN)
- FOUND: `63bc5e4cd` (Task 2 RED)
- FOUND: `378fb2891` (Task 2 GREEN)
- FOUND: `88ee5f2f7` (Task 2 fixture ripple)
