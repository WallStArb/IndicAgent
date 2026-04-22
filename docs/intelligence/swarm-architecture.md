# Intelligence Swarm Architecture

**Version:** 1.0.0
**Last Updated:** 2026-04-21
**Status:** Foundation operational (Phase 56). Swarm agents begin Phase 66 (SkepticAgent first).

---

## Overview

The Intelligence Swarm is a second analytical layer that runs asynchronously alongside the deterministic I1-I7 pipeline. Where the DAG computes signals in <10ms using mathematical plugins, the swarm evaluates each fired signal using specialist agents that reason about market context — producing an `AlphaMultiplier` that adjusts signal confidence after the fact, out-of-band, without ever blocking the hot path.

**The core pattern:** Multiple independent specialist agents analyze the same signal context. Each produces a quantified confidence-weighted multiplier. The `SwarmAggregator` synthesizes all contributions into a single `final_alpha_multiplier`. No single agent can dominate — the synthesis is confidence-weighted across the ensemble.

This is the genuine application of **Mixture-of-Agents (MoA)** in IndicAgent: independent LLM-reasoning proposers, aggregated into a single directional score, with statistical validation gates before any agent affects production decisions.

---

## Dual-Path Architecture

Every swarm contributor declares which path it operates on:

```
I7 signal fires
      │
      ▼
SwarmOrchestratorComputeAgent
      │
      ├── Path A: Deterministic contributors (asyncio.gather, parallel)
      │   • Fast, rule-based, no LLM
      │   • Uses SwarmContext from in-memory cache (no DB)
      │   • Results → topic_swarm_alpha_path_a
      │
      └── Path B: LLM Swarm contributors (async, out-of-band)
          • LLM reasoning per agent
          • Always shadow_only until promoted
          • Results → topic_swarm_results
                │
                ▼
          SwarmWriterAgent → alpha_multiplier_shadow (DB)
```

**Path A** is for deterministic, fast contributors — rule-based agents that can produce a multiplier in milliseconds using market data already in the `SwarmContextCache`. These can be promoted to production once validated.

**Path B** is for LLM-reasoning agents. Always starts in shadow mode. LLM outputs are probabilistic — no Path B agent affects production sizing until it has passed the statistical validation gate.

**Key invariant:** The swarm never blocks signal execution. The I7 winner is published to `intelligence.i7.signals` before the swarm runs. The `AlphaMultiplier` is applied downstream, after the fact.

---

## IAlphaContributor Protocol

Every swarm agent implements `IAlphaContributor` (`src/core/agents/alpha_contributor.py`):

```python
class IAlphaContributor(Protocol):
    agent_id: str                          # Unique identifier
    path: Literal["deterministic", "llm_swarm"]  # Execution path
    shadow_only: bool                      # True until statistically promoted
    latency_budget_ms: float               # Hard timeout enforced by SafeSwarmWrapper

    async def compute(self, context: SwarmContext) -> AgentResult:
        """Must not raise — return neutral AgentResult on any error."""

    async def warm_up(self) -> None:
        """Called once at service start — pre-load models, validate dependencies."""

    def health_check(self) -> dict[str, Any]:
        """Return health metadata for Prometheus scrape endpoint."""
```

**Rule:** `compute()` must never raise. The `SafeSwarmWrapper` enforces a hard timeout (`latency_budget_ms`) and catches all exceptions — returning a neutral `AgentResult` (multiplier=1.0, confidence=0.0) on any failure. A failing agent is invisible to the aggregator, not catastrophic.

---

## SwarmContext

Every agent receives a `SwarmContext` — a typed, immutable snapshot of the market state at the moment the signal fired. Built from the `SwarmContextCache` (populated by the bar loop), never from a DB query, never blocking.

