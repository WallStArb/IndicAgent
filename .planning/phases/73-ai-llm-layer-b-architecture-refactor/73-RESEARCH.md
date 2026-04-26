# Phase 73: AI LLM Layer B+ Architecture Refactor — Research

**Researched:** 2026-04-26
**Domain:** Python AI agent infrastructure, LLM chain refactoring, module reorganization, systemd service management
**Confidence:** HIGH (all findings verified against actual source files)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Fix D-01: Delete `services/swarm_orchestrator_agent.py`
- Fix D-02: Delete `/etc/systemd/system/indicagent-swarm-orchestrator.service`
- Fix D-03: Rename `swarm_dispatch_service.py` → `alpha_swarm_agent.py`; class `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent`
- Fix D-04: LLM rate limiter — call `await limiter.acquire(tokens=max_tokens)` in `chain.py` before provider dispatch
- Fix D-05: Guardrails — remove dead branch; if no schema registered, skip `validate()` entirely
- Fix D-06: Auto-audit — add `audit_context: dict | None = None` param to `LLMProviderChain`; publish to `llm.calls` topic when provided
- Fix D-07: Real token counts — use `response_meta["usage"]["total_tokens"]` from OpenRouter when present
- Fix D-08: Cache key — `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation in `semantic_cache.py`
- Fix D-09: Remove `WatchdogSec=60` + `NotifyAccess=main` from swarm-orchestrator systemd unit (already deleted by D-02)
- Fix D-10: Replace private `_context_cache._cache` access in `_find_lead_context` with public `AIContextCache.get_lead(symbol, tf)` method
- New infrastructure: `src/core/ai/` — 5 files (base_agent, base_group_service, context, output, safe_wrapper)
- Module moves: `src/intelligence/swarm/agents/` → `src/intelligence/ai/alpha/`; `src/intelligence/narrative/` → `src/intelligence/ai/narrative/`
- ABSORB: `src/core/swarm/base_agent.py` → `src/core/ai/base_agent.py`; `src/intelligence/swarm/context.py` → `src/core/ai/context.py`; `src/intelligence/swarm/safety.py` → `src/core/ai/safe_wrapper.py`
- KEEP: `src/intelligence/swarm/aggregator.py`, `src/intelligence/swarm/graduation.py`
- Narrative TF gate: `{"5m", "15m", "1h", "4h", "1d"}` — reject anything else before LLM call
- All agents extend `BaseAIAgent` instead of `SwarmBaseAgent`
- Shadow mode default: `shadow_only=True`
- Import boundary: `src/core/ai/` and `src/intelligence/ai/` import only from `schemas.py` and `stream_keys.py`

### Claude's Discretion

- Exact test coverage scope (unit tests for new base classes, integration tests for group service dispatch)
- Order of migration steps within execution (can be sequenced for minimal service disruption)
- Whether to update CLAUDE.md service table with renamed services
- Systemd unit file name for renamed alpha swarm agent

### Deferred Ideas (OUT OF SCOPE)

- Approach C (Independent AI Package): Extract `src/ai/` with `AILayerRouter`
- i2, i3, i5 tier contexts in AIContext (placeholder comment only)
- RiskSwarmComputeAgent (placeholder `__init__.py` only)
- Qualitative intelligence group

</user_constraints>

---

## Summary

Phase 73 refactors a structurally defective AI/LLM layer into a clean, extensible architecture. The current state has the `swarm_orchestrator_agent` running as an active systemd service (PID 281147, enabled) with zero contributors registered — it does nothing but consume resources. The real working service (`swarm_dispatch_service.py`) is NOT installed as a systemd service. This is the highest-priority defect to fix.

The codebase contains a well-built LLM infrastructure (`src/core/llm/`) that is partially wired: `RateLimiter` exists but `acquire()` is never called; `GuardrailsValidator.validate()` is called but only when schema is registered (creating a false-safety dead branch); the semantic cache key truncates at 200 chars enabling cross-symbol collisions; token usage returns estimated (not actual) counts. These are surgical one-file fixes.

The module reorganization is the largest work item: three swarm agents move from `src/intelligence/swarm/agents/` to `src/intelligence/ai/alpha/`, the narrative module moves from `src/intelligence/narrative/` to `src/intelligence/ai/narrative/`, and five new files in `src/core/ai/` replace the existing `src/core/swarm/` base classes. Every Python test that imports from old paths must be updated. There are 87 passing baseline tests across swarm/narrative/LLM code — all must continue passing after migration.

**Primary recommendation:** Execute in seven waves: (1) delete dead orchestrator, (2) build `src/core/ai/` infrastructure, (3) move agents, (4) fix LLM chain, (5) rename dispatch service, (6) refactor narrative service, (7) update tests and verify.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| AI agent protocol (IAIAgent, BaseAIAgent) | `src/core/ai/` | — | Framework-level concern, reused across all groups |
| Group dispatch infrastructure (BaseGroupService) | `src/core/ai/` | — | Same lifecycle regardless of agent type |
| Context building and caching (AIContext, AIContextCache) | `src/core/ai/` | — | Generalized from SwarmContext; shared across all groups |
| LLM chain (rate limit, cache, audit, tokens) | `src/core/llm/` | — | Existing home, 6 fixes applied in place |
| Alpha agents (skeptic, correlation, volume) | `src/intelligence/ai/alpha/` | — | Mandate-specific compute, imports only core/ai |
| Narrative agents | `src/intelligence/ai/narrative/` | — | Mandate-specific, separate group |
| Risk agents (future) | `src/intelligence/ai/risk/` | — | Placeholder only |
| Alpha aggregation math | `src/intelligence/swarm/aggregator.py` | — | Kept; called by AlphaSwarmComputeAgent |
| Graduation gate math | `src/intelligence/swarm/graduation.py` | — | Kept; called by BaseGroupService.graduation_loop |
| Service entry points | `services/alpha_swarm_agent.py`, `services/ai_narrative_agent.py` | — | Thin shells extending BaseGroupService |
| Systemd service management | `/etc/systemd/system/` | — | Delete orchestrator unit; new alpha-swarm unit needed |

---

## Current State Inventory (Verified Against Source)

### Files Being Deleted

| File | Verified Status |
|------|----------------|
| `services/swarm_orchestrator_agent.py` | EXISTS — 244 lines, zero contributors registered in `main()` |
| `/etc/systemd/system/indicagent-swarm-orchestrator.service` | EXISTS — active (running), enabled, has `WatchdogSec=60` + `NotifyAccess=main` (CLAUDE.md violation) |

**CRITICAL:** `indicagent-swarm-orchestrator` is currently `active (running)` with PID 281147 — it must be stopped and disabled before deleting the unit file. The service has been running since 2026-04-24 doing nothing (contributors=[]). The `services/indicagent-swarm-dispatch.service` reference template exists but the service is NOT installed in `/etc/systemd/system/` — only the orchestrator is installed.

### Files Being Renamed

| Old Path | New Path | Class Rename |
|----------|----------|-------------|
| `services/swarm_dispatch_service.py` | `services/alpha_swarm_agent.py` | `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent` |

### Files Being Moved (with Prompt Peers)

The design doc specifies moving agent files. The prompt files are peer dependencies that must move together:

| Old Path | New Path | Peer Files That Also Move |
|----------|----------|--------------------------|
| `src/intelligence/swarm/agents/skeptic_agent.py` | `src/intelligence/ai/alpha/skeptic_agent.py` | `skeptic_prompts.py` → `src/intelligence/ai/alpha/skeptic_prompts.py` |
| `src/intelligence/swarm/agents/correlation_agent.py` | `src/intelligence/ai/alpha/correlation_agent.py` | `correlation_prompts.py` → `src/intelligence/ai/alpha/correlation_prompts.py` |
| `src/intelligence/swarm/agents/volume_agent.py` | `src/intelligence/ai/alpha/volume_agent.py` | `volume_prompts.py` → `src/intelligence/ai/alpha/volume_prompts.py` |
| `src/intelligence/narrative/orchestrator.py` | `src/intelligence/ai/narrative/narrative_agent.py` | `prompts.py`, `parsers.py` (also move) |

Note: The archived agents (`_archived_*.py`) stay in `src/intelligence/swarm/agents/` and are not moved — they reference `IAlphaContributor` (old interface) which is no longer valid but they're already archived.

### Files Being Absorbed (Logic Migrated, Not Copied)

| Source | Absorbed Into | What to Preserve |
|--------|--------------|-----------------|
| `src/core/swarm/base_agent.py` (`SwarmBaseAgent`) | `src/core/ai/base_agent.py` (`BaseAIAgent`) | asyncio timeout, exception safety, structured logging, `_neutral()` pattern |
| `src/intelligence/swarm/context.py` (`SwarmContext`, `SwarmContextCache`) | `src/core/ai/context.py` (`AIContext`, `AIContextCache`) | `seed_from_db_row()`, `_TTL_SECONDS` TTL logic, `build()` field mapping; generalize hardcoded I4/I6 fields into typed tier contexts |
| `src/intelligence/swarm/safety.py` (`SafeSwarmWrapper`) | `src/core/ai/safe_wrapper.py` (`SafeAgentWrapper`) | timeout enforcement, neutral AgentOutput fallback |

### Files Kept (NOT Moved)

| File | Reason |
|------|--------|
| `src/intelligence/swarm/aggregator.py` | Used directly by `AlphaSwarmComputeAgent` |
| `src/intelligence/swarm/graduation.py` | Used by `graduation_compute_agent.py` (existing service) AND `BaseGroupService._graduation_loop` |
| `src/intelligence/swarm/metrics.py` | Prometheus metrics — leaving in place avoids metric name churn; update docstring |
| `src/intelligence/swarm/interface.py` | Backward-compat re-export for `IAlphaContributor`; archived agents reference it |
| `src/intelligence/swarm/registry.py` | Not imported by any active (non-archived) code |
| `src/intelligence/swarm/prompt_registry.py` | Not imported by any active code |
| `src/intelligence/swarm/dummy_contributors.py` | Not imported by any active code |

---

## Standard Stack

### Core (existing, no version changes needed)

| Library | Purpose | Notes |
|---------|---------|-------|
| `pydantic` (v2) | Frozen models for AIContext, AgentOutput | `ConfigDict(frozen=True)` pattern already used in `SwarmContext` |
| `asyncio` | Concurrent agent dispatch in `asyncio.gather` | Already used throughout swarm dispatch |
| `structlog` | Structured logging in all agents | `setup_service_logging()` pattern from `BaseAgent` |
| `asyncpg` | DB pool for AIContextCache seeding | Already used in `SwarmDispatchComputeAgent._seed_context_cache` |
| `hashlib` | SHA-256 cache key (fix D-08) | Already imported in `semantic_cache.py`; fix removes `[:200]` |

### New Patterns

| Pattern | Where | How |
|---------|-------|-----|
| `ABC` + `Protocol` | `src/core/ai/base_agent.py` | `IAIAgent` Protocol for type-checking; `BaseAIAgent(ABC)` for implementation |
| `Tier` enum (`str, Enum`) | `src/core/ai/context.py` | BAR, I1, I2, I3, I4, I5, I6, I7 — frozenset[Tier] on each agent |
| `model_copy(update=...)` | `BaseAIAgent.compute()`, `SafeAgentWrapper` | Already used in `SwarmDispatchComputeAgent._enrich_context` |

---

## Architecture Patterns

### System Architecture Diagram

```
I7 Signal Event (topic_intelligence_i7_signals)
  │
  ▼
