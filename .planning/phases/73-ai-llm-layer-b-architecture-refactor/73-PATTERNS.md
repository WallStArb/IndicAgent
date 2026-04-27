# Phase 73: AI LLM Layer B+ Architecture Refactor - Pattern Map

**Mapped:** 2026-04-26
**Files analyzed:** 18 new/modified files
**Analogs found:** 18 / 18

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/core/ai/base_agent.py` | utility/base-class | request-response | `src/core/swarm/base_agent.py` | exact (absorb) |
| `src/core/ai/base_group_service.py` | service | event-driven | `services/swarm_dispatch_service.py` | exact (generalize) |
| `src/core/ai/context.py` | model/utility | transform | `src/intelligence/swarm/context.py` | exact (absorb) |
| `src/core/ai/output.py` | model | transform | `src/intelligence/schemas.py` AgentResult | role-match |
| `src/core/ai/safe_wrapper.py` | utility | request-response | `src/intelligence/swarm/safety.py` | exact (absorb) |
| `src/core/llm/chain.py` | utility | request-response | self (6 surgical fixes) | self |
| `src/core/llm/semantic_cache.py` | utility | transform | self (1 line fix) | self |
| `src/core/stream_keys.py` | config/utility | — | self (3 new topic functions) | self |
| `services/alpha_swarm_agent.py` | service | event-driven | `services/swarm_dispatch_service.py` | exact (rename+refactor) |
| `services/ai_narrative_agent.py` | service | event-driven | self + `services/swarm_dispatch_service.py` | role-match |
| `src/intelligence/ai/alpha/skeptic_agent.py` | agent | request-response | `src/intelligence/swarm/agents/skeptic_agent.py` | exact (move+rebase) |
| `src/intelligence/ai/alpha/correlation_agent.py` | agent | request-response | `src/intelligence/swarm/agents/correlation_agent.py` | exact (move+rebase) |
| `src/intelligence/ai/alpha/volume_agent.py` | agent | request-response | `src/intelligence/swarm/agents/volume_agent.py` | exact (move+rebase) |
| `src/intelligence/ai/alpha/skeptic_prompts.py` | utility | — | `src/intelligence/swarm/agents/skeptic_prompts.py` | exact (move) |
| `src/intelligence/ai/alpha/correlation_prompts.py` | utility | — | `src/intelligence/swarm/agents/correlation_prompts.py` | exact (move) |
| `src/intelligence/ai/alpha/volume_prompts.py` | utility | — | `src/intelligence/swarm/agents/volume_prompts.py` | exact (move) |
| `src/intelligence/ai/narrative/narrative_agent.py` | agent | request-response | `src/intelligence/narrative/orchestrator.py` | role-match |
| `src/intelligence/ai/risk/__init__.py` | config | — | `src/intelligence/ai/alpha/__init__.py` | role-match |

---

## Pattern Assignments

### `src/core/ai/base_agent.py` (utility/base-class, request-response)

**Analog:** `src/core/swarm/base_agent.py` — absorb and generalize.

**Imports pattern** (lines 1-26 of analog):
```python
from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import TYPE_CHECKING

import structlog

from src.core.agent.base import BaseAgent
from src.intelligence.schemas import AgentResult  # replace with AgentOutput

if TYPE_CHECKING:
    from src.intelligence.swarm.context import SwarmContext  # replace with AIContext
```

**Class header pattern** — replace `SwarmBaseAgent(BaseAgent)` with `BaseAIAgent(BaseAgent, ABC)`. Add `IAIAgent` Protocol in same file using `typing.Protocol`.

**Class attributes pattern** (analog lines 36-43):
```python
agent_id: str = ""          # override in subclass
path: str = "deterministic" # REMOVE — not in AgentOutput
shadow_only: bool = True    # KEEP
latency_budget_ms: float = 5000.0  # KEEP

