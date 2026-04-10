# Phase 56: Swarm Foundation Design

**Status:** Approved — Ready for implementation planning
**Date:** 2026-04-09
**Author:** Brandon + Claude Code
**Supersedes:** `docs/plans/2026-04-08-ai-layer-refactor-design-v3.md` (Phase 56 portions)

---

## Overview

Phase 56 builds the **Swarm Foundation** — the shared infrastructure, correct DAG topology, and properly wired protocol layer that makes the Intelligence Swarm (The "Renaissance Loop") production-ready. Phase 57 (next) builds the first swarm agent (SkepticAgent) on top of this foundation.

**Design principle:** Humans generate ideas, data validates them. This phase wires the plumbing — no agent produces production alpha until 14 days of shadow validation proves ρ ≥ 0.4 with realized PnL.

**What exists today:**
- `src/intelligence/swarm/` — protocol, safety, registry, 4 stub agents (none wired)
- `src/intelligence/llm_providers.py` — 430-line LLMChain with circuit breaker (not moved, not tracked)
- `src/intelligence/narrative/` (partial) — NarrativeOrchestrator not refactored
- `services/ai_narrative_service.py` — 1,327-line monolith

**What Phase 56 builds:**
1. Moves and extends `llm_providers.py` → `src/core/llm/`
2. Fixes the protocol/schema layer (`IAlphaContributor`, `SwarmContext`, `AgentResult`, `AlphaMultiplier`)
3. Refactors narrative service to thin coordinator
4. Wires `SwarmOrchestratorAgent` as a proper DAG service
5. Adds `SwarmWriterAgent` for shadow persistence
6. Schema migration + stream keys for swarm topics
7. Alpha promotion script + shadow validation framework

---

## Section 1: Full DAG Topology

```
Signal Pipeline (existing, unchanged)
─────────────────────────────────────
IntelligencePipelineAgent (I1-I7)
  └─→ Kafka: intelligence.signals   (signal_id, symbol, tf, winner, all_ranked, features)
  └─→ Kafka: intelligence.i{1-7}    (tiered features)
  └─→ DB: signal_ledger             (via SignalWriterAgent)


Swarm DAG (new — fully async, never blocks signal pipeline)
──────────────────────────────────────────────────────────
SwarmOrchestratorAgent (new service: indicagent-swarm-orchestrator)
  subscribes to: intelligence.signals + intelligence.i{1-6}
  
  Bar loop (every bar):
    populates: in-memory SwarmContextCache (symbol+tf keyed, TTL 5min)
  
  Signal loop (every new signal):
    1. Build SwarmContext from cache (O(1), no DB)
    2. Run Path A agents (deterministic, synchronous, <5ms each)
       └─→ Publish: swarm.alpha.path_a  (AlphaMultiplier, path="deterministic")
    3. Dispatch Path B agents (LLM swarm, asyncio.gather with per-agent timeout)
       └─→ Publish: swarm.alpha.path_b  (AlphaMultiplier, path="llm_swarm")
    4. Delta-publish world state if changed
       └─→ Publish: swarm.world_state   (compacted topic, symbol+tf key)

SwarmWriterAgent (new service: indicagent-swarm-writer)
  subscribes to: swarm.alpha.path_a + swarm.alpha.path_b
  writes to: alpha_multiplier_shadow hypertable (shadow only until validated)
  DLQ: swarm.writer.dlq  (unprocessable payloads — malformed schema, DB insert failure)

SwarmOrchestratorAgent DLQs:
  swarm.orchestrator.dlq  (signals with no cache entry, unresolvable SwarmContext)

AlphaShadowAnalyzer (script: scripts/alpha_promotion.py — extended)
  reads: alpha_multiplier_shadow JOIN signal_ledger (on signal_id)
  computes: Pearson(agent_confidence, realized_pnl_r) segmented by (symbol, timeframe, hmm_regime)
  promotes: agents where ρ ≥ 0.4, n ≥ 100, p < 0.05 per segment → production flag
  note: a global ρ = 0.4 does NOT qualify — must hold within each regime segment


Narrative Service (refactored)
──────────────────────────────
AInarrativeAgent (services/ai_narrative_agent.py — replaces 1,327-line monolith)
  uses: NarrativeOrchestrator (src/intelligence/narrative/)
  uses: LLMProviderChain (src/core/llm/providers.py — moved from intelligence/)
```

