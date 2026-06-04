---
phase: 095-pydantic-ai-agents
reviewed: 2026-06-01T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - src/core/ai/worker_context.py
  - tests/unit/core/test_core_ai_worker_context.py
  - tests/unit/core/test_llm_response_format.py
  - src/core/llm/litellm_backend.py
  - src/core/llm/chain.py
  - src/core/ai/llm_adapter.py
  - tests/unit/core/test_core_ai_llm_adapter.py
  - src/core/ai/base_agent.py
  - tests/unit/core/test_core_ai_base_agent.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - services/alpha_swarm.py
  - src/api/routes/ai_stats.py
  - tools/validate_skeptic.py
  - tests/unit/services/test_skeptic_agent.py
  - tests/unit/services/test_alpha_swarm.py
  - tests/integration/test_swarm_graduation_loop.py
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 095: Code Review Report

**Reviewed:** 2026-06-01T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 095 delivers the Pydantic AI Agent Execution Layer — WorkerContext, LLMAdapter,
_run_typed(), and the SkepticAgent migration. The core abstractions (WorkerContext immutability,
LLMAdapter routing, audit context per-call_id uniqueness) are architecturally sound and the
unit tests are well-structured. Two blockers and four warnings were found.

The most serious issues are: (1) the integration test is broken in two independent ways and
can never pass, making it useless as a graduation gate; and (2) SWARM_AGENT_WEIGHT is an
up_down_counter used with `.add(weight, ...)` when it must be a point gauge using `.set()` —
repeated graduation cycles accumulate the weight rather than setting it, producing an unbounded
drifting metric.

## Critical Issues

### CR-01: Integration test broken — `_agents` / `_agent_weights` never set before `_run_graduation_cycle()`

**File:** `tests/integration/test_swarm_graduation_loop.py:100-109`
**Issue:** `AlphaSwarm.__new__(AlphaSwarm)` bypasses `__init__`, so `agent._agents`,
`agent._agent_weights`, and `agent._agent_weights` are never initialized. `_run_graduation_cycle()`
immediately iterates `self._agents` (line 273 of alpha_swarm.py) and calls
`_reload_agent_weights()` which accesses `self._agent_weights`. Both raise `AttributeError`
before any test assertion is reached. The test can never pass regardless of DB state.

**Fix:**
```python
# After agent._demotion_streak = 0, add:
agent._agents = [MagicMock(agent_id="skeptic")]
agent._agent_weights = {}
```

### CR-02: Integration test asserts wrong outcome — `shadow_registry.is_shadow` is never set by `_run_graduation_cycle()`

**File:** `tests/integration/test_swarm_graduation_loop.py:113-122`
**Issue:** Even if CR-01 is fixed, the test asserts `shadow_registry.is_shadow = FALSE` after
`_run_graduation_cycle()`. But `_run_graduation_cycle()` only UPSERTs into `swarm_agent_weights`
and calls `_refresh_shadow_state_from_registry()` which only READS from `shadow_registry`. The
service that writes `shadow_registry.is_shadow = FALSE` is `shadow_auditor.py`
(`services/shadow_auditor.py`), not AlphaSwarm. The promotion assertion can never be satisfied
by a single graduation cycle, making the test permanently false.

Additionally, the test inserts lineage rows into a `prediction` JSONB column but `_evaluate_agent`
queries `sl.multiplier`, so the inserted test data yields 0 rows and the graduation logic
never runs.

**Fix:** Rewrite the integration test to assert `swarm_agent_weights` is upserted with `rho > 0`
(the actual observable outcome of `_evaluate_agent`), and change the lineage insert to populate
`multiplier` rather than `prediction`:
```sql
-- Change insert to populate the column _evaluate_agent reads:
INSERT INTO signal_lineage
    (ts, signal_id, event_type, source, multiplier, symbol, tf)
VALUES ($1, $2, 'agent_prediction', 'skeptic', $3, 'ESM6', '5m')
```
Then assert `swarm_agent_weights` for skeptic/5m has `spearman_rho > 0`, not `shadow_registry.is_shadow`.

