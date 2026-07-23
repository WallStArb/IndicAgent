---
phase: 166-frame-execution-recalibration
plan: 05
subsystem: alpha-scoring
tags: [alpha-frames, structural-confluence, apr-config, timescaledb, asyncpg, config-service]

# Dependency graph
requires:
  - phase: 166-01
    provides: alpha.frame.stop_atr_mult.<regime>.<tf>/target_r_multiple.<regime>.<tf> APR namespace (72 keys), alpha.frame.geometry_source selector key (migration 253), structural-confluence threshold keys (cluster_radius_atr/single_level_radius_atr/zone_buffer_atr/min_width_atr/strength_weight/proximity_weight)
  - phase: 166-02
    provides: "_calibrate_stop_target() (services/ensemble_ic_engine.py) -- the mechanism that WRITES the per-(regime,tf) keys this plan's per_cell_scalar mode reads at runtime"
  - phase: 166-03
    provides: "src/intelligence/trading/structural_confluence.py -- ZoneCandidate/ZoneResult/resolve_structural_zone/set_config_service, the v3-native confluence resolution this plan wires into the writer"
provides:
  - "AlphaFrameWriter geometry_source dispatch (global | per_cell_scalar | structural) -- services/alpha_frame_writer.py"
  - "_resolve_scalar_geometry() / _resolve_structural_geometry() / _resolve_row_geometry() -- pure geometry-resolution functions, unit-testable without DB"
  - "_fetch_structural_market_data() / _fetch_structural_features() -- per-partition bulk fetches (causal scan-time ATR from market_data_ohlcv_tradeable, Phase-163 feature columns from feature_vectors)"
  - "_build_structural_config_service() -- cache-only ConfigService wiring structural_confluence's threshold reads from the already-loaded APR dict"
affects: [166-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "geometry_source dispatch: a per-(regime,tf) scalar resolution function shared by both per_cell_scalar and structural (the latter as a bounding seed), mirroring the existing hold_key lookup pattern"
    - "Bulk-fetch-once-per-partition for structural inputs (causal ATR window function query + feature_vectors SELECT *), never a per-row round trip -- gated entirely to geometry_source == 'structural'"
    - "Cache-only ConfigService construction from an already-loaded APR dict (mirrors services/_batch_utils.py's load_config_service_sync), avoiding a second DB round trip to wire a sibling module's config singleton"

key-files:
  created:
    - tests/unit/test_alpha_frame_writer_candidate_geometry.py
  modified:
    - services/alpha_frame_writer.py
    - tests/unit/test_alpha_frame_writer.py

key-decisions:
  - "structural mode never computes a live entry/stop/target price in the writer -- it derives an EFFECTIVE stop_atr_mult RATIO (structural stop distance / ATR) and snapshots that ratio onto the same stop_atr_mult column the writer has always written; CounterfactualTracker's own T+1 geometry computation (compute_frame_geometry, unchanged) consumes that snapshotted ratio exactly as it always has"
  - "entry_price for structural zone resolution is the alpha_event's own bar_ts close (a scan-time proxy), not the true T+1 execution entry CounterfactualTracker computes independently -- sufficient because only the resulting ATR-relative ratio is persisted, not a raw price (RESEARCH.md A2 flags the ATR-consistency assumption for a live spot-check in Plan 166-06)"
  - "'the near bound on the stop side' (166-05-PLAN.md) resolved as zone_low for long / zone_high for short -- the zone bound farther from entry, mirroring trade_framer.py's own 'stop < zone_low' convention for a support-side zone"
  - "structural_confluence's config singleton is wired via a cache-only ConfigService built directly from the already-loaded alpha.* APR dict (no second DB round trip), not the async pool-backed ConfigService pattern other batch services use"
  - "feature_vectors fetch uses SELECT * rather than an explicit Phase-163 column list, keeping ownership of which structural column names exist entirely inside structural_confluence.py's spec table"

patterns-established:
  - "Pattern: cache-only ConfigService construction from an already-loaded raw APR dict, for wiring a sibling module's set_config_service() singleton without a second DB fetch"

requirements-completed: [D-01b, D-01c, D-03]

# Metrics
duration: ~55min
completed: 2026-07-23
---

# Phase 166 Plan 05: Wire Both Candidates into AlphaFrameWriter Summary

**AlphaFrameWriter now dispatches on `alpha.frame.geometry_source` (global | per_cell_scalar | structural), resolving per-(regime,tf) or structural-confluence-derived stop_atr_mult/target_r_multiple scalars and snapshotting them onto each `alpha_frames` row at scan time -- `global` remains byte-identical to pre-166-05 behavior.**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-07-23T12:51:38Z
- **Tasks:** 2/2 completed
- **Files modified:** 3 (2 modified, 1 created)

## Accomplishments

- **Task 1:** `FrameConfig.from_apr` now reads and eagerly validates `alpha.frame.geometry_source` (default `"global"`, one of global/per_cell_scalar/structural, `ValueError` otherwise). Added `_resolve_scalar_geometry()`, mirroring the existing `hold_key` per-(regime,tf) lookup pattern exactly for `alpha.frame.stop_atr_mult.{regime}.{tf}`/`target_r_multiple.{regime}.{tf}`, each falling back to the global scalar when the per-cell key is absent. Missing keys accumulate into `missing_stop_keys`/`missing_target_keys` sets, warned once per partition (never per row).
- **Task 2:** Added the `structural` branch: `_resolve_structural_geometry()` calls `structural_confluence.resolve_structural_zone` with a scalar-seed-derived stop bounding the candidate search window, derives an effective `stop_atr_mult` ratio from the resolved zone's bound "on the stop side," and falls back to the scalar seed when the confluence tier is `"atr"` (no usable candidates -- e.g. before Phase 163 executes). `compute_frame_geometry`'s degenerate-stop-distance `ValueError`-skip contract (todo 162) is preserved for both the scalar seed and the final effective geometry. Two new per-partition bulk fetches (`_fetch_structural_market_data`, `_fetch_structural_features`) supply entry/ATR and Phase-163 feature columns, gated entirely to `geometry_source == "structural"` -- zero extra queries or behavior change for the other two modes.

## Task Commits

Each task was committed atomically:

1. **Task 1: geometry_source dispatch + per_cell_scalar lookup with fallback** - `7252f50a` (feat)
2. **Task 2: structural geometry mode via structural_confluence** - `5c85aa67` (feat)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode -- orchestrator handles final merge)