```python
class SwarmContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal_id: UUID
    symbol: str
    timeframe: str
    ts: datetime

    # I1 indicators
    atr: float | None
    adx: float | None
    rsi: float | None

    # I4 regime context
    hmm_regime: int | None
    trend_regime: float | None
    vol_regime: float | None
    garch_vol_ratio: float | None
    kalman_trend: float | None
    kalman_slope: float | None
    poc_price: float | None
    poc_price_rolling: float | None

    # I6 cross-timeframe confluence
    ctf_score: float | None
    ctf_trend_alignment: float | None
    ctf_regime_agreement: float | None
    ctf_fvg_alignment: float | None
    ctf_ob_alignment: float | None

    # Winner signal
    winner_plugin: str | None
    winner_direction: int | None
    winner_confidence: float | None

    # Bar OHLCV
    price: float | None
    volume: float | None
```

`SwarmContextCache` TTL is 5 minutes — stale context returns `None` and the orchestrator skips the swarm for that signal.

---

## AlphaMultiplier — The Output Contract

```python
class AlphaMultiplier(BaseModel):
    signal_id: UUID
    symbol: str
    timeframe: str
    ts: datetime
    path_a_multiplier: float | None        # Confidence-weighted mean of Path A agents
    path_b_multiplier: float | None        # Confidence-weighted mean of Path B agents
    contributors: dict[str, AgentResult]   # Per-agent result keyed by agent_id
    final_alpha_multiplier: float          # Combined Path A + Path B (B discounted 30%)
    production_multiplier: float           # Clamped to [0.7, 1.3] for safety
    shadow_only: bool                      # True if any contributor is still in shadow
```

**Aggregation logic:**
1. Path A contributors: confidence-weighted mean
2. Path B contributors: confidence-weighted mean, then discounted 30% (`_PATH_B_DISCOUNT = 0.3`)
3. Combined: weighted by total confidence across each path
4. `production_multiplier`: hard-clamped to `[0.7, 1.3]` — no swarm agent can more than halve or double a signal's effective confidence

**Why the clamp matters:** LLM outputs are probabilistic. A hallucinated extreme multiplier (0.0 or 5.0) would corrupt signal quality. The `[0.7, 1.3]` production clamp is a hard architectural safety constraint, not a tunable parameter.

---

## SafeSwarmWrapper — Defense in Depth

Every contributor is wrapped in `SafeSwarmWrapper` before registration:

```python
self._contributors = [SafeSwarmWrapper(c) for c in contributors]
```

**What it enforces:**
- **Hard timeout:** `asyncio.wait_for(compute(), timeout=budget_ms/1000)` — timeout returns neutral result, never hangs the orchestrator
- **Exception isolation:** Any exception from `compute()` → neutral result + structured log, never propagates
- **Neutral fallback:** `multiplier=1.0, confidence=0.0` — a failing agent has zero weight in the aggregation
- **Latency recording:** Every call records `latency_ms` for Prometheus

A swarm agent that consistently times out or fails is operationally visible (Prometheus metrics, structured logs) but never architecturally disruptive.

---

## Data Flow

```
Bar arrives → SwarmContextCache.update(IntelligenceEvent)   [bar loop]

I7 signal fires → topic_intelligence_i7_signals             [signal loop]
      │
      ▼
SwarmOrchestratorComputeAgent.build_context(signal)
      │
      ├── asyncio.gather(*[agent.run(context) for agent in path_a_agents])
      │         ↓
      │   path_a_results: list[AgentResult]
      │
      ├── asyncio.gather(*[agent.run(context) for agent in path_b_agents])
      │         ↓
      │   path_b_results: list[AgentResult]
      │
      ▼
SwarmAggregator.aggregate(path_a_results, path_b_results)
      │
      ├── → topic_swarm_alpha_path_a (AlphaMultiplier)
      └── → topic_swarm_results (AgentResult per contributor, fan-out)
                  │
                  ▼
          SwarmWriterAgent → alpha_multiplier_shadow (DB)
```

---

## Shadow-First Validation Gate

No swarm agent affects production signal confidence until it passes the correlation gate:

