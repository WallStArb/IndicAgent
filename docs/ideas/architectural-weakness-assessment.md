# Architectural Weakness Assessment

**Status:** Active — living document
**Priority:** High — foundational tech debt affecting all future phases
**Date:** 2026-05-10
**Last Updated:** 2026-05-16
**Trigger:** Pre-phase-80 architectural review to identify weakest links before investing more
**Updates:** 2026-05-16 — full persistence writer audit added (#3, #6); new entries #8-#12 from codebase survey; #4 revised with verified current state; fix priority list updated for Phase 084

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

**Audit note (2026-05-16):** Full writer audit confirmed this pattern exists across 6 of 13 writer
services. `lineage_writer_agent.py` is the worst offender — positional tuples + no schema validation
+ silent error swallowing. `contract_metadata_writer_agent.py` is the template for the correct pattern.
Full findings: `docs/ideas/persistence-layer-fragility-assessment.md`

---

## #4. AI layer has three dead/unfinished foundations (MEDIUM-HIGH)

1. **LineageRecorder** (`src/core/ai/lineage.py`, 107 lines) — imported only in `stream_keys.py`, `ml/transform_recorder.py`, `ml/shadow.py`, and `TEMPLATE_agent.py`. Zero instantiations in any production agent path.

2. **Graduation loop** (`src/core/ai/base_group_service.py:282`) — `has_graduation: bool = False` by default. When enabled, loop body contains `# TODO: Implement graduation logic (Phase 75)` with `await asyncio.sleep(900)`. Runs forever doing nothing. No agent currently sets `has_graduation = True`.

3. **Extension hooks** (`_on_error`, `_on_guardrail_violation`, `_audit_payload`) — `_on_error` IS now invoked in `BaseAIAgent.compute()` on timeout (line 118) and exception (line 135), but the default implementation is `pass` (line 271) and no production subclass overrides it. `_on_guardrail_violation` and `_audit_payload` remain unwired and no-ops. Comment at line 263 confirms: "Default implementations are no-ops."

**Verified:** 2026-05-16 — hooks are called but do nothing; graduation loop and LineageRecorder still dead.

**Fix:** Wire `_on_error` to emit an OTel span event or counter — the call site is correct, the body needs an implementation. Implement graduation or delete the loop and `has_graduation` flag. Wire or delete LineageRecorder.

---

## #5. Output queue drops messages silently (MEDIUM)

`_enqueue()` uses `put_nowait()` with maxsize=500. No retry, no priority, no backpressure feedback. A burst of bars or slow Kafka publish = intelligence events vanish. Counter increments but nothing acts on it.

**Fix:** Block or retry on full. Add priority for signal events over journal records.

---

## #6. Error handling: 63 bare `except Exception` blocks (MEDIUM)

Errors caught broadly, logged, then processing continues with partial/missing data. I4 plugin failure → I5/I6 get garbage input silently. No circuit breaker on repeated failures — a broken plugin just keeps failing every bar.

**Fix:** Add circuit breakers to plugin execution. Stop running broken plugins after N failures.

**Audit note (2026-05-16):** Writer-layer error handling audited. Three severity tiers found:
- **Silently swallowed** (worst): `lineage_writer_agent.py`, `signal_metrics_writer_agent.py`
- **Logged but suppressed**: `feature_writer_agent.py`, `ctx_writer_agent.py`, `llm_writer_service.py` (outcomes), `feature_snapshot_writer_agent.py`
- **Correctly raised**: lifecycle, contract_metadata, bar_writer, signal_writer, swarm_ledger

Also see #10 for the plugin circuit breaker gap specifically.

**Related:** `docs/ideas/service-resilience-patterns.md` — Pattern 1 (consumer circuit breaker design) and Pattern 3 (consumer observability metrics) are the implementation reference for this finding.

---

## #7. Global mutable state without thread protection (MEDIUM)

Module-level singletons (`_settings_singleton`, `_active_contracts_cache`) accessed from ThreadPoolExecutor threads without synchronization. Per-plugin locks exist but shared caches (`_cross_asset_cache`, `_macro_cache`) mutated from async loop AND thread pool.

**Fix:** Protect shared caches with threading.Lock or make them asyncio-only.

---

## #8. Bootstrap retry pattern duplicated 3x independently (MEDIUM)

Three services each re-implement exponential backoff with different configs and no shared logic:

- `signal_tracker_compute_agent.py:93-95` — `_BOOTSTRAP_MAX_ATTEMPTS=3`, backoff `(2,4,8)`
- `bar_aggregator_agent.py:209-254` — `_MAX_ATTEMPTS=4`, inline cleanup on failure
- `bar_writer_agent.py:198-218` — `_cache_attempts=3`, backoff handled inline

`retry_utils.exponential_backoff_with_jitter()` already exists but none of these use it.
`BaseAgent` already has a `_setup_with_retry()` stub (lines 446-469) that could encapsulate this.

**Fix:** Wire `BaseAgent._setup_with_retry()` with configurable `_bootstrap_max_attempts` and
`_bootstrap_base_delay` class attributes. All three agents switch to it.

---

## #9. `validate_signal()` exists but is never called — I7 output boundary unguarded (MEDIUM)

`src/intelligence/trading/signal_schema.py` exports a complete `validate_signal()` function
that checks required fields, schema version, confidence, direction, and targets. Nothing calls it.

Malformed I7 plugin output flows through the aggregator and into the persistence layer unchecked.
Type coercion in the DB masks bugs at the source.

`make_signal_from_frame()` is universally adopted (all 28 I7 plugins), but the output validation
gate that should sit between I7 and the signal writer is missing.

**Fix:** Call `validate_signal()` in `SignalWriterAgent._parse_payload()` before persist. Also
call it in `IntelligencePipelineAgent` after each I7 plugin returns output.

---

## #10. Plugin circuit breaker under-utilized — I1-I7 pipeline unprotected (MEDIUM)

`PluginCircuitBreaker` (`src/core/plugin_circuit_breaker.py`, 584 lines) is wired for the LLM
provider chain and IBKR connection. The 132 I1-I7 compute plugins inside
`intelligence_pipeline_agent.py` have no circuit breaker and no per-plugin timeout.

A single hung plugin blocks the entire bar. After N failures, the same plugin keeps running on
every bar with no automatic recovery or fallback.

**Fix:** Wrap each plugin call with `circuit_breaker.execute_with_fallback(plugin_name, fn, fallback=None)`
and `asyncio.wait_for(plugin_fn(...), timeout=0.1)`. Reuse the existing class — no new code needed.

**Related:** `docs/ideas/service-resilience-patterns.md` — Pattern 1 has the full circuit breaker config surface and integration design. `docs/ideas/latency-and-persistence-audit-design.md` — "Scientific Integrity" section covers per-plugin compute budgets and liveness tracking, which this addresses.

---

## #11. Intelligence pipeline checkpoint write swallowed — silent state loss (MEDIUM)

`intelligence_pipeline_agent.py` writes plugin state to a checkpoint file on shutdown.
The write failure path catches the exception, logs it, and continues. If the checkpoint
write fails, the next startup re-computes all plugin state from scratch (Kalman filters,
volume profiles, pattern state). For symbols with long warm-up windows this means stale outputs
until state converges.

**Fix:** Re-raise on checkpoint write failure. Fail fast — it's a shutdown path, not a hot loop.
The operator needs to know the checkpoint is corrupt, not find out indirectly from cold-start behavior.

---

## #12. Dashboard has no React error boundaries — render crashes are invisible (LOW-MEDIUM)

No `<ErrorBoundary>` component exists in `dashboard/src/`. A render-time exception in any
component propagates up and blanks the page with no user-visible message and only a console
error. SSE connection failures are also silent (no connection status indicator).

API endpoints accept unbounded query parameters (`limit=999999`, `offset=-1`) with no Pydantic
constraint models.

**Fix:**
- Add `<ErrorBoundary>` in `app-shell.tsx` wrapping the main content area
- Add error toast/banner for fetch failures that are not AbortError
- Add Pydantic `Query` models with `Field(le=1000, ge=0)` constraints to API endpoints
- Add SSE connection status indicator to dashboard

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

**Phase 084 — Persistence + Pipeline Hardening (scoped 2026-05-16):**
1. Fix `lineage_writer_agent.py` — add Pydantic model, DLQ routing, error counter (CRITICAL)
2. Fix `feature_snapshot_writer_agent.py` — replace clear-on-error with bounded retry (HIGH)
3. Fix `llm_writer_service.py` — re-raise outcome errors (HIGH)
4. Wire `validate_signal()` at I7 output boundary (MEDIUM)
5. Wire `PluginCircuitBreaker` into intelligence pipeline (MEDIUM)
6. Fix checkpoint write — fail fast on shutdown (MEDIUM)
7. Migrate positional-tuple writers to named params (MEDIUM)
8. Batch `signal_metrics_writer_agent.py` writes (MEDIUM)

**Later phases:**
9. Decompose the pipeline god class (highest leverage, largest effort)
10. Extract `BaseAgent._setup_with_retry()` to kill the 3x bootstrap duplication
11. Extract instrument definitions from Settings
12. Wire or delete LineageRecorder
13. Implement backpressure on output queue
14. Add React error boundaries + API input validation (#12)
