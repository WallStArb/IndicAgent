# Phase 101: Composite Fitness Function

**Milestone:** v2.8 Evolvable AI Foundation
**Status:** Planned
**Timeline:** ~2-3 weeks
**Plans:** 6 plans

## Goal

Build rigorous fitness evaluation across 5 dimensions (accuracy, novelty, calibration, regime specificity, efficiency) before enabling reproductive operators.

## Foundation from Phase 094

This phase builds on the genome infrastructure from Phase 094:
- AgentGenome with chromosome structure (Plan 07)
- Lineage tracking (parent_ids, generation) (Plan 07)
- PromotionGate with automated criteria (Plan 08)
- DemotionGate with soft death preservation (Plan 08)

## Plans

1. **Plan 01:** Accuracy metrics (bootstrap CI, Sharpe, win rate)
2. **Plan 02:** Novelty metrics (decorrelation from agent population)
3. **Plan 03:** Calibration metrics (confidence vs reality)
4. **Plan 04:** Regime specificity (performance by market regime)
5. **Plan 05:** Efficiency metrics (fitness per compute cost)
6. **Plan 06:** Composite score integration (weighted combination)

## Strategic Priority

Per your eAI research: **80% of effort on fitness function, 20% on reproductive mechanics.**

This phase is the critical gate — without rigorous fitness evaluation, reproductive operators (Phase 102) will optimize for the wrong objectives.

## Documentation

See ROADMAP.md for complete phase details.
