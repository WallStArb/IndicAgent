<!-- generated-by: gsd-doc-writer -->
# Evolvable AI (eAI) — Agents That Evolve

> **Domain:** Intelligence — deep-dive companion to [`intelligence-ai.md`](../intelligence/intelligence-ai.md)

**Version:** 2.8
**Last Updated:** 2026-05-27
**Status:** In progress — Phases 101-103 (v2.8 milestone, gated behind AI platform Phases 094-099)
**Full Design:** `docs/ideas/ai-03-evolvable-ai-agents.md`

## Overview

Beyond learning from data, the platform is designed for agents that evolve through Darwinian selection — inspired by research in evolvable AI (PNAS 2025) and Renaissance Technologies' approach to model management.

Three epochs of AI:

1. **Intelligence by design** — handcrafted rules, logic, expert systems
2. **Intelligence by learning** — training on data, gradient descent, RLHF
3. **Intelligence by evolution** — agents that improve their own capacity for improvement

Markets are non-stationary. Manual agent design produces agents that reflect current mental models. An evolutionary system discovers edges that exist beyond those models.

---

## The Agent Genome

Each agent's "DNA" is a composite of independently heritable and mutable components:

| Chromosome | What evolves | Example mutations |
|------------|-------------|-------------------|
| **System prompts** | Reasoning strategy, analytical frame | Reword CoT structure, add reasoning steps |
| **Configuration parameters** | Thresholds, timeframe weights, scoring coefficients | Nudge confidence ±5%, swap TF priority |
| **Tool sets** | Data sources, APIs, analysis tools | Add data feed, remove underperforming indicator |
| **Model adapters** | Fine-tuned LoRA weights for specialization | Blend adapter weight sets |
| **Guardrails** | Behavioral constraints | Tighten regime filter, add volatility guard |
| **Code / logic** | Analysis approaches, plugin implementations | LLM writes new variant of analysis function |

Chromosomes mutate independently and recombine across parents. A child inherits prompt strategy from parent A, config from parent B, tool set from a blend — producing novel combinations neither parent could produce alone.

---

## Three Reproductive Operators

| Operator | Strategy | Role |
|----------|----------|------|
| **Mutation** | Blind perturbation of genome components | Exploration — escape local optima |
| **Recombination** | Crossover of genome segments from two fit parents | Combination — genuinely novel composites |
| **LLM-directed mutation** | LLM analyzes parent genome + performance, proposes targeted improvements | Directed search — fastest convergence |

The system tracks which operator produces the fittest offspring and dynamically shifts reproductive budget toward better operators — meta-optimization of the search itself.

---

## Lifecycle: Birth → Shadow → Breeding → Promotion → Live

```
[Gene Bank] ───────────────────────────────────────────────────┐
                                                                │
  BIRTH ──► SHADOW INCUBATION ──► BREEDING ──► PROMOTION ──► LIVE
              │                                    │
              │ (failed gate)                      │ (fitness decay)
              ▼                                    ▼
          SOFT DEATH ──► FROZEN ARCHIVE ──► genome segments ──►┘
```

All newborn agents enter **shadow mode**: observing live data, producing analysis, zero production impact. Fitness is measured strictly out-of-sample across multiple market regimes.

### Composite Fitness Score

| Dimension | What it measures | Why it matters |
|-----------|-----------------|----------------|
| **Accuracy** | Does the analysis correctly predict outcomes? | Baseline — does it work? |
| **Novelty** | Are signals orthogonal to existing agents? | Unique alpha, not redundancy |
| **Calibration** | When agent says 80% confident, is it right ~80% of the time? | Usable for position sizing |
| **Regime specificity** | Does it know which regimes it works in? | Self-aware agents are more valuable |
| **Efficiency** | Fitness per unit of compute | Dynamic population pressure |

### Statistical Gates

- Bootstrap CI lower bound > 0 at 95% confidence
- Multi-regime validation: sustained fitness across trending, ranging, high-vol, low-vol
- Promotion requires both automated gates AND human review — the *why* matters

---

## Existing Infrastructure

The system already has the substrate eAI needs:

- **Shadow mode with statistical promotion gates** — operational since Phase 75; `shadow_registry` table auto-enrolls all I7 plugins and AI agents at startup
- **Signal ledger outcome tracking** — fitness evaluation data accumulating since day one
- **Lineage recording** — full ancestry tracking per agent call via `LineageRecorder`
- **Skeptic agent pattern** — adversarial coevolution already in the swarm (5 agents active)
- **`BaseAIAgent` framework** — genome mutations can be implemented as agent parameter variations
- **`llm_calls` audit trail** — every LLM call persisted with prompt version, outcome back-fill

---

## Implementation Phases (v2.8)

Evolvable agent phases are gated behind the AI platform stack (Phases 094-099). Phase 101 does not begin until the FIT-06 evidence gate is passed.

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 094** | LiteLLM + Instructor structured output — replace bespoke provider logic | Not started |
| **Phase 095** | Pydantic AI agent execution layer — `PydanticAIAdapter` bridge | Not started |
| **Phase 096** | Agent Registry — centralized agent catalog | Not started |
| **Phase 097** | Zep Episodic Memory | Not started |
| **Phase 098** | DSPy Offline Prompt Optimizer — timer-triggered batch, reads `llm_calls` | Not started |
| **Phase 099** | Guardrails AI Validation (conditional: only if parse failure rate > 1%) | Not started |
| **Phase 101** | Composite Fitness Function — `agent_fitness` table, Bootstrap CI + Sharpe + win rate | Not started |
| **Phase 102** | Genetic Infrastructure — `agent_genomes` table, frozen archive, genome decomposition | Gated on FIT-06 cross-agent variance >= 0.2 |
| **Phase 103** | Reproductive Operators — mutation, recombination, LLM-directed operator | Gated on Phase 101+102 complete |

---

## Related Documentation

- [Swarm Intelligence](swarm-intelligence.md) — the current specialist agent architecture
- [Signal Lifecycle](signal-lifecycle.md) — outcome tracking that feeds fitness evaluation
- [Full eAI Design](../ideas/ai-03-evolvable-ai-agents.md) — complete design document
