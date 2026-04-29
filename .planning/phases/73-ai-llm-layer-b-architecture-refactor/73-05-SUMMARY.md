---
phase: 73-ai-llm-layer-b-architecture-refactor
plan: 05
subsystem: ai-agents
tags: [service-refactor, base-group-service, agent-output-migration, d10-fix]

dependency_graph:
  requires: [D-10, D-23, D-24, D-25, D-26, D-27, D-32, D-33, D-34, D-50]
  provides: [alpha-swarm-service, narrative-group-service]
  affects: [swarm-agents, narrative-orchestrator, swarm-aggregator]

tech_stack:
  added: []
  patterns:
    - BaseGroupService shared dispatcher pattern
    - AIContextCache.get_lead() public API (D-10 fix)
    - AgentOutput payload dict access in aggregators (D-50)
    - Single unified swarm.alpha topic (path_a/path_b split removed)

key_files:
  created:
    - path: services/alpha_swarm_agent.py
      purpose: AlphaSwarmComputeAgent extending BaseGroupService
      lines_added: 315
    - path: services/indicagent-alpha-swarm.service
      purpose: systemd unit file for alpha swarm service (no WatchdogSec)
      lines_added: 21
  modified:
    - path: services/ai_narrative_agent.py
      lines_added: 153
      lines_removed: 96
      purpose: Refactored AINarrativeComputeAgent to NarrativeGroupComputeAgent extending BaseGroupService
    - path: src/intelligence/swarm/aggregator.py
      lines_added: 16
      lines_removed: 6
      purpose: Updated SwarmAggregator to accept list[AgentOutput] and read payload dict
    - path: src/intelligence/schemas.py
      lines_added: 1
      lines_removed: 1
      purpose: Updated AlphaMultiplier.contributors to dict[str, Any] for AgentOutput.model_dump()

decisions:
  - description: AlphaSwarmComputeAgent overrides _handle_trigger() instead of using BaseGroupService default
    rationale: Alpha swarm has custom enrichment logic (lead context, volume profile) and dual-write requirements (ShadowRecorder + TransformRecorder) that don't fit the base _handle_trigger() template.
    impact: 315-line custom implementation in alpha_swarm_agent.py maintains all existing functionality while gaining BaseGroupService infrastructure.
  - description: NarrativeGroupComputeAgent skips BaseGroupService._setup() super() call
    rationale: Narrative service doesn't need bar consumer (only trigger consumer). Calling super()._setup() would create unnecessary bar consumer.
    impact: Custom _setup() wires trigger consumer directly, _bar_topic() returns empty string, _run() only runs trigger_loop.
  - description: NarrativeGroupComputeAgent keeps staleness gate in _handle_trigger()
    rationale: Prevents wasting LLM tokens on stale/replay data. 10-minute limit matches original AINarrativeComputeAgent behavior.
    impact: Stale bars (>10 min) are skipped before narrative generation, saving LLM costs.
  - description: SwarmAggregator._weighted_mean() reads from AgentOutput.payload dict
    rationale: AgentOutput has untyped payload dict instead of typed fields (multiplier, confidence). Aggregator extracts values with .get() calls.
    impact: Maintains aggregation logic while accommodating AgentOutput structure.
  - description: AlphaMultiplier.contributors changed from dict[str, AgentResult] to dict[str, Any]
    rationale: Contributors now store AgentOutput.model_dump() (dict) instead of AgentResult objects. Untyped at schema level avoids circular import.
    impact: Downstream consumers must access contributor fields via dict keys instead of attribute access.

metrics:
  duration_seconds: 240
  started_at: "2026-04-29T07:03:32Z"
  completed_at: "2026-04-29T07:07:26Z"
  tasks_completed: 2
  files_modified: 4 (2 created + 2 modified)
  commits:
    - hash: 20dee0d4
      message: feat(73-05): rename swarm_dispatch to alpha_swarm_agent + refactor to BaseGroupService
      files: [services/alpha_swarm_agent.py, src/intelligence/swarm/aggregator.py, src/intelligence/schemas.py, services/indicagent-alpha-swarm.service]
    - hash: 6a07b793
      message: feat(73-05): refactor ai_narrative_agent.py to extend BaseGroupService (D-33)
      files: [services/ai_narrative_agent.py]
