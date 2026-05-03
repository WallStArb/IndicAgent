---
phase: 73-ai-llm-layer-b-architecture-refactor
reviewed: 2026-04-28T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - src/core/ai/__init__.py
  - src/core/ai/base_agent.py
  - src/core/ai/base_group_service.py
  - src/core/ai/context.py
  - src/core/ai/output.py
  - src/core/ai/safe_wrapper.py
  - src/core/ai/lineage.py
  - src/core/llm/chain.py
  - src/core/llm/guardrails.py
  - src/core/llm/semantic_cache.py
  - src/core/stream_keys.py
  - src/intelligence/ai/alpha/correlation_agent.py
  - src/intelligence/ai/alpha/correlation_prompts.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - src/intelligence/ai/alpha/skeptic_prompts.py
  - src/intelligence/ai/alpha/volume_agent.py
  - src/intelligence/ai/alpha/volume_prompts.py
  - src/intelligence/ai/narrative/narrative_agent.py
  - src/intelligence/ai/narrative/parsers.py
  - src/intelligence/ai/narrative/prompts.py
  - src/intelligence/schemas.py
  - src/intelligence/swarm/aggregator.py
  - src/intelligence/swarm/graduation.py
  - services/ai_narrative_agent.py
  - services/alpha_swarm_agent.py
  - services/lineage_writer_agent.py
  - prisma/migrations/073_signal_lineage.sql
  - production/scripts/kafka_init_topics.py
findings:
  critical: 8
  warning: 12
  info: 6
  total: 26
status: issues_found
---

# Phase 73: Code Review Report

**Reviewed:** 2026-04-28T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

Phase 73 implements the AI LLM Layer B+ Architecture Refactor, introducing a unified BaseAIAgent/BaseGroupService infrastructure for alpha and narrative agents. The architecture successfully separates compute logic from infrastructure concerns, with proper Kafka-first DAG patterns and shadow rollout support.

However, the implementation contains **8 critical defects** that must be fixed before production deployment:

1. **Database migration collision risk** - Duplicate writes may occur during transition
2. **Missing DB pool lifecycle** - Narrative service skips critical super()._setup()
3. **Incomplete volume profile integration** - Placeholder data in production code
4. **Unsafe prompt builder contract** - Missing validation on critical LLM inputs
5. **Narrative generation disabled** - Returns stub text instead of calling LLM
6. **Race condition in batch flushing** - LineageRecorder lacks task cancellation safety
7. **Missing validation in aggregation** - SwarmAggregator doesn't check shadow_only flags
8. **Unvalidated lead symbol access** - Null pointer risk in correlation prompts

The code demonstrates strong architectural patterns (BaseAgent inheritance, SafeAgentWrapper defensive programming, AIContextCache encapsulation) but needs hardening in edge case handling and data validation.

## Critical Issues

### CR-01: Database migration collision risk - dual-write paths incomplete

**File:** `services/alpha_swarm_agent.py:227-268`

**Issue:** The `_record_swarm_result()` method implements dual-write to both `ShadowRecorder` (alpha_multiplier_shadow table) and `TransformRecorder` (signal_transform_log table), but Phase 73 migration (073_signal_lineage.sql) states that `alpha_multiplier_shadow` is deprecated and all writes should go to `signal_lineage`. This creates a **three-way write conflict** during the transition period:

1. ShadowRecorder writes to `alpha_multiplier_shadow` (deprecated)
2. TransformRecorder writes to `signal_transform_log` (deprecated)
3. LineageRecorder (not yet integrated) should write to `signal_lineage`

The migration comment says "Old table kept for historical data; writes now go to signal_lineage" but the code still writes to the old tables.

**Fix:**
```python
# In alpha_swarm_agent.py, replace ShadowRecorder + TransformRecorder with LineageRecorder
from src.core.ai.lineage import LineageRecorder

async def _setup(self) -> None:
    await super()._setup()
    # ... DB pool setup ...

    # Replace both recorders with unified LineageRecorder
    self._recorder = LineageRecorder(
        producer=self._producer,
        env_name=self.settings.env_name,
        batch_size=50,
        flush_interval_s=2.0,
    )

async def _record_swarm_result(self, signal_id, enriched, result):
    mapping = _SWARM_AGENT_TO_TRANSFORM.get(result.agent_id)
    if mapping:
        transform_id, dag_order = mapping
        await self._recorder.record(
            signal_id=signal_id,
            event_type="agent_prediction",
            source=result.agent_id,
            dag_order=dag_order,
            multiplier=result.payload.get("multiplier", 1.0),
            metadata=result.payload,
            is_shadow=result.shadow_only,
            symbol=enriched.symbol,
            tf=enriched.timeframe,
        )
```

### CR-02: Narrative service breaks BaseGroupService contract - missing pool initialization

