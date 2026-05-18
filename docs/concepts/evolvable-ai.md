# Evolvable AI (eAI) — Agents That Evolve

**Last Updated:** 2026-05-10
**Status:** Designed, not yet implemented
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

- **Shadow mode with statistical promotion gates** — operational since Phase 75
- **Signal ledger outcome tracking** — fitness evaluation data accumulating since day one
- **Lineage recording** — full ancestry tracking per agent call
- **Skeptic agent pattern** — adversarial coevolution already in the swarm
- **`BaseAIAgent` framework** — genome mutations can be implemented as agent parameter variations

---

## Implementation Phases

| Phase | Scope |
|-------|-------|
| **Phase 1** | LLM-directed prompt mutation — lowest risk, leverages existing agent framework |
| **Phase 2** | Composite fitness function — building and stress-testing the evaluation substrate |
| **Phase 3** | Config parameter mutation + gene bank — persistent population management |
| **Phase 4** | Code/logic evolution — highest risk, LLM-generated analysis variants |

---

## Related Documentation

- [Swarm Intelligence](swarm-intelligence.md) — the current specialist agent architecture
- [Signal Lifecycle](signal-lifecycle.md) — outcome tracking that feeds fitness evaluation
- [Architecture Concepts](../architecture/concepts.md) — shadow governance and statistical gates
- [Full eAI Design](../ideas/ai-03-evolvable-ai-agents.md) — complete design document
