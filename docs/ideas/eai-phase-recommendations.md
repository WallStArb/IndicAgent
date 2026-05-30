# eAI Foundation Gaps and Phase Recommendations

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-21
**Tags:** evolvable-ai, genome, phase-recommendations, foundation, agents, shadow-governance

## Critical Missing Components

### 1. **Genome Versioning & Lineage Tracking** 🔴 CRITICAL

**Why:** Your research calls this the "rules to stay in the breeder scenario":
- Every agent variant must be hash-identified
- Full genome version-controlled
- Traceable ancestry chain to generation 0
- No agent deployed without provenance

**Current State:** ❌ Completely missing from Phase 094

**Recommended Addition:** Phase 094, Plan 07 (NEW)

```python
# src/core/ai/genome.py
@dataclass(frozen=True)
class AgentGenome:
    """Hash-identified genome for evolvable agents."""
    genome_id: str  # SHA256 hash of genome components
    parent_ids: list[str]  # Ancestry chain
    generation: int  # Distance from generation 0
    
    # Chromosomes
    system_prompt_hash: str
    config_hash: str
    tool_set_hash: str
    model_adapter_hash: str
    code_hash: str
    
    def hash(self) -> str:
        """Compute deterministic genome hash."""
        # Combine all chromosome hashes
        return hashlib.sha256(
            f"{self.system_prompt_hash}:{self.config_hash}:..."
        ).hexdigest()
```

**Effort:** ~3-4 days
**Risk:** LOW (pure data structure, no runtime impact)

---

### 2. **Composite Fitness Function Infrastructure** 🔴 CRITICAL

**Why:** Your research calls this "the single most dangerous component":
- **Accuracy** - Does it predict outcomes?
- **Novelty/Decorrelation** - Orthogonal to existing agents?
- **Calibration** - Confidence matches reality?
- **Regime Specificity** - Knows its limits?
- **Efficiency** - Fitness per compute unit?

**Current State:** ❌ Basic shadow validation only (Plan 05)

**Recommended Addition:** Phase 095 (NEW Phase)

**Phase 095: Composite Fitness Function**
- Plan 01: Accuracy metrics (bootstrap CI, sharpe, win rate)
- Plan 02: Novelty metrics (decorrelation from agent population)
- Plan 03: Calibration metrics (confidence vs reality)
- Plan 04: Regime specificity (performance by market regime)
- Plan 05: Efficiency metrics (fitness per compute cost)
- Plan 06: Composite score integration (weighted combination)

**Effort:** ~2-3 weeks
**Risk:** HIGH (your research: "80% of effort on fitness function")

---

### 3. **Promotion/Demotion Gates** 🟡 IMPORTANT

**Why:** Your research requires:
- **Automated gates:** Sustained fitness, multi-regime validation
- **Human review:** Evaluate agent's "why", not just "what"
- **Demotion triggers:** Fitness decay, correlation rise, regime shifts
- **Soft death:** Frozen archive with genome preservation

**Current State:** 🟡 Partial (Plan 05 has basic shadow validation)

**Recommended Addition:** Phase 094, Plan 08 (EXTENDED)

**Extend Plan 08 (Service Registration) with:**
```python
# src/core/ai/promotion.py
class PromotionGate:
    """Automated promotion criteria for agent advancement."""
    
    def can_promote(self, agent_id: str) -> tuple[bool, str | None]:
        """Check if agent meets automated promotion criteria."""
        # Sustained composite fitness across >=3 regimes
        # Novelty confirmed (decorrelation from live agents)
        # Stability: low fitness variance across audit cycles
        ...

class DemotionGate:
    """Demotion triggers for underperforming agents."""
    
    def should_demote(self, agent_id: str) -> tuple[bool, str | None]:
        """Check if agent should be demoted."""
        # Composite fitness drops below threshold
        # Statistical significance drops
        # Correlation with existing agents rises
        ...
```

**Effort:** ~4-5 days
**Risk:** MEDIUM (gating logic, not agent behavior)

---

### 4. **Gene Bank & Frozen Archive** 🟢 FUTURE PHASE

**Why:** Your research calls for:
- **Gene bank:** Catalog best genome segments from dead agents
- **Frozen archive:** Preserve full genomes for potential resurrection
- **Decomposition:** Extract best parts from failed agents

