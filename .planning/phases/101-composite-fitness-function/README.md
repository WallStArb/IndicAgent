# Phase 101: Composite Fitness Function

**Milestone:** v2.8 Evolvable AI Foundation
**Status:** Planned
**Timeline:** ~2-3 weeks
**Plans:** 6 plans

## Goal

Build rigorous multi-dimensional fitness evaluation for AI agents. This is the gate
before reproductive operators — without a validated fitness function, evolution
optimizes for the wrong objectives.

Per the eAI research principle: **80% of effort on fitness function, 20% on
reproductive mechanics.**

## Foundation Required from Phase 102

Phase 102 (genetic infrastructure) must deliver `AgentGenome` before this phase
executes. Fitness scores are attached to genomes, not raw agents.

## Fitness Dimensions — 5 axes, each independently scored [0, 1]

| Dimension | What it measures | Key metric |
|---|---|---|
| **Accuracy** | Prediction quality vs outcomes | Bootstrap CI on Sharpe, win rate |
| **Novelty** | Decorrelation from live agent population | 1 - max(|Pearson r| across live agents) |
| **Calibration** | Stated confidence vs realized accuracy | Brier score, isotonic residuals |
| **Regime specificity** | Performance consistency across market regimes | Fitness variance across >=3 regimes |
| **Efficiency** | Fitness per LLM token / compute dollar | Score / median_latency_ms |

## Plans

1. **Plan 01:** Accuracy metrics — bootstrap CI, Sharpe ratio, win rate by setup type
2. **Plan 02:** Novelty metrics — Pearson decorrelation from live agent population
3. **Plan 03:** Calibration metrics — Brier score, confidence vs realized accuracy
4. **Plan 04:** Regime specificity — per-regime breakdown, variance gate
5. **Plan 05:** Efficiency metrics — fitness per compute cost
6. **Plan 06:** Composite score + PromotionGate + DemotionGate integration

## Plan 06 Detail: Promotion and Demotion Gates

### PromotionGate — ALL criteria must pass

Extracted from 095-08 planning. Implements the governance layer before an agent
goes live from shadow mode.

```
can_promote(genome_id) -> (bool, str | None)

Criteria (all must pass):
  1. Regime coverage:   sustained composite fitness across >= 3 market regimes
  2. Sample gate:       n >= 100 predictions (statistical significance)
  3. Fitness threshold: composite_fitness > 0.05 in every covered regime
  4. Stability:         fitness_variance < 0.02 across last 3 evaluation cycles
  5. Novelty:           decorrelation from all live agents (no copycat promotion)
```

Promotion triggers human review — evaluator assesses agent's "why" (reasoning
quality, regime logic) not just "what" (raw fitness score).

### DemotionGate — ANY trigger sufficient

```
should_demote(genome_id) -> (bool, str | None)

Triggers (any one fires demotion):
  1. Fitness decay:         composite_fitness drops > 20% from promotion baseline
  2. Correlation rise:      Pearson r with any live agent crosses 0.85 (copycat)
  3. Regime shift failure:  fitness in newly dominant regime < 0.0 for 2 cycles
  4. Parse failure rate:    parse_success_rate < 0.80 over rolling 50 calls
```

Soft death on demotion: genome JSON preserved in `agents/demoted/` before removal
from active rotation. Preserved for potential resurrection via Phase 102 gene bank.

### Integration with shadow_registry

- `shadow_registry` table tracks shadow agents. PromotionGate replaces manual
  n>=100 + bootstrap_ci_lower>0 check with the composite fitness criteria above.
- DemotionGate replaces the current EV[R]<-0.05 × 3 cycles trigger with the
  multi-dimensional check.
- Both gates run in `ShadowAuditorAgent` evaluation cycle.

## Documentation

eAI research: `docs/ideas/ai-03-evolvable-ai-agents.md`
ROADMAP: `.planning/ROADMAP.md`