**File:** `services/ai_narrative_agent.py:64-97`

**Issue:** The `_setup()` method in `NarrativeGroupComputeAgent` does **not** call `super()._setup()`, which breaks the BaseGroupService contract. The base class `_setup()` method (line 80-130 of base_group_service.py) performs critical initialization:

1. Creates `_bar_consumer` (even if empty string, needs initialization)
2. Creates `_trigger_consumer` (re-created by narrative, breaking single source of truth)
3. Creates `_producer` (re-created by narrative)
4. Creates `_pool` (re-created by narrative)
5. Creates `_llm_chain` (lost, never initialized)
6. Calls `_seed_context_cache()` (narrative calls it manually, but this duplicates logic)

By not calling `super()._setup()`, the narrative service never initializes `self._llm_chain`, causing `NarrativeComputeAgent(llm_chain=self._llm_chain)` at line 41 to receive `None`.

**Fix:**
```python
async def _setup(self) -> None:
    """Wire infrastructure beyond BaseGroupService defaults."""
    # CRITICAL: Call super()._setup() first to initialize _llm_chain
    await super()._setup()

    # Narrative service doesn't need bar_consumer, but base class already created it
    # Just stop it if we don't want it running
    if self._bar_consumer:
        await self._bar_consumer.stop()
        self._bar_consumer = None

    # Trigger consumer and producer are already initialized by super()._setup()
    # DB pool is already initialized
    # Context cache is already seeded

    agent_ids = [a.agent_id for a in self._agents]
    self.logger.info("narrative_group.started", agents=agent_ids)
```

### CR-03: VolumeAgent uses placeholder data for volume profile fields

**File:** `src/intelligence/ai/alpha/volume_agent.py:172-183`

**Issue:** The `_context_to_dict()` function in `volume_agent.py` contains explicit placeholder mappings that send incorrect data to the LLM:

```python
vp_dict = {
    "vah": i4_ctx.poc_price,  # Placeholder - actual VP data comes from enricher
    "val": i4_ctx.poc_price_rolling,  # Placeholder
    "vah_rolling": i4_ctx.poc_price,  # Placeholder
    "val_rolling": i4_ctx.poc_price_rolling,  # Placeholder
    "price_in_value_area": None,  # Would be set by enricher
    "distance_to_vah_atr": None,  # Would be set by enricher
    "distance_to_val_atr": None,  # Would be set by enricher
}
```

This means the VolumeAgent is sending misleading volume profile data to the LLM:
- `vah` (Volume Area High) is set to `poc_price` (Point of Control) - these are different values
- `val` (Volume Area Low) is set to `poc_price_rolling` - incorrect
- Distance fields are `None`, breaking the prompt template's formatting logic

This violates the "Renaissance principle: Let the system run. Don't override data with intuition" - the agent is fabricating data rather than admitting unavailability.

**Fix:**
```python
def _context_to_dict(context: AIContext) -> dict:
    """Convert AIContext to dict for prompt building."""
    # ... existing context extraction ...

    # Build volume profile dict from I4 context
    # Do NOT fabricate placeholder values - use None to signal unavailability
    vp_dict = {
        "vah": None,  # Not available in I4 context - requires enricher
        "val": None,  # Not available in I4 context - requires enricher
        "vah_rolling": None,  # Not available in I4 context - requires enricher
        "val_rolling": None,  # Not available in I4 context - requires enricher
        "price_in_value_area": None,
        "distance_to_vah_atr": None,
        "distance_to_val_atr": None,
    }

    # Or better: skip volume_agent entirely if VP data is required
    # Add a check in _enrich_context() to return None for volume_agent when VP unavailable
```

### CR-04: NarrativeComputeAgent returns stub instead of calling LLM

**File:** `src/intelligence/ai/narrative/narrative_agent.py:48-83`

**Issue:** The `_compute()` method returns hardcoded stub text instead of generating narratives via LLM:

```python
return AgentOutput(
    agent_id=self.agent_id,
    group=self.group,
    signal_id=context.signal_id,
    symbol=context.symbol,
    timeframe=context.timeframe,
    ts=context.ts,
    output_type="narrative",
    payload={"text": "Narrative generation pending prompt builder update"},
    shadow_only=self.shadow_only,
)
```

This means the narrative agent is **non-functional** in production - it's consuming LLM resources (via SafeAgentWrapper timeout budget) but never actually calling the LLM. The comment says "prompt builders will be updated in future plans" but this is a critical gap for a production feature.