## Warnings

### WR-01: `SWARM_AGENT_WEIGHT` is an `up_down_counter` used as a point gauge — accumulates unboundedly

**File:** `services/alpha_swarm.py:369`
**Issue:** `SWARM_AGENT_WEIGHT.add(weight, {"agent_id": agent_id, "timeframe": tf})` passes the
current weight as a delta to an `up_down_counter`. On each graduation cycle (every 15 min) the
metric accumulates: after three cycles with `weight=0.6`, the counter reads `1.8`, not `0.6`.
This makes the metric useless and potentially misleading for Grafana dashboards.
CLAUDE.md states: point gauges (`create_gauge` / `point_gauge()`) → `.set(value, ...)`.
Per metrics.py: `SWARM_AGENT_WEIGHT = _meter.create_up_down_counter(...)` (line 684 of metrics.py).

**Fix:** Change the metric definition in `src/observability/metrics.py`:
```python
# Change from:
SWARM_AGENT_WEIGHT = _meter.create_up_down_counter(...)
# To:
SWARM_AGENT_WEIGHT = point_gauge("swarm_agent_weight", description="Current Spearman-derived agent weight")
```
Then in alpha_swarm.py line 369:
```python
SWARM_AGENT_WEIGHT.set(weight, {"agent_id": agent_id, "timeframe": tf})
```

### WR-02: `self._llm` is `None` at construction — `_run_typed()` passes `None` as `llm_chain` to `WorkerContext`

**File:** `src/core/ai/base_agent.py:393`
**Issue:** `BaseAIWorker.__init__` sets `self._llm = None` (line 102). If `_run_typed()` is called
before `self._llm` is wired (e.g. in a misconfigured agent or a unit test that bypasses setup),
`WorkerContext(llm_chain=None)` is created. Inside `LLMAdapter._request()`, `chain.generate()` is
called on `None`, raising `AttributeError: 'NoneType' object has no attribute 'generate'`. This
propagates through pydantic-ai's Agent.run(), which may or may not catch it cleanly. The failure
manifests as a cryptic error rather than a clear misconfiguration message.

**Fix:** Add a None guard at the top of `_run_typed()`:
```python
if self._llm is None:
    raise RuntimeError(
        f"{self.__class__.__name__}._llm is None - "
        "wire self._llm = llm_chain in __init__ before calling _run_typed()"
    )
```
This mirrors the existing `result_type is None` guard just above and gives a clear failure message.

### WR-03: `calibrated_confidence` accessed from `signal_dict` (post-parse) at line 620 even though CLAUDE.md states it is null in Kafka payloads

**File:** `services/alpha_swarm.py:620-621`
**Issue:** At line 620, `original_confidence = signal_dict.get("calibrated_confidence") or ...`
reads from `signal_dict` (the result of `signal.model_dump()`). CLAUDE.md states: "Swarm raw
signal confidence field: `calibrated_confidence` is null in Kafka signal payloads. Gate on
`raw_signal.get('confidence')` or `raw_signal.get('pre_quality_confidence')`." The upstream gate
at line 493-495 correctly uses `raw_signal.get("confidence") or raw_signal.get("pre_quality_confidence")`,
but line 620 falls back to a field that is always null. When `calibrated_confidence` is null and
`pre_quality_confidence` is also absent from the model-dumped dict, `original_confidence` defaults
to `0.5` silently, producing a fixed `adjusted_confidence = 0.5 * final_multiplier` regardless
of actual signal quality.

**Fix:**
```python
# Replace line 620-621:
original_confidence = (
    raw_signal.get("confidence")
    or raw_signal.get("pre_quality_confidence")
    or 0.5
)
```
Or alternatively, capture the gate-computed `signal_confidence` (line 494) and reuse it here.

