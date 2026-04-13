---
phase: 56-ml-ai-foundation
reviewed: 2026-04-10T00:00:00Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - services/ml_data_quality_agent.py
  - services/ml_discovery_agent.py
  - services/ml_orchestrator_agent.py
  - services/swarm_orchestrator_agent.py
  - services/swarm_writer_agent.py
  - services/ai_narrative_agent.py
  - src/core/agents/alpha_contributor.py
  - src/core/ml/extractor.py
  - src/core/ml/features.py
  - src/core/ml/registry.py
  - src/core/ml/shadow.py
  - src/core/ml/training_data.py
  - src/core/llm/chain.py
  - src/core/llm/guardrails.py
  - src/core/llm/providers.py
  - src/core/llm/rate_limiter.py
  - src/core/llm/semantic_cache.py
  - src/core/llm/token_budget.py
  - src/core/swarm/base_agent.py
  - src/core/stream_keys.py
  - src/intelligence/narrative/orchestrator.py
  - src/intelligence/narrative/parsers.py
  - src/intelligence/narrative/prompts.py
  - src/intelligence/swarm/aggregator.py
  - src/intelligence/swarm/context.py
  - src/intelligence/swarm/safety.py
  - src/intelligence/swarm/metrics.py
  - src/intelligence/swarm/prompt_registry.py
  - src/intelligence/schemas.py
findings:
  critical: 3
  warning: 6
  info: 4
  total: 13
status: issues_found
---

# Phase 56: Code Review Report

**Reviewed:** 2026-04-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

This review covers the entire Phase 56 ML/AI Foundation Layer: three ML pipeline services (data quality, discovery, orchestrator), two new swarm services (orchestrator, writer), the refactored AI narrative agent, and all supporting modules in `src/core/ml/`, `src/core/llm/`, `src/core/swarm/`, and `src/intelligence/swarm/`.

The overall architecture is sound. The DAG is clean, the LLM provider chain is well-structured, and the safety wrappers (`SafeSwarmWrapper`, `SwarmBaseAgent`) apply the correct defensive patterns. The swarm writer's batch+flush pattern is solid.

Three critical issues require fixes before this phase can go to production:

1. A SQL logic inversion in the CIS null-rate check produces an always-wrong score.
2. The ML orchestrator queries a table (`ml_data_quality_runs`) that does not exist in any migration — the audit agent writes Kafka only, not DB — so the orchestrator always reads a NULL score and the quality gate is permanently bypassed.
3. The `_call_llm_with_circuit_breaker` function accesses `_llm_circuit_breaker.plugin_states[provider_id]` using bare key lookup on a `defaultdict`, which is safe, but then mutates the state object directly without going through the circuit breaker's own state-transition logic — the circuit breaker never actually opens and the shared `_llm_circuit_breaker` instance never trips.

---

## Critical Issues

### CR-01: SQL logic inverted — CIS null-rate always measures non-null rate instead

**File:** `services/ml_data_quality_agent.py:100`

**Issue:** The `WHERE` filter condition is logically inverted. The intent is to count rows where CIS is null. The current filter `WHERE i7 IS NOT NULL OR i7->>'cis' IS NOT NULL` counts rows where CIS is present (non-null). The subtraction `1.0 - (non_null_count / total)` then yields the null rate as if counting nulls, but only when both conditions are false — i.e., when `i7 IS NULL AND i7->>'cis' IS NULL`. Because `i7 IS NOT NULL` short-circuits via OR, any row with a non-null `i7` column passes regardless of whether CIS is inside it. The actual CIS null rate inside `i7` is never measured.

The correct check is: count rows where `i7` is null OR where `i7->>'cis'` is null (i.e., CIS field missing from the JSONB). The filter should use `AND NOT` logic:

```sql
SELECT COALESCE(
    COUNT(*) FILTER (WHERE i7 IS NULL OR i7->>'cis' IS NULL)::float
    / NULLIF(COUNT(*), 0),
    1.0
)
FROM intelligence_features
WHERE ts >= NOW() - INTERVAL '30 days'
```

