<!-- generated-by: gsd-doc-writer -->
# Swarm Intelligence Architecture

> **Domain:** Intelligence — deep-dive companion to [`intelligence-ai.md`](../intelligence/intelligence-ai.md)

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27
**Code:** `src/core/ai/`, `src/intelligence/ai/`, `services/alpha_swarm_agent.py`

## Overview

The swarm intelligence layer is a Mixture of Agents (MoA) system where specialist AI agents evaluate trading signals from independent analytical dimensions. A composite agent — `AlphaSwarmComputeAgent` — orchestrates them the way a trading desk synthesizes input from specialists.

The swarm runs as an overlay on I7 signals. It never blocks signal execution. It produces a `swarm_multiplier` that adjusts signal confidence after the calibration chain.

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
| `prompt_version` | Auto-injected into `llm_calls` for prompt A/B testing |

Every agent gets: structured logging (structlog), OTel tracing, metrics, graceful SIGTERM/SIGINT shutdown, and automatic DLQ routing — all from the base class. Agents **must** use `self._llm_generate(context, ...)` — never `self._llm.generate()` directly. This auto-injects audit context (call_id, symbol, signal_id, regime, agent_id, prompt_version).

### BaseGroupService

Shared dispatcher (`src/core/ai/base_group_service.py`) that manages a group of agents:
- Provides Kafka consumer/producer, DB pool, `AIContextCache`, and `LLMProviderChain`
- Handles bar data updates and agent dispatch
- Agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`
- Runs graduation loop for auto-flipping `shadow_only` agents when statistical gates are met

### LineageRecorder

Unified signal lineage (`src/core/ai/lineage.py`):
- Records to `signal_lineage` Kafka topic (Kafka-first, not DB-first)
- Batch buffer with configurable size and flush interval
- Tracks: prompt version, model, inputs, outputs, timing, agent_id

---

## The Alpha Swarm: 5 Specialist Agents

| Agent | ID | Latency Budget | Analytical Dimension |
|-------|----|----|---------------------|
| **SkepticAgent** | `skeptic_v1` | 120s (LLM) | Counterfactual challenge — argues against every signal |
| **CorrelationAgent** | `correlation_v1` | 120s (LLM) | Cross-asset dependency — checks signal independence |
| **RegimeCoherenceAgent** | `regime_coherence_v1` | 120s (LLM) | Regime consistency — does the signal thesis match current regime? |
| **CounterfactualAgent** | `counterfactual_v1` | 120s (LLM) | Historical pattern — would similar setups have paid off? |
| **MLScorerAgent** | `ml_scorer_v1` | 50ms (local) | LightGBM score — local model, no LLM call |

Each LLM-based agent receives the full signal context via `AIContext` (typed tier data, only requested tiers populated), calls the LLM chain with a specialist prompt, and returns an `AgentOutput` with a multiplier and reasoning. `ml_scorer_v1` uses a local LightGBM model (no LLM call, 50ms budget).

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

Note: `calibrated_confidence` is null in Kafka signal payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")` when building swarm context.

---

## LLM Provider

The swarm uses a single provider: **Ollama Local** (gemma4:e4b default; `.env` may override via `OLLAMA_MODEL`). OpenRouter, DeepSeek, and OllamaCloud providers have been removed.

```python
# src/core/llm/chain.py — single provider
OllamaProvider → gemma4:e4b (default; .env OLLAMA_MODEL may override)
```

**gemma4:e4b JSON enforcement:** Outputs prose preamble without an explicit system message starting with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Also add `"Begin your response with { and end with }."` at end of user prompt.

**p50 latency:** ~47-52s with nemotron-3-nano:4b — well within the 120s budget. Live services `alpha_swarm` and `narrative_compute` hold persistent Ollama connections — kill them before swapping models or benchmarking.

---

## Shadow Governance

All swarm agents auto-enroll in the `shadow_registry` DB table at startup (idempotent via `ON CONFLICT DO NOTHING`). Shadow agents:
- Compute and record their analysis
- Produce `swarm_multiplier` values
- **Do not** affect `adjusted_confidence` in production signals

**Promotion gate:** `n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r) > 0.0`
**Demotion gate:** `EV[R] < -0.05` for 3 consecutive evaluation cycles

**Schema gate:** Swarm processing only runs on `signal_schema_version = 'v1'` signals — ensuring analysis quality matches signal quality.

---

## Database

**`swarm_agent_weights` table:**

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

- [CIS Scoring](cis-scoring.md) — calibration chain and confidence adjustment
- [Signal Lifecycle](signal-lifecycle.md) — what happens after signal fires
- [Evolvable AI](evolvable-ai.md) — evolutionary framework for agent improvement
- **Code:** `src/core/ai/base_agent.py`, `src/core/ai/base_group_service.py`, `src/intelligence/ai/alpha/`
