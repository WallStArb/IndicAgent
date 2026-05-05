# Plan: Renaissance Swarm Intelligence Layer

**Date:** 2026-05-05
**Status:** Approved — pending implementation plan
**Supersedes:** `docs/ideas/agent-orchestration-patterns.md` (March 2026 draft — framed as post-MLAgent; this design is the current canonical target)
**Related:** `docs/ideas/ai-integration-paths.md`, `docs/plans/2026-05-02-unified-intelligence-design.md`

---

## Executive Summary

Expand the alpha swarm from a single devil's advocate agent (Skeptic) into a multi-agent intelligence overlay that produces an outcome-learned, regime-segmented confidence multiplier on every qualifying signal. Each agent is independently measurable, shadow-gated, and contributes orthogonal information the quant pipeline cannot produce mechanically. Weights are earned through proof — Spearman correlation against realized `pnl_r` — never set by intuition.

The swarm is an async enrichment layer. It never blocks signal publication.

---

## Renaissance Alignment

| Principle | How This Design Satisfies It |
|---|---|
| Instrument everything | Per-agent multiplier, stated confidence, and calibration error logged in `llm_calls` from day one |
| Earn the right through proof | Shadow-only by default; graduation requires n ≥ 100 AND bootstrap_ci_lower(pnl_r) > 0.0 |
| Segment relentlessly | Weights learned per `(agent_id, timeframe)` — what works on 15m may not work on 1h |
| Degrade gracefully, adapt automatically | Graduation loop demotes underperforming agents; weight floor prevents full zeroing |
| Let the system run | Single TF gate, no manual routing, no per-signal decisions |
| Data quality over model complexity | Weighted average with learned weights beats complex routing built on intuition |
| Never drop data that could contain signal | `stated_confidence` logged per agent; calibration error computed; data exists before it's needed |

---

## Architecture

### Role in the Pipeline

```
intelligence.i7.signals
        │
        ▼
  AlphaSwarmAgent (dispatch)
        │
   [Gate 1: timeframe_minutes >= SWARM_MIN_TF_MINUTES (default 5)]
   [Gate 2: signal_schema_version == "v1"]
        │
   asyncio.gather() — all agents in parallel
   ┌──────────┬────────────┬──────────────────┬─────────────────┐
   │          │            │                  │                 │
Skeptic  Correlation  RegimeCoherence  Counterfactual   (future agents)
   │          │            │                  │                 │
   └──────────┴────────────┴──────────────────┴─────────────────┘
                     weight aggregator
               Σ(wᵢ × mᵢ) / Σ(wᵢ)  [normalized]
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
   signal_ledger                    llm_calls
   adjusted_confidence          (one row per agent)
   swarm_multiplier
   swarm_agent_count
```

### What the Swarm Is Not

- Not on the hot path — signal is published before swarm starts
- Not a veto layer — it never suppresses signal publication
- Not a routing layer — no per-agent conditional logic in dispatch
- Not a replacement for I1-I7 — it synthesizes tier outputs that quant cannot reason over holistically

### Relation to `intelligence.journal`

`intelligence.journal` is the canonical per-bar fan-out bus feeding `feature_writer`, `feature_snapshot_writer`, and the SSE dashboard. The swarm does not subscribe to it. Full I1-I7 context reaches agents via `AIContextCache.build()` reading `intelligence_features` at dispatch time — no additional topic subscription needed.

---

## Inheritance Chain

```
BaseAgent (lifecycle, logging, OTel)
    └── BaseAIAgent (timing, timeout, error safety, metrics)
            └── BaseMultiplierAgent  ← NEW: src/core/ai/multiplier_agent.py
                    ├── SkepticAgentComputeAgent       (refactored)
                    ├── CorrelationAgentComputeAgent    (new)
                    ├── RegimeCoherenceAgentComputeAgent (new)
                    └── CounterfactualAgentComputeAgent (new)
```

`BaseMultiplierAgent` provides:
- `_parse_multiplier_response(raw, validator_fn)` — try direct JSON parse → regex fallback → `None`
- `_build_multiplier_output(multiplier, confidence, payload, prompt_version)` — canonical `AgentOutput` construction with multiplier clamped to `[0.0, 2.0]`
- Abstract `output_schema: ClassVar[dict]` — expected LLM JSON keys, used in parse failure logging

All agents start `shadow_only = True`. The graduation loop flips this individually per agent.

