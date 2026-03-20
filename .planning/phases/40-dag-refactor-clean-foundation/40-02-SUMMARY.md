---
phase: 40-dag-refactor-clean-foundation
plan: 02
subsystem: intelligence
tags: [dag, pipeline, stages, kafka, signal-processing, circuit-breaker, attribution, enums]

# Dependency graph
requires:
  - phase: 40-01
    provides: Stage base class, CircuitBreaker, DataQualityMonitor
  - phase: 39
    provides: SignalStatus/SignalOutcome enums
provides:
  - QualityGateService — applies Hurst×Entropy and drift penalty to signal confidence
  - RegimeGateService — gates signals based on HMM regime (prob/duration/type)
  - TODAdjusterService — applies 120-cell (regime_type, tf, hour_et) TOD multipliers
  - CalibratorService — applies isotonic regression calibration curves per (plugin_name, tf)
  - RankerService — computes adjusted_rank = priority × perf_multiplier
  - WinnerSelectorService — CIS override or priority/majority tiebreak winner selection
  - All 6 stage services inherit from Stage base class with circuit breaker + attribution
affects: [40-03, 40-04, signal_generator_service, aggregator]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stage constructor pattern: inject KafkaConsumerClient/KafkaProducerClient from Settings"
    - "Attribution pattern: attribution_reason + attribution_inputs dict on every processed event"
    - "Enum enforcement: WinnerSelectorService uses SignalStatus.PENDING.value — never raw strings"
    - "Quality gate pattern: min(hurst_quality, entropy_quality) * drift_penalty"
    - "Regime gate pattern: priority order prob -> duration -> type"
    - "CIS override pattern: boost confidence 0.05 per additional agreeing plugin"

key-files:
  created:
    - src/intelligence/stages/quality_gate.py
    - src/intelligence/stages/regime_gate.py
    - src/intelligence/stages/tod_adjuster.py
    - src/intelligence/stages/calibrator.py
    - src/intelligence/stages/ranker.py
    - src/intelligence/stages/winner_selector.py
  modified:
    - src/intelligence/stages/__init__.py
    - src/core/stream_keys.py

key-decisions:
  - "drift_penalty sourced from event.features (pre-computed float) not DRIFT_PENALTIES dict import — avoids tight coupling to ks_drift_monitor.py"
  - "QualityGateService uses min(hurst, entropy) not product — correlated measures, min is more conservative"
  - "WinnerSelectorService buffers signals in _bar_buffer; bar completion wired in 40-04 integration"
  - "All 6 stages use KafkaConsumerClient/KafkaProducerClient injection pattern matching base class constructor signature"
  - "SignalStatus.REGIME_SUPPRESSED.value used instead of raw 'regime_suppressed' string in winner_selector"

patterns-established:
  - "Stage process() reads from event.features dict, never directly from I4/I5/I6 schemas"
  - "Each stage propagates attribution_reason and attribution_inputs for observability side channel"
  - "Stages do not import each other — all inter-stage communication via Kafka topics"

requirements-completed: []

# Metrics
duration: 35min
completed: 2026-03-20
---

# Phase 40 Plan 02: DAG Pipeline Stages Summary

**6 DAG pipeline stage services (QualityGate → RegimeGate → TODAdjuster → Calibrator → Ranker → WinnerSelector) implementing the typed, attributed signal processing chain with circuit breaker protection**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-20T02:42:00Z
- **Completed:** 2026-03-20T03:18:09Z
- **Tasks:** 7 (6 stage implementations + stream_keys/exports update)
- **Files modified:** 8

## Accomplishments

- All 6 pipeline stage services implemented with correct Stage base class inheritance
- QualityGateService: min(hurst_quality, entropy_quality) × drift_penalty confidence multipliers
- RegimeGateService: 3-tier gate (prob >= 0.55, duration >= 3 bars, type matches allowed list)
- TODAdjusterService: 120-cell (regime_type, tf, hour_et) grouping with [0.7, 1.3] clamp
- CalibratorService: np.interp isotonic calibration curves per (plugin_name, tf), graceful passthrough when no curve
- RankerService: adjusted_rank = priority × perf_multiplier with SETUP_PRIORITY lookup
- WinnerSelectorService: CIS override (direction match + confidence boost) or priority/majority fallback, using SignalStatus enum
- All 39 unit tests pass across all 6 stages
- Zero raw status/outcome string literals — all use SignalStatus/SignalOutcome enums

## Task Commits

Each task was committed atomically:

1. **Task 1-7: All 6 stages + stream_keys/exports** — `7b6c613` (test) + `4c169b8` (feat)

TDD pattern: failing tests first, then full implementation in one pass.

## Files Created/Modified

- `src/intelligence/stages/quality_gate.py` — Hurst×Entropy + drift penalty gate (100 lines)
- `src/intelligence/stages/regime_gate.py` — HMM regime prob/duration/type gate (123 lines)
- `src/intelligence/stages/tod_adjuster.py` — 120-cell TOD multiplier adjuster (144 lines)
- `src/intelligence/stages/calibrator.py` — Isotonic calibration curve applier (109 lines)
- `src/intelligence/stages/ranker.py` — Priority × perf_multiplier ranker (103 lines)
- `src/intelligence/stages/winner_selector.py` — CIS/majority winner selector (196 lines)
- `src/intelligence/stages/__init__.py` — All 6 services exported (already correct)
- `src/core/stream_keys.py` — topic_quality_gated/regime_gated/tod_adjusted/calibrated/ranked/winner (already present)

## Decisions Made

- drift_penalty sourced from `event.features` dict (pre-computed float) not via DRIFT_PENALTIES import — cleaner dependency boundary, drift monitor writes penalty into the features bag rather than stage importing from monitoring module directly
- `min(hurst_quality, entropy_quality)` not product — both are quality indicators measuring similar things from different angles; min is the conservative choice (weakest link)
- WinnerSelectorService `_bar_buffer` uses in-memory defaultdict per (symbol, tf); bar completion detection deferred to Phase 40-04 integration plan
- All 6 stages use constructor-injected KafkaConsumerClient/KafkaProducerClient matching the base class signature (consumer, producer, attribution_producer)
- `SignalStatus.REGIME_SUPPRESSED.value` used in winner_selector for no-signal result status (not raw "regime_suppressed")

## Deviations from Plan

None — plan executed exactly as written, with one minor improvement: drift_penalty reads from `event.features["drift_penalty"]` rather than importing `DRIFT_PENALTIES` from `ks_drift_monitor.py`. This is architecturally cleaner (monitoring module writes into features bag; stage reads from features bag — no cross-layer import).

## Issues Encountered

None — all tests pass on first run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 6 stage services ready for integration in Phase 40-03 (Kafka topic creation and service wiring)
- Stage constructors accept `Settings` object for environment-aware topic names and bootstrap servers
- Bar completion detection in WinnerSelectorService needs Phase 40-04 bar boundary marker
- 39 unit tests provide regression safety for all stage logic

---
*Phase: 40-dag-refactor-clean-foundation*
*Completed: 2026-03-20*
