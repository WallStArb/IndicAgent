---
phase: 110-renaissance-rename
reviewed: 2026-05-30T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - dashboard/src/hooks/use-observability-stream.ts
  - services/feature_validation_agent.py
  - services/hmm_training_agent.py
  - services/ml_training_agent.py
  - src/api/routes/health.py
  - src/api/routes/narrative.py
  - src/api/routes/validation.py
  - src/config/outbox_publisher.py
  - src/core/ai/base_agent.py
  - src/core/ai/base_group_service.py
  - src/core/ai/context.py
  - src/core/ai/evaluator.py
  - src/intelligence/ai/alpha/correlation_agent.py
  - src/intelligence/ai/alpha/counterfactual_agent.py
  - src/intelligence/ai/alpha/ml_scorer_agent.py
  - src/intelligence/ai/alpha/regime_coherence_agent.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - src/intelligence/ai/narrative/narrative_agent.py
findings:
  critical: 3
  warning: 3
  info: 2
  total: 8
status: issues_found
---

# Phase 110: Code Review Report

**Reviewed:** 2026-05-30
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 110 is a pure rename refactor. The majority of renamed classes (BaseAIWorker, BaseSwarmCoordinator, Evaluator, NarrativeSynthesizer, SkepticEvaluator, CounterfactualEvaluator, CorrelationAnalyzer, RegimeCoherenceAnalyzer, MLEvaluator) are applied correctly inside the reviewed source files. However, three post-rename bugs were introduced or left unresolved:

1. The dashboard `UNIT_TO_AGENT` map still carries old class names that no longer match the Prometheus metric labels emitted by the renamed classes — causing the entire agent health panel to always show as `unknown`.
2. `_prompt_hash` in the narrative route calls `model_dump(sorted_keys=True)`, which is not a valid Pydantic v2 argument and raises `TypeError` at every new narrative generation.
3. `src/api/routes/health.py` reads the `agent_last_message_timestamp_seconds` metric using label key `"agent"`, but `BaseDaemon` emits it under `"agent_id"` — the `/health/system` heartbeat map is always empty.

---

## Critical Issues

### CR-01: `model_dump(sorted_keys=True)` raises TypeError on every narrative generation

**File:** `src/api/routes/narrative.py:152`
**Issue:** `model_dump()` in Pydantic v2 does not accept a `sorted_keys` keyword argument. The call raises `TypeError: BaseModel.model_dump() got an unexpected keyword argument 'sorted_keys'` at runtime. This sits inside `_prompt_hash()`, which is called at line 232 on every cache-miss narrative generation request. The exception escapes to the outer `except Exception` block at line 256, which re-raises it wrapped in a 500 HTTP response. Every first-time narrative generation (i.e. when the signal is not yet cached) will fail with a 500 error. The fix is to sort the output in Python after the dump.

**Fix:**
```python
# Before (line 152):
h.update(str(val.model_dump(sorted_keys=True)).encode())

# After:
dumped = val.model_dump(exclude_none=True)
h.update(str(sorted(dumped.items())).encode())
```

---

### CR-02: `UNIT_TO_AGENT` in dashboard maps old class names — all renamed agents show as `unknown`

**File:** `dashboard/src/hooks/use-observability-stream.ts:71-74, 216`
**Issue:** `UNIT_TO_AGENT` maps systemd unit names to the Prometheus `agent_id` label values emitted via `agent_last_message_timestamp_seconds`. The metric label is set by `BaseDaemon.__init__` using `_last_msg_ts_attrs = {"agent_id": name}`, and `BaseSwarmCoordinator.__init__` (line 74) passes `name=self.__class__.__name__` — so after Phase 110 renames, the emitted label values are now `"AlphaSwarm"`, `"SignalTracker"`, `"CrossAssetAnalyzer"`, and `"GraduationAnalyzer"`. The dashboard still maps to the old names `"AlphaSwarmComputeAgent"`, `"SignalTrackerComputeAgent"`, `"CrossAssetComputeAgent"`, and `"GraduationComputeAgent"`. Additionally, line 216 hardcodes `agentAge["AlphaSwarmComputeAgent"]` which will always be `undefined`, causing the AI Swarm node health to permanently read `"unknown"`.

**Fix:**
```typescript
// Update UNIT_TO_AGENT to use post-rename class names:
const UNIT_TO_AGENT: Record<string, string> = {
  "indicagent-intelligence-pipeline":   "intelligence_pipeline_agent",
  "indicagent-bar-aggregator":          "bar_aggregator_agent",
  "indicagent-signal-tracker-compute":  "SignalTracker",          // was SignalTrackerComputeAgent
  "indicagent-alpha-swarm":             "AlphaSwarm",             // was AlphaSwarmComputeAgent
  "indicagent-cross-asset":             "CrossAssetAnalyzer",     // was CrossAssetComputeAgent
  "indicagent-graduation-compute":      "GraduationAnalyzer",     // was GraduationComputeAgent
  "indicagent-feature-writer":          "feature_writer_agent",
  "indicagent-lifecycle-writer":        "lifecycle_writer_agent",
  "indicagent-lineage-writer":          "lineage_writer_agent",
  "indicagent-signal-writer":           "signal_writer_agent",
};

// And on line 216:
const swarmAge = agentAge["AlphaSwarm"] ?? null;
```

---

### CR-03: `/health/system` reads `agent_last_message_timestamp_seconds` with wrong label key

**File:** `src/api/routes/health.py:121`
**Issue:** `BaseDaemon._last_msg_ts_attrs` is set as `{"agent_id": name}` (confirmed in `src/core/agent/base.py:139`). The `/health/system` route queries `agent_last_message_timestamp_seconds` and at line 121 reads `item["metric"].get("agent", "unknown")`. The key `"agent"` does not exist on this metric; the correct key is `"agent_id"`. As a result, every agent heartbeat is keyed as `"unknown"` and the `agent_heartbeats` response object is effectively useless — all timestamps land on the same `"unknown"` key, with only the last one surviving.