**Key invariants:**
- Signal pipeline (I1-I7) never imports from `swarm/` — zero coupling
- SwarmOrchestratorAgent never writes to DB directly — all writes via SwarmWriterAgent
- All swarm alpha is shadow-only until `alpha_promoted = True` in contributor config
- LLM calls never block the hot path — Path B is fire-and-publish

---

## Section 2: Protocol & Schema Redesign

### 2.1 SwarmContext (typed, built at service boundary)

```python
class SwarmContext(BaseModel):
    """Typed market context for swarm agent computation. Built from Kafka data — no DB lookups."""
    model_config = ConfigDict(frozen=True)

    # Identity
    signal_id: UUID
    symbol: str
    timeframe: str
    ts: datetime

    # From IntelligenceEvent (i1-i6 features)
    hmm_regime: int | None             # 0=ranging, 1=trending_up, 2=trending_down
    atr: float | None
    adx: float | None
    rsi: float | None
    vwap: float | None
    poc_price: float | None            # session volume profile POC
    poc_price_rolling: float | None    # rolling volume profile POC
    ctf_trend_alignment: float | None  # I6 confluence
    ctf_regime_agreement: float | None
    ctf_fvg_alignment: float | None
    ctf_ob_alignment: float | None

    # From RankedSignal (winner)
    winner_plugin: str | None
    winner_direction: str | None       # "long" | "short"
    winner_confidence: float | None
    winner_regime_type: str | None     # "trend" | "mean_reversion" | "any"

    # Path A deterministic features (populated by DeterministicContextBuilder)
    price: float | None
    volume: float | None
    spread_estimate: float | None      # optional, from I1 if available
```

**Construction:** `SwarmContextCache.build(bar_event, signal_event) -> SwarmContext`
- Cache key: `(symbol, timeframe)`
- Bar loop stores latest `IntelligenceEvent` per key
- Signal loop merges signal fields with cached bar features
- TTL: 5 minutes (stale = skip signal with warning)

### 2.2 IAlphaContributor (corrected protocol)

```python
@runtime_checkable
class IAlphaContributor(Protocol):
    """Protocol for all swarm intelligence contributors."""

    agent_id: str              # Unique name (matches config key)
    path: Literal["deterministic", "llm_swarm"]  # Determines phase in two-phase publish
    shadow_only: bool          # True until shadow-validated (default True)
    latency_budget_ms: float   # asyncio.wait_for timeout

    async def compute(self, context: SwarmContext) -> AgentResult:
        """Compute alpha contribution. Must not raise — return neutral on any error."""
        ...

    async def warm_up(self) -> None:
        """Called once at service start — pre-load models, validate dependencies."""
        ...

    def health_check(self) -> dict[str, Any]:
        """Return health metadata for Prometheus scrape."""
        ...
```

**Key corrections from current code:**
- `get_multiplier(sid, context: dict)` → `compute(context: SwarmContext)`
- Each agent returns `AgentResult` only — `SwarmAggregator` assembles `AlphaMultiplier`
- `context: dict[str, Any]` → `context: SwarmContext` (typed, validated at boundary)
- `path` is per-contributor attribute, not top-level on `AlphaMultiplier`

### 2.3 AgentResult (extended)

```python
class AgentResult(BaseModel):
    """Result from a single swarm agent. Immutable."""
    model_config = ConfigDict(frozen=True)

    agent_id: str
    path: Literal["deterministic", "llm_swarm"]  # moved here from AlphaMultiplier
    multiplier: float = Field(..., ge=MIN_MULTIPLIER, le=MAX_MULTIPLIER)
    confidence: float = Field(..., ge=0.0, le=1.0)
    shadow_only: bool = True           # mirrors contributor config
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0            # populated by SafeSwarmWrapper
    error: str | None = None           # populated on fallback
```

### 2.4 AlphaMultiplier (extended)

