---
phase: 116-sr-consensus
plan: "02"
subsystem: zone_engine
tags: [zone-engine, sr-candidates, vp-direction, hvn-strength, public-api]
dependency_graph:
  requires: [116-01]
  provides: [collect_sr_candidates, find_best_level, _SR_VP_DIRECTION]
  affects: [sr_consensus plugin (116-03)]
tech_stack:
  added: []
  patterns:
    - SR-semantic VP direction dict separate from trade-semantic VP direction dict
    - dist_atr inversion: 1/(1+val) maps HVN distance to strength (closer = higher)
    - Public wrapper function (find_best_level) hides private clustering internals
key_files:
  created: []
  modified:
    - src/intelligence/trading/zone_engine.py
    - tests/unit/trading/test_zone_engine.py
decisions:
  - _SR_VP_DIRECTION is a separate dict from _VP_DIRECTION; both coexist with distinct semantics
  - find_best_level is public API so consumers (sr_consensus) never import private internals
  - collect_sr_candidates uses passed atr argument for dedup (does not call get_atr internally)
metrics:
  duration_minutes: 3
  completed_date: "2026-06-05"
  tasks_completed: 2
  files_modified: 2
---

# Phase 116 Plan 02: Zone Engine SR Candidate Extension Summary

Extended `zone_engine` to cover 6 missing structural sources per direction, added `_SR_VP_DIRECTION` for correct SR-semantic VP field selection, and exposed `collect_sr_candidates` + `find_best_level` as public API for the Step 3 consensus plugin.

## What Was Built

### Task 1: Spec extensions, _SR_VP_DIRECTION, dist_atr strength handler

**`_SUPPORT_SPECS` now includes 6 new sources:**
- `nearest_fib_level` ("fib", 0.6, i3, fib)
- `prior_session_low` ("prior_sess_l", 0.7, i3, session)
- `asian_session_low` ("asian_l", 0.6, i3, session)
- `nearest_hvn_below` ("hvn_below", 0.8, i4, vp_hvn)
- `avwap_lower_band` ("avwap_lower", 0.6, i4, avwap)
- `kc_mid_20` ("kc_mid", 0.5, i1, ma_kc)

**`_RESISTANCE_SPECS` now includes 6 symmetric new sources** (nearest_fib_level, prior_session_high, asian_session_high, nearest_hvn_above, avwap_upper_band, kc_mid_20).

**`_STRENGTH_FIELD`** updated to `dict[str, str | None]` with new entries: fib -> fib_cluster_strength, hvn_below/hvn_above -> nearest_hvn_dist_atr, session/AVWAP/KC entries -> None (use default strength).

**`_SR_VP_DIRECTION`** added alongside (not replacing) `_VP_DIRECTION`:
- `_VP_DIRECTION` (trade-semantic): direction=1 (long) -> val/hvn_below (support side)
- `_SR_VP_DIRECTION` (SR-semantic): direction=1 (resistance) -> vah/hvn_above (above-price fields)

**`_resolve_strength` dist_atr branch**: `if "dist_atr" in key: return min(1.0, 1.0 / (1.0 + val))` - closer HVN node gets higher strength score.

Commit: `ea794ccd`

### Task 2: collect_sr_candidates + find_best_level + VP direction tests

**`collect_sr_candidates(features, direction, price, atr, max_dist)`:**
- direction=-1 (support): bounds = `[price - max_dist, price]`, specs = `_SUPPORT_SPECS`
- direction=1 (resistance): bounds = `[price, price + max_dist]`, specs = `_RESISTANCE_SPECS`
- VP block uses `_SR_VP_DIRECTION[direction]` (NOT `_VP_DIRECTION`) ensuring support candidates only see val/hvn_below and resistance candidates only see vah/hvn_above
- Raises `ValueError` for direction not in {-1, 1}
- Returns deduped candidates sorted by price ascending

**`find_best_level(candidates, atr, price)`:**
- Public wrapper over `_find_clusters` / `_source_diversity` / `_pick_single_best`
- Prefers structurally diverse cluster (2+ source_tiers); returns `ZoneCandidate(name="consensus")` with cluster mean price
- Falls back to `_pick_single_best` when no diverse cluster exists
- Returns `None` on empty candidate list

**9 new tests added** covering:
- VP direction correctness: direction=-1 excludes vah; direction=1 excludes val
- Support bounds: all candidates in `[price-max_dist, price]`
- Resistance bounds: all candidates in `[price, price+max_dist]`
- max_dist exclusion: feature at price+max_dist+1 excluded
- Invalid direction (0) raises ValueError
- find_best_level: empty returns None, single returns ZoneCandidate, multi-source returns consensus with mean price

Commit: `e7dd5d2a`

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

### Files exist:
- `src/intelligence/trading/zone_engine.py` - FOUND
- `tests/unit/trading/test_zone_engine.py` - FOUND

### Commits exist:
- `ea794ccd` - FOUND (feat(116-02): extend zone_engine specs...)
- `e7dd5d2a` - FOUND (feat(116-02): add collect_sr_candidates...)

### Test results: 21 passed in 0.09s

## Self-Check: PASSED