## Files Created/Modified

- `services/alpha_frame_writer.py` - `FrameConfig.geometry_source` field + validation; `_resolve_scalar_geometry`/`_resolve_structural_geometry`/`_resolve_row_geometry` pure dispatch functions; `_fetch_structural_market_data`/`_fetch_structural_features`/`_build_structural_config_service` async/sync helpers; `_process_partition` now resolves geometry per row via the dispatch and snapshots the resolved scalars (was: the constant global `frame_config` values); `compute_expected_r_snapshot` now uses the per-row resolved `target_r_multiple`.
- `tests/unit/test_alpha_frame_writer_candidate_geometry.py` - 22 new unit tests: geometry_source validation, global byte-identical regression, per_cell_scalar lookup/fallback/accumulation, structural zone derivation (long + short), tier="atr" fallback, degenerate-stop skip (both the scalar-seed and post-resolution guard), exact effective-ratio formula cross-check, dispatch-level market-data-missing fallback, and source guards (no second write path, config wired once at init).
- `tests/unit/test_alpha_frame_writer.py` - Updated 2 pre-existing regression tests (`test_no_feature_vectors_read` -> `test_feature_vectors_read_gated_to_structural_geometry_source`; `test_no_sr_resist_dist_branch` -> `test_no_sr_resist_dist_column_named_directly`) to reflect the new, gated, opaque `feature_vectors` read.

## Decisions Made

See `key-decisions` in frontmatter above. Notably: the writer only ever persists a dimensionless `stop_atr_mult` ratio for the structural candidate, never a raw structural price -- the real T+1 entry/stop/target computation stays entirely CounterfactualTracker's job, unchanged. This keeps DAG Invariant 3 intact (no second inline persistence path) and matches the snapshot-vs-live-APR discipline established in Phase 142B.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Two pre-existing regression tests required updating, not just extending**
- **Found during:** Task 2, first full-suite run
- **Issue:** `tests/unit/test_alpha_frame_writer.py::test_no_feature_vectors_read` and `::test_no_sr_resist_dist_branch` asserted the writer NEVER reads `feature_vectors` and never names `sr_resist_dist` -- both constraints Task 2's own action text explicitly requires relaxing (structural mode legitimately reads `feature_vectors` for Phase-163 columns). Left unmodified, both tests would fail after Task 2's implementation, and skipping them would leave the suite red.
- **Fix:** Renamed and rewrote both tests to assert the NEW, narrower invariant: the `feature_vectors` read is gated to `geometry_source == "structural"` via a dedicated helper (not unconditional), ATR itself is still never a `feature_vectors` column (H2's original constraint, unchanged), and no individual Phase-163 column name is ever referenced literally in `alpha_frame_writer.py` (the new `_STRUCTURAL_FEATURES_SQL` uses `SELECT *`, keeping that ownership boundary inside `structural_confluence.py`'s own spec table).
- **Files modified:** `tests/unit/test_alpha_frame_writer.py`
- **Verification:** Full `tests/unit/` suite green after the rewrite; both updated tests pass and still meaningfully guard the narrowed invariant.
- **Committed in:** `5c85aa67` (Task 2 commit)