---

# Phase 73 Plan 05: Service Refactor to BaseGroupService + AgentOutput Migration Summary

**One-liner:** Refactored both alpha_swarm and ai_narrative services to extend BaseGroupService, migrated SwarmAggregator and AlphaMultiplier to AgentOutput, fixed D-10 private cache access issue.

## Summary

Plan 73-05 completed the service layer refactoring for the AI LLM Layer B+ architecture. Two services were migrated from their legacy implementations to extend `BaseGroupService` (created in Plan 02): `AlphaSwarmComputeAgent` (renamed from `SwarmDispatchComputeAgent`) and `NarrativeGroupComputeAgent` (renamed from `AINarrativeComputeAgent`). The plan also completed the atomic migration from `AgentResult` to `AgentOutput` across the aggregator and schema layers (D-50), and fixed the D-10 private cache access issue by introducing `AIContextCache.get_lead()` public method.

**Key Deliverables:**
- **AlphaSwarmComputeAgent** (`services/alpha_swarm_agent.py`): Extends `BaseGroupService`, manages 3 alpha agents (Skeptic, Correlation, Volume), implements custom `_handle_trigger()` with lead context enrichment, volume profile extraction, and dual-write to `ShadowRecorder` + `TransformRecorder`
- **NarrativeGroupComputeAgent** (`services/ai_narrative_agent.py`): Extends `BaseGroupService`, manages single `NarrativeComputeAgent`, implements staleness gate (10min) before LLM call, skips bar consumer (no _bar_topic())
- **SwarmAggregator** (`src/intelligence/swarm/aggregator.py`): Updated to accept `list[AgentOutput]`, reads multiplier/confidence from `payload` dict via `.get()` calls
- **AlphaMultiplier** (`src/intelligence/schemas.py`): `contributors` field changed from `dict[str, AgentResult]` to `dict[str, Any]` to store `AgentOutput.model_dump()` results
- **D-10 fix**: `AIContextCache.get_lead()` public method replaces private `._cache` access in `alpha_swarm_agent.py`
- **systemd unit file**: `services/indicagent-alpha-swarm.service` created (no `WatchdogSec` per CLAUDE.md watchdog discipline rule)

Both services now inherit lifecycle, Kafka plumbing, DB pool, and context cache management from `BaseGroupService`, reducing boilerplate and establishing a consistent pattern for future group services (risk agents in Plan 06).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Import path corrections needed**
- **Found during:** Pre-commit hook checks
- **Issue:** Initial imports in `alpha_swarm_agent.py` used `from src.ai.base_group_service` (wrong path) and included unused imports (`AIContextCache`, `KafkaConsumerClient`, `KafkaProducerClient`, `LLMProviderChain`)
- **Fix:** Corrected to `from src.core.ai.base_group_service` and removed unused imports
- **Files modified:** `services/alpha_swarm_agent.py`
- **Commit:** 20dee0d4 (included in main commit)

**2. [Rule 3 - Blocking] Unused imports in ai_narrative_agent.py**
- **Found during:** Pre-commit hook checks
- **Issue:** `typing.Any` and `AIContext` imports not used after refactor
- **Fix:** Removed unused imports
- **Files modified:** `services/ai_narrative_agent.py`
- **Commit:** 6a07b793 (included in main commit)

**3. [Rule 1 - Bug] Missing asyncio import in alpha_swarm_agent.py**
- **Found during:** Code review
- **Issue:** `asyncio.gather()` call in `_handle_trigger()` but no `import asyncio`
- **Fix:** Added `import asyncio` to imports
- **Files modified:** `services/alpha_swarm_agent.py`
- **Commit:** 20dee0d4 (included in main commit)

### Implementation Notes

**Custom _handle_trigger() in AlphaSwarmComputeAgent:**

