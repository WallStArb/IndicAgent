---
phase: 166-frame-execution-recalibration
plan: 03
subsystem: trading
tags: [confluence, structural-candidate, apr, zone-engine-port, phase-163-dependent]

# Dependency graph
requires:
  - phase: 166-01
    provides: alpha.frame.cluster_radius_atr / single_level_radius_atr / zone_buffer_atr / min_width_atr / strength_weight / proximity_weight APR keys (migration 253, seeded and live)
  - phase: 163
    provides: sr_support_dist/sr_resist_dist/resistance_strength/support_strength/resistance_age_bars/support_age_bars/poc_dist_atr/poc_rolling_dist_atr/distance_to_vah_atr/distance_to_val_atr feature_vectors columns (NOT executed yet -- NULL_PENDING_163; this plan does not require live data, only Plan 166-06's runtime does)
provides:
  - src/intelligence/trading/structural_confluence.py -- v3-native ZoneCandidate/ZoneResult + resolve_structural_zone public API
  - collect_candidates() -- reconstructs S/R and VP price candidates from Phase-163 ATR-normalized distance fields
  - EXTENSION POINT for Phase 166 Part 2 (SMC/swing/fib/anchored-VWAP), pointing at todo 175
affects: [166-05, 166-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Direction-agnostic candidate reconstruction: both S/R sides and all VP fields are always reconstructed to prices, then filtered to the strict (stop, entry) window -- the reconstruction formula itself selects the relevant side, no direction-conditioned spec-table split needed (unlike zone_engine.py's _SUPPORT_SPECS/_RESISTANCE_SPECS)"

key-files:
  created:
    - src/intelligence/trading/structural_confluence.py
    - tests/unit/test_structural_confluence.py
  modified: []

key-decisions:
  - "collect_candidates always reconstructs both S/R sides (support AND resistance) and all 4 VP fields, then filters strictly to (stop, entry) -- simpler and more direction-agnostic than zone_engine.py's direction-conditioned _SUPPORT_SPECS/_RESISTANCE_SPECS split, made possible because the v3 price-reconstruction formula (entry +/- dist*atr) naturally lands the irrelevant side outside the window"
  - "_resolve_strength combines Phase-163 D-19's companion strength AND age_bars fields (averaged when both present) rather than using either alone -- interprets the plan's 'companion strength field (support_strength / *_age_bars)' instruction as both signals feeding one normalized quality score, not an either/or lookup"
  - "_find_clusters explicitly sorts candidates by price before the walk (zone_engine.py's analog relies on insertion order happening to be price-sorted after its dedup pass, which does not hold in general) -- a correctness improvement on the ported algorithm, not a deviation from the plan's intent"

patterns-established:
  - "Pattern: ATR-normalized-distance-to-price reconstruction (entry +/- dist*atr) as the general technique for any future Phase-163-style column that stores a signed/unsigned ATR distance instead of a raw price -- reusable for Phase 164/165's eventual SMC/swing/fib columns per the EXTENSION POINT"

requirements-completed: [D-01c, D-03, D-06]

# Metrics
duration: ~25min
completed: 2026-07-23
---

# Phase 166 Plan 03: Structural Candidate Part 1 (VP/S-R Confluence) Summary

**A new `src/intelligence/trading/structural_confluence.py` ports zone_engine.py's generic 3-tier confluence-resolution core (diverse-cluster confluence -> single-best -> ATR fallback) onto a fresh v3 candidate universe reconstructed entirely from Phase-163's ATR-normalized distance columns, with zero v2.x feature names and zero archived-tier imports.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-23T12:14:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (1 new module + 1 new test file)

## Accomplishments

- **Task 1:** Ported `ZoneCandidate`/`ZoneResult` dataclasses and the generic `_find_clusters`/`_source_diversity`/`_score_cluster`/`_pick_single_best` clustering-and-scoring core from `zone_engine.py` nearly unmodified (references no feature names). Implemented `_resolve_zone(candidates, entry, atr)` as the 3-tier resolution (diverse-cluster -> single-best -> `tier="atr"` empty fallback). Added a module-level `set_config_service`/`_read_config` pair reading fresh `alpha.frame.cluster_radius_atr`/`single_level_radius_atr`/`zone_buffer_atr`/`min_width_atr`/`strength_weight`/`proximity_weight` keys (all seeded live by migration 253 in Plan 166-01) -- zero reads of the archived `feature.zone_engine.*`/`weights.zone_engine.*` namespace.
- **Task 2:** Added a fresh v3 spec table populated ONLY with `sr_support_dist`/`sr_resist_dist` plus a VP reconstruction block for `poc_dist_atr`/`poc_rolling_dist_atr`/`distance_to_vah_atr`/`distance_to_val_atr`, all converted from ATR-normalized distances to prices via `entry +/- dist*atr` (Phase 163's D-16/D-18 design deliberately ships no raw price columns). `_resolve_strength` maps candidates to their D-19 companion `resistance_strength`/`support_strength`/`resistance_age_bars`/`support_age_bars` fields, normalized to 0.0-1.0, decaying to the spec default when absent. `collect_candidates`/`resolve_structural_zone` form the public API. An explicit `# EXTENSION POINT` comment marks where Phase 164/165's SMC/swing/fib/anchored-VWAP sources land (todo 175), and a comment flags RESEARCH.md's A2 ATR-consistency assumption at the price-reconstruction line.

## Task Commits

Each task was committed atomically:

1. **Task 1: Port ZoneCandidate + generic clustering/scoring core + config read** - `227a4727` (feat)
2. **Task 2: v3 spec table (Phase-163 fields), collect_candidates + public API + extension point** - `6db10abf` (feat)

**Plan metadata:** committed separately as part of this SUMMARY's own commit (worktree mode -- orchestrator handles final merge)

## Files Created/Modified

- `src/intelligence/trading/structural_confluence.py` - v3-native structural confluence module: `ZoneCandidate`/`ZoneResult` dataclasses, generic clustering/scoring core (`_find_clusters`/`_score_cluster`/`_pick_single_best`), 3-tier `_resolve_zone`, v3 spec table (`_SR_SPECS`/`_VP_SPECS`), `_resolve_strength`, `collect_candidates`, and the public `resolve_structural_zone` entry point.
- `tests/unit/test_structural_confluence.py` - 11 unit tests covering the generic core (Tests 1-4, 5 test functions) and the v3 spec table/candidate collection (Tests 5-9, 6 test functions, including the Pitfall 3 all-None regression guard). All fixtures use only Phase-163 field names.

## Decisions Made

- **collect_candidates reconstructs both sides unconditionally, then filters** (see key-decisions above) -- a deliberate simplification over zone_engine.py's direction-conditioned spec-table split, enabled by the price-reconstruction formula naturally excluding the irrelevant side.
- **`_resolve_strength` combines strength AND age** rather than treating them as alternative lookups for different candidate names -- the plan text listed both `support_strength` and `*_age_bars` as "companion fields" for the same candidate, which reads more naturally as "use both signals" than "pick one."
- **`_find_clusters` explicitly sorts by price** before clustering -- zone_engine.py's own version does not sort and only produces correct results because its upstream dedup pass happens to leave same-family candidates in price order; this port fixes that implicit assumption rather than reproducing it, since the new candidate universe (S/R + VP, not zone_engine's ~14-source spec table) has no equivalent ordering guarantee.

## Deviations from Plan

None - plan executed exactly as written. The three items above are implementation choices made within the plan's own stated flexibility (the plan's action text for `_resolve_strength` and `collect_candidates` described the required inputs/outputs and cited the shape to copy, not a byte-for-byte algorithm), not corrections to a bug or gap in the plan -- no deviation-rule classification applies.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 166-05 (wiring `structural_confluence` into `alpha_frame_writer.py`'s per-frame geometry call, per `166-PATTERNS.md`'s `AlphaFrameWriter` extension pattern) can proceed immediately -- `resolve_structural_zone(features, direction, entry, stop, atr)` is the stable public entry point, and all 7 `alpha.frame.*` threshold keys it reads are already live from migration 253.
- Plan 166-06's structural-candidate RUNTIME (as opposed to this plan's synthetic-fixture unit tests) remains gated on `/gsd-execute-phase 163` completing first, exactly as documented in 166-01-SUMMARY.md -- `sr_support_dist`/`sr_resist_dist`/etc. are still `NULL_PENDING_163` corpus-wide as of this plan's completion; this plan's own unit tests do not require live data and are unaffected.
- No blockers for this plan's own scope: the module is fully unit-tested (11 tests, exceeding the required minimum of 9), lints/formats clean, and grep-verified to reference zero archived-tier imports, zero archived config namespaces, and zero v2.x field names.

---
*Phase: 166-frame-execution-recalibration*
*Completed: 2026-07-23*

## Self-Check: PASSED

All created files verified present on disk (`structural_confluence.py`, `test_structural_confluence.py`,
this SUMMARY). Both task commits (`227a4727`, `6db10abf`) verified present in `git log --oneline --all`.
No missing items.