This directly computes the null rate (fraction of rows missing CIS) rather than the non-null rate. The `1.0 - ...` subtraction should be removed — the result is already a null rate.

### CR-02: `ml_orchestrator_agent.py` queries a non-existent table — quality gate permanently bypassed

**File:** `services/ml_orchestrator_agent.py:162-165`

**Issue:** `_data_quality_node` runs `indicagent-ml-data-quality.service` via systemctl and then immediately queries `ml_data_quality_runs` for the score:

```python
score = await conn.fetchval(
    "SELECT score FROM ml_data_quality_runs ORDER BY ts DESC LIMIT 1"
)
```

No migration exists for `ml_data_quality_runs`. The `MLDataQualityAuditorAgent` does not write to any database table — it emits metrics to Prometheus and publishes an alert to Kafka when the score falls below threshold, but writes nothing to PostgreSQL. This query will either raise a `UndefinedTableError` (if the table doesn't exist) or return `NULL` if someone creates an empty table manually.

When `score is None`, the code falls back to `0.0`, which is below the 0.85 threshold, making the quality gate permanently fail on every orchestrator run. Discovery never runs. The entire weekly ML pipeline is silently broken.

**Fix options (choose one):**
- Add a `ml_data_quality_runs` table migration and have `MLDataQualityAuditorAgent._run()` write the score row to the DB before exiting:
  ```python
  async with self._pool.acquire() as conn:
      await conn.execute(
          "INSERT INTO ml_data_quality_runs (ts, score) VALUES ($1, $2)",
          datetime.now(UTC), round(score, 4)
      )
  ```
- Or read the score directly from the Kafka alert topic published by the auditor — but this requires a consumer and is more complex.
- Or pass the score via a shared state mechanism (e.g., a temp file or environment variable set by the one-shot service).

The DB write approach is simplest and consistent with how `ml_discovery_runs` works.

### CR-03: Circuit breaker state mutation bypasses transition logic — circuit never opens for LLM providers

**File:** `src/core/llm/providers.py:75-139`

**Issue:** `_call_llm_with_circuit_breaker` accesses `_llm_circuit_breaker.plugin_states[provider_id]` directly and manually increments `failure_count` / `success_count` on the `CircuitBreakerState` dataclass. It does not call any of the `PluginCircuitBreaker`'s state-transition methods (e.g., `execute_with_fallback`). The circuit breaker's `state` field on each `CircuitBreakerState` is never updated from `CLOSED` to `OPEN` through this path — the transition logic lives inside `PluginCircuitBreaker.execute_with_fallback()`, which is never called here.

As a result, the circuit breaker never opens. LLM providers that are consistently failing will continue to be called on every request, burning the retry budget on every call rather than failing fast during recovery timeout.

Additionally, `_llm_circuit_breaker` is a module-level singleton shared across all `LLMProviderChain` instances. The `plugin_states` dict is a `defaultdict(CircuitBreakerState)`, so any access with a new `provider_id` silently creates state rather than raising an error.

**Fix:** Wrap each provider call through the circuit breaker's own execute path, or implement a minimal open/half-open state check inside `_call_llm_with_circuit_breaker`:

```python
# Check if circuit is OPEN before calling
if plugin_state.state == CircuitState.OPEN:
    elapsed = time.monotonic() - _llm_open_since.get(provider_id, 0)
    if elapsed < _llm_circuit_breaker.config.recovery_timeout:
        logger.warning("llm_circuit_open.skipping", provider=provider_id)
        return None
    else:
        plugin_state.state = CircuitState.HALF_OPEN

# After failure:
if plugin_state.failure_count >= _llm_circuit_breaker.config.failure_threshold:
    plugin_state.state = CircuitState.OPEN
```

---

## Warnings

### WR-01: `ml_discovery_agent.py` — `setup_service_logging` not called in `__init__` or before `super().__init__`

**File:** `services/ml_discovery_agent.py:64-71`

**Issue:** `MLDiscoveryComputeAgent.__init__` does not call `setup_service_logging()`. The `main()` function calls it before constructing the agent, but if the agent is instantiated directly (e.g., in tests or by the orchestrator in future), logging goes to stderr only. Compare with `MLDataQualityAuditorAgent` which correctly calls `setup_service_logging` inside `__init__` at line 52. This is an inconsistency that will cause missing log files for the discovery service.

**Fix:** Add `setup_service_logging("logs/ml_discovery_agent.log")` as the first line of `MLDiscoveryComputeAgent.__init__`, matching the pattern in the other ML agents.

### WR-02: `swarm_orchestrator_agent.py` — private attribute access on `SafeSwarmWrapper` for path filtering

**File:** `services/swarm_orchestrator_agent.py:141`

**Issue:** The path filter accesses `w._contributor.path` — a private attribute of `SafeSwarmWrapper`:

```python
path_a_wrappers = [
    w for w in self._contributors if getattr(w._contributor, "path", "") == "deterministic"
]
```

`SafeSwarmWrapper` already exposes `self._path` (set in `__init__` from the contributor's `path` attribute). The correct accessor is `w._path`, but even that is private. `SafeSwarmWrapper` should expose `path` as a public property, or the filter should use `getattr(w, "path", "")` if the attribute is promoted to public.

**Fix:** Add a `path` property to `SafeSwarmWrapper`:
```python
@property
def path(self) -> str:
    return self._path
```
Then filter with `w.path == "deterministic"`.

### WR-03: `swarm_writer_agent.py` — data lost on DB failure without per-row retry or DLQ with content

**File:** `services/swarm_writer_agent.py:122-149`

**Issue:** When `_write_batch` fails (any DB error), the entire batch is published to DLQ as a single message containing only `{"error": str(exc), "batch_size": N}` — without the actual payload content. The original rows are not included, so the DLQ cannot be used to replay the failed writes. All shadow predictions in the failing batch are permanently lost.

**Fix:** Include the row payloads in the DLQ message so they can be replayed:
```python
await self._producer.publish(
    topic_swarm_writer_dlq(self._settings.env_name),
    {"error": str(exc), "batch_size": len(batch), "payloads": batch},
)
```
Or truncate to a safe size if payloads are large: `"payloads": batch[:10]`.

### WR-04: `ml_orchestrator_agent.py` — blocking `subprocess.run()` called from async context

**File:** `services/ml_orchestrator_agent.py:153-158` and `177-182`

**Issue:** `subprocess.run()` with `timeout=600` (10 min) and `timeout=1800` (30 min) is called directly in an `async` method without `asyncio.to_thread()`. This blocks the entire asyncio event loop for the duration of the systemctl command, preventing any other coroutines from running. For a one-shot agent this is low-impact but still wrong — if any other async cleanup tasks are pending they will not run.

**Fix:**
```python
import asyncio
proc = await asyncio.to_thread(
    subprocess.run,
    ["sudo", "systemctl", "start", "indicagent-ml-data-quality.service"],
    timeout=600,
    capture_output=True,
)
```

### WR-05: `src/core/llm/chain.py` — `_guardrails` module-level singleton is instantiated but `validate()` is never called

**File:** `src/core/llm/chain.py:24` and `src/core/llm/chain.py:76-132`

**Issue:** `_guardrails = GuardrailsValidator()` is created at module level, but the `generate()` method never calls `_guardrails.validate(self._call_type, response)`. The guardrails system is wired up but the validation step is missing. LLM responses are returned to callers without schema validation regardless of whether a schema is registered for the call type.

**Fix:** Call validate after receiving a non-None response, before caching it:
```python
# After: response = await self._inner.generate(...)
if response is not None and self._call_type:
    validated = _guardrails.validate(self._call_type, response)
    # validated is None if no schema registered (pass through)
    # or None if validation failed (reject)
    if validated is None and self._call_type in _guardrails._schemas:
        logger.warning("llm_chain.guardrails_rejected", call_type=self._call_type)
        return None
```

### WR-06: `src/core/ml/training_data.py` — SQL regime filter appended after `ORDER BY` clause

**File:** `src/core/ml/training_data.py:91-92`

**Issue:** `_BASE_SQL` ends with `ORDER BY f.ts`. When `regime is not None`, the filter is appended after the `ORDER BY`:

```python
sql += f" AND (f.i4->>'hmm_regime')::int = ${len(params) + 1}"
```

This generates invalid SQL: `...ORDER BY f.ts AND (f.i4->>'hmm_regime')::int = $5`. PostgreSQL will raise a syntax error on any regime-filtered query, meaning the ML discovery agent's segmented discovery (which always passes a regime) will always fail with a DB error.

**Fix:** Move the dynamic filter into the `WHERE` clause of `_BASE_SQL` by using a placeholder or restructure the query assembly:
```python
_BASE_SQL_REGIME = _BASE_SQL.replace(
    "ORDER BY f.ts",
    f"  AND (f.i4->>'hmm_regime')::int = $5\nORDER BY f.ts"
)
```
Or build the SQL before adding `ORDER BY`, keeping the filter in the correct clause position.

---

## Info

### IN-01: `services/swarm_orchestrator_agent.py` — `setup_service_logging` not called

**File:** `services/swarm_orchestrator_agent.py:193-196`

**Issue:** `main()` has no `setup_service_logging()` call, unlike every other agent service. Structured logs will go to stderr/journald instead of `logs/swarm_orchestrator_agent.log`. The `CLAUDE.md` rule states: "All service logs go to `logs/<service>.log` via `setup_service_logging()`."

**Fix:**
```python
def main() -> None:
    from src.core.service_utils import setup_service_logging
    setup_service_logging("logs/swarm_orchestrator_agent.log")
    settings = Settings()
    agent = SwarmOrchestratorComputeAgent(settings, contributors=[])
    asyncio.run(agent.start())
```

### IN-02: `src/core/ml/shadow.py` — `ShadowRecorder` has no periodic flush task

**File:** `src/core/ml/shadow.py:29-80`

**Issue:** `ShadowRecorder` accumulates rows in `_pending` and flushes when `batch_size` is reached or `flush()` is called explicitly. There is no asyncio background task to flush at `flush_interval_s` intervals. The `flush_interval_s` parameter is accepted but unused. If batch_size is never reached, rows accumulate indefinitely until a SIGTERM flush. Compare: `SwarmWriterAgent` correctly runs a `_flush_loop()` task alongside its consume loop.

**Fix:** Either remove `flush_interval_s` from the constructor signature (if callers drive the flush schedule externally), or document clearly that the periodic flush is the caller's responsibility and the parameter is reserved for a future background task.

### IN-03: `src/intelligence/swarm/metrics.py` — metrics created directly with `prometheus_client`, not via `src/observability/metrics.py`

**File:** `src/intelligence/swarm/metrics.py:10-51`

**Issue:** The file imports `Counter`, `Gauge`, `Histogram` directly from `prometheus_client` and creates metrics at module level. The `CLAUDE.md` rule states: "create via `src/observability/metrics.py` to prevent duplicate registration." If `src/intelligence/swarm/metrics.py` is imported multiple times or alongside any other module that registers a same-named metric, a `ValueError: Duplicated timeseries` will be raised at import time, crashing the service.

**Fix:** Move metric definitions into `src/observability/metrics.py` and import them from there, or use the `registry` parameter to route to a test registry in tests.

### IN-04: `src/core/llm/chain.py` — module-level `_cache`, `_budget`, `_guardrails` singletons are shared across all LLMProviderChain instances

**File:** `src/core/llm/chain.py:22-24`

**Issue:** These three singletons are module-level, meaning all `LLMProviderChain` instances (narrative, discovery hypothesis, etc.) share a single cache and a single daily token budget counter. This is probably intentional for the budget, but creates cross-call-type cache collisions: a narrative prompt and a discovery prompt with the same first 200 characters and same model would collide in the cache. The `call_type` is not part of the cache key in `SemanticCache._key()`.

**Fix:** Include `call_type` in the cache key:
```python
def _key(self, system: str, prompt: str, model: str, call_type: str = "") -> str:
    raw = f"{call_type}|{system}|{prompt[:200]}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()
```
Or pass `call_type` into `get()`/`put()` and propagate through `LLMProviderChain.generate()`.

---

_Reviewed: 2026-04-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