**Fix:**
```python
# Line 121 — change "agent" to "agent_id":
agent_key = item["metric"].get("agent_id", "unknown")
```

---

## Warnings

### WR-01: Dashboard `agentAge` lookup uses wrong label key — silently returns `undefined`

**File:** `dashboard/src/hooks/use-observability-stream.ts:211`
**Issue:** `agentAge` is populated at line 211 using `r.labels["agent"] ?? r.labels["exported_instance"]`. The `agent_last_message_timestamp_seconds` metric is emitted with label key `"agent_id"` (not `"agent"`), so `r.labels["agent"]` is always `undefined`. The fallback `r.labels["exported_instance"]` would only be populated by Prometheus federation scraping. In direct scraping, this means `agentAge` is always empty and all node health derived from it defaults to `"unknown"`. This is related to but distinct from CR-02 — it is the root cause of why agent age lookups fail even for agents that are mapped correctly (e.g., `intelligence_pipeline_agent`).

**Fix:**
```typescript
// Line 211 — change "agent" to "agent_id":
const name = r.labels["agent_id"] ?? r.labels["exported_instance"];
```

---

### WR-02: `IAIAgent` protocol not renamed to `AgentProtocol` per Phase 110 plan

**File:** `src/core/ai/base_agent.py:37`
**Issue:** CLAUDE.md Phase 095 states `IAIAgent` is to be renamed to `AgentProtocol`. Phase 110 is described as the "Renaissance rename phase" and is expected to apply all pending renames. `IAIAgent` is defined at line 37 but its name was not updated. The protocol is imported and tested by name in `tests/unit/core/test_core_ai_base_agent.py` — if the rename is applied here without updating the test file, the tests break. If Phase 110 intentionally defers this rename, there should be a comment here explaining why.

**Fix:** Rename to `AgentProtocol` and update all consumers:
```python
# base_agent.py line 37:
class AgentProtocol(Protocol):  # was IAIAgent
```
Update the test import: `from src.core.ai.base_agent import BaseAIWorker, AgentProtocol`

---

### WR-03: `SERVICE_LAYERS` in dashboard includes two decommissioned services

**File:** `dashboard/src/hooks/use-observability-stream.ts:58, 60`
**Issue:** `SERVICE_LAYERS` layer 6 includes `"indicagent-contract-metadata-writer"` and layer 8 includes `"indicagent-roll-compute"`. Per CLAUDE.md, both were replaced by the nightly `roll-batch` timer in a prior phase — no corresponding systemd daemon units exist in `production/systemd/`. These phantom entries will always show `health: "unknown"` in the service panel, creating misleading operational noise.

**Fix:** Remove both stale entries from `SERVICE_LAYERS`:
```typescript
// Layer 6 — remove "indicagent-contract-metadata-writer"
{ layer: 6, name: "Feature Writers", units: ["indicagent-feature-writer", "indicagent-signal-writer", "indicagent-signal-tracker-compute", "indicagent-lifecycle-writer", "indicagent-lineage-writer", "indicagent-ctx-writer"] },
// Layer 8 — remove "indicagent-roll-compute"
{ layer: 8, name: "Analytics", units: ["indicagent-signal-metrics-compute", "indicagent-signal-metrics-writer", "indicagent-graduation-compute", "indicagent-graduation-writer", "indicagent-feature-snapshot-writer", "indicagent-ml-training"] },
```

---

## Info

### IN-01: `base_group_service.py` module file name does not reflect post-rename class `BaseSwarmCoordinator`

**File:** `src/core/ai/base_group_service.py:1`
**Issue:** The file is named `base_group_service.py` but now contains `class BaseSwarmCoordinator`. This is a naming-system violation per CLAUDE.md's ring rule: concept name derives file name (`base_swarm_coordinator` → `base_swarm_coordinator.py`). All import paths that reference `from src.core.ai.base_group_service import BaseSwarmCoordinator` will continue to work, but the file name is misleading and inconsistent with the renaming intent of Phase 110. This is low priority since Python does not require filename-to-class alignment, but it leaves a confusing artifact.

**Fix:** Rename the file to `base_swarm_coordinator.py` and update all imports:
- `services/alpha_swarm.py:41`
- `services/narrative_swarm.py:23`

---

### IN-02: `_neutral()` calls in agents pass `latency_ms=0.0` instead of actual elapsed time

**File:** `src/intelligence/ai/alpha/correlation_agent.py:120`, `src/intelligence/ai/alpha/counterfactual_agent.py:125`, `src/intelligence/ai/alpha/regime_coherence_agent.py:122`, `src/intelligence/ai/alpha/skeptic_agent.py:113`
**Issue:** When `_llm_generate_structured` returns `None` (instructor retry exhaustion), the agent calls `self._neutral(error="Structured output failed", latency_ms=0.0)`. Since `_llm_generate_structured` can take up to `latency_budget_ms` milliseconds exhausting retries, reporting `latency_ms=0.0` produces a misleading zero in the `AgentOutput` and in `llm_calls` audit rows. The true elapsed time is not captured at the agent level (it is captured by the `BaseAIWorker.compute()` wrapper, which overwrites `latency_ms` with the real value). This is a minor inaccuracy in the payload field but does not affect the outer wrapper's timing.

**Fix:** This is effectively cosmetic given that `compute()` overwrites the value; document the intent with a comment, or measure elapsed time from the call site. No code change required unless the per-agent payload field is used directly.

---

_Reviewed: 2026-05-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
