# Phase 103: Reproductive Operators

**Milestone:** v2.8 Evolvable AI Foundation
**Status:** Planned
**Timeline:** ~2-3 weeks
**Plans:** 4 plans

## Goal

Implement the three reproductive operators that generate new agent variants, plus
adaptive operator selection that meta-optimizes the search itself. This is the
final phase of the eAI foundation — it comes last because it requires a validated
fitness function (Phase 101) and a gene bank to draw from (Phase 102).

Per the eAI research principle: **20% of effort on reproductive mechanics.**
The fitness function (Phase 101) is the hard part.

## Foundation Required

- Phase 101: Composite fitness function + PromotionGate/DemotionGate
- Phase 102: AgentGenome, gene bank, frozen archive

## Plans

1. **Plan 01:** Random mutation operator
2. **Plan 02:** Sexual recombination operator
3. **Plan 03:** LLM-directed mutation operator (Lamarckian)
4. **Plan 04:** Adaptive operator selection (meta-optimization)

## Plan 01: Random Mutation

**Role:** Exploration — escapes local optima, generates diversity, explores unknown territory.

```
mutate(parent_genome: AgentGenome, mutation_rate: float) -> AgentGenome

For each chromosome:
  - With probability mutation_rate: apply perturbation
  - system_prompt: reword sections, add/remove reasoning steps
  - config_params: nudge numeric values ±5-15% within bounds
  - guardrails: tighten/relax one constraint
  - tool_set: swap one tool for an alternative from the gene bank
  - model_adapter / logic: skip (too high variance for blind mutation)

Output: new AgentGenome with parent_ids=[parent.genome_id], generation+1
```

Low mutation_rate (0.1-0.2) for exploitation; higher (0.3-0.4) when population
fitness has stagnated for N cycles (diversity injection).

## Plan 02: Sexual Recombination

**Role:** Combination — merges uncorrelated alpha sources from two parents.
The key insight: two agents that each find different edges can produce offspring
that finds both, via chromosome crossover.

```
recombine(parent_a: AgentGenome, parent_b: AgentGenome) -> AgentGenome

Per chromosome, independently select source:
  - system_prompt:   from parent with higher accuracy score
  - config_params:   weighted blend (arithmetic mean of numeric values)
  - tool_set:        union with deduplication (prefer parent_a on conflict)
  - guardrails:      intersection (more conservative = safer offspring)
  - model_adapter:   from parent with higher calibration score
  - logic:           from parent with higher novelty score

Output: new AgentGenome with parent_ids=[a.genome_id, b.genome_id], max(generation)+1
```

Parent selection: favor high composite fitness but maintain diversity — do not
always pair the top two (converges to local optima). Use tournament selection
with novelty as a tiebreaker.

## Plan 03: LLM-Directed Mutation (Lamarckian)

**Role:** Directed search — uses LLM to analyze parent performance and propose
targeted improvements. The LLM draws on quant literature, trading research, and
market microstructure theory as its gene pool (horizontal gene transfer).

This is the "Phase 1" operator from the eAI research recommendation:
> *"LLM-directed prompt mutation — lowest risk, implement now"*

```
llm_mutate(parent_genome: AgentGenome, performance_record: dict) -> AgentGenome

Prompt to LLM:
  - Parent's system_prompt chromosome
  - Last N failure cases (signals where parse_success=False or win=False)
  - Regime distribution of failures
  - Parent's fitness scores by dimension

LLM proposes:
  - Revised system_prompt addressing identified failure modes
  - Optional: config_params adjustments (specific thresholds)
  - Reasoning for each proposed change (stored in genome metadata)

Output: new AgentGenome with genome_id from proposed chromosomes, parent_ids=[parent.genome_id]
```

LLM call goes through `_llm_generate()` for full audit trail in `llm_calls`.
The reasoning for each mutation is stored in genome JSONB metadata for post-hoc
analysis of which operator insights are most reliable.

## Plan 04: Adaptive Operator Selection

**Role:** Meta-optimization — track which operator produces the most fit offspring
and dynamically shift reproductive budget toward better operators.

```
OperatorBudget:
  mutation:       starting_weight = 0.33
  recombination:  starting_weight = 0.33
  llm_directed:   starting_weight = 0.34

After each generation:
  - Compute mean composite fitness of offspring per operator
  - Update weights via exponential moving average (alpha=0.3)
  - Normalize weights to sum to 1.0
  - Enforce floor of 0.10 per operator (prevent complete abandonment)
```

Budget state stored in `operator_stats` table (operator, offspring_count,
mean_fitness, weight) — queryable for research into which operator works best
in which market regime.

## Agent Lifecycle

```
[Gene Bank] ──────────────────────────────────────────────────────────┐
                                                                       │
  BIRTH ──► SHADOW INCUBATION ──► BREEDING ──► PROMOTION ──► LIVE     │
              │                                    │                    │
              │ (failed PromotionGate)             │ (DemotionGate)    │
              ▼                                    ▼                    │
          SOFT DEATH ──► FROZEN ARCHIVE ──► genome segments ──────────►┘
```

New agents enter shadow incubation automatically. PromotionGate (Phase 101)
gates the shadow→live transition. DemotionGate triggers soft death. Gene bank
feeds recombination and LLM-directed operators.

## Documentation

eAI research: `docs/ideas/ai-03-evolvable-ai-agents.md`
ROADMAP: `.planning/ROADMAP.md`