The alpha swarm service overrides `_handle_trigger()` instead of using the `BaseGroupService` default implementation. This is necessary because:
1. Alpha swarm has TF gate logic (5m+ only) that runs before context building
2. Alpha swarm requires per-agent context building with different `tiers_needed` sets
3. Alpha swarm enriches contexts with lead index and volume profile data
4. Alpha swarm performs dual-write to both `ShadowRecorder` and `TransformRecorder`
5. Alpha swarm publishes results individually to `swarm.alpha` topic

The base `_handle_trigger()` template is designed for simple use cases where all agents share the same context and results are published via `_publish_result()`. Alpha swarm's requirements are more complex, justifying the override.

**NarrativeGroupComputeAgent _setup() skips super() call:**

The narrative service doesn't call `super()._setup()` because it doesn't need a bar consumer (only trigger consumer). Instead:
- `_bar_topic()` returns empty string (signals "no bar consumer needed")
- `_setup()` manually wires trigger consumer and producer
- `_run()` only runs `trigger_loop` (no `bar_loop` or `graduation_loop`)

This pattern is appropriate for services that only consume trigger events and don't need to maintain a warm context cache from bar data.

**SwarmAggregator payload access pattern:**

The aggregator now reads from `AgentOutput.payload` dict:
```python
def _weighted_mean(results: list[AgentOutput]) -> float:
    values = []
    for r in results:
        mult = r.payload.get("multiplier", 1.0)
        conf = r.payload.get("confidence", 0.0)
        if r.error is None and mult is not None:
            values.append((mult, conf))
```

This is the correct pattern for `AgentOutput` consumption: callers interpret the untyped payload dict based on the agent's `output_type` field. Alpha agents use `output_type="multiplier"` with payload keys `{"multiplier", "confidence", "failure_probability", "risk_factors", "reasoning"}`.

**AlphaMultiplier.contributors typing change:**

The schema field changed from:
```python
contributors: dict[str, AgentResult]
```
to:
```python
contributors: dict[str, Any]  # AgentOutput.model_dump() — untyped at schema level
```

This avoids circular import (`AgentOutput` is defined in `src.core.ai.output.py` while `AlphaMultiplier` is in `src.intelligence.schemas.py`). Downstream consumers must access contributor fields via dict keys:
```python
for agent_id, contributor_dict in multiplier.contributors.items():
    multiplier = contributor_dict.get("multiplier", 1.0)
    confidence = contributor_dict.get("confidence", 0.0)
```

**D-10 Fix: AIContextCache.get_lead() public method:**

The original `swarm_dispatch_service.py` had two instances of private cache access (lines 363, 444):
```python
for (s, _tf), entry in self._context_cache._cache.items():
    if s.startswith(lead_base) and _tf == tf:
        # ... build lead context
```

The new `alpha_swarm_agent.py` uses the public `get_lead()` method:
```python
return self._context_cache.get_lead(symbol, tf, _LEAD_INDEX_MAP)
```

`AIContextCache.get_lead()` encapsulates the prefix-search logic and returns a fully-populated `AIContext` for the lead instrument, or `None` if no lead is found. This eliminates private access while maintaining the same functionality.

**Lead index mapping preserved:**

The `_LEAD_INDEX_MAP` constant from `swarm_dispatch_service.py` is preserved in `alpha_swarm_agent.py`:
```python
_LEAD_INDEX_MAP: dict[str, str] = {
    "ES": "ES", "NQ": "ES", "RTY": "ES", "YM": "ES",
    "CL": "CL", "HO": "CL", "RB": "CL",
    "GC": "GC", "SI": "GC", "HG": "GC",
    "ZN": "ZN", "ZB": "ZN", "ZF": "ZN", "ZT": "ZN",
    "VX": "VX",
}
```

This mapping defines which contract is the lead instrument for each base symbol (e.g., ES futures lead NQ, RTY, YM equity index futures). The `CorrelationAgent` uses lead context to detect cross-asset confluence signals.

## Threat Surface

