# Intelligence Swarm Architecture

**Version:** 2.0.0
**Last Updated:** 2026-05-05
**Status:** Current target — lineage-first alpha swarm, Phase 80 planned
**Canonical plan:** `docs/plans/2026-05-05-swarm-intelligence-design.md`

---

## Overview

The alpha swarm is an async intelligence overlay for I7 signals. It runs after signal publication, never blocks the hot I1-I7 pipeline, and records every agent prediction for outcome-based evaluation.

The current architecture is lineage-first:

```text
intelligence.i7.signals
  -> AlphaSwarmComputeAgent
       -> BaseMultiplierAgent subclasses
       -> LineageRecorder
       -> topic_signal_lineage()
  -> LineageWriterAgent
       -> signal_lineage
  -> writer-owned projection
       -> signal_ledger.adjusted_confidence
       -> signal_ledger.swarm_multiplier
       -> signal_ledger.swarm_agent_count
```

`signal_lineage` is the canonical audit trail for swarm predictions. `signal_ledger` swarm columns are derived projections for query/API convenience.

---

## Agent Contract

Swarm agents are pure compute objects, not persistence services. They extend `BaseMultiplierAgent`, which extends `BaseAIAgent`.

Required class attributes:

| Attribute | Rule |
|---|---|
| `agent_id` | Stable `<concept>_v<N>` identifier; must match `shadow_registry.component_name`. |
| `group` | `"alpha"` for Phase 80 agents. |
| `tiers_needed` | `frozenset[Tier]`; drives `AIContextCache.build()`. |
| `latency_budget_ms` | Hard timeout budget. |
| `shadow_only` | Starts `True`; runtime state is refreshed from `shadow_registry`. |

Each agent returns an `AgentOutput` with `output_type="multiplier"` and a payload containing:

- `multiplier`
- `confidence`
- `prompt_version`
- agent-specific validated fields
- parse/validation status when available

Phase 80 is discount-only: agent formulas may reduce confidence but should not boost above `1.0` until sufficient outcome data proves positive edge.

---

## Phase 80 Agents

| Agent | Class | Purpose |
|---|---|---|
| Skeptic | `SkepticAgentComputeAgent` | Estimates holistic failure probability. |
| Correlation | `CorrelationAgentComputeAgent` | Judges cross-asset coherence. |
| RegimeCoherence | `RegimeCoherenceAgentComputeAgent` | Checks setup type against current regime. |
| Counterfactual | `CounterfactualAgentComputeAgent` | Tests what must be true for the signal to work. |

All start shadow-only and keep writing lineage whether shadow or live.

---

## Future Agent Backlog

The pre-Phase-80 swarm plan contained useful agent ideas. They remain valid, but should be implemented on the current `BaseMultiplierAgent` + `AIContext` + `signal_lineage` substrate rather than the old Path A/Path B / `alpha_multiplier_shadow` model.

| Candidate | Former path | Current implementation shape | What it quantifies |
|---|---|---|---|
| Skeptic | LLM | Phase 80 `SkepticAgentComputeAgent` | Counterfactual failure probability: "given this market state, what's the probability this signal fails?" |
| Correlation Cluster | Deterministic | Phase 80 `CorrelationAgentComputeAgent` first; deterministic variant can follow if rules prove enough | Cross-asset decorrelation from lead index (ES/NQ spread), ZN/VIX/CL coherence |
| Volume Profile Validator | Deterministic | Future `VolumeProfileAgentComputeAgent` or deterministic multiplier component | Signal proximity to high-density institutional zones (POC, HVN, VAH/VAL) |
| Liquidity Decay Arbiter | Deterministic | Future microstructure agent once order book/depth substrate exists | LOB dynamics, fill probability, liquidity friction score |
| SMC Trap Detector | Deterministic | Future SMC-focused multiplier agent | Absorption patterns in order blocks; declining volume inside OB as liquidity hunt |
| Macro Event Observer | LLM/context | Future `MacroContextAgent` after ctx substrate | High-impact event proximity (FOMC, CPI) and catalyst risk |
| Regime Sentinel | Deterministic/LLM hybrid | Future regime transition agent once enough transition labels exist | Latent regime transition probability from entropy, dispersion, momentum |
| Volatility Arbiter | Deterministic | Future DerivAgent/options-dependent agent | ATR expected move vs implied vol skew; compression/expansion state |

