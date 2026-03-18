---
phase: 037-cross-asset-intelligence-service
plan: 01
subsystem: services
tags: [kafka, redpanda, cross-asset, spread, z-score, correlation, microservice, prometheus]

requires:
  - phase: 036-microstructure-plugins
    provides: completed I7 plugin set (OFI/CVD) before adding cross-asset service dependency
  - phase: 038-automated-futures-roll-detection
    provides: topic_system_events() stream key pattern in stream_keys.py

provides:
  - topic_cross_asset() Kafka topic builder in src/core/stream_keys.py
  - cross_asset_enabled / cross_asset_window_bars / cross_asset_metrics_port Settings fields
  - src/intelligence/cross_asset_features.py — pure-function compute_eq_index_features()
  - services/cross_asset_service.py — CrossAssetService microservice
  - production/systemd/indicagent-cross-asset.service — systemd unit
  - development.cross_asset Redpanda topic with 7-day retention

affects:
  - 037-02 (next plan — I7 plugins that consume cross_asset topic features)
  - 037-03 (final plan — dashboard integration)

tech-stack:
  added: []
  patterns:
    - "Pure-function feature module pattern: src/intelligence/cross_asset_features.py
       contains all math (z-scores, Pearson corr, vol imbalance) with no I/O; service
       layer handles all Kafka/DB side effects"
    - "CROSS_ASSET_GROUPS dict pattern: extensible group config mapping group_name ->
       frozenset[base_symbols]; new groups (e.g. RATES, COMMODITIES) added by extending dict"
    - "Rolling window keyed by 'BASE:tf' string: enables O(1) lookup across all TFs
       per base symbol without nested dicts"
    - "TDD RED-GREEN cycle: tests written before implementation for all 35 test cases;
       verified failing before implementing"

key-files:
  created:
    - src/intelligence/cross_asset_features.py
    - services/cross_asset_service.py
    - production/systemd/indicagent-cross-asset.service
    - tests/unit/test_cross_asset_features.py
    - tests/unit/service_tests/test_cross_asset_service.py
  modified:
    - src/core/stream_keys.py (added topic_cross_asset)
    - src/config/settings.py (added 3 cross_asset_* fields)

key-decisions:
  - "Z-score computed from full spread series (window_bars values) rather than maintaining
     a separate rolling spread deque; simplifies API — callers pass close/vol deques and
     the function recomputes the spread series internally each call"
  - "5-bar log return used for spread computation (not 1-bar); gives more stable spreads
     less sensitive to single-bar noise; configurable via _SHORT_WINDOW constant"
  - "Pearson correlation computed on 1-bar log returns (not 5-bar) for corr_break;
     provides finer granularity for detecting regime shifts in correlation"
  - "Staleness gate: any symbol with last_bar_ts > 1 TF-interval old suppresses publish
     for that TF; data_quality_score reflects fraction of fresh symbols"
  - "CROSS_ASSET_ENABLED=false by default (shadow mode); service exits gracefully when
     disabled rather than sitting idle"
  - "Redpanda topic development.cross_asset created with retention.ms=604800000 (7 days)
     per CLAUDE.md requirement for all development.* topics"

patterns-established:
  - "Service __new__ test pattern: tests/unit/service_tests/test_cross_asset_service.py
     uses CrossAssetService.__new__(CrossAssetService) to bypass __init__; all instance
     attrs manually set in _make_service() helper"

requirements-completed: [XA-01, XA-02]

duration: 25min
completed: 2026-03-18
---

# Phase 037 Plan 01: Cross-Asset Service Infrastructure Summary

**Cross-asset microservice with spread z-score and correlation break features for EQ_INDEX group (ES/NQ/RTY/YM), subscribing to intelligence topic and publishing to development.cross_asset with 7-day retention**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-18T16:30:00Z
- **Completed:** 2026-03-18T16:55:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Pure-function `compute_eq_index_features()` computes 5-bar log return spread z-scores
  (ES/NQ and ES/RTY), Pearson correlation break (5-bar vs 20-bar window), and ES/NQ
  volume imbalance with full numpy-free implementation
- `CrossAssetService` follows canonical service lifecycle: SIGINT/SIGTERM handling,
  DB seed on startup from `intelligence_features`, rolling window management, staleness
  detection, dedup by (tf, ts), Prometheus metrics at port 9118
- 35 unit tests covering all behaviors (TDD RED-GREEN cycle); all passing
- Redpanda topic `development.cross_asset` created with `retention.ms=604800000`

## Task Commits

Each task was committed atomically:

1. **Task 1: Stream key + Settings fields + cross_asset_features module** - `0b46781` (feat)
2. **Task 2: CrossAssetService + systemd unit + Redpanda topic** - `36e7f32` (feat)

**Plan metadata:** (this SUMMARY commit)

## Files Created/Modified

- `src/core/stream_keys.py` — added `topic_cross_asset()` Kafka topic builder
- `src/config/settings.py` — added `cross_asset_enabled`, `cross_asset_window_bars`, `cross_asset_metrics_port` fields
- `src/intelligence/cross_asset_features.py` — pure-function feature computation module
- `services/cross_asset_service.py` — CrossAssetService microservice (~300 lines)
- `production/systemd/indicagent-cross-asset.service` — systemd unit with PYTHONUNBUFFERED=1
- `tests/unit/test_cross_asset_features.py` — 20 unit tests for feature module
- `tests/unit/service_tests/test_cross_asset_service.py` — 15 unit tests for service

## Decisions Made

- Z-score computed by recomputing spread series from close windows on each call (not a
  separate maintained spread deque) — simpler API; callers only manage close/vol deques
- 5-bar log return for spread computation, 1-bar for correlation analysis (different
  granularity tradeoffs for each metric)
- Staleness gate: any stale symbol suppresses publish rather than degrading quality;
  data_quality_score tracks fresh fraction for observability
- Service exits cleanly when CROSS_ASSET_ENABLED=false rather than blocking

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test for low_vol_flag with alternating prices**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** Test used alternating prices (i%2)*val for all 4 symbols; ES and RTY had
  proportionally identical alternating patterns making their spread always exactly 0 =>
  std=0 => low_vol_flag always True, defeating the test intent
- **Fix:** Changed test to use persistent drift (ES +1.0/bar, NQ flat, RTY -0.5/bar)
  which produces genuinely varying spreads with non-zero std
- **Files modified:** tests/unit/test_cross_asset_features.py
- **Verification:** Test passes, low_vol_flag correctly False
- **Committed in:** 0b46781 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test data bug)
**Impact on plan:** Minor test data fix; no production code affected. No scope creep.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required for this plan. Service disabled by
default (CROSS_ASSET_ENABLED=false). To enable in production: add
`CROSS_ASSET_ENABLED=true` to the service environment, then:
```bash
sudo cp production/systemd/indicagent-cross-asset.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now indicagent-cross-asset
```

## Next Phase Readiness

- Phase 037-02 can begin: I7 plugins that read cross_asset features from the
  `development.cross_asset` topic are unblocked
- Service infrastructure (topic, stream key, Settings, unit file) is production-ready
- Feature computation verified correct with 20+ unit tests

---
*Phase: 037-cross-asset-intelligence-service*
*Completed: 2026-03-18*