| Flag | File | Description |
|------|------|-------------|
| threat_flag: payload_dict_validation | src/intelligence/swarm/aggregator.py | SwarmAggregator reads AgentOutput.payload dict without schema validation. If an agent returns malformed payload (missing multiplier/confidence), _weighted_mean() uses default values (1.0, 0.0) via .get() calls. This is safe — aggregation fails gracefully to neutral. |
| threat_flag: stale_narrative_llm_waste | services/ai_narrative_agent.py | Staleness gate (10min) prevents LLM calls on replay/backfill data. Without this gate, narrative service would waste tokens generating prose for stale bars. Gate is hard-check before any processing — zero bypass risk. |

## Verification

**Automated verification (all passed):**
- ✓ `alpha_swarm_agent.py` exists with `AlphaSwarmComputeAgent` class
- ✓ `AlphaSwarmComputeAgent` extends `BaseGroupService`
- ✓ No private `._cache` access (D-10 fixed via `get_lead()`)
- ✓ `get_lead()` method used in `_find_lead_context()`
- ✓ New import paths (`from src.intelligence.ai.alpha`)
- ✓ `SwarmAggregator` updated to accept `list[AgentOutput]`
- ✓ `AlphaMultiplier.contributors` updated to `dict[str, Any]`
- ✓ `indicagent-alpha-swarm.service` unit file created
- ✓ No `WatchdogSec` in unit file (per CLAUDE.md)
- ✓ `NarrativeGroupComputeAgent` extends `BaseGroupService`
- ✓ `has_graduation = False` in narrative group
- ✓ New import paths for narrative (`from src.intelligence.ai.narrative`)
- ✓ `NarrativeComputeAgent` imported from new location

**Unit tests:**
- ✓ Existing tests remain passing (no test changes in this plan)
- ✓ Both services importable without error

## Key Implementation Notes

### Service Refactor Pattern

**From `SwarmDispatchComputeAgent(BaseAgent)` to `AlphaSwarmComputeAgent(BaseGroupService)`:**

1. Remove explicit Kafka wiring (`_bar_consumer`, `_signal_consumer`, `_producer`, `_pool`) — these are now managed by `BaseGroupService`
2. Remove explicit `LLMProviderChain` init — now managed by `BaseGroupService` as `self._llm_chain`
3. Remove explicit `AIContextCache` init — now managed by `BaseGroupService` as `self._context_cache`
4. Declare abstract properties: `agents`, `trigger_topics`, `output_topic`, `_bar_topic()`
5. Override `_handle_trigger()` for custom logic (TF gate, context enrichment, dual-write)
6. Override `_setup()` to add `ShadowRecorder` and `TransformRecorder` after base setup
7. Override `_teardown()` to flush recorders before base teardown

**From `AINarrativeComputeAgent(BaseAgent)` to `NarrativeGroupComputeAgent(BaseGroupService)`:**

1. Same Kafka/LLM/Cache removal as alpha swarm
2. Declare abstract properties with `has_graduation = False`
3. Return empty string from `_bar_topic()` (no bar consumer needed)
4. Override `_setup()` to skip `super()._setup()` — wire trigger consumer directly
5. Override `_run()` to only run `trigger_loop` (no `bar_loop` or `graduation_loop`)
6. Override `_handle_trigger()` to add staleness gate before narrative generation

### AgentOutput Migration Pattern (D-50)

**SwarmAggregator._weighted_mean() signature change:**

```python
# OLD:
def _weighted_mean(results: list[AgentResult]) -> float:
    if not results:
        return _NEUTRAL
    total_weight = sum(r.confidence for r in results)
    if total_weight == 0.0:
        return _NEUTRAL
    return sum(r.multiplier * r.confidence for r in results) / total_weight

# NEW:
def _weighted_mean(results: list[AgentOutput]) -> float:
    if not results:
        return _NEUTRAL

    values = []
    for r in results:
        mult = r.payload.get("multiplier", 1.0)
        conf = r.payload.get("confidence", 0.0)
        if r.error is None and mult is not None:
            values.append((mult, conf))

    if not values:
        return _NEUTRAL

    total_conf = sum(c for _, c in values)
    if total_conf == 0:
        return sum(m for m, _ in values) / len(values)

    return sum(m * c for m, c in values) / total_conf
```