```python
class AlphaMultiplier(BaseModel):
    """Assembled alpha multiplier for a signal. Published to swarm.alpha.* topics."""
    model_config = ConfigDict(frozen=True)

    signal_id: UUID
    symbol: str                        # NEW — for routing/filtering
    timeframe: str                     # NEW — for routing/filtering
    ts: datetime

    # Path breakdown (replaces top-level path)
    path_a_multiplier: float | None    # deterministic path result
    path_b_multiplier: float | None    # llm_swarm path result (None until available)
    path_b_discount: float = 0.3       # discount applied to path_b confidence weight

    contributors: dict[str, AgentResult]
    final_alpha_multiplier: float = Field(..., ge=MIN_MULTIPLIER, le=MAX_MULTIPLIER)
    production_multiplier: float       # NEW — clamped [0.7, 1.3], safe for production
    shadow_only: bool                  # True if any contributing agent is shadow_only

    @property
    def is_production_ready(self) -> bool:
        return not self.shadow_only
```

**Aggregation function (short-term):** Confidence-weighted average with Path B discount

```python
def aggregate_results(path_a: list[AgentResult], path_b: list[AgentResult]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for r in path_a:
        w = r.confidence
        weighted_sum += r.multiplier * w
        total_weight += w
    for r in path_b:
        w = r.confidence * PATH_B_DISCOUNT  # 0.3
        weighted_sum += r.multiplier * w
        total_weight += w
    raw = weighted_sum / total_weight if total_weight > 0 else 1.0
    return max(0.7, min(1.3, raw))  # conservative production clamp
```

**Long-term:** `alpha_promotion.py` trains learned per-agent weights (Pearson correlation → weight, ensemble diversity bonus).

---

## Section 3: SwarmOrchestratorAgent

### 3.1 Service Identity

| Field | Value |
|-------|-------|
| File | `services/swarm_orchestrator_agent.py` |
| Class | `SwarmOrchestratorAgent` |
| Systemd | `indicagent-swarm-orchestrator` |
| Port | `:9127` (Prometheus) |
| Consumer groups | `swarm_bar_consumer` (intelligence.i1-i6) + `swarm_signal_consumer` (intelligence.signals) |
| Publishes to | `swarm.alpha.path_a`, `swarm.alpha.path_b`, `swarm.world_state` |

### 3.2 Two-Phase Publication

```
Signal arrives → Build SwarmContext (O(1) from cache)
                ↓
        [Path A: deterministic agents]
        asyncio.gather(agent.compute(ctx) for agent in path_a_agents)
        └─→ Publish swarm.alpha.path_a immediately (~5ms)
                ↓
        [Path B: LLM swarm agents — fire and forget]
        asyncio.gather(
            asyncio.wait_for(agent.compute(ctx), timeout=agent.latency_budget_ms/1000)
            for agent in path_b_agents
        )
        └─→ Publish swarm.alpha.path_b when complete (~5-60s async)
```

- Signal execution pipeline reads from `swarm.alpha.path_a` (fast path)
- `swarm.alpha.path_b` enriches shadow table for correlation analysis only
- `SwarmWriterAgent` subscribes to both topics independently

### 3.3 Context Cache

```python
class SwarmContextCache:
    """Thread-safe in-memory context cache. Bar loop populates, signal loop reads."""
    
    _TTL_SECONDS = 300  # 5 minutes
    
    # key: (symbol, timeframe) → (IntelligenceEvent, timestamp)
    _cache: dict[tuple[str, str], tuple[IntelligenceEvent, float]]
    
    def update(self, event: IntelligenceEvent) -> None: ...
    def build(self, symbol: str, tf: str, signal: RankedSignal) -> SwarmContext | None:
        """Returns None if cache entry is stale (>TTL) — caller logs warning and skips."""
        ...
```

### 3.4 State Recovery (World State)

- World state published to `swarm.world_state` (compacted Kafka topic, key=`{symbol}:{tf}`)
- On startup: `SwarmOrchestratorAgent` seeks to latest offset on `swarm.world_state` to rebuild cache
- Same pattern as existing `intelligence_pipeline_agent.py` state checkpointing
- Delta publishing: only publish when `hash(new_state) != hash(last_published_state)`

### 3.5 Signal Deduplication

```python
class BoundedLRUSet:
    """Deduplication set with bounded memory. Prevents reprocessing on Kafka redelivery."""
    
    def __init__(self, maxsize: int = 10_000): ...
    def add(self, key: str) -> bool: ...  # returns False if already seen
```

