# Intelligence Swarm Architecture — Pre-Phase-80 Draft

**Archived:** 2026-05-05
**Original version:** 1.0.0
**Original last updated:** 2026-04-21
**Status:** Superseded future-idea draft. Preserved for Path A/Path B, MoA, and future-agent ideas.
**Current canonical swarm architecture:** `docs/intelligence/swarm-architecture.md`
**Current implementation plan:** `docs/plans/2026-05-05-swarm-intelligence-design.md`

> This document is archived because its implementation model (`SwarmOrchestratorAgent`,
> `SwarmWriterAgent`, `IAlphaContributor`, `SwarmContext`, `alpha_multiplier_shadow`,
> Path A/Path B topics) was superseded by the lineage-first alpha swarm architecture:
> `AlphaSwarmComputeAgent` → `LineageRecorder` → `LineageWriterAgent` → `signal_lineage`.
> The ideas here remain useful as future design material, but do not implement these
> names or persistence paths without a new plan.

---

## Overview

The Intelligence Swarm is a second analytical layer that runs asynchronously alongside the deterministic I1-I7 pipeline. Where the DAG computes signals in <10ms using mathematical plugins, the swarm evaluates each fired signal using specialist agents that reason about market context — producing an `AlphaMultiplier` that adjusts signal confidence after the fact, out-of-band, without ever blocking the hot path.

**The core pattern:** Multiple independent specialist agents analyze the same signal context. Each produces a quantified confidence-weighted multiplier. The `SwarmAggregator` synthesizes all contributions into a single `final_alpha_multiplier`. No single agent can dominate — the synthesis is confidence-weighted across the ensemble.

This is the genuine application of **Mixture-of-Agents (MoA)** in IndicAgent: independent LLM-reasoning proposers, aggregated into a single directional score, with statistical validation gates before any agent affects production decisions.

---

## Dual-Path Architecture

Every swarm contributor declares which path it operates on:

```text
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
    agent_id: str
    path: Literal["deterministic", "llm_swarm"]
    shadow_only: bool
    latency_budget_ms: float

    async def compute(self, context: SwarmContext) -> AgentResult:
        """Must not raise — return neutral AgentResult on any error."""

    async def warm_up(self) -> None:
        """Called once at service start — pre-load models, validate dependencies."""

    def health_check(self) -> dict[str, Any]:
        """Return health metadata for Prometheus scrape endpoint."""
```

**Rule:** `compute()` must never raise. The `SafeSwarmWrapper` enforces a hard timeout (`latency_budget_ms`) and catches all exceptions — returning a neutral `AgentResult` (`multiplier=1.0`, `confidence=0.0`) on any failure. A failing agent is invisible to the aggregator, not catastrophic.

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

    atr: float | None
    adx: float | None
    rsi: float | None

    hmm_regime: int | None
    trend_regime: float | None
    vol_regime: float | None
    garch_vol_ratio: float | None
    kalman_trend: float | None
    kalman_slope: float | None
    poc_price: float | None
    poc_price_rolling: float | None

    ctf_score: float | None
    ctf_trend_alignment: float | None
    ctf_regime_agreement: float | None
    ctf_fvg_alignment: float | None
    ctf_ob_alignment: float | None

    winner_plugin: str | None
    winner_direction: int | None
    winner_confidence: float | None

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
    path_a_multiplier: float | None
    path_b_multiplier: float | None
    contributors: dict[str, AgentResult]
    final_alpha_multiplier: float
    production_multiplier: float
    shadow_only: bool