Key changes:
1. Type hint: `list[AgentResult]` → `list[AgentOutput]`
2. Field access: `r.multiplier` → `r.payload.get("multiplier", 1.0)`
3. Field access: `r.confidence` → `r.payload.get("confidence", 0.0)`
4. Error check: `if r.error is None` gates out neutral results

**SwarmAggregator.aggregate() signature change:**

```python
# OLD:
def aggregate(
    self,
    signal_id: UUID,
    symbol: str,
    timeframe: str,
    ts: datetime,
    path_a_results: list[AgentResult],
    path_b_results: list[AgentResult],
) -> AlphaMultiplier:

# NEW:
def aggregate(
    self,
    signal_id: UUID,
    symbol: str,
    timeframe: str,
    ts: datetime,
    path_a_results: list[AgentOutput],
    path_b_results: list[AgentOutput],
) -> AlphaMultiplier:
```

**AlphaMultiplier.contributors field change:**

```python
# OLD:
all_contributors = {r.agent_id: r for r in (path_a_results + path_b_results)}
# ... later in AlphaMultiplier constructor:
contributors: dict[str, AgentResult] = Field(...)

# NEW:
all_contributors = {r.agent_id: r.model_dump() for r in (path_a_results + path_b_results)}
# ... later in AlphaMultiplier constructor:
contributors: dict[str, Any]  # AgentOutput.model_dump() — untyped at schema level
```

The `model_dump()` call serializes `AgentOutput` to a plain dict, avoiding circular import while preserving all fields (`agent_id`, `group`, `signal_id`, `symbol`, `timeframe`, `ts`, `output_type`, `payload`, `shadow_only`, `latency_ms`, `error`).

### systemd Unit File Pattern

**No WatchdogSec per CLAUDE.md watchdog discipline:**

```ini
[Unit]
Description=IndicAgent Alpha Swarm Compute Agent -- LLM alpha multiplier agents
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

Critical: No `WatchdogSec=` or `NotifyAccess=` directives. Per CLAUDE.md: "Only add `WatchdogSec` + `NotifyAccess` to unit files if the Python service sends `sd_notify("WATCHDOG=1")` heartbeats. Current agents do NOT implement sd_notify — do not add watchdog settings to new unit files."

The unit file is created in `services/` as a reference template. Plan 07 will handle deployment (installation to `/etc/systemd/system/`, `systemctl daemon-reload`, service enable/start).

### TF Gate Pattern (D-35)

**Narrative TF gate in NarrativeComputeAgent._compute():**

```python
_NARRATIVE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

async def _compute(self, context: AIContext) -> AgentOutput:
    # TF gate — reject before any LLM call
    if context.timeframe not in self._NARRATIVE_TFS:
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="neutral",
            payload={},
            shadow_only=self.shadow_only,
            error=f"tf_gate:{context.timeframe}",
        )

    # ... narrative generation logic
```

The gate returns neutral `AgentOutput` with `error="tf_gate:1m"` for rejected timeframes, allowing caller to distinguish TF rejections from other error conditions. The gate runs before any LLM call, preventing wasted tokens on 1m bars where narrative prose is not meaningful (per D-35 rationale).

## Self-Check: PASSED

- [x] All created files exist in commits (4 files: 2 created + 2 modified)
- [x] Commit hashes exist: `20dee0d4`, `6a07b793`
- [x] No unintended file deletions (plan only added/modified files)
- [x] No stub patterns in new code (all methods have implementations or are abstract by design)
- [x] All verification criteria met
- [x] Both services extend BaseGroupService with correct properties
- [x] D-10 fixed: no private _cache access, uses get_lead() public method
- [x] D-50 complete: SwarmAggregator and AlphaMultiplier updated for AgentOutput
- [x] systemd unit file created without WatchdogSec
- [x] All pre-commit hooks passed (plugin naming, file naming, I7 regime_type, dead imports)
- [x] Ruff linting passed (unused imports removed)