def __init__(self, *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._timeout_s = self.latency_budget_ms / 1000.0
```

New: add `group: str = ""` and `tiers_needed: frozenset[Tier] = frozenset()` class attributes (from design spec).

**Core compute wrapper pattern** (analog lines 44-64):
```python
async def compute(self, context: SwarmContext) -> AgentResult:
    import time
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            self._compute(context),
            timeout=self._timeout_s,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        return result.model_copy(update={"latency_ms": latency_ms})
    except TimeoutError:
        latency_ms = (time.monotonic() - t0) * 1000
        logger.warning("swarm_agent.timeout", agent_id=self.agent_id, timeout_s=self._timeout_s)
        msg = f"timeout after {self._timeout_s:.1f}s"
        return self._neutral(error=msg, latency_ms=latency_ms)
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        logger.exception("swarm_agent.exception", agent_id=self.agent_id, error=str(exc))
        return self._neutral(error=str(exc), latency_ms=latency_ms)
```

Rename `compute()` signature to `AIContext → AgentOutput`. Keep `asyncio.wait_for` + `model_copy(update=...)` pattern exactly.

**Abstract method pattern** (analog lines 66-69):
```python
@abstractmethod
async def _compute(self, context: SwarmContext) -> AgentResult:
    """Implement the agent's core alpha computation logic."""
    ...
```

**Neutral fallback pattern** (analog lines 71-80):
```python
def _neutral(self, error: str, latency_ms: float) -> AgentResult:
    return AgentResult(
        agent_id=self.agent_id,
        path=self.path,
        multiplier=_NEUTRAL_MULTIPLIER,
        confidence=_NEUTRAL_CONFIDENCE,
        shadow_only=self.shadow_only,
        latency_ms=latency_ms,
        error=error,
    )
```

New version uses `AgentOutput(agent_id=..., group=..., payload={}, shadow_only=..., latency_ms=..., error=...)`.

---

### `src/core/ai/base_group_service.py` (service, event-driven)

**Analog:** `services/swarm_dispatch_service.py` — the concrete dispatch service is the template for the abstract base.

**Class header pattern** (analog line 74):
```python
class SwarmDispatchComputeAgent(BaseAgent):
```
New: `class BaseGroupService(BaseAgent): ...` — same `BaseAgent` inheritance. `_setup`, `_run`, `_teardown` are abstract properties that subclasses implement.

**__init__ infrastructure pattern** (analog lines 82-105):
```python
def __init__(self, settings: Settings) -> None:
    super().__init__(name="SwarmDispatchComputeAgent", max_idle_seconds=300)
    self.settings = settings
    self._llm_chain = LLMProviderChain(call_type="swarm", settings=settings, cache_ttl=300.0)
    self._context_cache = SwarmContextCache()
    self._recorder: ShadowRecorder | None = None
    self._agents = [
        SkepticAgentComputeAgent(llm_chain=self._llm_chain),
        CorrelationAgentComputeAgent(llm_chain=self._llm_chain),
        VolumeAgentComputeAgent(llm_chain=self._llm_chain),
    ]
    self._bar_consumer: KafkaConsumerClient | None = None
    self._signal_consumer: KafkaConsumerClient | None = None
    self._producer: KafkaProducerClient | None = None
    self._pool: asyncpg.Pool | None = None
```

**_setup pattern** (analog lines 107-150): Consumer/producer startup + DB pool + cache seeding. `BaseGroupService._setup()` should call `super()._setup()` if it exists (BaseAgent._setup is a no-op), then connect bar consumer, trigger consumer, producer, pool.

**_run dual-loop pattern** (analog lines 166-174):
```python
async def _run(self) -> None:
    bar_task = asyncio.create_task(self._bar_loop())
    signal_task = asyncio.create_task(self._signal_loop())
    try:
        await asyncio.gather(bar_task, signal_task)
    except Exception:
        bar_task.cancel()
        signal_task.cancel()
        raise
```

New: add a third `graduation_task = asyncio.create_task(self._graduation_loop())` alongside bar and trigger tasks.

**_bar_loop cache update pattern** (analog lines 176-187):
```python
async def _bar_loop(self) -> None:
    assert self._bar_consumer is not None
    async for _topic, _key, payload in self._bar_consumer.messages():
        if not self.running:
            break
        self._record_message_consumed()
        try:
            self._context_cache.update(payload)
        except Exception as exc:
            self.logger.warning("swarm_dispatch.bar_cache_error", error=str(exc))
```

**_signal_loop dispatch pattern** (analog lines 189-200):
```python
async def _signal_loop(self) -> None:
    assert self._signal_consumer is not None
    async for _topic, _key, payload in self._signal_consumer.messages():
        if not self.running:
            break
        self._record_message_consumed()
        try:
            await self._handle_signal(payload)
        except Exception as exc:
            self.logger.exception("swarm_dispatch.signal_error", error=str(exc))
```

Rename to `_trigger_loop` / `_handle_trigger` in `BaseGroupService`.

**asyncio.gather agents pattern** (analog lines 231-234):
```python
results = await asyncio.gather(
    *[agent.compute(enriched) for agent in self._agents]
)
```

In `BaseGroupService._handle_trigger`, use `SafeAgentWrapper` around each agent: `asyncio.gather(*[SafeAgentWrapper(a).run(ctx) for a in self.agents])`.

**DB seed pattern** (analog lines 461-484):
```python
async def _seed_context_cache(self, pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (symbol, tf)
                symbol, tf, ts, bar, i1, i4, i6
            FROM intelligence_features
            WHERE ts > NOW() - INTERVAL '7 days'
              AND i1 IS NOT NULL AND i4 IS NOT NULL
            ORDER BY symbol, tf, ts DESC
        """)
    for row in rows:
        self._context_cache.seed_from_db_row(dict(row))
```

**_teardown flush pattern** (analog lines 152-164):
```python
async def _teardown(self) -> None:
    if self._recorder:
        await self._recorder.flush()
    if self._pool:
        await self._pool.close()
    if self._bar_consumer:
        await self._bar_consumer.stop()
    if self._signal_consumer:
        await self._signal_consumer.stop()
    if self._producer:
        await self._producer.stop()
```

---

### `src/core/ai/context.py` (model/utility, transform)

**Analog:** `src/intelligence/swarm/context.py` — absorb and generalize.

**Module header and imports pattern** (analog lines 1-21):
```python
from __future__ import annotations

import time
import types
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.intelligence.schemas import IntelligenceEvent, RankedSignal

logger = structlog.get_logger(__name__)
_TTL_SECONDS = 300  # 5 minutes
```

**Frozen Pydantic model pattern** (analog lines 25-73):
```python
class SwarmContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    signal_id: UUID
    symbol: str
    timeframe: str
    ts: Any  # datetime
    # fields...
    lead_context: SwarmContext | None = None  # self-referential frozen model
```

For self-referential `AIContext.lead_context: "AIContext | None" = None`, use `from __future__ import annotations` (already present) and call `AIContext.model_rebuild()` after class definition — exact pattern proven in analog line 72.

**`model_copy(update=...)` for frozen enrichment** (analog usage in `swarm_dispatch_service.py` line 332):
```python
return ctx.model_copy(update={
    "lead_context": lead_context,
    "volume_profile": volume_profile,
})
```

**Cache class pattern** (analog lines 76-168 of `context.py`):
```python
class SwarmContextCache:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[Any, float]] = {}

    def update(self, event: IntelligenceEvent) -> None:
        key = (event.symbol, event.tf)
        self._cache[key] = (event, time.monotonic())

    def seed_from_db_row(self, row: dict) -> None:
        # SimpleNamespace proxy for asyncpg dict rows
        def _ns(d: dict | None) -> types.SimpleNamespace:
            if isinstance(d, dict):
                return types.SimpleNamespace(**d)
            return types.SimpleNamespace()
        # ... proxy construction ...
        self._cache[(symbol, tf)] = (proxy, time.monotonic())

    def build(self, symbol: str, tf: str, ...) -> SwarmContext | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        event, cached_at = entry
        age = time.monotonic() - cached_at
        if age > _TTL_SECONDS:
            return None
        # field mapping from event → context
```

New: `AIContextCache.build(symbol, tf, tiers_needed: frozenset[Tier])` — use `tiers_needed` to conditionally populate tier contexts instead of always populating all I1/I4/I6.

New: `AIContextCache.get_lead(symbol, tf, lead_map)` — encapsulates the private `._cache` prefix-search logic currently in `swarm_dispatch_service._find_lead_context` (lines 354-432). This eliminates D-10 private access.

**`_safe` helper pattern** (analog line 134, and `swarm_dispatch_service.py` line 69):
```python
def _safe(obj: Any, attr: str) -> Any:
    return getattr(obj, attr, None)
```

**`Tier` enum**: `class Tier(str, Enum): BAR="bar"; I1="i1"; I2="i2"; ...` — `str, Enum` pattern consistent with CLAUDE.md enum convention (extends `str` for DB compatibility).

---

### `src/core/ai/output.py` (model, transform)

**Analog:** `src/intelligence/schemas.py` `AgentResult` (lines 878-915).

**Frozen Pydantic model pattern** (analog lines 878-891):
```python
class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent_id: str
    path: Literal["deterministic", "llm_swarm"]
    multiplier: float = Field(..., ge=MIN_MULTIPLIER, le=MAX_MULTIPLIER)
    confidence: float = Field(..., ge=0.0, le=1.0)
    shadow_only: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None
```

New `AgentOutput` drops `path`, `multiplier`, `confidence` fields. Adds `group`, `signal_id`, `symbol`, `timeframe`, `ts`, `output_type`, and `payload: dict[str, Any]` (untyped by design). All field names follow `snake_case`. Import: `from pydantic import BaseModel, ConfigDict, Field`.

`AlphaMultiplier.contributors: dict[str, AgentResult]` in `src/intelligence/schemas.py` (line 907) must be updated to `dict[str, AgentOutput]` in the same plan wave.

---

### `src/core/ai/safe_wrapper.py` (utility, request-response)

**Analog:** `src/intelligence/swarm/safety.py` — absorb directly, rename types.

**Full class pattern** (analog lines 26-86):
```python
class SafeSwarmWrapper:
    def __init__(self, contributor: object) -> None:
        self._contributor = contributor
        self._agent_id: str = getattr(contributor, "agent_id", "unknown")
        self._path: str = getattr(contributor, "path", "deterministic")
        self._shadow_only: bool = getattr(contributor, "shadow_only", True)
        budget_ms: float = getattr(contributor, "latency_budget_ms", 5000.0)
        self._timeout_s: float = budget_ms / 1000.0

    async def run(self, context: SwarmContext) -> AgentResult:
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._contributor.compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            return result.model_copy(update={"latency_ms": latency_ms})
        except TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning("swarm_wrapper.timeout", agent_id=self._agent_id,
                           timeout_s=self._timeout_s, latency_ms=round(latency_ms, 1))
            return self._neutral(error=f"timeout after {self._timeout_s:.1f}s", latency_ms=latency_ms)
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception("swarm_wrapper.exception", agent_id=self._agent_id, error=str(exc))
            return self._neutral(error=str(exc), latency_ms=latency_ms)

    def _neutral(self, error: str, latency_ms: float) -> AgentResult:
        return AgentResult(agent_id=self._agent_id, path=self._path,
                           multiplier=1.0, confidence=0.0,
                           shadow_only=self._shadow_only, latency_ms=latency_ms, error=error)
```

New: rename to `SafeAgentWrapper`, swap `SwarmContext → AIContext`, `AgentResult → AgentOutput`. `_neutral()` returns `AgentOutput(payload={}, ...)`. Remove `path` attribute (not in `AgentOutput`). Drop `_path` from `__init__`.

---

### `src/core/llm/chain.py` (utility, request-response) — 6 surgical fixes

**Current file:** `/home/bg/dev/indicagent/src/core/llm/chain.py` (159 lines). All fixes are in `generate()` and `__init__`.

**Fix D-04 — rate limiter wiring** (insert after cache miss at line ~91, before budget check):
```python
# After cache miss, before budget check:
limiter = self._rate_limiters.get("default") or next(iter(self._rate_limiters.values()), None)
if limiter is not None:
    await limiter.acquire(tokens=max_tokens)
```

**Fix D-05 — guardrails dead branch** (current lines 127-131):
```python
# Current (broken intent — private attr access):
if self._call_type and self._call_type in _guardrails._schemas:
    validated = _guardrails.validate(self._call_type, response)
    if validated is None:
        return None
# Fix: Add has_schema() to GuardrailsValidator. Then:
if _guardrails.has_schema(self._call_type):
    validated = _guardrails.validate(self._call_type, response)
    if validated is None:
        return None
```

**Fix D-06 — auto-audit** (`generate()` signature and publish block):
```python
async def generate(
    self,
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    model: str = "default",
    audit_context: dict | None = None,  # NEW param
) -> str | None:
    # ... existing logic ...
    # After storing in cache, add:
    if audit_context is not None and self._producer is not None:
        await self._producer.publish(
            topic_llm_calls(self._settings.env_name),
            {**audit_context, "response": response, "provider": provider_id,
             "call_type": self._call_type, "tokens": estimated_tokens},
        )
```

**Fix D-07 — real token counts** (lines 133-140):
```python
# Current (estimated):
estimated_tokens = max(1, len(prompt) // 4 + len(response) // 4)

# New: read from provider's last_token_usage (add attribute to LLMChain/providers.py)
token_usage = getattr(self._inner, "last_token_usage", None)
actual_tokens = (token_usage.get("total_tokens") if token_usage else None)
tokens = actual_tokens if actual_tokens else max(1, len(prompt) // 4 + len(response) // 4)
_budget.record(call_type=self._call_type, provider=provider_id, tokens=tokens)
```

**Fix D-08 location:** `semantic_cache.py` line 23 (see below).

---

### `src/core/llm/semantic_cache.py` (utility, transform) — 1 line fix

**Current line 23:**
```python
raw = f"{system}|{prompt[:200]}|{model}"
```

**Fixed:**
```python
raw = f"{system}|{prompt}|{model}"
```

No other changes. Single-character deletion (remove `[:200]`).

---

### `src/core/stream_keys.py` (config/utility) — 3 new topic functions

**Analog pattern** for existing swarm topics (lines 302-333):
```python
def topic_swarm_results(env_name: str) -> str:
    """Per-AgentResult fan-out topic. SwarmWriterAgent subscribes here."""
    return f"{env_prefix(env_name)}intelligence.swarm"

def topic_swarm_alpha_path_a(env_name: str) -> str:
    """Assembled AlphaMultiplier from deterministic (Path A) contributors."""
    return f"{env_prefix(env_name)}swarm.alpha.path_a"
```

**Three new functions to add** (append to the Swarm topics section, after line 333):
```python
def topic_swarm_alpha(env_name: str) -> str:
    """Assembled AlphaMultiplier from all swarm paths (unified aggregate).

    Published by AlphaSwarmComputeAgent after asyncio.gather() across all agents.
    Consumed by SwarmWriterAgent for persistence to signal_transform_log.
    """
    return f"{env_prefix(env_name)}swarm.alpha"


def topic_swarm_graduation(env_name: str) -> str:
    """Per-agent graduation flip events from BaseGroupService._graduation_loop.

    Published when shadow_only flips True→False via Spearman gate passage.
    Consumed by future GraduationWriterAgent (or logged for audit).
    """
    return f"{env_prefix(env_name)}swarm.graduation"


def topic_shadow_recordings(env_name: str) -> str:
    """ShadowRecorder publishes AgentOutput records here (Kafka-first DAG).

    Consumed by shadow_writer_agent (or swarm_writer_agent) for persistence
    to signal_transform_log. Hot path NEVER writes to DB directly.
    """
    return f"{env_prefix(env_name)}intelligence.shadow_recordings"
```

---

### `services/alpha_swarm_agent.py` (service, event-driven)

**Analog:** `services/swarm_dispatch_service.py` — rename + refactor to extend `BaseGroupService`.

**Module docstring pattern** (analog lines 1-7):
```python
"""alpha_swarm_agent.py -- AlphaSwarmComputeAgent extending BaseGroupService.

Per B+ architecture: one service, all alpha agents, extends BaseGroupService.
group_id="alpha", has_graduation=True
"""
```

**Imports pattern** (analog lines 9-41): Keep all existing imports. Add:
```python
from src.core.ai.base_group_service import BaseGroupService
from src.core.ai.context import AIContext, AIContextCache
from src.core.ai.output import AgentOutput
from src.core.stream_keys import topic_swarm_alpha, topic_shadow_recordings
# Change agent imports from old path → new path:
from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent
from src.intelligence.ai.alpha.correlation_agent import CorrelationAgentComputeAgent
from src.intelligence.ai.alpha.volume_agent import VolumeAgentComputeAgent
```

**Class definition** — rename `SwarmDispatchComputeAgent → AlphaSwarmComputeAgent`, extend `BaseGroupService` instead of `BaseAgent`.

**group_id and properties** — concrete override of `BaseGroupService` abstract properties:
```python
group_id = "alpha"
has_graduation = True

@property
def agents(self) -> list[BaseAIAgent]:
    return self._agents

@property
def trigger_topics(self) -> list[str]:
    return [topic_intelligence_i7_signals(self.env_name)]

@property
def output_topic(self) -> str:
    return topic_swarm_alpha(self.env_name)
```

**D-10 fix**: replace both `self._context_cache._cache` accesses (lines 363, 444 of analog) with `self._context_cache.get_lead(symbol, tf, _LEAD_INDEX_MAP)`.

---

### `services/ai_narrative_agent.py` (service, event-driven)

**Analog (current file):** `services/ai_narrative_agent.py` (160 lines) + `services/swarm_dispatch_service.py` (group service pattern).

**Current class header pattern** (analog line 24):
```python
class AINarrativeComputeAgent(BaseAgent):
```

New: rename to `NarrativeGroupComputeAgent`, extend `BaseGroupService` instead of `BaseAgent`.

**Trigger consumer pattern** (analog lines 36-48):
```python
async def _setup(self) -> None:
    self._consumer = KafkaConsumerClient(
        topic_intelligence_journal(self.settings.env_name),
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id="ai_narrative_consumer",
    )
    self._producer = KafkaProducerClient(...)
    await self._consumer.start()
    await self._consumer.skip_lag_if_needed(max_lag=100)
    await self._producer.start()
```

**Staleness gate pattern** (analog lines 70-105) — keep this exact logic in `NarrativeComputeAgent._compute()`:
```python
_STALENESS_LIMIT = timedelta(minutes=10)

bar_ts_raw = adapted.intelligence.ts
if bar_ts_raw:
    bar_ts = datetime.fromisoformat(...) if isinstance is str else bar_ts_raw
    if bar_ts.tzinfo is None:
        bar_ts = bar_ts.replace(tzinfo=UTC)
    age = datetime.now(UTC) - bar_ts
    if age > self._STALENESS_LIMIT:
        self.logger.info("ai_narrative_agent.skipped_stale_bar", ...)
        return
```

**TF gate** — add before staleness check in `NarrativeComputeAgent._compute()`:
```python
_NARRATIVE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})

if tf not in _NARRATIVE_TFS:
    return  # return neutral AgentOutput, not None
```

**_RecordAdapter pattern** (analog lines 127-149) — keep as utility class; it adapts raw Kafka dict payloads. Move to `src/intelligence/ai/narrative/narrative_agent.py` alongside the NarrativeComputeAgent.

---

### `src/intelligence/ai/alpha/skeptic_agent.py` (agent, request-response)

**Analog:** `src/intelligence/swarm/agents/skeptic_agent.py` — move + rebase to `BaseAIAgent`.

**Import changes only** (analog lines 1-22):
```python
# Old imports to replace:
from src.core.swarm.base_agent import SwarmBaseAgent
from src.intelligence.schemas import AgentResult
from src.intelligence.swarm.agents.skeptic_prompts import ACTIVE_VERSION, build_skeptic_prompt
from src.intelligence.swarm.context import SwarmContext

# New imports:
from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput
from src.intelligence.ai.alpha.skeptic_prompts import ACTIVE_VERSION, build_skeptic_prompt
```

**Class definition** (analog line 35):
```python
# Old:
class SkepticAgentComputeAgent(SwarmBaseAgent):
# New:
class SkepticAgentComputeAgent(BaseAIAgent):
```

**Class attributes** (analog lines 42-45) — add `group` and `tiers_needed`:
```python
agent_id = "skeptic_v1"
group = "alpha"
tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7})
shadow_only = True
latency_budget_ms = 5000.0
```

**`_compute()` return** (analog lines 83-96): replace `AgentResult(...)` with `AgentOutput(agent_id=..., group=..., payload={"multiplier": ..., "confidence": ..., ...}, shadow_only=..., ...)`. The `failure_probability`, `confidence`, `risk_factors`, `reasoning` all go into `payload` dict.

**`_neutral()` inherited** — no override needed; `BaseAIAgent._neutral()` handles it.

**JSON parse helpers** (analog lines 99-152) — move unchanged. These are standalone pure functions with no type dependencies.

---

### `src/intelligence/ai/alpha/correlation_agent.py` and `volume_agent.py`

Same pattern as `skeptic_agent.py`:
- Update 4 imports (base class, context type, output type, prompts path)
- Change class parent from `SwarmBaseAgent` → `BaseAIAgent`
- Add `group = "alpha"` and `tiers_needed = frozenset({...})` class attributes
- Change `_compute()` return from `AgentResult` → `AgentOutput` with `payload` dict
- JSON parse helpers move unchanged

---

### `src/intelligence/ai/narrative/narrative_agent.py` (agent, request-response)

**Analog:** `src/intelligence/narrative/orchestrator.py` — generalize to `BaseAIAgent._compute()` interface.

**Key interface change:** Current `NarrativeOrchestrator.generate(record: BarIntelligenceRecord)` → New `NarrativeComputeAgent._compute(context: AIContext) -> AgentOutput`.

The prompt building logic in `orchestrator.py` reads `record.intelligence.symbol`, `record.intelligence.tf`, `record.winner_direction` etc. These fields exist in `AIContext` as `context.symbol`, `context.timeframe`, `context.i7.winner_plugin`, `context.i7.winner_direction`. Map directly — no adapter needed.

**Return type change**: `return AgentOutput(agent_id="narrative_v1", group="narrative", payload={"text": narrative_text, ...}, shadow_only=self.shadow_only, ...)`

---

## Shared Patterns

### BaseAgent Extension (all new service files)

**Source:** `src/core/agent/base.py` lines 90-129
**Apply to:** `BaseGroupService`, `AlphaSwarmComputeAgent`, `NarrativeGroupComputeAgent`

```python
def __init__(self, name: str, max_idle_seconds: int = 300, settings: Settings | None = None) -> None:
    super().__init__(name=name, max_idle_seconds=max_idle_seconds)
    self.settings = settings or Settings()
```

Critical: `BaseAgent.__init__` auto-configures logging via `setup_service_logging()` using PascalCase→snake_case convention. Do NOT call `setup_service_logging()` again after `super().__init__()`.

### Kafka Consumer/Producer Setup

**Source:** `services/swarm_dispatch_service.py` lines 107-133, `services/ai_narrative_agent.py` lines 36-48
**Apply to:** All service files

```python
self._consumer = KafkaConsumerClient(
    topic_name(env),
    bootstrap_servers=self.settings.kafka_bootstrap_servers,
    group_id="<concept>_consumer",  # snake_case, idempotent on restart
    auto_offset_reset="latest",
)
await self._consumer.start()

self._producer = KafkaProducerClient(
    bootstrap_servers=self.settings.kafka_bootstrap_servers,
)
await self._producer.start()
```

Consumer group naming: `<concept>_consumer` (from CLAUDE.md). For renamed services, keep consumer group stable to avoid Kafka offset reset.

### asyncpg DB Pool

**Source:** `services/swarm_dispatch_service.py` lines 136-137
**Apply to:** `BaseGroupService._setup()`, `AIContextCache` seeding

```python
self._pool = await asyncpg.create_pool(
    self.settings.database_url, min_size=2, max_size=5,
)
```

### Frozen Pydantic Model Copy

**Source:** `services/swarm_dispatch_service.py` line 332-336, `src/core/swarm/base_agent.py` line 55
**Apply to:** All frozen model enrichment, `BaseAIAgent.compute()` latency injection

```python
return result.model_copy(update={"latency_ms": latency_ms})
```

### UTC Timestamp Pattern

**Source:** `services/ai_narrative_agent.py` lines 89-96
**Apply to:** Any timestamp parsing in `AIContext`, `AgentOutput`, narrative agent

```python
from datetime import UTC, datetime
bar_ts = datetime.fromisoformat(str(bar_ts_raw))
if bar_ts.tzinfo is None:
    bar_ts = bar_ts.replace(tzinfo=UTC)
```

### Structlog Logging Pattern

**Source:** `src/core/swarm/base_agent.py` line 26; `services/swarm_dispatch_service.py` line 42
**Apply to:** All new files

```python
import structlog
logger = structlog.get_logger(__name__)
# In services: use self.logger (inherited from BaseAgent)
# In standalone modules: use module-level logger
```

### stream_keys Topic Function Pattern

**Source:** `src/core/stream_keys.py` lines 302-333
**Apply to:** All 3 new topic functions in `stream_keys.py`

```python
def topic_<concept>(env_name: str) -> str:
    """One-line docstring describing producer and consumer."""
    return f"{env_prefix(env_name)}<domain>.<subdomain>"
```

Topic string format: dots only, never colons. Domain-scoped: `swarm.*`, `intelligence.*`. Always call `env_prefix(env_name)` not f-string manual prefix.

### systemd Unit File Pattern

**Source:** `services/indicagent-swarm-dispatch.service` (reference template per RESEARCH.md)
**Apply to:** New `indicagent-alpha-swarm.service` unit file

```ini
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
```

CRITICAL: Do NOT add `WatchdogSec` or `NotifyAccess` — no `sd_notify` is implemented (CLAUDE.md watchdog discipline rule).

---

## No Analog Found

All files have close analogs. No entries in this section.

---

## Key Patterns Summary

1. **Frozen Pydantic + `model_copy(update=...)`**: The universal enrichment pattern for immutable context objects. Used in `SwarmContext`, `AgentResult` — carry forward to `AIContext`, `AgentOutput`.
2. **ABC class absorbs into BaseAgent**: `BaseAIAgent(BaseAgent, ABC)` — gains SIGTERM handling, structured logging, Prometheus metrics, watchdog from `BaseAgent` lifecycle. Never re-implement these.
3. **asyncio.gather for concurrent agent dispatch**: Pattern locked in `swarm_dispatch_service.py` line 231-234. `BaseGroupService` generalizes it with `SafeAgentWrapper` per agent.
4. **Private `_cache` access eliminated**: D-10 fix adds `AIContextCache.get_lead()` to replace `self._context_cache._cache` at `swarm_dispatch_service.py` lines 363 and 444.
5. **topic functions always via `stream_keys.py`**: Never hardcode topic strings. Three new functions follow the `f"{env_prefix(env_name)}<topic>"` pattern.
6. **Cache key collision fix**: Single-line change in `semantic_cache.py` line 23 — remove `[:200]` from `prompt[:200]`.
7. **Rate limiter acquire**: Insert `await limiter.acquire(tokens=max_tokens)` after cache miss, before budget check in `chain.py` — `limiter = self._rate_limiters.get("default") or next(iter(...), None)`.

---

## Metadata

**Analog search scope:** `src/core/`, `src/intelligence/swarm/`, `src/intelligence/narrative/`, `services/`, `src/core/llm/`
**Files scanned:** 11 source files read in full
**Pattern extraction date:** 2026-04-26
