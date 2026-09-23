---
phase: 176-earnings-season-calendar-primitive-todo-353
plan: "06"
subsystem: intelligence
tags: [ic-engine, cross-sectional, stratification, memory-guard, apr]

# Dependency graph
requires:
  - phase: 176-01
    provides: "D-01a gate evidence: SWEEP_VERDICT=CONFIRMED, 31 non-empty SWEEP_SURVIVORS (176-EVIDENCE-A1.md)"
  - phase: 176-04
    provides: "_earnings_season_labels, ICEngineConfig.earnings_season_conditioned (alpha.ic.earnings_season_conditioned), the per-symbol earnings_season stratification pass this plan mirrors on the cross-sectional path"
  - phase: 176-05
    provides: "ensemble_trainer/consumer-audit exclusion of regime_scope='earnings_season' -- guarantees this plan's new cross-sectional cells cannot leak into ensemble weighting or alpha emission"
provides:
  - "_plan_season_subcells: pure planner deciding which cross-sectional earnings-season sub-cells to compute from an already-materialized cell, with four named skip reasons"
  - "_compute_one_cross_sectional_cell(resolved_regime_scope=...): parameterized regime_scope stamp, default preserves every pre-176 caller"
  - "Season sub-cell loop in _compute_cross_sectional_tf: two extra row-sliced (never re-fetched) sub-cells per eligible cell, under regime_scope='earnings_season', with per-cell memory/row-count telemetry (ic_engine.season_subcell_pass)"
