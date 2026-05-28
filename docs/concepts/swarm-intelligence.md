# Swarm Intelligence Architecture

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-10
**Code:** `src/core/ai/`, `src/intelligence/ai/`, `services/alpha_swarm_agent.py`

## Overview

The swarm intelligence layer is a Mixture of Agents (MoA) system where specialist AI agents evaluate trading signals from independent analytical dimensions. A composite agent — `AlphaSwarmComputeAgent` — orchestrates them the way a trading desk synthesizes input from specialists.

The swarm runs as an overlay on Path A signals. It never blocks signal execution. It produces a `swarm_multiplier` that adjusts signal confidence after the calibration chain.

---

## Agent Framework

### BaseAIAgent

Universal base class (`src/core/ai/base_agent.py`) for all AI agents:

| Attribute | Purpose |
|-----------|---------|
| `agent_id` | Unique identifier (e.g., `skeptic_v1`) |
| `group` | Agent group membership (`alpha`, `narrative`, `risk`) |
| `tiers_needed` | Which intelligence tiers to load into context |
| `latency_budget_ms` | Wall-clock timeout (default: 5000ms) |
| `shadow_only` | Start in shadow mode — no production impact |

Every agent gets: structured logging (structlog), OTel tracing, Prometheus metrics, graceful SIGTERM/SIGINT shutdown, and automatic DLQ routing — all from the base class.

### BaseGroupService

Shared dispatcher (`src/core/ai/base_group_service.py`) that manages a group of agents:
- Provides Kafka consumer/producer, DB pool, `AIContextCache`, and `LLMProviderChain`
- Handles bar data updates and agent dispatch
- Runs graduation loop for auto-flipping `shadow_only` agents when statistical gates are met

### LineageRecorder

Unified signal lineage (`src/core/ai/lineage.py`):
- Records to `signal_lineage` Kafka topic (Kafka-first, not DB-first)
- Batch buffer with configurable size and flush interval
- Tracks: prompt version, model, inputs, outputs, timing, agent_id
- Events: `transform`, `agent_prediction`, `lifecycle`

---

## The Alpha Swarm: 4 Specialist Agents

| Agent | ID | Analytical Dimension |
|-------|----|--------------------|
| **SkepticAgent** | `skeptic_v1` | Counterfactual challenge — argues against every signal, looking for reasons it will fail |
| **CorrelationAgent** | `correlation_v1` | Cross-asset dependency — checks whether the signal is genuinely independent or a restating of correlated positions |
| **RegimeCoherenceAgent** | `regime_coherence_v1` | Regime consistency — does the signal's thesis match the current regime classification? |
| **CounterfactualAgent** | `counterfactual_v1` | Historical pattern — would similar setups in recent history have paid off? |

Each agent:
- Receives the full signal context via `AIContext` (typed tier data, only requested tiers populated)
- Calls the LLM chain with a specialist prompt
- Returns an `AgentOutput` with a multiplier and reasoning
- Is tracked by `LineageRecorder` for full reproducibility

---

## Mixture of Agents Composition

The `AlphaSwarmComputeAgent` combines specialist outputs using **per-agent learned weights**:

```
swarm_multiplier = Σ (agent_output × agent_weight)
```

Weights are learned from a 30-day rolling Spearman correlation between each agent's multiplier and actual signal outcomes. The system adapts automatically:

- Agents producing useful analysis → higher weight → more influence
- Agents producing noisy or uncorrelated analysis → lower weight → less influence
- Agent timeout or error → contribution defaults to `1.0` (neutral) — graceful degradation

The final multiplier is range-clamped to `[0.0, 2.0]` and applied as:
```
adjusted_confidence = calibrated_confidence × swarm_multiplier
```

---

## Multi-Provider LLM Chain

Agents are not bound to a single LLM. The provider chain (`src/core/llm/chain.py`) runs in priority order:

| Priority | Provider | Models | Circuit Breaker |
|----------|----------|--------|----------------|
| 1 | OpenRouter | Free model catalogue | 3 failures → open 5 min |
| 2 | DeepSeek | `deepseek-v4-flash` ($0.14/1M in) | 3 failures → open 5 min |
| 3 | Ollama Cloud | minimax-m2.7, gemini-3-flash-preview | 3 failures → open 5 min |
| 4 | Ollama Local | gemma4:e4b (AMD ROCm GPU) | 5 failures → open 1 min |

Each provider has an independent circuit breaker. If OpenRouter goes down, DeepSeek takes over seamlessly. If all remote providers fail, local Ollama serves as the offline fallback.

---

## Shadow Governance

All swarm agents auto-enroll in shadow mode at startup (`shadow_registry` DB table). Shadow agents:
- Compute and record their analysis
- Produce `swarm_multiplier` values
- **Do not** affect `adjusted_confidence` in production signals

**Promotion gate:** Agent weight must show statistically significant correlation with signal outcomes over a sufficient sample. The graduation loop in `BaseGroupService` checks periodically and auto-promotes when criteria are met.

**Schema gate:** Swarm processing only runs on `signal_schema_version = 'v1'` signals — ensuring analysis quality matches signal quality.

---

## Database

**`swarm_agent_weights` table** (migration `082_swarm_weights_and_adjusted_confidence.sql`):

| Column | Type | Purpose |
|--------|------|---------|
| `agent_id` | TEXT | Agent identifier (e.g., `skeptic_v1`) |
| `timeframe` | TEXT | Per-timeframe weight |
| `weight` | FLOAT | Learned weight from Spearman correlation |
| `sample_size` | INTEGER | Number of resolved signals in window |
| `spearman_rho` | FLOAT | Correlation coefficient |
| `calibration_error` | FLOAT | Calibration quality metric |
| `updated_at` | TIMESTAMPTZ | Last recalculation |

**`signal_ledger` additions:** `swarm_multiplier`, `adjusted_confidence`, `swarm_agent_count` — recorded per signal for full audit trail.

---

## Related Documentation

- [Architecture Concepts](../architecture/concepts.md) — Dual-Path Intelligence Architecture
- [CIS Scoring](cis-scoring.md) — calibration chain and confidence adjustment
- [Signal Lifecycle](signal-lifecycle.md) — what happens after signal fires
- [Evolvable AI](evolvable-ai.md) — evolutionary framework for agent improvement
- **Code:** `src/core/ai/base_agent.py`, `src/core/ai/base_group_service.py`, `src/intelligence/ai/alpha/`