**Current State:** ❌ Not in Phase 094

**Recommended Addition:** Phase 096 (Future Phase)

**Phase 096: Genetic Infrastructure**
- Plan 01: Frozen archive (TimescaleDB table for agent genomes)
- Plan 02: Gene bank extraction (best segment catalog)
- Plan 03: Decomposition algorithms (chromosome extraction)
- Plan 04: Resurrection evaluation (test dead agents against new data)

**Effort:** ~1-2 weeks
**Risk:** MEDIUM (data infrastructure, not agent logic)

---

### 5. **Reproductive Operator Infrastructure** 🟢 FUTURE PHASE

**Why:** Your research specifies three operators:
- **Random mutation:** Blind perturbations (exploration)
- **Sexual recombination:** Crossover between parents (combination)
- **LLM-directed mutation:** Directed search (exploitation)

**Current State:** ❌ Not in Phase 094

**Recommended Addition:** Phase 097 (Future Phase)

**Phase 097: Reproductive Operators**
- Plan 01: Mutation operator (prompt nudges, parameter shifts)
- Plan 02: Recombination operator (crossover between parents)
- Plan 03: LLM-directed operator (analyze parent, propose improvements)
- Plan 04: Adaptive operator selection (track which works best)

**Effort:** ~2-3 weeks
**Risk:** HIGH (your research: validate fitness function first)

---

## Updated Phase Roadmap

### Phase 094: Multi-Tenant + Pydantic AI Foundation (Current)
- **Wave 0:** Multi-tenant foundation (Plan 00)
- **Wave 1:** Core infrastructure (Plans 01-02)
- **Wave 2:** Agent implementation (Plans 03-04)
- **Wave 3:** Service integration (Plan 05)
- **Wave 4:** **NEW - Genome foundation** (Plan 07: AgentGenome, Plan 08: Promotion/Demotion gates)

**Timeline:** ~15-18 days total (+3-5 days for genome foundation)

### Phase 095: Composite Fitness Function (NEW)
- **Goal:** Build rigorous fitness evaluation before enabling evolution
- **Timeline:** ~2-3 weeks
- **Risk:** HIGH (critical to get right per your research)

### Phase 096: Genetic Infrastructure (NEW)
- **Goal:** Gene bank, frozen archive, decomposition
- **Timeline:** ~1-2 weeks
- **Risk:** MEDIUM

### Phase 097: Reproductive Operators (NEW)
- **Goal:** Mutation, recombination, LLM-directed operators
- **Timeline:** ~2-3 weeks
- **Risk:** HIGH (depends on validated fitness function)

---

## Immediate Recommendations

### For Phase 094 (Current Phase)

**Add Plan 07: AgentGenome Foundation**
- Create `AgentGenome` dataclass with chromosome hashes
- Add `lineage` tracking (parent_ids, generation)
- Extend `llm_calls` to include `genome_id`
- Add `agents/` directory for genome storage

**Add Plan 08: Promotion/Demotion Gates**
- Implement `PromotionGate.can_promote()` logic
- Implement `DemotionGate.should_demote()` logic
- Add human review workflow for promotion decisions
- Extend shadow validation to track regime-specific performance

**Effort:** +7-9 days to Phase 094
**Strategic Value:** HIGH (enables your entire eAI vision)

---

## Your Research Recommendations Validated ✅

Your document recommends:
> "Phase 1 — LLM-directed prompt mutation (lowest risk, now)"

**Our Phase 094 alignment:**
- ✅ Pydantic AI → Clean prompt versioning
- ✅ Multi-tenant → Per-user tracking for fitness
- ✅ Shadow validation → Safe incubation
- ⚠️ Missing: Genome versioning (Plan 07)
- ⚠️ Missing: Promotion gates (Plan 08)

**Conclusion:** Add Plans 07-08 to Phase 094 to enable "Phase 1" of your eAI vision while maintaining the conservative, gated approach you advocate.

---

**Decision Point:**
1. **Add Plans 07-08 to Phase 094?** (+7-9 days, enables genome foundation)
2. **Sequence Phase 095 immediately after?** (Fitness function first, per your research)
3. **Keep Phase 094 focused, defer genome work?** (Implement clean foundation first)

Your research is clear on the priority: **fitness function before reproductive mechanics**. The question is whether to build the minimal genome infrastructure now or defer it.
