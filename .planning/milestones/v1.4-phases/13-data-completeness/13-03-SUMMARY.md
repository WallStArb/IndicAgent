---
phase: 13-data-completeness
plan: "03"
subsystem: intelligence
tags: [ai-narrative, i8, redis-streams, llm, intelligence-bus]

# Dependency graph
requires:
  - phase: 13-01
    provides: intelligence_i8 stream key function in src/core/stream_keys.py and feature_writer i8 UPSERT logic

provides:
  - ai_narrative_service publishes i8 metadata payload to intelligence_i8:SYMBOL:TF after each successful per-signal narrative
  - i8 stream messages contain ts, symbol, tf, model, confidence, summary (max 280 chars), generated_at
  - 5 new unit tests verifying i8 publish behavior; existing assert_called_once assertion updated

affects:
  - 13-04 (feature_writer reads intelligence_i8 stream; i8 column now populated in intelligence_features)
  - 14 (Feedback Loop — i8 data will be part of feature vectors for ML training)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sparse enrichment: only bars with actual narratives receive i8 data; bars without narratives keep default '{}'"
    - "__new__ bypass pattern for AINarrativeService tests — instance attributes set manually to avoid __init__ chain setup"

key-files:
  created: []
  modified:
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_ai_narrative_service.py

key-decisions:
  - "i8 xadd placed inside existing redis_client guard (if self.redis_client:) for consistency with rest of service"
  - "summary truncated to first 280 chars of narrative_text — compact for stream storage, full text still in narratives stream"
  - "Group synthesis does not publish to i8 — group narratives are cross-asset synthesis, not per-bar"
  - "signal_id omitted from i8 payload — not available in signals:aggregated stream; feature_writer matches via (ts, symbol, tf)"

patterns-established:
  - "Enrichment stream publish: after primary stream publish, add secondary enrichment xadd in same if block"
  - "Test isolation for service with heavy __init__: use __new__ + manual attribute setup to bypass LLM chain construction"

requirements-completed:
  - DATA-02
  - DATA-03

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 13 Plan 03: AI Narrative i8 Enrichment Stream Summary

**ai_narrative_service now publishes i8 metadata (model, confidence, 280-char summary, generated_at) to intelligence_i8:SYMBOL:TF after each successful per-signal narrative, populating DATA-02's i8 JSONB column in intelligence_features**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T10:03:21Z
- **Completed:** 2026-03-05T10:05:40Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `intelligence_i8 as sk_intelligence_i8` import to ai_narrative_service.py
- After `self._total_narratives += 1` in `_process_single_message`, added i8 xadd with payload: ts, symbol, tf, model, confidence (str), summary (narrative_text[:280]), generated_at (UTC ISO)
- Updated existing `test_process_message_publishes_narrative` to use `call_count >= 1` with targeted narratives-stream search instead of `assert_called_once()`
- Added 5 new i8 unit tests via `_make_service_new()` / `_make_signal_fields_i8()` helpers
- All 18 tests in ai_narrative test file pass; full unit suite at 1127 passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Publish i8 metadata to intelligence_i8 stream after narrative generation** - `a8176cf` (feat)
2. **Task 2: Unit tests for i8 publish behavior** - `544841c` (test)

**Plan metadata:** (this commit — docs: complete plan)

## Files Created/Modified

- `services/ai_narrative_service.py` — Added `sk_intelligence_i8` import; added i8 xadd block inside `if narrative_text:` after `self._total_narratives += 1`
- `tests/unit/service_tests/test_ai_narrative_service.py` — Updated `test_process_message_publishes_narrative` assertion; appended `_make_service_new()`, `_make_signal_fields_i8()` helpers and 5 new i8 tests

## Decisions Made

- `if self.redis_client:` guard retained for consistency with the rest of the service (defensive, already present)
- `narrative_text[:280]` — summary capped at 280 chars to keep stream payload compact; full narrative text still goes to narratives:SYMBOL:TF unchanged
- Group synthesis path (`_synthesize_group`) has no i8 publish — group narratives are cross-asset, not bar-specific
- `signal_id` absent from i8 payload: not present in `signals:aggregated` stream; feature_writer UPSERT matches on `(ts, symbol, tf)` per 13-01 design

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 13-04 (feature_writer concurrent polling) can now read from intelligence_i8 streams and UPSERT i8 data into intelligence_features
- The i8 JSONB column will be populated for bars where narratives were generated; bars without narratives keep default '{}'
- ML training dataset in intelligence_features will have i8 metadata for high-confidence 5m/15m/1h signals

---
*Phase: 13-data-completeness*
*Completed: 2026-03-05*