Promotion rules stay the same for all future agents: shadow-first, lineage always written, segment-local graduation, cost-aware evaluation, and writer-owned persistence.

---

## Separation Of Concerns

`AlphaSwarmComputeAgent` owns:

- consuming I7 signal triggers
- building `AIContext`
- running agents in parallel
- aggregating eligible outputs
- emitting lineage and aggregate adjustment events
- metrics for invocation, latency, parse status, capacity skips, and multipliers

`AlphaSwarmComputeAgent` must not write to TimescaleDB directly.

Writer ownership:

| Fact | Canonical owner |
|---|---|
| Per-agent prediction lineage | `LineageWriterAgent` writes `signal_lineage`. |
| Swarm projection on ledger | Writer-owned projection updates `signal_ledger` swarm columns. |
| LLM prompt/response audit | `LLMWriterAgent` writes `llm_calls`; direct swarm writes are deferred. |
| Shadow state and weights | Writer-owned registry/weight updates from evaluation recommendations. |

---

## Persistence Model

Each agent writes one lineage event per signal:

```json
{
  "event_type": "agent_prediction",
  "source": "correlation_v1",
  "multiplier": 0.68,
  "metadata": {
    "segment_key": "2.15m",
    "confidence": 0.72,
    "prompt_version": "correlation_v1",
    "group": "alpha",
    "payload": {
      "multiplier": 0.68,
      "confidence": 0.72,
      "reasoning": "..."
    }
  }
}
```

`llm_calls` remains the audit table for prompt/response/model/provider records. A future phase may link swarm lineage to `llm_calls`, but Phase 80 does not require direct swarm-specific `llm_calls` writes.

---

## Graduation Governance

Shadow/live controls whether an agent can affect production confidence. It does not control whether the agent writes predictions. All agents continue writing lineage in both modes.

The target governance DAG is:

```text
AlphaSwarmComputeAgent
  -> signal_lineage events

LineageWriterAgent
  -> signal_lineage table

SwarmEvaluationComputeAgent
  -> resolved lineage JOIN signal_ledger outcomes
  -> promotion/demotion/weight recommendations

Writer-owned registry update
  -> shadow_registry
  -> swarm_agent_weights
  -> transition audit
```

Phase 80 may use the existing in-service graduation shortcut, but the clean target is a separate evaluator compute node plus writer-owned registry persistence.

Graduation should require multiple gates:

- minimum resolved N
- positive rank correlation between multiplier and `pnl_r`
- bucket lift
- bootstrap CI lower bound above zero
- stability across rolling subwindows
- output coverage
- parse quality
- calibration sanity
- cost gate

Eligibility is segment-local:

1. Phase 80: `(agent_id, timeframe)`
2. Future: `(agent_id, timeframe, regime)`
3. Later: `(agent_id, timeframe, regime, setup_family)`

---

## Cost And Capacity

The swarm is async but not free. Runtime must cap LLM pressure with a semaphore and capacity-skip behavior.

Track:

- latency
- timeout rate
- parse failure rate
- valid output coverage
- capacity skip rate
- estimated token/GPU cost
- value added per call

Agents must earn their compute. Small edge at high inference cost should remain shadow-only or receive lower weight.

---

## Deprecated Design Notes

Older docs described `SwarmOrchestratorAgent`, `SwarmWriterAgent`, `IAlphaContributor`, `SwarmContext`, and `alpha_multiplier_shadow`. That was pre-Phase-78 swarm plumbing. The current path is `AlphaSwarmComputeAgent` + `BaseAIAgent`/`BaseMultiplierAgent` + `LineageRecorder` + `signal_lineage`.

Historical docs may still mention the old model. Use this document and the Phase 80 plan as the current target.

---

## See Also

- `docs/plans/2026-05-05-swarm-intelligence-design.md`
- `src/intelligence/ai/AUTHORING.md`
- `services/alpha_swarm_agent.py`
- `services/lineage_writer_agent.py`
- `src/core/ai/lineage.py`
- `docs/architecture/canonical-truth-registry.md`