- Key: `f"{signal_id}:{path}"` (separate dedup for path_a and path_b)
- `OrderedDict`-based LRU eviction — evict oldest when `len > maxsize`

### 3.6 Backpressure

```python
# In bar_loop — skip stale bars under lag
consumer_lag = await _get_kafka_lag("swarm_bar_consumer", "intelligence.i1")
if consumer_lag > LAG_THRESHOLD_BARS:  # default: 50 bars
    logger.warning("swarm_backpressure", lag=consumer_lag)
    continue  # skip this bar update, let lag drain
```

### 3.7 All-Agents-Down Detection

- If all Path A agents are circuit-open: log `ERROR swarm_all_path_a_down`, emit Prometheus alert
- Do NOT halt signal pipeline — swarm is non-blocking
- Path A result falls back to `AlphaMultiplier(final=1.0, shadow_only=True)`

---

## Section 4: Safety Layer & Observability

### 4.1 SafeSwarmWrapper (corrected)

**Current problems:**
1. Wraps a callable, not an `IAlphaContributor` instance
2. Fallback hardcodes `path="deterministic"` (wrong for LLM agents)
3. No Prometheus metrics for violations

**Fixed design:**

```python
class SafeSwarmWrapper:
    """Wraps IAlphaContributor with safety guardrails and observability."""
    
    def __init__(self, contributor: IAlphaContributor):
        self._contributor = contributor
        self._circuit_breaker = PluginCircuitBreaker(
            config=CircuitBreakerConfig(failure_threshold=3, recovery_timeout=60)
        )  # per-agent instance — reuses src/core/plugin_circuit_breaker.py
    
    async def compute(self, context: SwarmContext) -> AgentResult:
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._contributor.compute(context),
                timeout=self._contributor.latency_budget_ms / 1000,
            )
            # Validate multiplier bounds
            if not (MIN_MULTIPLIER <= result.multiplier <= MAX_MULTIPLIER):
                SWARM_SAFETY_VIOLATIONS.labels(
                    agent_id=self._contributor.agent_id, violation="out_of_bounds"
                ).inc()
                return self._neutral(error="out_of_bounds")
            # Validate schema (Pydantic frozen model — already validated on construction)
            return result.model_copy(update={"latency_ms": (time.monotonic() - start) * 1000})
        
        except asyncio.TimeoutError:
            SWARM_SAFETY_VIOLATIONS.labels(
                agent_id=self._contributor.agent_id, violation="timeout"
            ).inc()
            return self._neutral(error="timeout")
        except ValidationError:
            SWARM_SAFETY_VIOLATIONS.labels(
                agent_id=self._contributor.agent_id, violation="schema_error"
            ).inc()
            return self._neutral(error="schema_error")
        except Exception as e:
            SWARM_SAFETY_VIOLATIONS.labels(
                agent_id=self._contributor.agent_id, violation="execution_error"
            ).inc()
            return self._neutral(error=str(e))
    
    def _neutral(self, error: str) -> AgentResult:
        return AgentResult(
            agent_id=self._contributor.agent_id,
            path=self._contributor.path,  # use contributor's actual path
            multiplier=1.0,
            confidence=0.0,
            shadow_only=True,
            error=error,
        )
```

### 4.2 SwarmMetrics (Golden Signals)

```python
# src/intelligence/swarm/metrics.py

# Traffic
SWARM_SIGNALS_PROCESSED = Counter("swarm_signals_processed_total", ["symbol", "tf"])
SWARM_AGENT_CALLS = Counter("swarm_agent_calls_total", ["agent_id", "path"])

# Latency
SWARM_AGENT_LATENCY = Histogram(
    "swarm_agent_latency_ms", ["agent_id", "path"],
    buckets=[1, 5, 10, 50, 100, 500, 1000, 5000, 30000]
)
SWARM_PATH_A_LATENCY = Histogram("swarm_path_a_total_latency_ms", buckets=[1, 5, 10, 50, 100])

# Errors
SWARM_SAFETY_VIOLATIONS = Counter(
    "swarm_safety_violations_total", ["agent_id", "violation"]
)
SWARM_CIRCUIT_BREAKER_OPEN = Gauge("swarm_circuit_breaker_open", ["agent_id"])

# Saturation
SWARM_CONTEXT_CACHE_SIZE = Gauge("swarm_context_cache_entries", ["symbol"])
SWARM_DEDUP_SET_SIZE = Gauge("swarm_dedup_set_size", ["path"])
SWARM_KAFKA_LAG = Gauge("swarm_kafka_consumer_lag", ["consumer_group"])
```

