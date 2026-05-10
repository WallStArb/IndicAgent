# Architectural Weakness Assessment

**Status:** Idea
**Priority:** High — foundational tech debt affecting all future phases
**Date:** 2026-05-10
**Trigger:** Pre-phase-80 architectural review to identify weakest links before investing more

---

## #1. IntelligencePipelineComputeAgent — 1820-line god class needs in-process decomposition (CRITICAL)

**File:** `services/intelligence_pipeline_agent.py`

**Intentional design (correct):** Unified in-process I1→I7 pipeline eliminates Kafka round-trips between tiers. This is the right trade-off for latency — no boundaries between compute stages.

**Accidental complexity (fixable):** "One process" became "one class." 9+ responsibilities, 44 mutable state dicts (233 `self._` accesses), signal gating/calibration/ranking, state checkpoint/restore, 6 async DB cache refresh loops, shadow governance, metrics, DLQ routing — all in one class.

**Key distinction:** Decomposing into focused classes (StateManager, PluginExecutor, SignalProcessor, CacheManager) within the same process adds zero latency overhead. In-process method calls are nanoseconds. The latency benefit comes from avoiding Kafka/IPC boundaries, not from having a single class.

**What breaks first:** Doubling symbols (58→116) = 44 state dicts × 2 entries, ThreadPoolExecutor contention doubles, 500-deep output queue overflows. Hard to test or refactor any single concern without understanding all 44 state dicts and their coupling.

**Fix:** Extract focused classes that share memory in-process. No Kafka boundaries needed — just separation of concerns within the same address space.

---

## #2. Settings is a 1131-line god object (HIGH)

**File:** `src/config/settings.py`

Infrastructure config (Kafka URLs, DB connections) entangled with business logic (instrument definitions, LLM providers, Kalman params). Adding a contract requires editing the same class controlling DB pooling. No separation between static and runtime-adjustable config.

**Fix:** Extract instrument definitions to DB or YAML. Settings should only be infra.

---

## #3. Signal ledger schema — 64-field accordion (HIGH)

**File:** `src/persistence/repository/signal_ledger_repository.py` (977 lines)

LedgerEntry has 64 fields accumulated across phases 1→79 with no field removal. `to_insert_params()` returns raw 64-element positional tuple — schema changes require manual column reordering. Per-signal DB calls for individual updates instead of batched writes.

**Fix:** Replace positional tuple with named params or asyncpg named parameter binding. Batch lifecycle updates.

---

## #4. AI layer has three dead/unfinished foundations (MEDIUM-HIGH)

1. **LineageRecorder** (`src/core/ai/lineage.py`, 107 lines) — never imported anywhere. Zero instantiations. Template references it but nothing uses it.
2. **Graduation loop** (`src/core/ai/base_group_service.py:246`) — `await asyncio.sleep(900)` with `# TODO: Implement graduation logic (Phase 75)`. Runs forever doing nothing.
3. **Extension hooks** (`_on_error`, `_on_guardrail_violation`, `_audit_payload`) — all no-ops in BaseAIAgent. Documented as "future phase" but never wired.

**Fix:** Wire or delete LineageRecorder. Implement graduation or remove the loop. Wire hooks to OTel.

---

## #5. Output queue drops messages silently (MEDIUM)

`_enqueue()` uses `put_nowait()` with maxsize=500. No retry, no priority, no backpressure feedback. A burst of bars or slow Kafka publish = intelligence events vanish. Counter increments but nothing acts on it.

**Fix:** Block or retry on full. Add priority for signal events over journal records.

---

## #6. Error handling: 63 bare `except Exception` blocks (MEDIUM)

Errors caught broadly, logged, then processing continues with partial/missing data. I4 plugin failure → I5/I6 get garbage input silently. No circuit breaker on repeated failures — a broken plugin just keeps failing every bar.

**Fix:** Add circuit breakers to plugin execution. Stop running broken plugins after N failures.

---

## #7. Global mutable state without thread protection (MEDIUM)

Module-level singletons (`_settings_singleton`, `_active_contracts_cache`) accessed from ThreadPoolExecutor threads without synchronization. Per-plugin locks exist but shared caches (`_cross_asset_cache`, `_macro_cache`) mutated from async loop AND thread pool.

**Fix:** Protect shared caches with threading.Lock or make them asyncio-only.

---

## What's Actually Solid (Do Not Refactor)

These are well-designed and working. Don't touch unless there's a specific reason.

- **Plugin system** — registry + tier validation + frozen outputs. 129 plugins across 7 tiers, validated at startup. Single source of truth in `register_plugins.py`.
- **Typed bus** — `IntelligenceEvent` with Pydantic schemas. Strong type safety across I1-I7. `model_validate` catches schema drift at deserialization boundaries.
- **BaseAIAgent compute wrapper** — timing capture, `asyncio.wait_for` timeout, neutral fallback on error, Prometheus metrics. Clean template pattern.
- **Signal lifecycle state machine** — `lifecycle_tracker.py` is pure functions. Well-tested, no side effects, no DB access. Easy to reason about.
- **Aggregator logic** — CIS scoring + regime gating + co-fire detection. `_build_all_ranked()` with perf weights, alpha decay, calibration. Complex but correct.
- **Kafka isolation** — all topics via `stream_keys.py`. Zero hardcoded topic strings. Environment prefix handled centrally.
- **Shadow governance** — auto-enrollment at startup, promotion/demotion gates with statistical thresholds. DB-backed `shadow_registry`.

---

## Overlap with Existing Ideas

Some findings confirm or extend ideas already tracked in `.planning/IDEAS.md`:

| Finding | Existing Idea | Delta |
|---------|--------------|-------|
| #1 Pipeline god class | "Parallel DAG execution" (#21) | Different scope — #21 is about within-tier parallelism; finding #1 is about class decomposition |
| #5 Queue drops | "Backpressure & autoscaling" (#23) | Finding #5 confirms it's a real problem today, not theoretical |
| #6 Bare excepts | "Service resilience patterns" (#20) | Finding #6 is the concrete symptom; #20 is the broader pattern |
| #2 Settings god object | No existing idea | **New** |
| #3 64-field ledger tuple | No existing idea | **New** |
| #4 Dead AI foundations | No existing idea | **New** |
| #7 Unprotected global state | No existing idea | **New** |

---

## Dead Code & Quick Wins

Items that can be cleaned up immediately with low risk:

1. **LineageRecorder** (`src/core/ai/lineage.py`, 107 lines) — delete or wire. Currently dead code that the TEMPLATE references, creating false expectations for new agents.
2. **Graduation loop** (`src/core/ai/base_group_service.py:246`) — either implement or remove the empty `asyncio.sleep(900)` loop. Running a noop every 15 min is worse than not running it.
3. **Extension hooks** (`_on_error`, `_on_guardrail_violation`, `_audit_payload` in `src/core/ai/base_agent.py`) — wire to OTel spans or remove. Currently decorative no-ops.

---

## Recommended Fix Priority

1. Decompose the pipeline god class (highest leverage)
2. Extract instrument definitions from Settings
3. Replace positional tuple with named params in LedgerEntry
4. Wire or delete LineageRecorder
5. Implement backpressure on output queue
6. Add circuit breakers to plugin execution