---

## Shared Utilities

### `src/core/ai/prompt_utils.py` additions

| Addition | Purpose |
|---|---|
| `JSON_BLOCK_RE` | Compiled `\{[^{}]*\}` regex — moved from `skeptic_agent.py`, single source of truth |
| `parse_llm_json(raw, validator_fn)` | Try direct parse → regex extract fallback → `None` on failure |
| `clamp(val, lo, hi)` | `max(lo, min(hi, float(val)))` — used in every agent validator |

Existing `DIRECTION_LABELS`, `REGIME_LABELS`, `fmt()` unchanged.

---

## Agent Contracts

All four agents output one thing: a multiplier in `[0.0, 2.0]`. Floats clamped `[0.0, 1.0]` before formula.

### Skeptic (refactored from existing)

**Orthogonal value:** Holistic failure probability across all tiers — synthesizes what quant measures individually into a unified "will this fail?" judgment.

```json
{"failure_probability": float, "confidence": float, "risk_factors": [str], "reasoning": str}
```

`multiplier = (1.0 - failure_probability) × confidence`
`tiers_needed = {I1, I4, I6, I7, SMC}`

---

### Correlation

**Orthogonal value:** Cross-asset coherence — does ZN/VIX/ES behavior support or contradict this signal? I6 has `corr_z` scores but cannot reason about the *meaning* of correlation breakdowns.

```json
{"coherence_score": float, "confidence": float, "contradicting_assets": [str], "reasoning": str}
```

`multiplier = coherence_score × confidence`
`tiers_needed = {I1, I4, I6, I7}`

---

### RegimeCoherence

**Orthogonal value:** Setup type vs regime fit — is a mean-reversion signal firing in a strong trend? I4 classifies regime; LLM judges whether the *setup type* is appropriate for that regime.

```json
{"regime_fit": float, "confidence": float, "mismatches": [str], "reasoning": str}
```

`multiplier = regime_fit × confidence`
`tiers_needed = {I4, I7, SMC}`

---

### Counterfactual

**Orthogonal value:** Validation path reasoning — "what needs to be true for this to work, and is each condition plausible?" No quant equivalent exists for this.

```json
{
  "plausibility": float,
  "confidence": float,
  "validation_conditions": [str],
  "invalidation_conditions": [str],
  "reasoning": str
}
```

`multiplier = plausibility × confidence`
`tiers_needed = {I1, I4, I7}`

---

## Dispatch Layer

### `services/alpha_swarm_agent.py` changes

Agent registration is a typed list — adding an agent is one line, no other dispatch code changes:

```python
self._agents: list[BaseMultiplierAgent] = [
    SkepticAgentComputeAgent(llm_chain=self._llm_chain),
    CorrelationAgentComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceAgentComputeAgent(llm_chain=self._llm_chain),
    CounterfactualAgentComputeAgent(llm_chain=self._llm_chain),
]
```

Dispatch loop, weight aggregation, shadow enrollment, and graduation calls are all driven by `self._agents` — no per-agent conditional logic in dispatch.

### Aggregation

```
final_multiplier = Σ(wᵢ × mᵢ) / Σ(wᵢ)   [normalized weighted average]
```

Default weight `1/N` (equal) until `sample_size >= SWARM_WEIGHT_MIN_SAMPLES`. Weights loaded from `swarm_agent_weights` at dispatch time (cached, refreshed each graduation cycle).

---

## Weight Learning

### `swarm_agent_weights` table

```sql
CREATE TABLE swarm_agent_weights (
    agent_id          TEXT        NOT NULL,
    timeframe         TEXT        NOT NULL,
    weight            FLOAT       NOT NULL DEFAULT 1.0,
    sample_size       INT         NOT NULL DEFAULT 0,
    spearman_rho      FLOAT,
    calibration_error FLOAT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, timeframe)
);
```

`calibration_error = |stated_confidence - empirical_win_rate|` — logged from day one, not acted on until sufficient N.

### Update rule (runs each graduation cycle, ~15 min)

```
1. Query llm_calls JOIN signal_ledger ON signal_id
   WHERE outcome IS NOT NULL AND llm_calls.created_at > NOW() - INTERVAL '30 days'
2. Compute Spearman(multiplier, pnl_r) per (agent_id, timeframe)
3. weight = max(WEIGHT_FLOOR, 0.5 + spearman_rho)
     rho = 0   → weight 0.5 (neutral)
     rho = 1   → weight 1.5 (boosted)
     rho = -1  → weight floor (0.05)
4. Renormalize weights across active agents (sum preserved)
5. Update sample_size, spearman_rho, calibration_error, updated_at
```