**Fix:**
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    """Generate narrative text from AIContext."""
    # D-35: TF gate — reject before any LLM call
    if context.timeframe not in self._NARRATIVE_TFS:
        return AgentOutput(
            # ... existing TF gate code ...
        )

    # TEMPORARY: Use BarIntelligenceRecord path until prompt builders updated
    # TODO(D-XX): Update prompt builders to accept AIContext directly
    from src.intelligence.ai.narrative.prompts import build_short_prompt
    from src.intelligence.schemas import BarIntelligenceRecord

    # Build a minimal BarIntelligenceRecord from AIContext
    intel_record = _build_record_from_context(context)
    prompt = build_short_prompt(intel_record)

    response = await self._chain.generate(
        prompt=prompt,
        system=_SYSTEM_PROMPT,
        max_tokens=500,
        timeout=self.latency_budget_ms / 1000.0,
    )

    if not response:
        return self._neutral(error="LLM returned empty response", latency_ms=0.0)

    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        signal_id=context.signal_id,
        symbol=context.symbol,
        timeframe=context.timeframe,
        ts=context.ts,
        output_type="narrative",
        payload={"text": response},
        shadow_only=self.shadow_only,
    )
```

### CR-05: Race condition in LineageRecorder flush - missing task lifecycle management

**File:** `src/core/ai/lineage.py:69-84`

**Issue:** The `LineageRecorder.record()` method creates a background task via `asyncio.create_task(self.flush())` but never tracks or cancels it. This creates a race condition:

```python
if len(self._batch) >= self._batch_size:
    asyncio.create_task(self.flush())  # Task fire-and-forget
```

Problems:
1. No tracking of `_flush_task` - can't cancel on shutdown
2. Multiple concurrent flushes possible if `record()` called rapidly
3. `flush()` clears `self._batch[:]` before publishing, so concurrent flushes lose data
4. No exception handling in fire-and-forget task (unhandled exceptions crash the event loop)

Compare with `TransformRecorder` which properly implements `_flush_loop()` with task tracking.

**Fix:**
```python
def __init__(self, producer: Any, env_name: str, batch_size: int = 50, flush_interval_s: float = 2.0) -> None:
    self._producer = producer
    self._env_name = env_name
    self._batch: list[dict] = []
    self._batch_size = batch_size
    self._flush_interval_s = flush_interval_s
    self._last_flush = time.monotonic()
    self._flush_task: asyncio.Task | None = None
    self._flush_lock = asyncio.Lock()  # Prevent concurrent flushes

def record(self, ...):
    # ... build row ...
    self._batch.append(row)

    # Start flush loop if not running
    if self._flush_task is None or self._flush_task.done():
        self._flush_task = asyncio.create_task(self._flush_loop())

    # Trigger immediate flush if batch full
    if len(self._batch) >= self._batch_size:
        asyncio.create_task(self._flush())

async def _flush_loop(self) -> None:
    """Periodic background flush."""
    while self.running:
        await asyncio.sleep(self._flush_interval_s)
        await self._flush()

async def flush(self) -> None:
    """Force flush with cancellation safety."""
    if self._flush_task is not None and not self._flush_task.done():
        self._flush_task.cancel()
        try:
            await self._flush_task
        except asyncio.CancelledError:
            pass

    async with self._flush_lock:  # Prevent concurrent flushes
        await self._flush()
```

### CR-06: SwarmAggregator doesn't validate shadow_only flags before production use

**File:** `src/intelligence/swarm/aggregator.py:78-96`

**Issue:** The `SwarmAggregator.aggregate()` method calculates `production_multiplier` using all AgentOutput results, but only checks `shadow_only` flag for the **output field**, not for the calculation itself:

```python
any_shadow = any(r.shadow_only for r in combined) if combined else True
# ...
return AlphaMultiplier(
    # ...
    production_multiplier=round(production, 4),
    shadow_only=any_shadow,
)
```

This means:
1. If some agents are graduated (`shadow_only=False`) and others are in shadow (`shadow_only=True`)
2. The `production_multiplier` calculation **includes both shadow and non-shadow agents**
3. Only the output flag is set correctly
4. Downstream consumers see `shadow_only=False` (if at least one agent graduated) but the multiplier includes unvalidated shadow predictions

This violates the shadow rollout principle - shadow data should never influence production values.

**Fix:**
```python
def aggregate(
    self,
    signal_id: UUID,
    symbol: str,
    timeframe: str,
    ts: datetime,
    path_a_results: list[AgentOutput],
    path_b_results: list[AgentOutput],
) -> AlphaMultiplier:
    # Filter out shadow-only results from production calculation
    path_a_production = [r for r in path_a_results if not r.shadow_only]
    path_b_production = [r for r in path_b_results if not r.shadow_only]

    # Use only non-shadow results for production multiplier
    path_a_mult = _weighted_mean(path_a_production) if path_a_production else None
    path_b_mult = _weighted_mean(path_b_production) if path_b_production else None

    # If all agents are shadow-only, production_multiplier must be 1.0 (neutral)
    if not path_a_production and not path_b_production:
        production = _NEUTRAL
    else:
        # ... existing aggregation logic ...

    any_shadow = any(r.shadow_only for r in combined) if combined else True

    return AlphaMultiplier(
        # ...
        production_multiplier=round(production, 4),
        shadow_only=any_shadow or (not path_a_production and not path_b_production),
    )