AlphaSwarmComputeAgent (BaseGroupService)
  │   bar_loop: AIContextCache.update(IntelligenceEvent)
  │   trigger_loop: _handle_trigger(event)
  │       └─ AIContextCache.build(symbol, tf, agent.tiers_needed) → AIContext
  │       └─ asyncio.gather([SafeAgentWrapper(agent).compute(ctx) for agent in agents])
  │           ├─ SkepticAgentComputeAgent._compute()   → LLMProviderChain → AgentOutput
  │           ├─ CorrelationAgentComputeAgent._compute() → LLMProviderChain → AgentOutput
  │           └─ VolumeAgentComputeAgent._compute()    → LLMProviderChain → AgentOutput
  │       └─ SwarmAggregator.aggregate(outputs) → AlphaMultiplier
  │       └─ publish(topic_swarm_alpha), publish(topic_swarm_results)
  │   graduation_loop (15 min): evaluate_all() → auto-flip shadow_only
  │
LLMProviderChain.generate(prompt, system, max_tokens, timeout, audit_context)
  │   rate_limiter.acquire(tokens=max_tokens)            ← FIX D-04
  │   semantic_cache.get(sha256(system+prompt+model))    ← FIX D-08
  │   budget.is_exceeded() → route to Ollama if True
  │   provider.generate() with circuit breaker
  │   guardrails.validate() if schema registered         ← FIX D-05
  │   budget.record(actual_tokens from response.usage)   ← FIX D-07
  │   semantic_cache.put(...)
  │   if audit_context: publish to topic_llm_calls       ← FIX D-06

