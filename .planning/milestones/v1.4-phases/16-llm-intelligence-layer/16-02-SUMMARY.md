---
phase: 16-llm-intelligence-layer
plan: "02"
subsystem: services
tags: [llm, timescaledb, redis, consumer-group, batch-writer, scipy, prometheus, tdd]

# Dependency graph
requires:
  - phase: 16-01
    provides: "llm_calls hypertable, llm_model_scores table, stream key helpers, TDD RED tests"
provides:
  - "services/llm_writer_service.py — complete cold-tier LLM data persistence service"
  - "_parse_llm_call_fields: validates required fields, returns typed dict or None"
  - "_parse_outcome_fields: signal_id required, returns outcome update dict or None"
  - "_build_score_insert_params: binomtest significance gate (p<0.05, n>=30 Renaissance standard)"
  - "LLMWriterService: buffered batch INSERT for llm_calls, immediate UPDATE for outcomes"
  - "Score recompute loop: 15-min cadence, upserts llm_model_scores + Redis HSET cache"
  - "Prometheus metrics on port 9117"
affects: [16-03-ai-narrative-instrumentation, 16-04-lifecycle-emission, 16-05-deployment]

# Tech tracking
tech-stack:
  added:
    - "scipy.stats.binomtest — used for Renaissance significance gate in score computation"
  patterns:
    - "Dual-stream consumer: buffered batch path for high-volume calls, immediate path for low-volume outcomes"
    - "Redis HSET score cache: llm_scores:{call_type}:{regime} — HSET with model as field, JSON blob as value"
    - "Score recompute: asyncio.sleep(900) loop, queries DB, upserts table, updates cache atomically"

key-files:
  created:
    - services/llm_writer_service.py
  modified: []

key-decisions:
  - "_build_score_insert_params accepts a list[dict] of rows (not pre-aggregated values) — tests define interface"
  - "Outcomes processed immediately (no buffering) — low volume (one per signal exit) justifies direct DB UPDATE"
  - "Calls buffered in _calls_buffer and flushed at BATCH_SIZE=50 or FLUSH_INTERVAL_SECS=5.0 — matches feature_writer_service pattern exactly"
  - "Score cache key: llm_scores:{call_type}:{regime} — enables per-call-type, per-regime model selection by ai_narrative_service"

patterns-established:
  - "Dual-stream consumer pattern: two separate xreadgroup loops sharing a consumer group — each loop owns one stream, avoiding cross-contamination of message positions"
  - "Pure function contract from TDD RED tests honored without modification — tests are the authority on function signatures"

requirements-completed: [LLM-04]

# Metrics
duration: 8min
completed: 2026-03-05
---

# Phase 16 Plan 02: LLM Writer Service Summary

**LLMWriterService with dual-stream consumer groups, scipy binomtest significance gate, 15-min score recompute loop, and Redis HSET score cache — all 12 TDD tests GREEN**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-05T19:40:00Z
- **Completed:** 2026-03-05T19:48:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `services/llm_writer_service.py` created (819 lines) — complete cold-tier LLM data writer mirroring `feature_writer_service.py` pattern
- All 7 TDD RED tests (from 16-01) now pass GREEN; all 12 tests in `test_llm_writer_service.py` PASS
- Full unit suite remains clean: 1149 passing, 0 regressions
- `_build_score_insert_params` implements the Renaissance significance gate: `binomtest(wins, n, 0.50, alternative='greater').pvalue < 0.05 AND n >= 30` — no model earns `is_significant=True` without statistically significant proof
- Score recompute loop queries `llm_calls` by group, upserts `llm_model_scores`, and updates Redis HSET at `{env}:llm_scores:{call_type}:{regime}` for fast O(1) model routing lookups

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement llm_writer_service.py (GREEN phase)** - `daed51f` (feat)
2. **Task 2: Run full unit test suite** - no commit (verification-only, no file changes)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `services/llm_writer_service.py` — LLMWriterService with `_calls_process_loop`, `_outcomes_process_loop`, `_score_recompute_loop`, `_health_monitor_loop`, `_shutdown`, `start`; pure functions `_parse_llm_call_fields`, `_parse_outcome_fields`, `_build_score_insert_params`

## Decisions Made

- `_build_score_insert_params` signature uses `rows: list[dict]` (not pre-aggregated values) — the TDD tests are the ground truth; the plan's interface description was aspirational but the tests define the binding contract
- Outcomes are processed immediately without buffering because they are low-volume (one per signal exit) — this also reduces latency before score recompute can observe fresh outcomes
- The `_score_recompute_loop` uses `asyncio.sleep(SCORE_RECOMPUTE_INTERVAL_SECS)` at the top of each iteration (not a timer) — this means first recompute fires 15 minutes after service start, not at startup, which is intentional (need outcomes to accumulate first)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- One ruff E501 line-too-long on unpacking line 628 — fixed inline (1-char fix, line broken to two lines)
- Pre-existing modification to `services/indicator_service.py` (warmup_bars 20→120) was discovered during `git status` — out of scope for this plan, not touched

## User Setup Required

None — no external service configuration required. `llm_writer_service.py` requires migration 019 to be applied (done in 16-01 plan) before the service can be started.

## Next Phase Readiness

- `llm_writer_service.py` is complete and tested — ready for integration
- Plans 16-03 (ai_narrative instrumentation) and 16-04 (lifecycle emission) can now publish to `llm_calls:stream` and `llm_outcomes:stream` respectively and trust this service will consume and persist them
- Score cache will be populated after first 30+ outcomes accumulate — `ai_narrative_service` can begin reading `{env}:llm_scores:{call_type}:{regime}` for adaptive model routing

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-05*