affects: [176-07, 176-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Post-materialization in-memory row masking + re-invocation of an existing per-cell compute function, instead of a third DB-fetch dimension -- reuses 100% of bootstrap/CI/FDR/walk-forward internals"
    - "Parent-qualified sub-cell labels (f'{parent}__{suffix}') as a workaround for a uniqueness key that omits the stratification-scope column (todo 391)"
    - "Per-cell (not per-row) structlog telemetry carrying byte-size/row-count fields so an unmeasured memory-risk question gets a real answer on the first corpus run, per docs/foundation/performance-investigation-sop.md"

key-files:
  created: []
  modified:
    - services/ic_engine.py
    - tests/unit/services/test_ic_engine.py

key-decisions:
  - "Season sub-cell rows enter the SAME corpus-level BH-FDR family as the primary and broadcast rows (D-07 precedent, same decision the broadcast cell already made in Phase 173 Plan 04): they are appended into the same all_results list the cluster-representative-selection loop iterates over below, and their parent-qualified regime label already differs from the parent's own label, so the existing (regime, lookahead_bars, cluster_id) grouping key gives them their own representative-selection group with zero extra machinery -- no separate FDR pass, no new table."
  - "Disk-backed cells (use_disk=True) skip the season split entirely rather than row-slicing a memmap-backed X_raw -- the parent cell is already at the memory ceiling by definition (todo 371's OOM shape), and a boolean-mask slice would materialize a fresh in-RAM copy of roughly half the cell on top of everything already resident. Skipped loudly (disk_backed_cell skip reason, logged), not silently."
  - "min_rows for the per-season sufficiency check is config.min_reliable_n (the project's existing reliability gate), not a new threshold -- each season subset below it is dropped individually; the other season may still be returned."
  - "The four skip reasons (apr_disabled, disk_backed_cell, flag_column_all_null, subset_below_min_n) are evaluated in that priority order inside _plan_season_subcells, and are exact string values asserted by tests -- 176-08's corpus run can grep the ic_engine.season_subcell_pass log for these without guessing at free-text messages."

requirements-completed: [ES-05]

# Metrics
duration: 18min
completed: 2026-09-23
---

# Phase 176 Plan 06: Cross-Sectional Earnings-Season IC Stratification Summary

**Cross-sectional cells now measure IC separately for in-season and off-season rows via post-materialization row masking (never a re-fetch), reusing `_compute_one_cross_sectional_cell` verbatim with a new `resolved_regime_scope` parameter, gated by a memory guard that skips disk-backed cells and logs per-cell byte-size telemetry.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-09-23T17:02:51-04:00 (worktree base commit)
- **Completed:** 2026-09-23T17:20:08-04:00
- **Tasks:** 2 (both TDD RED/GREEN)
- **Files modified:** 2

## Gate Record (D-01a)

Executed only after reading `176-EVIDENCE-A1.md`: `SWEEP_VERDICT=CONFIRMED` with 31 non-empty `SWEEP_SURVIVORS` -- PROCEED condition met (per the orchestrator's pre-execution instruction and independently re-confirmed by grep against the evidence doc before Task 1 began).

## Accomplishments

- `_plan_season_subcells(flag_column, parent_regime_label, *, enabled, use_disk, min_rows)` is a pure, DB-free helper that decides, per already-materialized cross-sectional cell, which season sub-cells (if any) to compute and why any were skipped -- four named skip reasons (`apr_disabled`, `disk_backed_cell`, `flag_column_all_null`, `subset_below_min_n`), parent-qualified labels (`{parent}__in_season`/`{parent}__off_season`), disjoint masks whose union excludes only NaN-flag rows.
- `_compute_one_cross_sectional_cell` gained a `resolved_regime_scope: str = "cross_sectional"` keyword parameter, replacing a hardcoded literal in its emitted row dict; the default preserves every existing caller's behavior byte-for-byte (verified: with the APR switch off, exactly one call happens per cell, same as before this plan).
- `_compute_cross_sectional_tf` now calls `_plan_season_subcells` immediately after the broadcast-cell call (inside the same `try`, before the `finally` that unlinks the memmap) and re-invokes `_compute_one_cross_sectional_cell` once per returned season entry with row-sliced (never re-fetched) `X_raw`/`returns_mat`/`complete_mat` arrays and `resolved_regime_scope="earnings_season"`. Each sliced subset is deleted before the next iteration so at most one subset copy is resident at a time.
- One `ic_engine.season_subcell_pass` log line per parent cell (never per row) carries `tf`, `regime`, `n_subcells`, `skipped`, `use_disk`, `n_parent_rows`, `n_in_season`, `n_off_season`, `x_raw_mb`, and `subset_peak_mb` -- the memory-risk measurement this plan's objective calls for, ready for 176-07/176-08's real corpus run to populate with real numbers.
- The two pre-existing duplicate "two invariants" comment blocks above the function's `try:` were both updated to name the season calls as a third synchronous, non-reference-holding consumer of `X_raw`; the "last consumer of X_raw" comment on the broadcast-cell call was updated to point at the season loop instead.
- 20 new DB-free tests (11 planner-behavior tests in Task 1, 9 wiring/scope/telemetry tests in Task 2 using a recording-stub + fake-connection pattern mirrored from `tests/unit/test_ic_engine_cell_memory_bound.py`'s established fixtures).

## Task Commits

Each task committed atomically through the RED/GREEN gates:

1. **Task 1 RED** - `06c876393` (test): failing tests for the season-subcell planner helper
2. **Task 1 GREEN** - `48dc4e104` (feat): `_plan_season_subcells` implementation
3. **Task 2 RED** - `3e3293f09` (test): failing tests for season sub-cell wiring into `_compute_cross_sectional_tf`
4. **Task 2 GREEN** - `9278517b1` (feat): wired season sub-cells + `resolved_regime_scope` parameterization

_Both tasks proved RED by temporarily reverting the implementation half of the working tree, running the new tests to confirm they failed for the expected reason (ImportError for Task 1, wrong call-count assertion for Task 2), committing the test-only diff, then restoring and re-verifying GREEN before committing the implementation. No REFACTOR commit was needed for either task -- implementation was clean on first pass once RED was proven._

## Files Created/Modified

- `services/ic_engine.py` -- `_plan_season_subcells` (new, between `_earnings_season_labels` and `_build_regime_passes`), `_compute_one_cross_sectional_cell`'s new `resolved_regime_scope` parameter + docstring note + row-dict change, `_compute_cross_sectional_tf`'s new season-sub-cell loop + `ic_engine.season_subcell_pass` log call + updated invariant/last-consumer comments
- `tests/unit/services/test_ic_engine.py` -- 11 tests for `_plan_season_subcells` (both-seasons/disk-backed/apr-disabled/all-null/below-min-n-single/below-min-n-both/parent-qualified-labels/disjoint-masks/reuse-discipline), 9 tests for the wiring (call-count with APR on/off, output-row scope/label correctness, disk-backed skip, telemetry-log field completeness, skip-without-raise, structural call-ordering guard, `resolved_regime_scope`/literal-count guard), plus new fake-connection/recording-stub fixtures (`_CsFakeConn`/`_CsFakeCursor`/`_cs_patch_*`/`_cs_call`/`_cs_config`/`_cs_season_batch`)

## BH-FDR Family Decision (Task 2 acceptance requirement)

Season sub-cell rows enter the **same** corpus-level BH-FDR family as the primary and broadcast rows for this cell -- no separate FDR pass, no new table. Provenance: this mirrors the decision Phase 173 Plan 04 (D-07) already made for broadcast rows in this exact function -- both broadcast and season rows are appended into the same `all_results` list the cluster-representative-selection loop (immediately after the `finally` block) iterates over, and both rely on the SAME grouping key, `(r["regime"], r["lookahead_bars"], cid)`, to keep their representative-selection group separate from the parent cell's own rows: broadcast rows do it via a `cluster_id` offset (`_BROADCAST_CLUSTER_ID_OFFSET`), season rows do it via their parent-qualified `regime` label already differing from the parent's own label. No new grouping mechanism was needed.

## Decisions Made

See `key-decisions` in frontmatter above.

## Deviations from Plan

None -- plan executed exactly as written. The interfaces section's line-number references (~4466, ~3762-3805, etc.) had drifted from the plan's authoring session (176-01 through 176-05's own edits shifted line numbers), consistent with the plan's own "grep for names, not line numbers" caveat; no functional deviation resulted.

## Issues Encountered

One self-caught authoring bug, fixed before any commit: the `_compute_one_cross_sectional_cell` docstring addition for `resolved_regime_scope` originally quoted the literal string `"cross_sectional"` in prose, which pushed the function's total occurrence count of that literal to 2 and would have failed the plan's own `s.count('"cross_sectional"') <= 1` acceptance check. Reworded to `cross_sectional string literal` (no quotes) before the first commit of Task 2's GREEN phase -- caught by running the acceptance check locally, not shipped.

## Known Stubs

None. Both cell calls (planner + wiring) are real, executable code paths -- verified against `services/ic_engine.py`'s live `_FEATURE_NAMES`-ordered column contract, not mocked beyond the DB connection layer in tests.

## Threat Flags

None new beyond this plan's own `<threat_model>` (T-176-06-01 through T-176-06-05, all `mitigate`, all addressed by the implementation as designed -- no new network endpoints, auth paths, or schema changes; T-176-06-SC `accept`, no package installs in this plan).

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- Plan 176-07 (fingerprint/backfill plumbing, migration 351 owner) and Plan 176-08 (corpus run + dashboard/ops surface) can now key off `regime_scope='earnings_season'` cross-sectional cells the same way 176-04's per-symbol cells already work, plus the `ic_engine.season_subcell_pass` log event for the real memory/cost measurement this plan's objective calls for.
- Per 176-04's own deferred-items note (item 2), the Step 4/5 `_apply_feature_transitions` aggregation and the Step 2 material-fail loop currently only ever see per-symbol earnings cells (which cannot reach them by construction) -- this plan's new POOLED cross-sectional earnings cells (`symbol='POOLED', is_pooled=true`) WILL reach those hooks. `_lifecycle_guard_cells` already excludes `regime_scope='earnings_season'` at its own call site (Step 3), but whichever plan first runs a real corpus pass with these cells live should re-verify Step 4/5's per-feature aggregation semantics for a feature whose cell_rows now mix `cross_sectional`/`symbol_hmm`/`earnings_season` scopes -- flagging forward per 176-04's own note, not fixed in this plan (out of this plan's stated scope: code + unit tests only, no live corpus run).
- No blockers. `pytest tests/unit/ -q` is green (0 failures, 2 pre-existing unrelated skips) with no regressions from this plan's additions. `ruff check`/`black --check` clean on both modified files.

---
*Phase: 176-earnings-season-calendar-primitive-todo-353*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: `services/ic_engine.py` contains `_plan_season_subcells`, `resolved_regime_scope`, `ic_engine.season_subcell_pass`
- FOUND: `tests/unit/services/test_ic_engine.py` contains the new planner + wiring test sections
- FOUND: commit `06c876393` (Task 1 RED)
- FOUND: commit `48dc4e104` (Task 1 GREEN)
- FOUND: commit `3e3293f09` (Task 2 RED)
- FOUND: commit `9278517b1` (Task 2 GREEN)