| Step | Condition | Action |
|------|-----------|--------|
| **Shadow mode** | `shadow_only=True` (default) | Predictions written to `alpha_multiplier_shadow`; no effect on live signals |
| **Correlation analysis** | Daily automated job | `Pearson(agent_multiplier, realized_pnl_r)` |
| **Promotion gate** | `ρ > 0.4` AND `N ≥ 100` AND `p < 0.05` over 14-day rolling window | `shadow_only` flipped to `False`; agent enters production |
| **Continuous monitoring** | Daily after promotion | Correlation checks continue |
| **Degradation** | `ρ < 0.2` for 7 consecutive days | Agent auto-disabled, `shadow_only` reset to `True` |

This gate applies to every agent regardless of path. A deterministic Path A agent that passes the correlation gate is promoted alongside a Path B LLM agent — the mechanism is identical.

---

## Planned Swarm Agents

The swarm registry is currently populated with dummy contributors for integration testing. Real agents begin Phase 66:

| Priority | Agent | Path | What it quantifies |
|----------|-------|------|-------------------|
| **Phase 66** | SkepticAgent | Path B (LLM) | Counterfactual failure probability — "given this market state, what's the probability this signal fails?" |
| S1 | Correlation Cluster | Path A | Cross-asset decorrelation from lead index (ES/NQ spread) |
| S2 | Volume Profile Validator | Path A | Signal proximity to high-density institutional zones (POC, HVN) |
| S3 | Liquidity Decay Arbiter | Path A | LOB dynamics → fill probability → `LOB_Friction_Score` |
| S4 | SMC Trap Detector | Path A | Absorption pattern in order blocks — declining volume inside OB = liquidity hunt |
| S5 | Macro Event Observer | Path B (LLM) | High-impact event proximity (FOMC, CPI) → confidence adjustment |
| S6 | Regime Sentinel | Path A | Latent manifold projection (Entropy, Dispersion, Momentum) → `RegimeTransitionProbability` |
| S7 | Volatility Arbiter | Path A | ATR expected move vs. implied vol skew → compression/expansion state |

**Adding a new agent:**
1. Implement `IAlphaContributor` protocol
2. Set `path`, `shadow_only=True`, `latency_budget_ms`
3. Register in `SwarmOrchestratorComputeAgent` contributors list
4. Write unit test using `SwarmContext` fixture
5. Monitor `alpha_multiplier_shadow` for correlation signal

---

## Infrastructure

| Component | File | Purpose |
|-----------|------|---------|
| `SwarmOrchestratorComputeAgent` | `services/swarm_orchestrator_agent.py` | Bar + signal consumer; runs contributors; publishes `AlphaMultiplier` |
| `SwarmWriterAgent` | `services/swarm_writer_agent.py` | Consumes `topic_swarm_results`; batch-inserts to `alpha_multiplier_shadow` |
| `IAlphaContributor` | `src/core/agents/alpha_contributor.py` | Protocol all swarm agents implement |
| `SwarmContext` / `SwarmContextCache` | `src/intelligence/swarm/context.py` | Typed context passed to every agent; TTL-keyed in-memory cache |
| `SwarmAggregator` | `src/intelligence/swarm/aggregator.py` | Path A + Path B → `AlphaMultiplier` |
| `SafeSwarmWrapper` | `src/intelligence/swarm/safety.py` | Timeout + exception isolation around every contributor |
| `SwarmRegistry` | `src/intelligence/swarm/registry.py` | Agent registration and discovery |

**Metrics port:** `SwarmOrchestratorComputeAgent` — `:9134` (see `docs/architecture/observability.md`)

**DB table:** `alpha_multiplier_shadow` — one row per `(signal_id, agent_id)`; `ON CONFLICT DO NOTHING` (idempotent)

---

## See Also

- `docs/ideas/intelligence-swarm-manifest.md` — Detailed swarm design and agent specifications
- `docs/intelligence/ai-intelligence-architecture.md` — Full I1-I8 pipeline architecture
- `docs/architecture/agent-standard.md` — Agent role taxonomy
- `src/intelligence/swarm/` — All swarm infrastructure source
- `src/core/agents/alpha_contributor.py` — `IAlphaContributor` protocol