### 4.3 Prompt Template Security

```python
# src/intelligence/swarm/prompt_registry.py

_REGISTRY: dict[str, str] = {
    "skeptic_agent_v1": "...",
    "narrative_signal_v2": "...",
}

def get_prompt(template_id: str, **kwargs) -> str:
    """Bounded template lookup — no f-string injection from untrusted data."""
    template = _REGISTRY.get(template_id)
    if template is None:
        raise ValueError(f"Unknown prompt template: {template_id!r}")
    # Sanitize kwargs — strip control characters
    safe_kwargs = {k: _sanitize(str(v)) for k, v in kwargs.items()}
    return template.format_map(safe_kwargs)

def _sanitize(value: str) -> str:
    """Remove prompt injection characters."""
    return re.sub(r"[\x00-\x1f\x7f]", "", value)[:500]  # truncate at 500 chars
```

All LLM agents must call `get_prompt(template_id, **context_fields)` — never build prompts with raw f-strings from market data.

---

## Section 5: Module Structure

```
src/
├── core/
│   └── llm/                          # NEW — moved from src/intelligence/
│       ├── __init__.py               # exports: LLMProviderChain, LLMProvider
│       ├── providers.py              # MOVED from src/intelligence/llm_providers.py
│       │                             # EXTENDED: add call_type param, Kafka tracking
│       └── _archived_llm_providers.py  # stub with deprecation header
│
├── intelligence/
│   ├── llm_providers.py              # REPLACED by stub → import from src.core.llm
│   ├── narrative/                    # REFACTORED
│   │   ├── __init__.py
│   │   ├── prompts.py                # Pure functions — build_signal_prompt(), build_group_prompt()
│   │   ├── parsers.py                # Pure functions — parse_narrative_response()
│   │   ├── orchestrator.py           # NarrativeOrchestrator — uses LLMProviderChain
│   │   └── synthesizer.py            # GroupSynthesizer — multi-signal aggregation
│   └── swarm/
│       ├── __init__.py
│       ├── interface.py              # UPDATED — IAlphaContributor protocol (corrected)
│       ├── context.py                # NEW — SwarmContext, SwarmContextCache
│       ├── safety.py                 # UPDATED — wraps IAlphaContributor (corrected)
│       ├── registry.py               # UPDATED — DI, protocol validation, per-agent CB
│       ├── aggregator.py             # NEW — SwarmAggregator (confidence-weighted avg)
│       ├── metrics.py                # NEW — Golden Signals Prometheus metrics
│       ├── prompt_registry.py        # NEW — bounded template lookup, sanitization
│       └── agents/
│           ├── __init__.py
│           ├── contagion_agent.py    # STUB — update to use SwarmContext + AgentResult
│           ├── sweep_hunter.py       # STUB — update to use SwarmContext + AgentResult
│           ├── trend_vol.py          # STUB — update to use SwarmContext + AgentResult
│           └── narrative_agent.py    # STUB — update to use SwarmContext + AgentResult
│
services/
├── ai_narrative_agent.py             # NEW — thin coordinator (~200 lines)
├── swarm_orchestrator_agent.py       # NEW — SwarmOrchestratorAgent
├── swarm_writer_agent.py             # NEW — SwarmWriterAgent (shadow persistence)
└── _archived_ai_narrative_service.py # ARCHIVED — 1,327-line monolith

config/
└── intelligence_contributors.json    # UPDATED — add path, trigger, latency_budget_ms, shadow_only

migrations/
└── 058_alpha_multiplier_shadow.sql   # NEW — alpha_multiplier_shadow hypertable

scripts/
└── alpha_promotion.py                # EXTENDED — calibration, ensemble diversity, Pearson

src/core/
└── stream_keys.py                    # EXTENDED — topic_swarm_alpha_path_a/b(), topic_swarm_world_state()

production/systemd/
├── indicagent-swarm-orchestrator.service  # NEW
└── indicagent-swarm-writer.service        # NEW
```

---

## Section 6: Implementation Plans (7 Plans, 5 Waves)