### Demotion

Existing graduation loop handles demotion when `EV[R] < -0.05` for 3 consecutive cycles → agent returns to `shadow_only = True`. Weight floor (0.05) prevents an agent from being fully silenced before formal demotion.

---

## Database Changes

### `signal_ledger` additions

```sql
ALTER TABLE signal_ledger ADD COLUMN adjusted_confidence  FLOAT;
ALTER TABLE signal_ledger ADD COLUMN swarm_multiplier     FLOAT;
ALTER TABLE signal_ledger ADD COLUMN swarm_agent_count    INT;
```

`adjusted_confidence = original_confidence × swarm_multiplier`. Original confidence column untouched — quant pipeline output is never overwritten.

### Migration file

`migrations/NNN_swarm_weights_and_adjusted_confidence.sql`

---

## Settings

All configurable via `src/config/settings.py`:

```python
SWARM_MIN_TF_MINUTES: int = 5        # gate: don't run on 1m
SWARM_WEIGHT_MIN_SAMPLES: int = 30   # samples before weight learning activates
SWARM_WEIGHT_FLOOR: float = 0.05     # minimum weight before formal demotion
```

---

## Observability

New Prometheus metrics registered via `src/observability/metrics.py`:

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `swarm_invocations_total` | Counter | `agent_id, timeframe, status` | Per-agent call rate + error rate |
| `swarm_multiplier_distribution` | Histogram | `agent_id` | Per-agent output distribution over time |
| `swarm_aggregated_multiplier` | Histogram | `timeframe` | Final combined multiplier distribution |
| `swarm_agent_weight` | Gauge | `agent_id, timeframe` | Weight drift — key Renaissance health signal |

`swarm_agent_weight` gauge is the primary diagnostic: Grafana shows exactly when the system learns an agent adds or destroys value, segmented by TF.

---

## File Map

### New files
```
src/core/ai/multiplier_agent.py
src/intelligence/ai/alpha/correlation_agent.py
src/intelligence/ai/alpha/correlation_prompts.py
src/intelligence/ai/alpha/regime_coherence_agent.py
src/intelligence/ai/alpha/regime_coherence_prompts.py
src/intelligence/ai/alpha/counterfactual_agent.py
src/intelligence/ai/alpha/counterfactual_prompts.py
migrations/NNN_swarm_weights_and_adjusted_confidence.sql
```

### Modified files
```
src/core/ai/prompt_utils.py               ← add JSON_BLOCK_RE, parse_llm_json, clamp
src/intelligence/ai/alpha/skeptic_agent.py ← extend BaseMultiplierAgent, import shared utils
src/intelligence/ai/TEMPLATE_agent.py      ← update to show BaseMultiplierAgent pattern
services/alpha_swarm_agent.py              ← TF gate, typed agent list, weight aggregation
services/service_auditor_agent.py          ← _DAG_ORDER if needed
src/config/settings.py                    ← SWARM_* settings
src/observability/metrics.py              ← new swarm metrics
```

---

## Future Agents (not in this phase)

The following agents are natural extensions once the substrate is in place:

| Agent | Dependency | Orthogonal value |
|---|---|---|
| MacroContextAgent | `ctx` substrate (P-CTX-01) | Catalyst/risk event awareness in next N hours |
| NewsContextAgent | `ctx` substrate + news lane | Sentiment shift risk |
| VolatilitySurfaceAgent | DerivAgent / options data | GEX/VANNA regime context |

All will extend `BaseMultiplierAgent` and register in `self._agents` with zero dispatch changes.

---

## What This Design Explicitly Defers

- **MoA (Mixture-of-Agents) proposer/aggregator pattern** — valid future evolution, premature before outcome data proves N-agent weighted average is a bottleneck
- **Adversarial red team** — Skeptic is already the "bear case"; full bull/bear debate requires sufficient agent diversity first
- **Dynamic leadership / regime-conditional agent routing** — let the learned weights handle this; manual routing adds maintenance burden the data can eliminate
- **LLM confidence calibration correction** — data is captured from day one; act when N is sufficient