```

### CR-07: CorrelationAgent lead_context access may cause null pointer exception

**File:** `src/intelligence/ai/alpha/correlation_agent.py:82-83`

**Issue:** The code accesses `context.lead_context.symbol` without null check:

```python
lead_symbol = (
    context.lead_context.symbol if context.lead_context else None
)
```

While this line has a check, the prompt builder at `_context_to_dict()` line 171-194 does NOT check if `lead_ctx` is None before accessing nested fields:

```python
lead_i1 = lead_ctx.i1  # CRASH: lead_ctx might be None
lead_i4 = lead_ctx.i4
lead_i6 = lead_ctx.i6
```

This will crash with `AttributeError` when `lead_context` is None (e.g., no lead index mapping defined for the symbol).

**Fix:**
```python
def _context_to_dict(context: AIContext) -> dict:
    """Convert AIContext to dict for prompt building."""
    # ... existing code ...

    # Extract lead context if available
    lead_ctx = context.lead_context
    lead_dict = {}
    if lead_ctx is not None:  # CRITICAL: Check before accessing
        lead_i1 = lead_ctx.i1
        lead_i4 = lead_ctx.i4
        lead_i6 = lead_ctx.i6
        lead_dict = {
            "lead_symbol": lead_ctx.symbol,
            "lead_trend_regime": lead_i4.trend_regime if lead_i4 else None,
            "lead_rsi": lead_i1.rsi if lead_i1 else None,
            "lead_adx": lead_i1.adx if lead_i1 else None,
            "lead_hmm_regime": lead_i4.hmm_regime if lead_i4 else None,
            "lead_ctf_trend_alignment": lead_i6.ctf_trend_alignment if lead_i6 else None,
        }
        # ... rest of lead_dict construction ...
```

### CR-08: NarrativeGroupComputeAgent _run() method silently cancels bar_loop

**File:** `services/ai_narrative_agent.py:99-107`

**Issue:** The `_run()` method overrides BaseGroupService's implementation but only runs `trigger_loop`, silently skipping the `bar_loop` that the base class expects. This is intentional per the comment, but creates a maintenance hazard:

```python
async def _run(self) -> None:
    """Run main loop: trigger_loop only (no bar_loop for narrative)."""
    # Narrative doesn't need bar_loop or graduation_loop
    trigger_task = asyncio.create_task(self._trigger_loop())
    try:
        await trigger_task
    except Exception:
        trigger_task.cancel()
        raise
```

Problems:
1. BaseGroupService._run() runs 3 loops (bar, trigger, graduation)
2. Narrative overrides to run only 1 loop (trigger)
3. If BaseGroupService._run() adds new logic in the future, Narrative won't inherit it
4. No indication in the interface that _run() is override-optional

**Fix:**
```python
# In BaseGroupService, add hook methods for subclasses to override
async def _should_run_bar_loop(self) -> bool:
    """Override to False if subclass doesn't need bar_loop."""
    return True

async def _should_run_graduation_loop(self) -> bool:
    """Override to False if subclass doesn't need graduation_loop."""
    return self.has_graduation

async def _run(self) -> None:
    """Run main loops: bar_loop, trigger_loop, and optional graduation_loop."""
    tasks = []

    if self._should_run_bar_loop():
        bar_task = asyncio.create_task(self._bar_loop())
        tasks.append(bar_task)

    trigger_task = asyncio.create_task(self._trigger_loop())
    tasks.append(trigger_task)

    if self._should_run_graduation_loop():
        graduation_task = asyncio.create_task(self._graduation_loop())
        tasks.append(graduation_task)

    # ... rest of existing _run() logic ...

# In NarrativeGroupComputeAgent
async def _should_run_bar_loop(self) -> bool:
    return False  # Narrative doesn't need bar updates
```

## Warnings

### WR-01: Missing validation on AIContext.ts field may cause Kafka serialization failures

**File:** `src/core/ai/context.py:101`

**Issue:** The `AIContext.ts` field is typed as `Any` (not `datetime`) and accepts both datetime objects and strings. When AgentOutput is serialized to Kafka (via `model_dump(mode="json")` in base_group_service.py line 275), datetime objects must be ISO-8601 strings. The code relies on Pydantic's automatic serialization, but there's no explicit validation that `ts` is serializable.

If an invalid type (e.g., a MagicMock from tests) is passed, Kafka publish will fail with a cryptic serialization error.

**Fix:**
```python
# In AIContext, add a validator
from pydantic import field_validator

