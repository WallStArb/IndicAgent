---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: Production Hardening
status: executing
stopped_at: Completed 22-04-PLAN.md
last_updated: "2026-03-09T12:28:21.439Z"
last_activity: "2026-03-09 — 20-01: retry_utils.py with exponential backoff and jitter complete"
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 25
  completed_plans: 19
  percent: 36
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-08)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** Phase 18 - Financial Math Safety

## Current Position

Phase: 20 of 21 (Circuit Breaker Integration)
Plan: 1 of 4 in current phase (20-01 complete)
Status: In Progress
Last activity: 2026-03-09 — 20-01: retry_utils.py with exponential backoff and jitter complete

Progress: [████░░░░░░] 36%

## Performance Metrics

**Velocity:**
- Total plans completed: 45
- Average duration: ~30 min
- Total execution time: ~22.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1-9 (v1.0) | 21 | ~8h | ~23 min |
| 10 (v1.1) | 1 | ~20m | ~20 min |
| 11-14 (v1.2) | 8 | ~4h | ~30 min |
| 15-16 (v1.3) | 4 | ~2h | ~30 min |
| 17 (v1.4) | 3 | ~1.5h | ~30 min |
| 18-21 (v1.5) | 0 | - | - |

**Recent Trend:**
- Last 5 plans: Phase 17 (3 plans, ~30 min each)
- Trend: Stable

