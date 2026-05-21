# Plan 08: Promotion/Demotion Gates — Summary

**Phase:** 094 (Pydantic AI Agents + Multi-Tenant Foundation)
**Wave:** 4 (Service Integration + Genome Foundation)
**Status:** Planned
**Date:** 2026-05-21

## Objective

Create promotion/demotion gates for agent lifecycle management, enabling governance for evolvable AI agents. Implement automated promotion criteria (sustained fitness, novelty, stability) and demotion triggers (fitness decay, correlation rise, regime shifts) with human review workflow and soft death genome preservation.

## Strategic Rationale

Your eAI research requires **governance before reproductive operators**:
- Promote only proven agents (sustained fitness across regimes)
- Demote underperformers quickly (conserve resources)
- Preserve genomes for potential resurrection (soft death)
- Human review evaluates agent's "why" not just "what"

This completes the **genome foundation** for your "Phase 1" eAI vision: LLM-directed prompt mutation with provenance tracking and promotion gates.

## Deliverables

### 1. PromotionGate (`src/core/ai/promotion.py`)

**Automated Criteria (ALL must pass):**
- **Regime Coverage:** Sustained composite fitness across >=3 market regimes
- **Minimum Predictions:** n >= 100 (statistical significance)
- **Fitness Threshold:** Composite fitness > 5% in all regimes
- **Stability:** Fitness variance < 2% (prevents cherry-picking)
- **Novelty:** Decorrelation from live agents (correlation < 0.7)

**Governance Gate:**
- Returns `(can_promote, reason, human_review_required)`
- `human_review_required` always **True** (evaluate "why" not just "what")
- Prevents automated promotion without human oversight

### 2. DemotionGate (`src/core/ai/demotion.py`)

**Demotion Triggers (ANY fires demotion):**
- **Fitness Decay:** Composite fitness < -5% for 3 consecutive cycles
- **Negative Returns:** Expected returns < 0 (statistical significance lost)
- **Correlation Rise:** Correlation > 0.8 with any live agent (loss of novelty)
- **Regime Shift:** Performance drop > 15% on regime change

**Soft Death:**
- Genome preserved to `agents/` directory via `AgentGenome.to_dict()`
- Enables potential resurrection or gene bank extraction
- Follows eAI research "frozen archive" pattern

### 3. AlphaSwarm Integration (`services/alpha_swarm_agent.py`)

**Shadow Validation Cycle Enhancement:**
```python
async def _evaluate_shadow_agents_for_promotion(self):
    """Check shadow agents against promotion gates."""
    for agent_id, agent in self._agents.items():
        if not agent.shadow_only:
            continue

        # Fetch fitness metrics from signal_ledger or shadow_registry
        fitness_metrics = await self._load_agent_fitness_metrics(agent_id)
        regime_performance = await self._load_agent_regime_performance(agent_id)
        live_agent_correlations = await self._compute_live_agent_correlations(agent_id)

        can_promote, reason, human_review_required = self._promotion_gate.can_promote(...)
        if can_promote and human_review_required:
            await self._store_pending_promotion(agent_id, reason)

async def _evaluate_live_agents_for_demotion(self):
    """Check live agents against demotion gates."""
    # Similar logic for demotion checks
    # Preserves genome before demotion (soft death)
```

### 4. Unit Tests

**PromotionGate Tests (`test_promotion.py`):**
- All criteria met → promotion with human review
- Insufficient predictions → deny
- Insufficient regime coverage → deny
- Low fitness in regime → deny
- High variance → deny
- High correlation → deny

**DemotionGate Tests (`test_demotion.py`):**
- No triggers → no demotion
- Consecutive fitness decay → demote
- Negative returns → demote
- Correlation rise → demote
- Regime shift collapse → demote
- Insufficient consecutive failures → no demotion

## Integration with Phase 095

### Dependencies
- **Plan 05** (Service Registration): Shadow validation cycle for gate evaluation
- **Plan 07** (AgentGenome): Genome preservation on soft death

### Future Phases
- **Phase 095** (Composite Fitness Function): Provides detailed fitness metrics for gates
- **Phase 096** (Genetic Infrastructure): Gene bank extraction from demoted genomes
- **Phase 097** (Reproductive Operators): Uses promotion gates to select parents

## Feature Gates

**ENABLE_PROMOTION_DEMOTION_GATES** (default: false)
- **false:** Gates disabled, manual agent management only
- **true:** Automated promotion/demotion checks in shadow validation cycle

**Recommendation:** Keep disabled until Phase 095 (Composite Fitness Function) completes. Gates require accurate fitness metrics to function correctly.

## Threat Model Coverage

| Attack Vector | Mitigation |
|---------------|------------|
| Cherry-picking favorable regimes | Requires >=3 regimes + low variance gate |
| Novelty spoofing via noise | Decorrelation AND sustained accuracy required |
| Copycat correlation attack | Demotion triggers on correlation > 0.8 |
| Regime shift exploitation | Regime specificity gate + demotion on regime delta |
| Genome poisoning | Serialization validation + resurrection requires human review |
| Human review bypass | `human_review_required` always True |

## Effort Estimate

**Total:** ~4-5 days
- Task 1 (PromotionGate): 1 day
- Task 2 (DemotionGate): 1 day
- Task 3 (AlphaSwarm integration): 1-2 days
- Task 4-5 (Unit tests): 1 day

**Risk:** MEDIUM (gating logic, not agent behavior)

## Success Criteria

- [ ] PromotionGate enforces all 4 automated criteria
- [ ] DemotionGate triggers on all 4 conditions
- [ ] Human review required for all promotion decisions
- [ ] Soft death preserves genome before demotion
- [ ] AlphaSwarm integrates gates in shadow validation cycle
- [ ] Unit tests cover all criteria and triggers
- [ ] Feature gated (disabled until Phase 095)

## Completion

**Status:** ✅ Planned

**Next Steps:**
1. Execute Plan 08 following task sequence
2. Verify unit tests pass
3. Feature gate remains disabled until Phase 095
4. Document promotion/demotion workflow for operators

**Foundation Achieved:**
Phase 095 now has **complete genome foundation** for eAI:
- ✅ AgentGenome with chromosome structure (Plan 07)
- ✅ Lineage tracking (parent_ids, generation) (Plan 07)
- ✅ Genome versioning (SHA256 hash) (Plan 07)
- ✅ Promotion gates (automated + human review) (Plan 08)
- ✅ Demotion gates (soft death + preservation) (Plan 08)

**Enables Your "Phase 1" eAI Vision:**
> "Phase 1 — LLM-directed prompt mutation (lowest risk, now)"

Phase 095 provides the **provenance tracking** and **governance gates** required for safe LLM-directed prompt mutation. Phase 095 will add the **composite fitness function** to validate mutations before reproductive operators (Phase 097).