```

**Aggregation logic:**

1. Path A contributors: confidence-weighted mean
2. Path B contributors: confidence-weighted mean, then discounted 30% (`_PATH_B_DISCOUNT = 0.3`)
3. Combined: weighted by total confidence across each path
4. `production_multiplier`: hard-clamped to `[0.7, 1.3]`

**Why the clamp matters:** LLM outputs are probabilistic. A hallucinated extreme multiplier (`0.0` or `5.0`) would corrupt signal quality. The `[0.7, 1.3]` production clamp is a hard architectural safety constraint, not a tunable parameter.

---

## SafeSwarmWrapper — Defense In Depth

Every contributor is wrapped in `SafeSwarmWrapper` before registration:

```python
self._contributors = [SafeSwarmWrapper(c) for c in contributors]
```

**What it enforces:**

- Hard timeout
- Exception isolation
- Neutral fallback
- Latency recording

A swarm agent that consistently times out or fails is operationally visible (Prometheus metrics, structured logs) but never architecturally disruptive.

---

## Data Flow

```text
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
| Shadow mode | `shadow_only=True` | Predictions written to `alpha_multiplier_shadow`; no effect on live signals |
| Correlation analysis | Daily automated job | `Pearson(agent_multiplier, realized_pnl_r)` |
| Promotion gate | `rho > 0.4` AND `N >= 100` AND `p < 0.05` over 14-day rolling window | `shadow_only` flipped to `False`; agent enters production |
| Continuous monitoring | Daily after promotion | Correlation checks continue |
| Degradation | `rho < 0.2` for 7 consecutive days | Agent auto-disabled, `shadow_only` reset to `True` |

This gate applies to every agent regardless of path. A deterministic Path A agent that passes the correlation gate is promoted alongside a Path B LLM agent — the mechanism is identical.

---

## Planned Swarm Agents

The swarm registry was planned with these future agents:

| Priority | Agent | Path | What it quantifies |
|----------|-------|------|-------------------|
| Phase 66 | SkepticAgent | Path B (LLM) | Counterfactual failure probability |
| S1 | Correlation Cluster | Path A | Cross-asset decorrelation from lead index |
| S2 | Volume Profile Validator | Path A | Signal proximity to high-density institutional zones |
| S3 | Liquidity Decay Arbiter | Path A | LOB dynamics → fill probability |
| S4 | SMC Trap Detector | Path A | Absorption pattern in order blocks |
| S5 | Macro Event Observer | Path B (LLM) | High-impact event proximity |
| S6 | Regime Sentinel | Path A | Regime transition probability |
| S7 | Volatility Arbiter | Path A | ATR expected move vs implied vol skew |

These remain useful future-agent ideas, but Phase 80 implements a different current substrate: `BaseMultiplierAgent` agents under `AlphaSwarmComputeAgent`, with lineage-first persistence.

---

## Infrastructure From This Superseded Draft

| Component | Former file | Former purpose |
|-----------|-------------|----------------|
| `SwarmOrchestratorComputeAgent` | `services/swarm_orchestrator_agent.py` | Bar + signal consumer; runs contributors; publishes `AlphaMultiplier` |
| `SwarmWriterAgent` | `services/swarm_writer_agent.py` | Consumes `topic_swarm_results`; batch-inserts to `alpha_multiplier_shadow` |
| `IAlphaContributor` | `src/core/agents/alpha_contributor.py` | Protocol all swarm agents implement |
| `SwarmContext` / `SwarmContextCache` | `src/intelligence/swarm/context.py` | Typed context passed to every agent |
| `SwarmAggregator` | `src/intelligence/swarm/aggregator.py` | Path A + Path B → `AlphaMultiplier` |
| `SafeSwarmWrapper` | `src/intelligence/swarm/safety.py` | Timeout + exception isolation |
| `SwarmRegistry` | `src/intelligence/swarm/registry.py` | Agent registration and discovery |

Current Phase 80 equivalent:

| Current component | Purpose |
|---|---|
| `AlphaSwarmComputeAgent` | Runs alpha agents on I7 signals and emits lineage |
| `BaseMultiplierAgent` | Shared multiplier-output base for alpha agents |
| `AIContext` / `AIContextCache` | Typed context passed to AI agents |
| `LineageRecorder` | Emits `agent_prediction` events |
| `LineageWriterAgent` | Persists `signal_lineage` |