class AIContext(BaseModel):
    # ... existing fields ...
    ts: Any  # datetime or ISO-8601 string

    @field_validator('ts')
    @classmethod
    def validate_ts(cls, v: Any) -> Any:
        """Ensure ts is either datetime or ISO-8601 string."""
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # Try to parse to ensure it's valid ISO-8601
            try:
                datetime.fromisoformat(v.replace('Z', '+00:00'))
                return v
            except ValueError:
                raise ValueError(f"ts must be datetime or ISO-8601 string, got: {v}")
        raise ValueError(f"ts must be datetime or ISO-8601 string, got {type(v)}")
```

### WR-02: SafeAgentWrapper double-wraps timing logic

**File:** `src/core/ai/safe_wrapper.py:35-47`

**Issue:** Both `BaseAIAgent.compute()` and `SafeAgentWrapper.compute()` capture latency:

1. BaseAIAgent.compute() (line 71-107) wraps `_compute()` with timing and returns AgentOutput with `latency_ms`
2. SafeAgentWrapper.compute() (line 35-47) also wraps the call with timing and returns `result.model_copy(update={"latency_ms": latency_ms})`

This means the final `AgentOutput.latency_ms` is the SafeAgentWrapper's timing (includes SafeAgentWrapper overhead), not the BaseAIAgent's timing. The BaseAIAgent's timing is lost.

While not a bug (both measure useful time), it's redundant and creates confusion about which latency is being reported.

**Fix:**
```python
# In SafeAgentWrapper, don't re-time if already timed by BaseAIAgent
async def compute(self, context: AIContext) -> AgentOutput:
    """Run agent.compute() with timeout + exception safety."""
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            self._agent.compute(context),
            timeout=self._timeout_s,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        # Only update latency if not already set by BaseAIAgent
        if result.latency_ms == 0.0:
            return result.model_copy(update={"latency_ms": latency_ms})
        return result

    except TimeoutError:
        # ... existing timeout handling ...
```

### WR-03: AIContextCache TTL expiration may cause stale context in long-running agents

**File:** `src/core/ai/context.py:18, 191`

**Issue:** The context cache has a 5-minute TTL (`_TTL_SECONDS = 300`), but narrative agents have a 60-second latency budget (`latency_budget_ms = 60000.0`). If the narrative agent takes 50+ seconds to generate text, the context may be nearly expired by the time it finishes. More critically, if an agent queues multiple signals (e.g., during market open with high signal volume), later signals in the queue may use significantly stale context.

The cache doesn't distinguish between "freshness for initial read" and "freshness for compute duration."

**Fix:**
```python
# Add a "compute_started_at" timestamp to AIContext
class AIContext(BaseModel):
    # ... existing fields ...
    compute_started_at: float | None = None  # time.monotonic() when build() called

# In build(), set the timestamp
def build(self, ...):
    # ... existing code ...
    return AIContext(
        # ... existing fields ...
        compute_started_at=time.monotonic(),
    )

# In BaseAIAgent._compute(), check context age
async def _compute(self, context: AIContext) -> AgentOutput:
    if context.compute_started_at:
        age = time.monotonic() - context.compute_started_at
        if age > 240:  # 4 minutes - warn before TTL expires
            self.logger.warning(
                "ai_agent.stale_context",
                agent_id=self.agent_id,
                age_s=round(age, 1),
            )
```

### WR-04: LLMProviderChain doesn't validate cache_ttl parameter

**File:** `src/core/llm/chain.py:41-42`

**Issue:** The `LLMProviderChain.__init__()` accepts `cache_ttl` as a parameter but doesn't validate it. Negative values or extremely large values (e.g., `cache_ttl=-1` or `cache_ttl=1e9`) will cause undefined behavior in `SemanticCache`:

- Negative TTL: `expires_at = monotonic() + (-1)` → cache entries expire immediately
- Extremely large TTL: cache entries persist for decades, violating "cache as transport" principle

**Fix:**
```python
def __init__(
    self,
    call_type: str,
    settings: Any | None = None,
    producer: Any | None = None,
    cache_ttl: float = 300.0,
) -> None:
    if cache_ttl < 0:
        raise ValueError(f"cache_ttl must be non-negative, got {cache_ttl}")
    if cache_ttl > 86400:  # 24 hours
        self.logger.warning(
            "llm_chain.excessive_cache_ttl",
            call_type=call_type,
            cache_ttl=cache_ttl,
        )
    self._cache_ttl = max(0.0, min(cache_ttl, 86400))  # Clamp to [0, 24h]