Intelligence Journal Event (topic_intelligence_journal)
  │
  ▼
NarrativeGroupComputeAgent (BaseGroupService)
  │   trigger_loop: _handle_trigger(event)
  │       └─ TF gate: reject if tf not in {"5m","15m","1h","4h","1d"}
  │       └─ NarrativeComputeAgent._compute() → LLMProviderChain → AgentOutput
  │       └─ publish(topic_narratives)
```

### Recommended Project Structure (Post-Phase)

```
src/core/ai/                        ← NEW — universal AI infrastructure
    __init__.py
    base_agent.py                   ← BaseAIAgent ABC + IAIAgent Protocol
    base_group_service.py           ← BaseGroupService shared dispatcher
    context.py                      ← AIContext, AIContextCache, Tier enum, TierContext models
    output.py                       ← AgentOutput universal envelope
    safe_wrapper.py                 ← SafeAgentWrapper (timeout + exception isolation)

src/core/llm/                       ← EXISTS — 6 fixes applied
    chain.py                        ← + rate limiter called, auto-audit, real tokens, guardrails fixed
    semantic_cache.py               ← cache key: full prompt hash (remove [:200])
    guardrails.py                   ← dead branch removed
    providers.py, rate_limiter.py, token_budget.py  ← unchanged

src/intelligence/ai/                ← NEW — mandate-based agent groups
    alpha/
        __init__.py
        skeptic_agent.py            ← moved + extends BaseAIAgent
        skeptic_prompts.py          ← moved (peer)
        correlation_agent.py        ← moved + extends BaseAIAgent
        correlation_prompts.py      ← moved (peer)
        volume_agent.py             ← moved + extends BaseAIAgent
        volume_prompts.py           ← moved (peer)
    narrative/
        __init__.py
        narrative_agent.py          ← refactored from orchestrator.py + extends BaseAIAgent
        prompts.py                  ← moved
        parsers.py                  ← moved
    risk/
        __init__.py                 ← placeholder only

src/intelligence/swarm/             ← TRIMMED — kept files only
    aggregator.py                   ← kept
    graduation.py                   ← kept
    (other files: metrics, interface, registry — kept but not actively used)

services/
    alpha_swarm_agent.py            ← RENAMED from swarm_dispatch_service.py
    ai_narrative_agent.py           ← REFACTORED to extend BaseGroupService
    (swarm_dispatch_service.py and swarm_orchestrator_agent.py: DELETED)