*Updated after v1.4 completion*
| Phase 18-financial-math-safety P02 | 88 | 2 tasks | 1 files |
| Phase 18 P01 | 4 min | 3 tasks | 3 files |
| Phase 18 P03 | 420 | 5 tasks | 6 files |
| Phase 18 P05 | 1 min | 1 task | 1 file |
| Phase 18-financial-math-safety P07 | 10 | 1 tasks | 2 files |
| Phase 18 P06 | 170 | 2 tasks | 2 files |
| Phase 18 P04 | 10 | 1 tasks | 1 files |
| Phase 19-financial-math-characterization P02 | 3 | 1 tasks | 1 files |
| Phase 19-financial-math-characterization P03 | 2 | 1 tasks | 1 files |
| Phase 19-financial-math-characterization P01 | 4 | 1 tasks | 2 files |
| Phase 20-circuit-breaker-integration P01 | 2 | 2 tasks | 2 files |
| Phase 20 P03 | 122 | 3 tasks | 1 files |
| Phase 20 P02 | 4 | 2 tasks | 2 files |
| Phase 20 P04 | 303 | 3 tasks | 3 files |
| Phase 21-efficiency-optimizations P01 | 2 | 2 tasks | 2 files |
| Phase 21-efficiency-optimizations P03 | 103 | 3 tasks | 2 files |
| Phase 21-efficiency-optimizations P02 | 147 | 2 tasks | 2 files |
| Phase 21 P04 | 223 | 3 tasks | 3 files |
| Phase 22-i8-narrative-three-tier-redesign P04 | 2 | 1 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:
- Phase 12 (v1.4): Regime-aware gating on all I7 plugins enforced via hmm_regime + prob>=0.60 + duration>=5
- Phase 13 (v1.4): Shadow signals tracked in signal_ledger for empirical gate tuning
- Phase 16 (v1.4): perf_multiplier as primary aggregator sort key
- Phase 18 (v1.5): Renaissance framing — safety first, efficiency second for algorithmic improvements
- [Phase 18]: EPSILON_TOLERANCE = 1e-9 for all floating-point comparisons across trading layer — Renaissance principle: instrument everything. Prevents precision issues in financial calculations.
- [Phase 18]: ATR multipliers and regime thresholds as named constants with Renaissance framing — Renaissance principle: explicit structural levels over hidden constants. Makes magic numbers discoverable and explainable.
- [Phase 18-05]: All LLM providers expose timeout: float | None = None in __init__ defaulting to _default_llm_timeout() — consistent pattern across OpenRouterProvider, AnthropicProvider, ZAIProvider, OllamaProvider
- [Phase 18-financial-math-safety]: Two async helpers (_update_plugin_state, _save_plugin_state) activate orphaned lock infrastructure in I1 indicator service — state read and write wrapped with per-key asyncio.Lock()
- [Phase 18]: _run_tier converted to async nested function to enable async with lock inside synchronous-style pipeline flow
- [Phase 18]: Lock wraps both plugin state read (setdefault) and write-back (_state reassignment) as atomic unit
- [Phase 18]: Stop directional checks use entry ± EPSILON_TOLERANCE to prevent degenerate stops at exactly entry price
- [Phase 19-02]: Characterization tests for zero-ATR emergency fallback in frame_trade() pin ATR_EMERGENCY_FALLBACK_PCT == 0.001 and verify stop = entry - (entry*0.001*2.0)
- [Phase 19-03]: Use __new__ pattern to bypass __init__ and set only the lock dict needed for isolated asyncio.Lock testing
- [Phase 19-financial-math-characterization]: RSI characterization: seed _state directly to isolate compute_next — avoids full dataset dependency in unit tests
- [Phase 19-financial-math-characterization]: RSI characterization Test 3: assert directional ordering (rsi2 < rsi1) rather than exact floats — pins behavioral invariant robustly
- [Phase 20-01]: jitter_factor=0.5 default (±50%) spread — wide enough to prevent thundering herd on concurrent retries
- [Phase 20-01]: retry_with_backoff() re-raises on final attempt directly (not via last_exception capture) to preserve full exception traceback
- [Phase 20-01]: retry_on=(Exception,) default catches all; callers narrow for precision; no retry_tracker callback — instrumentation delegated to circuit breaker state counts
- [Phase 20]: Module-level _ibkr_circuit_breaker singleton tracks connection health — IBKR has one connection, one breaker
- [Phase 20]: [Phase 20-03]: retry_with_backoff base_delay=2.0s, max_delay=15.0s for IBKR — longer than default to match TWS reconnect timing
- [Phase 20]: [Phase 20-03]: failure_window=120s, recovery_timeout=180s — IBKR reconnects ~1 min, 3 min recovery buffer
- [Phase 20]: _call_llm_with_circuit_breaker accepts sync call_fn not coroutine — each retry gets fresh to_thread invocation, preventing coroutine reuse errors
- [Phase 20-02]: Module-level _llm_circuit_breaker shared across all LLM providers, keyed by provider_id — failure history persists across chain iterations
- [Phase 20-04]: Circuit breaker state transitions use state snapshots (previous_state captured before operation) to detect actual changes at metric recording time
- [Phase 21-01]: cache_invalidated flag pattern — set inside while/popitem() loop, conditionally invalidates _df_cache only when buffer eviction occurs
- [Phase 21-efficiency-optimizations]: np.dot(weights_array, scores_array) replaces scalar sum() for CIS weighted aggregation — identical numerical result, leverages compiled BLAS
- [Phase 21-efficiency-optimizations]: CIS vectorization scoped to aggregation layer only — bucket methods (_trend, _momentum, etc.) left as-is to preserve readability
- [Phase 21-efficiency-optimizations]: Overflow detection uses len_before == history.maxlen (deque semantics): cache invalidated only when deque was at capacity before append
- [Phase 21]: PLUGIN_METRICS_SAMPLE_RATE=10 documented with explicit modulo pattern and rationale
- [Phase 21]: Error path records every call without sampling — safety invariant pinned by tests
- [Phase 22-04]: narrative backward-compat: narrative?: string kept optional in NarrativeData — set as alias when narrative_type=short, allows gradual migration in components
- [Phase 22-04]: spread-merge SSE pattern: {existing, ...newFields} merges short and deep into same state key enabling independent async arrivals

### Pending Todos

From .planning/todos/pending/:
- 2026-03-06-dashboard-intelligence-field-gaps.md — Largely complete, minor remaining work
- 2026-02-24-fix-sequential-stream-polling-in-feature-writer-service.md — Pre-existing

### Blockers/Concerns

None currently blocking v1.5 work.

## Session Continuity

Last session: 2026-03-09T12:28:21.438Z
Stopped at: Completed 22-04-PLAN.md
Resume file: None