```

### WR-05: GuardrailsValidator.validate() doesn't log successful validations

**File:** `src/core/llm/guardrails.py:30-51`

**Issue:** The `validate()` method logs only validation failures (line 45-50), not successes. This makes it impossible to measure guardrail effectiveness (e.g., "99.5% of responses passed validation") without querying the database.

For debugging and monitoring, both success and failure should be logged.

**Fix:**
```python
def validate(self, call_type: str, response: str) -> dict[str, Any] | None:
    """Parse and validate response against registered schema."""
    schema = self._schemas.get(call_type)
    if schema is None:
        logger.debug("guardrails.no_schema", call_type=call_type)
        return None

    try:
        raw = json.loads(response)
        validated = schema.model_validate(raw)
        logger.debug(
            "guardrails.validation_success",
            call_type=call_type,
            response_length=len(response),
        )
        return validated.model_dump()
    except Exception as exc:
        logger.warning(
            "guardrails.validation_failed",
            call_type=call_type,
            error=str(exc),
            response_preview=response[:100],
        )
        return None
```

### WR-06: AlphaSwarmComputeAgent duplicates DB pool creation

**File:** `services/alpha_swarm_agent.py:102-116`

**Issue:** The `_setup()` method calls `super()._setup()` (which creates a DB pool at line 113-117 of base_group_service.py), then **immediately creates another DB pool** at line 108-110:

```python
async def _setup(self) -> None:
    await super()._setup()  # Creates self._pool at base class line 113-117

    # DB pool + ShadowRecorder
    import asyncpg
    self._pool = await asyncpg.create_pool(  # DUPLICATE CREATION
        self.settings.database_url, min_size=2, max_size=5,
    )
```

This creates two connection pools to the same database, wasting resources and potentially causing connection exhaustion.

**Fix:**
```python
async def _setup(self) -> None:
    await super()._setup()  # self._pool already created by base class

    # ShadowRecorder and TransformRecorder use existing pool
    self._recorder = ShadowRecorder(
        self._pool, batch_size=50, flush_interval_s=2.0,
    )
    self._transform_recorder = TransformRecorder(
        self._pool, batch_size=50, flush_interval_s=2.0,
    )
```

### WR-07: NarrativeGroupComputeAgent._bar_topic() returns empty string

**File:** `services/ai_narrative_agent.py:58-62`

**Issue:** The `_bar_topic()` method returns an empty string, which is then passed to `KafkaConsumerClient.__init__()` in `BaseGroupService._setup()`. The KafkaConsumerClient doesn't validate the topic name, so this creates a consumer with an invalid topic.

While the narrative service intends to not consume bars, this creates a broken Kafka consumer that may log errors or consume resources.

**Fix:**
```python
# In BaseGroupService._setup(), check for empty bar_topic
async def _setup(self) -> None:
    # ... existing trigger_consumer setup ...

    # Wire bar consumer (only if subclass provides a topic)
    bar_topic = self._bar_topic()
    if bar_topic:  # Only create consumer if topic is non-empty
        self._bar_consumer = KafkaConsumerClient(
            bar_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self.group_id}_bar_consumer",
            auto_offset_reset="latest",
        )
        await self._bar_consumer.start()
    else:
        self._bar_consumer = None

# In NarrativeGroupComputeAgent, return None instead of empty string
def _bar_topic(self) -> str | None:
    """No bar consumer needed for narrative service."""
    return None
```

### WR-08: Prompt builders don't validate required context fields

**File:** `src/intelligence/ai/alpha/skeptic_prompts.py:71-102`

**Issue:** The `build_skeptic_prompt()` function accesses `ctx.get()` calls without validation, then formats them. If a critical field is missing (e.g., `winner_plugin` is None), the prompt will contain "unknown" but the LLM won't know the field was missing.

More critically, the template uses `.0%` format specifier (line 85) which requires a float, but if `winner_confidence` is None or a non-numeric string, this will crash with `ValueError`.

**Fix:**
```python
def build_skeptic_prompt(ctx: dict) -> str:
    """Build the skeptic prompt from context dict."""
    template = PROMPT_REGISTRY[ACTIVE_VERSION]

    # Validate required fields
    required_fields = ["symbol", "timeframe", "winner_plugin"]
    missing = [f for f in required_fields if not ctx.get(f)]
    if missing:
        raise ValueError(f"Missing required context fields: {missing}")

    # Validate numeric fields
    winner_confidence = ctx.get("winner_confidence", 0.0)
    if not isinstance(winner_confidence, (int, float)):
        raise ValueError(f"winner_confidence must be numeric, got {type(winner_confidence)}")

    return template.format(
        symbol=ctx.get("symbol", "N/A"),
        timeframe=ctx.get("timeframe", "N/A"),
        winner_plugin=ctx.get("winner_plugin") or "unknown",
        winner_direction_label=_DIRECTION_LABELS.get(
            ctx.get("winner_direction", 0), "UNKNOWN",
        ),
        winner_confidence=_fmt(float(winner_confidence), ".0%"),  # Safe after validation
        # ... rest of fields ...
    )