### WR-04: `_compute` in `SkepticEvaluator` uses `# type: ignore[assignment]` to suppress a real type mismatch

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:102`
**Issue:** `result = await self._run_typed(...)  # type: ignore[assignment]` suppresses the type
checker's legitimate complaint that `_run_typed()` returns `BaseModel` while `result` is then
accessed as `SkepticResult` (`.failure_probability`, `.confidence`, `.risk_factors`, `.reasoning`).
If `result_type` is ever changed to a different model or `_run_typed()` returns a base-class
instance, this will raise `AttributeError` at runtime with no static warning. The fix is a typed
downcast that gives the type checker real information.

**Fix:**
```python
raw = await self._run_typed(context, prompt=prompt, system=_SYSTEM_MESSAGE, max_tokens=500)
assert isinstance(raw, SkepticResult), f"_run_typed returned {type(raw).__name__}, expected SkepticResult"
result: SkepticResult = raw
```
Or define `_run_typed()` with a TypeVar bound to the subclass's `result_type` so the return type
is already correct (requires a Protocol or Generic on BaseAIWorker — deferred to a future phase,
but the assert above covers it now).

## Info

### IN-01: TODO comment in `_run_typed` describes a timestamp artifact that should be addressed

**File:** `src/core/ai/base_agent.py:387-390`
**Issue:** The TODO notes that `_build_audit_context` stamps `called_at = datetime.now(UTC)` into
the base audit dict, then `llm_adapter._request()` overwrites it with a fresh timestamp. The base
`called_at` is silently discarded. This is harmless but wastes a datetime allocation and leaves
a misleading field in the base dict. The intent of the base dict is to carry static fields; it
should not include `called_at` for the `_run_typed()` path since the adapter always overwrites it.

**Fix:** Pass `call_id=""` and omit `called_at` from the base dict in `_run_typed()` by either
adding a `skip_called_at` param to `_build_audit_context`, or by popping the key from the returned
dict before passing it to `make_llm_adapter`.

### IN-02: Dead `else` branch in `SkepticEvaluator._compute` when `ACTIVE_VERSION == "skeptic_v2"` is guaranteed

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:97-100`
**Issue:** The test at line 136 asserts `ACTIVE_VERSION == "skeptic_v2"`. Since `ACTIVE_VERSION` is
a module-level constant, the `else` branch (v1 dict-path) is permanently dead code. The v1 dict
adapter `_context_to_dict` is kept for rollback purposes (per code comment), but the branch
checking `ACTIVE_VERSION == "skeptic_v2"` is uncoverable in tests and adds cognitive overhead.

**Fix:** If v2 is stable, remove the branch and the `_context_to_dict` adapter. If rollback is
genuinely needed, document it as a deliberate toggle and add a test that validates the v1 path
explicitly.

### IN-03: `validate_skeptic.py` queries a non-existent view/table `alpha_multiplier_shadow`

**File:** `tools/validate_skeptic.py:72`
**Issue:** The validation tool queries `FROM alpha_multiplier_shadow s JOIN signal_ledger l ...`
but `alpha_multiplier_shadow` is not referenced anywhere else in the codebase. The actual lineage
data is stored in `signal_lineage` (joined to `signal_ledger_full`), which is what `_evaluate_agent`
uses. If `alpha_multiplier_shadow` does not exist as a materialized view or table, this tool will
fail with `relation "alpha_multiplier_shadow" does not exist` at runtime for any agent.

**Fix:** Update the query to match the schema actually used by the graduation logic:
```sql
FROM signal_lineage s
JOIN signal_ledger_full l ON l.signal_id = s.signal_id
WHERE s.event_type = 'agent_prediction'
  AND s.source = $1
  AND s.multiplier IS NOT NULL
  AND s.ts >= NOW() - $2::interval
```

---

_Reviewed: 2026-06-01T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