### Wave 1 (Parallel — no shared files)

**Plan 56-01: LLM Infrastructure Move**
- Move `src/intelligence/llm_providers.py` → `src/core/llm/providers.py`
- Leave backward-compat stub at original path (import alias, deprecation header)
- Extend: add `call_type: str` param to `LLMChain.generate()`, publish to `llm.calls` Kafka topic
- Add `src/core/llm/__init__.py` with clean exports
- Tests: `tests/unit/test_llm_providers.py` (10 tests — circuit breaker, provider chain, Kafka tracking)

**Plan 56-02: Narrative Module Extraction**
- Create `src/intelligence/narrative/` — prompts, parsers, orchestrator, synthesizer
- All against real `IntelligenceEvent` + `BarIntelligenceRecord` schemas (not mock `.i1/.i4`)
- `NarrativeOrchestrator` uses `LLMProviderChain` from `src/core/llm/`
- Tests: `tests/unit/test_narrative_*.py` (10 tests — prompts, parsers, orchestrator, synthesizer)

### Wave 2 (Parallel — no shared files)

**Plan 56-03: Swarm Protocol + Schema Fixes**
- Update `IAlphaContributor`: `compute(SwarmContext) -> AgentResult` (remove `get_multiplier`)
- Add `SwarmContext`, `SwarmContextCache` to `src/intelligence/swarm/context.py`
- Extend `AgentResult` schema: add `path`, `shadow_only`, `latency_ms`, `error`
- Extend `AlphaMultiplier` schema: add `symbol`, `timeframe`, `path_a_multiplier`, `path_b_multiplier`, `production_multiplier`, `shadow_only`
- Update stub agents to new protocol (return `AgentResult`)
- Update `intelligence_contributors.json`: add `path`, `trigger`, `latency_budget_ms`, `shadow_only`
- Tests: `tests/unit/test_swarm_protocol.py` (8 tests)

**Plan 56-04: Safety + Aggregator + Metrics**
- Rewrite `SafeSwarmWrapper` to wrap `IAlphaContributor` instance (not callable)
- Add per-agent `PluginCircuitBreaker`
- Add `asyncio.wait_for` timeout enforcement
- Correct fallback path (use `contributor.path`)
- Create `SwarmAggregator` with confidence-weighted aggregation + conservative clamp
- Create `SwarmMetrics` (Golden Signals — 9 metrics)
- Create `PromptRegistry` with sanitization
- Tests: `tests/unit/test_swarm_safety.py` (8 tests)

### Wave 3 (Sequential — depends on 56-01, 56-02)

**Plan 56-05: Narrative Service Refactor**
- Write `services/ai_narrative_agent.py` (~200 lines) using `NarrativeOrchestrator`
- Archive `services/ai_narrative_service.py` → `_archived_ai_narrative_service.py`
- Update systemd unit
- Tests: `tests/unit/service_tests/test_ai_narrative_agent.py` (2 tests)

### Wave 4 (Sequential — depends on 56-03, 56-04)

**Plan 56-06: Swarm Infrastructure (DB + Stream Keys + Migration)**
- Add `topic_swarm_alpha_path_a()`, `topic_swarm_alpha_path_b()`, `topic_swarm_world_state()`, `topic_swarm_orchestrator_dlq()`, `topic_swarm_writer_dlq()` to `src/core/stream_keys.py`
- Write migration `migrations/058_alpha_multiplier_shadow.sql`:
  ```sql
  CREATE TABLE alpha_multiplier_shadow (
    ts TIMESTAMPTZ NOT NULL,
    signal_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    path TEXT NOT NULL,
    multiplier FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    shadow_only BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB,
    latency_ms FLOAT,
    error TEXT,
    -- populated later by alpha_promotion.py
    realized_pnl_r FLOAT,
    outcome TEXT
  );
  SELECT create_hypertable('alpha_multiplier_shadow', 'ts');
  CREATE INDEX ON alpha_multiplier_shadow (signal_id, agent_id);
  ```
- Tests: `tests/unit/test_stream_keys.py` additions (5 tests — 3 alpha/world-state + 2 DLQ topics)

### Wave 5 (Sequential — depends on 56-03, 56-04, 56-06)