**2. [Implementation-detail decision, not a deviation] Data plumbing for `entry_price`/`atr`/`features` at write time**
- **Found during:** Task 2 design
- **Issue:** The plan's action text names the call shape (`resolve_structural_zone(features, direction, entry_price, scalar_stop_seed, atr)`) but `AlphaFrameWriter` had never previously computed or fetched any of these three inputs -- `_process_partition` worked entirely off `alpha_events` with no join to price/feature data.
- **Resolution (not a deviation -- filling in an unspecified implementation detail consistent with the plan's own guidance to compute ATR "the same way AlphaFrameWriter already computes it [i.e., independently from `market_data_ohlcv_tradeable`, per 166-PATTERNS.md]"):** Added two per-partition bulk fetches, gated to `geometry_source == "structural"` only: a causal, scan-time ATR (simple moving average of true range, same methodology as `CounterfactualTracker`'s `_true_range`/`tr_window`) computed via a window-function query over `market_data_ohlcv_tradeable`, and a `feature_vectors` fetch for the Phase-163 structural columns. `entry_price` is the alpha_event's own bar close (a scan-time proxy, not the true T+1 execution entry) -- documented in both the module docstring and `key-decisions` above, and flagged for a live spot-check in Plan 166-06 per RESEARCH.md's A2 note.
- **Files modified:** `services/alpha_frame_writer.py`
- **Verification:** Both async fetch functions verified directly against live data (`SPY`/`1d`: 5,032 market-data rows, 4,780 feature rows fetched correctly); the full `_build_structural_config_service` -> `set_config_service` -> `resolve_structural_zone` chain verified end-to-end against live APR config (empty-features case correctly returns `tier="atr"`).

---

**Total deviations:** 1 auto-fixed (Rule 3, test-suite consistency), 1 implementation-detail decision (not a plan violation, documented for traceability)
**Impact on plan:** Zero scope creep. Both items are necessary consequences of Task 2's own explicit requirements (reading `feature_vectors`, computing ATR independently) rather than unplanned work.

## Issues Encountered

None beyond the items documented under Deviations above. Full unit suite (`tests/unit/ -q`) green throughout both tasks and after the final restore; ruff and black clean on every commit.

## User Setup Required

None - no external service configuration required. `geometry_source` defaults to `"global"` (current production behavior, unchanged); switching to `per_cell_scalar` or `structural` is an APR config change for Plan 166-06's live comparison run.

## Next Phase Readiness

- Plan 166-06 can now run `AlphaFrameWriter --backfill` under all three `geometry_source` values (`global`, `per_cell_scalar`, `structural`) to regenerate a distinct OOS frame population per candidate for the validation gate to score.
- The structural candidate's live runtime remains gated on Phase 163 execution (`sr_support_dist`/`sr_resist_dist` still `NULL_PENDING_163` as of this plan's completion, per 166-01-SUMMARY.md and 166-03-SUMMARY.md) -- when `NULL_PENDING_163`, `resolve_structural_zone` returns `tier="atr"` for every row and the structural candidate degrades to the scalar seed for 100% of frames (verified live against the current corpus state: `resolve_structural_zone({}, 1, 100.0, 97.0, 2.0)` -> `tier="atr"`). Plan 166-06 must verify Phase 163 has executed and check the non-fallback fraction before treating a structural gate result as meaningful (already flagged in 166-06-PLAN.md's own Task 2).
- RESEARCH.md's A2 ATR-consistency assumption (this writer's independently-computed scan-time ATR vs. the ATR normalizing Phase-163's distance columns) is unverified against live data -- explicitly deferred to Plan 166-06's live spot-check, as originally scoped.
- No blockers introduced. Full unit suite remains green post-merge.

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*

## Self-Check: PASSED

All created/modified files verified present on disk (`services/alpha_frame_writer.py`,
`tests/unit/test_alpha_frame_writer_candidate_geometry.py`,
`tests/unit/test_alpha_frame_writer.py`, this SUMMARY). All 3 commits (`7252f50a`, `5c85aa67`,
`15b95a23`) verified present in `git log --oneline --all`. No missing items.