```

### WR-09: SwarmAggregator._weighted_mean doesn't handle all-error case

**File:** `src/intelligence/swarm/aggregator.py:22-41`

**Issue:** The `_weighted_mean()` function filters out results with errors (`if r.error is None`), but doesn't check if the filtered list is empty before computing weights. If all results have errors, `total_conf` will be 0 and the function will return the unweighted mean.

However, the unweighted mean of an empty list (`values` will be empty) will cause `ZeroDivisionError` at line 39.

**Fix:**
```python
def _weighted_mean(results: list[AgentOutput]) -> float:
    """Confidence-weighted mean multiplier. Returns 1.0 for empty/all-error list."""
    if not results:
        return _NEUTRAL

    values = []
    for r in results:
        mult = r.payload.get("multiplier", 1.0)
        conf = r.payload.get("confidence", 0.0)
        if r.error is None and mult is not None:
            values.append((mult, conf))

    if not values:
        return _NEUTRAL  # All had errors

    total_conf = sum(c for _, c in values)
    if total_conf == 0:
        return sum(m for m, _ in values) / len(values) if values else _NEUTRAL

    return sum(m * c for m, c in values) / total_conf
```

### WR-10: AlphaSwarmComputeAgent._enrich_context may corrupt lead_context

**File:** `services/alpha_swarm_agent.py:270-291`

**Issue:** The `_enrich_context()` method calls `ctx.model_copy(update={...})` with new `lead_context` and `volume_profile` values. However, `model_copy()` creates a **new instance** but doesn't update the original object in the cache.

If multiple agents share the same `AIContext` instance from `build()`, and each calls `_enrich_context()`, they'll get different enriched copies. This is actually correct behavior, but the method name suggests in-place mutation which is misleading.

More critically, if `lead_context` is already set in the original `AIContext` (e.g., from a previous enrichment), the code will overwrite it rather than merge.

**Fix:**
```python
def _enrich_context(self, ctx: AIContext) -> AIContext:
    """Enrich AIContext with agent-specific data.

    Returns a NEW AIContext with enrichment fields added.
    Original ctx is never mutated (Pydantic immutability).
    """
    # Only add lead_context if not already present
    lead_context = ctx.lead_context
    if lead_context is None:
        lead_context = self._find_lead_context(ctx.symbol, ctx.timeframe, ctx)

    # Only add volume_profile if not already present
    volume_profile = ctx.volume_profile
    if volume_profile is None:
        volume_profile = self._extract_volume_profile(ctx.symbol, ctx.timeframe)

    return ctx.model_copy(update={
        "lead_context": lead_context,
        "volume_profile": volume_profile,
    })
```

### WR-11: Graduation.query_agent_predictions uses SQL string concatenation

**File:** `src/intelligence/swarm/graduation.py:259-273`

**Issue:** The SQL query uses `conn.fetch("""...""", agent_id)` which is safe (parameterized), but the function doesn't validate that `agent_id` doesn't contain SQL injection patterns. While asyncpg's parameterized queries prevent injection, the function should validate the input format.

More critically, the query joins `signal_ledger` on `(signal_id, symbol)` which is a composite key, but the JOIN condition only matches on `signal_id`. This will cause incorrect matches if two signals have the same ID but different symbols (which shouldn't happen, but the schema doesn't prevent it).

**Fix:**
```python
def query_agent_predictions(conn, agent_id: str, min_samples: int = 30) -> list[dict]:
    """Query signal_lineage for agent prediction events."""
    # Validate agent_id format
    if not agent_id or not isinstance(agent_id, str):
        raise ValueError(f"agent_id must be a non-empty string, got {agent_id}")

    rows = conn.fetch("""
        SELECT sl.signal_id, sl.multiplier, sl.metadata, sl.symbol, sl.tf,
               sl.ts, sl.is_shadow,
               COALESCE(s.outcome, 'pending') as outcome,
               COALESCE(s.pnl_r, 0.0) as pnl_r
        FROM signal_lineage sl
        LEFT JOIN signal_ledger s
            ON sl.signal_id = s.signal_id
            AND sl.symbol = s.symbol  -- Match on composite key
            AND sl.tf = s.tf  -- Also match timeframe for correctness
        WHERE sl.event_type = 'agent_prediction'
          AND sl.source = $1
        ORDER BY sl.ts DESC
        LIMIT $2
    """, agent_id, min_samples)
    return rows