**Plan 56-07: Swarm Services (Orchestrator + Writer)**
- Write `services/swarm_orchestrator_agent.py` — `SwarmOrchestratorAgent`
  - Two separate consumer tasks (bar_loop + signal_loop)
  - `SwarmContextCache` (5min TTL)
  - Two-phase publication (Path A immediate, Path B async)
  - `BoundedLRUSet` deduplication (10,000 entries)
  - World state delta publishing to compacted topic
  - Backpressure (lag > 50 bars → skip bar update)
  - DLQ publish to `swarm.orchestrator.dlq` on unresolvable `SwarmContext`
  - SIGTERM graceful drain
- Write `services/swarm_writer_agent.py` — `SwarmWriterAgent`
  - Subscribes to `swarm.alpha.path_a` + `swarm.alpha.path_b`
  - Batch writes to `alpha_multiplier_shadow` (same pattern as `signal_writer_agent.py`)
  - DLQ publish to `swarm.writer.dlq` on malformed payload or DB insert failure
  - SIGTERM graceful drain
- Write systemd units: `indicagent-swarm-orchestrator.service`, `indicagent-swarm-writer.service`
- Extend `scripts/alpha_promotion.py`: calibration curves, ensemble diversity, **regime segmentation** — Pearson computed per `(symbol, timeframe, hmm_regime)` cell; global correlation alone does not qualify for promotion
- Tests: `tests/unit/service_tests/test_swarm_orchestrator_agent.py` (4 tests)
         `tests/unit/service_tests/test_swarm_writer_agent.py` (2 tests)

---

## Wave Summary

| Wave | Plans | Parallel? | Gate |
|------|-------|-----------|------|
| 1 | 56-01, 56-02 | Yes | — |
| 2 | 56-03, 56-04 | Yes | — |
| 3 | 56-05 | No | 56-01 + 56-02 done |
| 4 | 56-06 | No | 56-03 + 56-04 done |
| 5 | 56-07 | No | 56-06 done |

**Total TDD tests:** ~47 (10 + 10 + 8 + 8 + 2 + 3 + 6 + 2 buffer)

---

## Success Criteria

1. `LLMProviderChain` lives in `src/core/llm/` — all imports updated
2. `ai_narrative_service.py` reduced from 1,327 → ~200 lines (archived, not deleted)
3. `IAlphaContributor.compute(SwarmContext)` is the contract — no `get_multiplier` callers remain
4. `SafeSwarmWrapper` wraps instances, reports violations to Prometheus
5. `SwarmOrchestratorAgent` runs as independent service, publishes Path A within 10ms
6. `alpha_multiplier_shadow` hypertable exists and receives writes
7. All shadow agents stay `shadow_only=True` until `alpha_promotion.py` promotes them per regime segment
8. DLQ topics exist for both services; unprocessable payloads routed there (not silently dropped)
9. 49 TDD tests pass, integration test confirms end-to-end flow

---

## What Phase 57 Builds (Next)

**SkepticAgent** — "What's wrong with this signal?"

- Implements `IAlphaContributor` protocol (from Phase 56 foundation)
- `path = "llm_swarm"`, `shadow_only = True` (validated before production)
- Prompt: given `SwarmContext` (winner, regime, confidence, CTF scores), ask LLM: "probability this signal fails?"
- Output: `AgentResult(multiplier=1-fail_prob, confidence=0.7)`
- Shadow validation: 7-14 days → compute Pearson(fail_prob, realized_pnl_r)
- Decision gate: ρ ≥ 0.4, n ≥ 30, p < 0.05 → promote; else kill

**Renaissance Principle:** The SkepticAgent is a hypothesis. Phase 56 builds the measurement apparatus. Phase 57 runs the first experiment.

---

## References

- **Swarm Manifest:** `docs/ideas/intelligence-swarm-manifest.md`
- **Renaissance I7/I8 Refinement:** `docs/ideas/renaissance-i7-i8-refinement.md`
- **Current swarm stubs:** `src/intelligence/swarm/`
- **Existing LLM infra:** `src/intelligence/llm_providers.py` (430 lines)
- **Phase 56 old plans:** `.planning/phases/56-ai-layer-refactor-v3/` (to be replaced)
- **ROADMAP:** `.planning/ROADMAP.md` (Phase 56 entry to be updated)
