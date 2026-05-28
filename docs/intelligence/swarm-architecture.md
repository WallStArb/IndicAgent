<!-- generated-by: gsd-doc-writer -->
# Intelligence Swarm Architecture

**Version:** 2.1.0
**Last Updated:** 2026-05-27
**Status:** Operational — alpha swarm active with 4 LLM agents (shadow) + 1 ML scorer (shadow) + narrative agent (live). Milestone: v2.8 AI Platform.

---

## Overview

The alpha swarm is an async intelligence overlay for I7 signals. It runs after signal publication, never blocks the hot I1-I7 pipeline, and records every agent prediction for outcome-based evaluation.

The current architecture is lineage-first:

```text
intelligence.i7.signals
  -> AlphaSwarmComputeAgent
       -> BaseMultiplierAgent subclasses (parallel dispatch)
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
| `group` | `"alpha"` for alpha agents, `"narrative"` for narrative agents. |
| `tiers_needed` | `frozenset[Tier]`; drives `AIContextCache.build()`. |
| `latency_budget_ms` | Hard timeout budget. |
| `shadow_only` | Starts `True`; runtime state is refreshed from `shadow_registry`. |
| `prompt_version` | Set from agent's `ACTIVE_VERSION` constant; auto-injected into `llm_calls`. |

Each agent returns an `AgentOutput` with `output_type="multiplier"` and a payload containing:

- `multiplier`
- `confidence`
- `prompt_version`
- agent-specific validated fields
- parse/validation status when available

Current policy is discount-only: agent formulas may reduce confidence but should not boost above `1.0` until sufficient outcome data proves positive edge.

---

## Active Agents

| Agent | Class | Purpose | Budget | Status |
|---|---|---|---|---|
| Skeptic | `SkepticAgentComputeAgent` | Estimates holistic failure probability | 120s | Shadow |
| Correlation | `CorrelationAgentComputeAgent` | Judges cross-asset coherence | 120s | Shadow |
| RegimeCoherence | `RegimeCoherenceAgentComputeAgent` | Checks setup type against current regime | 120s | Shadow |
| Counterfactual | `CounterfactualAgentComputeAgent` | Tests what must be true for the signal to work | 120s | Shadow |
| MLScorerV1 | `MLScorerV1Agent` | Local ML model signal score | 50ms | Shadow |
| Narrative | `NarrativeComputeAgent` | Market narrative prose (on-demand HTTP) | — | Live |

**LLM agents:** All 4 LLM agents use Ollama local (default gemma4:e4b). With gemma4:e4b on AMD ROCm, p50 latency is approximately 47-52s — within the 120s budget.

All start shadow-only and keep writing lineage whether shadow or live. The `shadow_only` flag is refreshed from `shadow_registry` at runtime — modifying the DB record changes live behavior without restart.

**Critical:** `agent_last_message_timestamp_seconds` label key is `agent_id` (not `agent=`). Use `r["metric"].get("agent_id")` when querying this metric from Prometheus.

---

## Future Agent Backlog

These agent ideas remain valid and should be implemented on the current `BaseMultiplierAgent` + `AIContext` + `signal_lineage` substrate:

| Candidate | Implementation Shape | What it quantifies |
|---|---|---|
| Volume Profile Validator | Future `VolumeProfileAgentComputeAgent` or deterministic multiplier component | Signal proximity to high-density institutional zones (POC, HVN, VAH/VAL) |
| Liquidity Decay Arbiter | Future microstructure agent once order book/depth substrate exists | LOB dynamics, fill probability, liquidity friction score |
| SMC Trap Detector | Future SMC-focused multiplier agent | Absorption patterns in order blocks; declining volume inside OB as liquidity hunt |
| Macro Event Observer | Future `MacroContextAgent` after ctx substrate | High-impact event proximity (FOMC, CPI) and catalyst risk |
| Regime Sentinel | Future regime transition agent once enough transition labels exist | Latent regime transition probability from entropy, dispersion, momentum |
| Volatility Arbiter | Future DerivAgent/options-dependent agent | ATR expected move vs implied vol skew; compression/expansion state |

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
| LLM prompt/response audit | `LLMWriterAgent` writes `llm_calls`; composite PK `(call_id, called_at)`. |
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

`llm_calls` remains the audit table for prompt/response/model/provider records. `indicagent-llm-writer` consumes `llm.calls` Kafka topic, writes to `llm_calls` hypertable, back-fills outcome fields, and recomputes `llm_model_scores` every 15 min.

**Swarm raw signal confidence:** `calibrated_confidence` is null in Kafka signal payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

---

## Graduation Governance

Shadow/live controls whether an agent can affect production confidence. It does not control whether the agent writes predictions. All agents continue writing lineage in both modes.

**Auto-enrollment:** All I7 plugins and swarm agents are auto-enrolled in `shadow_registry` at startup via `shadow_registry_ensure()` / `enroll_all_plugins()`. Uses ON CONFLICT DO NOTHING — custom gate parameters tuned directly in DB are never overwritten by restarts.

**Promotion criteria (current):**
- `n >= 100` resolved signals
- `bootstrap_ci_lower(pnl_r) > 0.0` (at 95% confidence)

**Demotion criteria:**
- EV[R] < -0.05 for 3 consecutive evaluation cycles

**Full target governance DAG:**

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

**Full graduation gates (target):**

- minimum resolved N (n >= 100)
- positive rank correlation between multiplier and `pnl_r`
- bucket lift
- bootstrap CI lower bound above zero
- stability across rolling subwindows
- output coverage
- parse quality
- calibration sanity
- cost gate

**Eligibility is segment-local:**

1. Current: `(agent_id, timeframe)`
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

**Local Ollama resource management:** Live services `alpha_swarm` and `narrative_compute` hold persistent Ollama connections. Kill them before swapping models or benchmarking.

---

## Deprecated Design Notes

Older docs described `SwarmOrchestratorAgent`, `SwarmWriterAgent`, `IAlphaContributor`, `SwarmContext`, and `alpha_multiplier_shadow`. That was pre-Phase-78 swarm plumbing. The current path is `AlphaSwarmComputeAgent` + `BaseAIAgent`/`BaseMultiplierAgent` + `LineageRecorder` + `signal_lineage`.

Historical docs may still mention the old model. Use this document as the current target.

---

## See Also

- `docs/plans/2026-05-05-swarm-intelligence-design.md`
- `src/intelligence/ai/AUTHORING.md`
- `services/alpha_swarm_agent.py`
- `services/lineage_writer_agent.py`
- `src/core/ai/lineage.py`
- `docs/architecture/canonical-truth-registry.md`
- `src/intelligence/register_plugins.py` — `shadow_registry_ensure()`, `enroll_all_plugins()`