```

---

## LLM Chain Fixes — Verified Current State

### Fix D-04: Rate Limiter Never Called
**Current code in `chain.py`:** `RateLimiter` is instantiated in `__init__` and stored in `self._rate_limiters` dict but `acquire()` is never called in `generate()`. The `self._rate_limiters` dict is populated from `settings.LLM_RATE_LIMITS` but the `generate()` method has no call to `limiter.acquire()` anywhere. [VERIFIED: src/core/llm/chain.py]

**Fix:** Before provider dispatch, look up the provider's rate limiter (by `self._inner.last_provider_id` or default) and call `await limiter.acquire(tokens=max_tokens)`.

**Note:** The rate limiter must be called BEFORE the cache lookup is bypassed — if cached, no need to acquire. Insert after cache miss check.

### Fix D-05: Guardrails Dead Branch
**Current code in `chain.py` line 127:** `if self._call_type and self._call_type in _guardrails._schemas:` — this check prevents calling `validate()` when no schema is registered. However `guardrails.py:validate()` already handles `schema is None` by returning `None`. The chain code then interprets `None` from `validate()` as rejection and returns `None` to the caller — even for valid responses when no schema was registered. [VERIFIED: src/core/llm/chain.py lines 127-133, src/core/llm/guardrails.py lines 32-34]

**Fix:** The chain's guard `self._call_type in _guardrails._schemas` is the actual dead-branch check. Remove it; let `guardrails.validate()` handle the no-schema case (its own `if schema is None: return None` already handles it). But this would still break callers since `None` from validate means rejection. **Correct fix:** Remove the entire `validate()` call when no schema is registered — check `if _guardrails.has_schema(self._call_type):` and add a `has_schema()` method to `GuardrailsValidator`, OR inline the check: only call `validate()` when `self._call_type in _guardrails._schemas`.

**Simplest correct implementation:** Keep the existing guard check `if self._call_type and self._call_type in _guardrails._schemas:` but rename the private `_schemas` attribute to public OR add `has_schema()` method. The CONTEXT says "remove dead branch; if no schema registered, skip `validate()` entirely" — the existing check does this correctly; the defect description says the false confidence is that guardrails "silently pass everything" when no schema is registered, which is actually correct behavior. The fix is documentation/intent clarity plus ensuring the check doesn't accidentally fail to access `_schemas`.

### Fix D-07: Real Token Counts
**Current code:** `providers.py` `OpenRouterProvider.generate()` calls `_call_llm_with_circuit_breaker` which parses the JSON response but only extracts `choices[].message.content`. The `usage` field in the OpenRouter response (`{"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}`) is never captured. [VERIFIED: src/core/llm/providers.py lines 264-293]

**What needs changing:** `LLMChain.generate()` currently returns `str | None`. To surface token usage, either:
1. Return `tuple[str | None, dict]` (breaks callers) — bad approach
2. Store `last_token_usage: dict | None` on `LLMChain` (same pattern as `last_provider_id`) — correct approach
3. Pass a callback — over-engineered

**Correct approach:** Add `self.last_token_usage: dict | None = None` on `LLMChain`, populate from `result.get("usage", {})` in `OpenRouterProvider._call()`, then read in `LLMProviderChain.generate()` via `getattr(self._inner, "last_token_usage", None)`.

### Fix D-08: Cache Key Truncation
**Current code in `semantic_cache.py` line 23:** `raw = f"{system}|{prompt[:200]}|{model}"` [VERIFIED: src/core/llm/semantic_cache.py]

**Fix:** Change to `raw = f"{system}|{prompt}|{model}"` — remove `[:200]`. Single-line change.

### Fix D-10: Private Cache Access
**Current code in `swarm_dispatch_service.py` lines 363, 444:** Two locations access `self._context_cache._cache` directly (a private dict). [VERIFIED: services/swarm_dispatch_service.py]

**Fix:** Add `get_lead(symbol, tf)` method to `AIContextCache` in `src/core/ai/context.py`. The method encapsulates the prefix-search logic currently in `_find_lead_context`. The `AlphaSwarmComputeAgent` calls `self._context_cache.get_lead(symbol, tf)` instead of accessing `._cache`.

---

## Import Impact Analysis (Complete)

### Files That Import From Paths Being Deleted/Moved

All of these need updating during migration:

**Imports `src/core/swarm.base_agent` (SwarmBaseAgent):**
- `src/core/swarm/__init__.py` — re-exports SwarmBaseAgent (keep or remove)
- `src/intelligence/swarm/agents/skeptic_agent.py` → moves to `src/intelligence/ai/alpha/`, imports BaseAIAgent
- `src/intelligence/swarm/agents/correlation_agent.py` → moves, imports BaseAIAgent
- `src/intelligence/swarm/agents/volume_agent.py` → moves, imports BaseAIAgent

**Imports `src/intelligence/swarm.context` (SwarmContext, SwarmContextCache):**
- `services/swarm_dispatch_service.py` → becomes `alpha_swarm_agent.py`, uses AIContext/AIContextCache
- `src/core/swarm/base_agent.py` (TYPE_CHECKING only) → absorbed into base_agent.py
- `src/core/agents/alpha_contributor.py` (TYPE_CHECKING only) → update to AIContext
- `src/intelligence/swarm/agents/correlation_agent.py` → moves, uses AIContext
- `src/intelligence/swarm/agents/skeptic_agent.py` → moves, uses AIContext
- `src/intelligence/swarm/agents/volume_agent.py` → moves, uses AIContext
- `src/intelligence/swarm/agents/correlation_prompts.py` → moves, uses AIContext
- `src/intelligence/swarm/agents/skeptic_prompts.py` → moves, uses AIContext
- `src/intelligence/swarm/agents/volume_prompts.py` → moves, uses AIContext
- `src/intelligence/swarm/safety.py` → absorbed into safe_wrapper.py
- Tests: `test_swarm_dispatch.py`, `test_swarm_dispatch_integration.py`, `test_swarm_protocol.py`, `test_swarm_safety.py`, `test_skeptic_agent.py`, `test_correlation_agent.py`, `test_volume_agent.py`
- Tests: `service_tests/test_swarm_orchestrator_agent.py`, `service_tests/test_swarm_orchestrator_seeding.py`

**Imports `src/intelligence/narrative`:**
- `services/ai_narrative_agent.py` → refactored to use `src/intelligence/ai/narrative/narrative_agent.py`
- `src/intelligence/narrative/__init__.py` → update to re-export from new location (or delete)
- Tests: `test_narrative_orchestrator.py`, `test_narrative_parsers.py`, `test_narrative_prompts.py`

**Imports from `services/swarm_orchestrator_agent.py` (being deleted):**
- `tests/unit/service_tests/test_swarm_orchestrator_agent.py` → DELETE this test file
- `tests/unit/service_tests/test_swarm_orchestrator_seeding.py` → DELETE this test file

**Imports from `services/swarm_dispatch_service.py` (being renamed):**
- `tests/unit/test_swarm_dispatch.py` → update import path to `alpha_swarm_agent`
- `tests/unit/test_swarm_dispatch_integration.py` → update import path

---

## New Topic Needed in stream_keys.py

The design specifies `aggregate_topic=topic_swarm_alpha` for `AlphaSwarmComputeAgent`. Currently only `topic_swarm_alpha_path_a` and `topic_swarm_alpha_path_b` exist. A new `topic_swarm_alpha()` function is needed. [VERIFIED: grep of stream_keys.py]

Similarly, `BaseGroupService._graduation_loop` publishes to `topic_swarm_graduation` — this topic function does not exist. `topic_transform_graduation` exists (for the GraduationComputeAgent) but that is a different topic. A `topic_swarm_graduation()` function is needed for per-agent shadow_only flip events.

**Additions to `src/core/stream_keys.py`:**
```python
def topic_swarm_alpha(env_name: str) -> str:
    """Assembled AlphaMultiplier from all swarm paths (unified aggregate)."""
    return f"{env_prefix(env_name)}swarm.alpha"

def topic_swarm_graduation(env_name: str) -> str:
    """Per-agent graduation flip events from BaseGroupService._graduation_loop."""
    return f"{env_prefix(env_name)}swarm.graduation"
```

---

## AgentResult → AgentOutput Schema Change

**Current:** `AgentResult` in `src/intelligence/schemas.py` has fields: `agent_id`, `path` (Literal["deterministic", "llm_swarm"]), `multiplier`, `confidence`, `shadow_only`, `metadata`, `latency_ms`, `error`. [VERIFIED: schemas.py lines 878-892]

**New:** `AgentOutput` in `src/core/ai/output.py` has fields: `agent_id`, `group`, `signal_id`, `symbol`, `timeframe`, `ts`, `output_type`, `payload` (untyped dict), `shadow_only`, `latency_ms`, `error`.

**Migration impact:** The swarm aggregator (`aggregator.py`) reads `AgentResult.multiplier` and `AgentResult.confidence`. After migration, it will receive `AgentOutput` objects and read `payload["multiplier"]` and `payload["confidence"]`. `aggregator.py` is kept but its aggregate method signature must be updated to accept `list[AgentOutput]`.

`SwarmAggregator.aggregate()` currently takes explicit path_a/path_b lists with typed `AgentResult`. Under new design it takes `list[AgentOutput]`. The split into path_a/path_b may be removed (all agents are LLM now — no "deterministic" path). [VERIFIED: src/intelligence/swarm/aggregator.py]

**Also:** `AlphaMultiplier` in `schemas.py` has `contributors: dict[str, AgentResult]` — this will need to accept `dict[str, AgentOutput]` or a new `AlphaMultiplier` type needs to be created in `src/core/ai/output.py`.

---

## Common Pitfalls

### Pitfall 1: Prompt Files Are Not Listed in Migration Checklist
**What goes wrong:** The design doc migration checklist lists `skeptic_agent.py`, `correlation_agent.py`, `volume_agent.py` but not their peer prompt files (`skeptic_prompts.py`, `correlation_prompts.py`, `volume_prompts.py`). If prompt files are not moved, agents in their new location will have broken relative imports.
**Why it happens:** Prompts are implementation details, not interfaces — easy to overlook.
**How to avoid:** Move prompt files alongside their agents. Update imports in agent files to use new path.
**Warning signs:** `ImportError` on agent import after move.

### Pitfall 2: Tests Reference Deleted Service File
**What goes wrong:** `test_swarm_orchestrator_agent.py` and `test_swarm_orchestrator_seeding.py` import from `services.swarm_orchestrator_agent` which is being deleted. If tests aren't also deleted, `pytest` will fail on import.
**How to avoid:** Delete both test files when deleting the service file (D-01).

### Pitfall 3: Swarm Orchestrator Is Currently Running — Must Stop Before Delete
**What goes wrong:** The systemd unit file cannot be safely deleted while the service is active. The service is enabled — it will restart on boot if not disabled.
**How to avoid:** `sudo systemctl stop indicagent-swarm-orchestrator && sudo systemctl disable indicagent-swarm-orchestrator` before deleting the unit file. Then `sudo systemctl daemon-reload`.
**Warning signs:** `rm` succeeds but `systemctl status` still shows the unit (systemd caches unit files).

### Pitfall 4: Old Consumer Groups Leave Kafka Lag Monitors Confused
**What goes wrong:** After deleting `swarm_orchestrator_agent.py`, the consumer groups `swarm_orchestrator_bar_consumer` and `swarm_orchestrator_signal_consumer` will show as "Stable" with 0 lag because no consumer is reading them (they were reading from topics but not processing anything). They're not harmful but are noise in `rpk group list`.
**How to avoid:** Note that these consumer groups can be cleaned up with `rpk group delete` if desired, but this is optional (not blocking).

### Pitfall 5: Module-Level `_cache`, `_budget`, `_guardrails` Singletons in chain.py
**What goes wrong:** `chain.py` creates `_cache = SemanticCache(...)`, `_budget = TokenBudget(...)`, `_guardrails = GuardrailsValidator()` at module import time. If `rate_limiter.acquire()` is added as a module-level singleton too, all chain instances share one rate limiter — which may or may not be desired.
**How to avoid:** Rate limiters are per-provider (in `self._rate_limiters`). The `acquire()` call should look up the right limiter by provider ID. If no rate limiter configured for a provider, skip the acquire call.

### Pitfall 6: `NarrativeOrchestrator` Has Different Interface Than `BaseAIAgent._compute()`
**What goes wrong:** Current `NarrativeOrchestrator.generate()` takes a `BarIntelligenceRecord` object with dict-adapter compatibility. The new `NarrativeComputeAgent._compute()` receives `AIContext`. The context-to-prompt mapping logic in `orchestrator.py` must be rewritten to use `AIContext` fields.
**How to avoid:** Read `parsers.py` and `prompts.py` carefully before writing `NarrativeComputeAgent._compute()`. The `parse_bar_intelligence_record` function reads from `record.intelligence.symbol/tf/ts` and `record.winner_direction` — equivalent fields exist in `AIContext` (`symbol`, `timeframe`, `ts`, `i7.winner_plugin` etc.).

### Pitfall 7: `BaseGroupService` Must Extend `BaseAgent` — Not Just `ABC`
**What goes wrong:** If `BaseGroupService` doesn't call `super().__init__()` from `BaseAgent`, it loses SIGINT/SIGTERM handling, structured logging, Prometheus metrics server, and the `_run()`/`_setup()`/`_teardown()` lifecycle. These are critical for service stability.
**How to avoid:** `class BaseGroupService(BaseAgent): ...` — call `super().__init__(name=..., max_idle_seconds=...)` in `__init__`. The `_setup`, `_run`, `_teardown` methods must match `BaseAgent`'s contract (they're not abstract in BaseAgent — they're no-ops that subclasses override). [VERIFIED: src/core/agent/base.py lines 209-220]

### Pitfall 8: `AIContext` Must Be Frozen Pydantic But `lead_context` Is Self-Referential
**What goes wrong:** `AIContext` has `lead_context: AIContext | None = None` — a self-referential frozen model. Pydantic v2 supports this with `model_rebuild()` but requires `from __future__ import annotations` and `model_rebuild()` call after class definition.
**How to avoid:** Use the forward reference pattern: `lead_context: "AIContext | None" = None` with `AIContext.model_rebuild()` after class definition. This is the same pattern used in `SwarmContext.lead_context: SwarmContext | None`. [VERIFIED: src/intelligence/swarm/context.py line 72]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SHA-256 hashing | Custom hash function | `hashlib.sha256(raw.encode()).hexdigest()` | Already in semantic_cache.py |
| Asyncio timeout | Try/except around awaits | `asyncio.wait_for(coro, timeout)` | Already in `SwarmBaseAgent.compute()` |
| Pydantic frozen models | Custom `__setattr__` guards | `ConfigDict(frozen=True)` + `model_copy(update=...)` | Already proven pattern in SwarmContext |
| Token bucket rate limiting | Custom sleep loop | `src/core/llm/rate_limiter.py` `RateLimiter.acquire()` | Already built, just not wired |
| LLM provider fallback chain | Per-agent provider logic | `src/core/llm/providers.py` `LLMChain` | Already built with circuit breaker |
| Graduation math | Custom Spearman calculation | `src/intelligence/swarm/graduation.py` `evaluate_all()` | Already built, proven |

---

## Code Examples

### BaseAIAgent Pattern (from design doc, verified against SwarmBaseAgent)
```python
# Source: docs/plans/2026-04-26-ai-llm-layer-design.md
class BaseAIAgent(ABC):
    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    shadow_only: bool = True
    latency_budget_ms: float = 5000.0

    @abstractmethod
    async def _compute(self, context: AIContext) -> AgentOutput: ...

    async def compute(self, context: AIContext) -> AgentOutput:
        t0 = time.monotonic()
        try:
            result = await self._compute(context)
            return result.model_copy(update={"latency_ms": (time.monotonic() - t0) * 1000})
        except Exception as exc:
            return self._neutral(error=str(exc), latency_ms=(time.monotonic() - t0) * 1000)
```

### Cache Key Fix (D-08)
```python
# Source: src/core/llm/semantic_cache.py — current (broken)
raw = f"{system}|{prompt[:200]}|{model}"

# Fixed
raw = f"{system}|{prompt}|{model}"
```

### Guardrails Fix (D-05) — Current code in chain.py
```python
# Current (line 127) — the check is correct but needs slight refactor
if self._call_type and self._call_type in _guardrails._schemas:
    validated = _guardrails.validate(self._call_type, response)
    if validated is None:
        return None
# Note: accessing _guardrails._schemas (private) — add has_schema() method OR keep check
# The fix is to add GuardrailsValidator.has_schema() to avoid private attr access
```

### Rate Limiter Wiring (D-04)
```python
# In LLMProviderChain.generate() — add BEFORE provider dispatch, AFTER cache miss
# Get the limiter for the "default" provider or skip if not configured
limiter = self._rate_limiters.get("default") or next(iter(self._rate_limiters.values()), None)
if limiter is not None:
    await limiter.acquire(tokens=max_tokens)
```

### SwarmContext → AIContext Context Building
```python
# Current (SwarmContextCache.build) — hardcodes I1/I4/I6 fields
# New (AIContextCache.build) — uses tiers_needed to populate only declared tiers
def build(self, symbol: str, tf: str, tiers_needed: frozenset[Tier]) -> AIContext | None:
    entry = self._cache.get((symbol, tf))
    if not entry:
        return None
    event, cached_at = entry
    if time.monotonic() - cached_at > _TTL_SECONDS:
        return None
    return AIContext(
        symbol=symbol, timeframe=tf, ts=event.ts, trigger="signal",
        i1=I1Context(...) if Tier.I1 in tiers_needed else None,
        i4=I4Context(...) if Tier.I4 in tiers_needed else None,
        i6=I6Context(...) if Tier.I6 in tiers_needed else None,
    )
```

### get_lead() Public Method (D-10)
```python
# In AIContextCache — replaces private _cache access in alpha_swarm_agent.py
def get_lead(self, symbol: str, tf: str, lead_map: dict[str, str]) -> "AIContext | None":
    """Look up lead index context without exposing _cache internals."""
    base = _extract_base(symbol)
    lead_base = lead_map.get(base)
    if not lead_base or lead_base == base:
        return None
    for (s, t), entry in self._cache.items():
        if s.startswith(lead_base) and t == tf:
            event, _ = entry
            return self.build(s, t, frozenset({Tier.I1, Tier.I4, Tier.I6}))
    return None
```

---

## Systemd Service Changes

### Services to Stop/Disable/Delete
| Action | Target | Command |
|--------|--------|---------|
| Stop | `indicagent-swarm-orchestrator` | `sudo systemctl stop indicagent-swarm-orchestrator` |
| Disable | `indicagent-swarm-orchestrator` | `sudo systemctl disable indicagent-swarm-orchestrator` |
| Delete unit file | `/etc/systemd/system/indicagent-swarm-orchestrator.service` | `sudo rm /etc/systemd/system/indicagent-swarm-orchestrator.service` |
| Reload | systemd daemon | `sudo systemctl daemon-reload` |

### New Unit File Needed
The renamed `alpha_swarm_agent.py` needs a new unit file: `indicagent-alpha-swarm.service`. Per CLAUDE.md naming: concept is `alpha_swarm` → unit is `indicagent-alpha-swarm.service`. Per CLAUDE.md watchdog rule: **do NOT add `WatchdogSec` or `NotifyAccess`** since no `sd_notify` is implemented.

Template based on existing `services/indicagent-swarm-dispatch.service` (removing the `Wants/After indicagent-swarm-orchestrator` dependency):
```ini
[Unit]
Description=IndicAgent Alpha Swarm Compute Agent — LLM alpha multiplier agents
After=network-online.target indicagent-redpanda-ready.service
Requires=indicagent-redpanda-ready.service

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/alpha_swarm_agent.py
Restart=always
RestartSec=10
TimeoutStopSec=75
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-alpha-swarm
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Note: The `ai_narrative_agent.py` unit file is already installed as `indicagent-ai-narrative.service` — no name change needed (the service class inside will change but the unit stays).

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` or inline config |
| Quick run command | `.venv/bin/pytest tests/unit/test_swarm_dispatch.py tests/unit/test_skeptic_agent.py tests/unit/test_narrative_orchestrator.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q --tb=short` |

### Baseline Test Status (Verified)
```
87 passed in 0.77s (swarm/narrative/LLM-related tests only)
3290 passed, 22 failed total (failures are pre-existing, unrelated to this phase)
```

### Phase Requirements → Test Map

| Req | Behavior | Test Type | Command | File |
|-----|----------|-----------|---------|------|
| D-01 | swarm_orchestrator_agent.py deleted | smoke | `python -c "import services.swarm_orchestrator_agent"` exits with ImportError | DELETE test files |
| D-02 | systemd unit deleted | manual | `ls /etc/systemd/system/indicagent-swarm-orchestrator.service` returns not found | manual |
| D-03 | alpha_swarm_agent.py exists, class name correct | smoke | `python -c "from services.alpha_swarm_agent import AlphaSwarmComputeAgent"` | ❌ Wave 0 |
| D-04 | rate limiter called | unit | `test_rate_limiter_called_before_dispatch` | ❌ Wave 0 |
| D-05 | guardrails skip when no schema | unit | `test_guardrails_skip_when_no_schema_registered` | ❌ Wave 0 |
| D-06 | auto-audit publishes to topic | unit | `test_auto_audit_publishes_when_audit_context_provided` | ❌ Wave 0 |
| D-07 | real token counts used | unit | `test_real_token_count_from_response_usage` | ❌ Wave 0 |
| D-08 | cache key uses full prompt | unit | `test_cache_key_no_truncation` — verify two prompts differing after char 200 get different keys | ❌ Wave 0 |
| D-10 | get_lead() method exists | unit | `test_context_cache_get_lead_method` | ❌ Wave 0 |
| NEW | BaseAIAgent ABC contract | unit | `test_base_ai_agent_requires_compute_implementation` | ❌ Wave 0 |
| NEW | AIContext frozen model | unit | `test_ai_context_is_frozen` | ❌ Wave 0 |
| NEW | AgentOutput universal envelope | unit | `test_agent_output_payload_untyped` | ❌ Wave 0 |
| NEW | Narrative TF gate | unit | `test_narrative_rejects_1m_bars` | ❌ Wave 0 |
| MOVE | Skeptic agent at new path | unit | update `test_skeptic_agent.py` imports | ❌ Wave 0 |
| MOVE | Correlation agent at new path | unit | update `test_correlation_agent.py` imports | ❌ Wave 0 |
| MOVE | Volume agent at new path | unit | update `test_volume_agent.py` imports | ❌ Wave 0 |
| MOVE | Narrative at new path | unit | update `test_narrative_*.py` imports | ❌ Wave 0 |

### Wave 0 Gaps
- [ ] `tests/unit/test_core_ai_base_agent.py` — covers BaseAIAgent, IAIAgent Protocol, `_neutral()`
- [ ] `tests/unit/test_core_ai_context.py` — covers AIContext, AIContextCache, Tier enum, get_lead()
- [ ] `tests/unit/test_core_ai_output.py` — covers AgentOutput construction
- [ ] `tests/unit/test_core_ai_safe_wrapper.py` — covers SafeAgentWrapper timeout + exception isolation
- [ ] `tests/unit/test_llm_chain_fixes.py` — covers D-04, D-05, D-06, D-07, D-08 fixes
- [ ] Update `tests/unit/test_skeptic_agent.py` — update import paths after move
- [ ] Update `tests/unit/test_correlation_agent.py` — update import paths after move
- [ ] Update `tests/unit/test_volume_agent.py` — update import paths after move
- [ ] Update `tests/unit/test_narrative_*.py` — update import paths after move
- [ ] Update `tests/unit/test_swarm_dispatch.py` — rename to `test_alpha_swarm_agent.py`, update imports
- [ ] Delete `tests/unit/service_tests/test_swarm_orchestrator_agent.py`
- [ ] Delete `tests/unit/service_tests/test_swarm_orchestrator_seeding.py`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | LLM prompt injection prevention via structured prompts; response parsing validates JSON shape before use |
| V6 Cryptography | yes (weak) | SHA-256 for cache key is non-cryptographic use — correct; no secret material in cache keys |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM prompt injection via malformed OHLCV | Tampering | `PromptRegistry` and `build_*_prompt()` functions sanitize inputs; AIContext is a frozen Pydantic model — no raw string interpolation from untrusted sources |
| Cache pollution | Tampering | Full SHA-256 of system+prompt+model prevents partial prefix collision after D-08 fix |
| Shadow mode bypass | Elevation of privilege | `shadow_only=True` default on all agents; graduation_loop is the only mechanism to flip it |
| Token budget exhaustion | Denial of service | `TokenBudget.is_exceeded()` falls back to Ollama; `RateLimiter.acquire()` throttles per-provider |

---

## Open Questions

1. **Should `SwarmAggregator.aggregate()` accept `list[AgentOutput]` directly?**
   - What we know: Aggregator currently reads `AgentResult.multiplier` and `AgentResult.confidence`; AgentOutput stores these in `payload["multiplier"]` etc.
   - What's unclear: Whether to update aggregator signature to take `list[AgentOutput]` or create an adapter
   - Recommendation: Update aggregator to read from `AgentOutput.payload` — it's a one-file change and eliminates the adapter pattern

2. **Should `AlphaMultiplier` be updated or a new aggregate type created?**
   - What we know: `AlphaMultiplier.contributors: dict[str, AgentResult]` ties to the old type
   - Recommendation: Update `AlphaMultiplier.contributors` to `dict[str, AgentOutput]` in `schemas.py` — it's used by `swarm_writer_agent.py` which should be checked for field access patterns

3. **What happens to `src/intelligence/swarm/metrics.py`?**
   - These Prometheus metrics reference `SwarmOrchestratorComputeAgent` in their docstrings but the metric names themselves are stable
   - Recommendation: Update docstrings only; keep metric names unchanged to avoid breaking dashboards

4. **Does `graduation_compute_agent.py` (the standalone service) conflict with `BaseGroupService._graduation_loop`?**
   - The standalone `graduation_compute_agent.py` evaluates `signal_transform_log` for ALL transforms and publishes to `topic_transform_graduation` consumed by `GraduationWriterAgent`
   - `BaseGroupService._graduation_loop` is a 15-min in-process loop that calls `evaluate_all()` and auto-flips `shadow_only` on the in-memory agents
   - No conflict: they serve different purposes. The standalone service writes graduation state to DB; the in-process loop updates live agent behavior.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Redpanda (Kafka) | BaseGroupService topic publish | ✓ | running | — |
| TimescaleDB | AIContextCache seed | ✓ | running | Empty cache (degraded) |
| Ollama | LLM fallback | ✓ | running | None (cloud-only) |
| systemd | Unit file management | ✓ | Linux | — |
| Python asyncio | Async agent dispatch | ✓ | 3.11+ | — |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Prompt files (skeptic_prompts.py, etc.) should move alongside their agents | Files Being Moved | Import error at agent level; would need to add backward-compat re-exports |
| A2 | `topic_swarm_alpha()` needs to be added to stream_keys.py as a new function | New Topic Needed | If it already exists under another name, plan would create duplicate |
| A3 | `AlphaMultiplier.contributors` type should be updated to `dict[str, AgentOutput]` | AgentResult→AgentOutput | If left as AgentResult, swarm_writer_agent.py would fail type validation |

---

## Sources

### Primary (HIGH confidence)
- All source files read directly from `/home/bg/dev/indicagent/` — exact current state verified
- `docs/plans/2026-04-26-ai-llm-layer-design.md` — primary design specification
- `.planning/phases/73-ai-llm-layer-b-architecture-refactor/73-CONTEXT.md` — locked decisions
- `.planning/phases/73-ai-llm-layer-b-architecture-refactor/73-AI-SPEC.md` — AI design contract

### Secondary (MEDIUM confidence)
- `src/intelligence/CLAUDE.md` — intelligence layer developer reference
- Root `CLAUDE.md` — project-wide naming conventions, systemd watchdog rules

---

## Metadata

**Confidence breakdown:**
- Structural defects (D-01 to D-10): HIGH — verified against actual source files
- Import impact analysis: HIGH — verified via grep across entire codebase
- New infrastructure design: HIGH — from locked design spec + verified against existing patterns
- New topic names (topic_swarm_alpha, topic_swarm_graduation): MEDIUM — inferred from design doc + stream_keys.py pattern

**Research date:** 2026-04-26
**Valid until:** 2026-05-26 (stable codebase)