```

### WR-12: LLMProviderChain auto-audit publishes sensitive metadata

**File:** `src/core/llm/chain.py:180-196`

**Issue:** The auto-audit feature publishes the full `audit_context` dict to Kafka (line 187-194), which may contain sensitive information like user IDs, internal system state, or PII. The code doesn't filter or sanitize the audit_context before publishing.

Additionally, the audit includes `response` (the full LLM output) which may contain sensitive market analysis or trading signals that shouldn't be logged in a separate audit system.

**Fix:**
```python
# D-06: Auto-audit — publish to topic_llm_calls when audit_context provided
if audit_context is not None and self._producer is not None:
    from src.core.stream_keys import topic_llm_calls
    try:
        # Sanitize audit_context - remove sensitive fields
        sanitized_audit = {
            k: v for k, v in audit_context.items()
            if k not in {"user_id", "session_id", "ip_address", "pii"}
        }

        await self._producer.publish(
            topic_llm_calls(self._settings.env_name),
            {
                **sanitized_audit,
                "response": response[:1000] if response else None,  # Truncate long responses
                "response_length": len(response) if response else 0,
                "provider": provider_id,
                "call_type": self._call_type,
                "tokens": tokens,
                "model": model,
            },
        )
    except Exception:
        logger.exception("auto_audit.publish_failed", call_type=self._call_type)
```

## Info

### IN-01: Inconsistent error message formatting

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:66, 75`

**Issue:** Error messages use different formats:
- Line 66: `error="LLM returned empty response"`
- Line 75: `error="JSON parse failed"`

Some include quotes, some don't. Standardize on a consistent format for log parsing.

**Fix:**
```python
# Define error constants at module level
_ERROR_EMPTY_RESPONSE = "llm_empty_response"
_ERROR_JSON_PARSE_FAILED = "json_parse_failed"
_ERROR_TIMEOUT = "timeout"

# Use constants in error returns
return self._neutral(error=_ERROR_EMPTY_RESPONSE, latency_ms=0.0)
```

### IN-02: Magic numbers in aggregation logic

**File:** `src/intelligence/swarm/aggregator.py:16-19`

**Issue:** Path B discount factor (0.3) and production clamp bounds (0.7, 1.3) are hardcoded. These should be constants with documentation explaining their rationale.

**Fix:**
```python
# Path B discount: LLM swarm predictions are less reliable than deterministic transforms
# Apply 30% discount to confidence weights
_PATH_B_DISCOUNT = 0.3

# Production clamp: limit multiplier impact on position sizing to prevent extreme over/under-leverage
# Even if all agents agree perfectly, max position size is 1.3x base
# Min position size is 0.7x base (never fully zero out)
_PRODUCTION_CLAMP_LOW = 0.7
_PRODUCTION_CLAMP_HIGH = 1.3
```

### IN-03: NarrativeComputeAgent has unused latency_budget_ms

**File:** `src/intelligence/ai/narrative/narrative_agent.py:39`

**Issue:** `latency_budget_ms = 60000.0` is defined but never used (the agent returns stub text). The timeout should be enforced even if the LLM call is disabled.

**Fix:**
```python
# In the stub return, still respect latency budget
return AgentOutput(
    # ... existing fields ...
    latency_ms=0.0,  # Stub is instant
    error=f"stub_mode_not_implemented:{self.latency_budget_ms}",
)
```

### IN-04: AIContext frozen=True but uses model_copy() frequently

**File:** `src/core/ai/context.py:96`

**Issue:** `AIContext` has `model_config = ConfigDict(frozen=True)` for immutability, but the code frequently uses `model_copy(update={...})` which creates new instances. This is correct Pydantic usage, but creates many temporary objects.

Consider using `frozen=False` if performance becomes an issue, or document the immutability rationale.

**Fix:**
```python
# Document why frozen=True is important
class AIContext(BaseModel):
    """Typed context for AI agent computation.

    Immutable after construction (frozen=True) to prevent accidental mutation
    in multi-agent dispatch where multiple agents share the same context instance.
    Use model_copy(update={...}) to create enriched variants.
    """
    model_config = ConfigDict(frozen=True)
```

### IN-05: Kafka topic names duplicated in multiple files

**File:** `src/core/stream_keys.py`, `services/alpha_swarm_agent.py`, `services/ai_narrative_agent.py`

**Issue:** Topic names are defined in `stream_keys.py` (good) but some services hardcode prefixes or suffixes. For example, `alpha_swarm_agent.py` line 34 defines `_ELIGIBLE_TFS` which should be in a shared config.

**Fix:**
```python
# Move to src/config/settings.py or a constants module
class AgentConfig:
    """Shared configuration for AI agents."""
    NARRATIVE_ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})
    ALPHA_ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})
```

### IN-06: graduation.py import statement unused

**File:** `src/intelligence/swarm/graduation.py:13-15`

**Issue:** The file imports `datetime`, `UTC`, `timedelta` at lines 13-14 but the `datetime` class is imported twice (line 13 and line 15). Line 13 imports `datetime` (the module) and line 15 imports `UTC` (from datetime module), but line 295 uses `datetime.now(UTC)` which requires the `datetime` class from the module.

**Fix:**
```python
from datetime import UTC, datetime, timedelta  # Remove duplicate import
```

---

_Reviewed: 2026-04-28T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
