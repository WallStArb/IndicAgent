# Phase 095: Complete Foundation for Multi-Tenant, Complex Agents, and Evolvable AI

**Status:** ✅ Planned (8 plans: 00-08)
**Timeline:** ~16-20 days total
**Date:** 2026-05-21

## Executive Summary

Phase 095 has been strategically extended to provide **complete foundation** for three critical capabilities:

1. **Multi-Tenant, Multi-User Agent Execution** — Per-user quotas, cost tracking, isolation
2. **Complex Agent Development** — Tool use, composition, stateful sessions
3. **Evolvable AI (eAI)** — Genome versioning, governance gates, lineage tracking

**Strategic ROI:** +6-8 days effort prevents 2-3 weeks of painful refactoring later + enables user-facing features + eAI research vision.

## Phase 095 Structure

### Wave 0: Multi-Tenant Foundation (2-3 days) ⚡

**Plan 00: UserContext + Multi-Tenant Support**
- UserContext dataclass with user_id, tenant_id, quotas, permissions
- AgentLimits for quota enforcement (requests, cost, concurrency)
- Database migration: Add user_id and tenant_id to llm_calls
- Unit tests for quota enforcement
- Feature gate: ENABLE_MULTI_TENANT defaults false

**Why First:** Must come before all other plans (AgentDeps needs UserContext). Minimal risk (feature gated, backward compatible).

### Wave 1: Core Infrastructure (4-5 days)

**Plan 01: AgentDeps (with user_context)**
- AgentDeps dataclass with signal_context, llm_chain, user_context, db_pool, memory_client
- frozen=True for immutability
- Package exports and unit tests

**Plan 02: PydanticAIAdapter (with quota enforcement)**
- Adapter bridge preserving audit trail
- Quota enforcement via AgentLimits
- User context propagation to llm_calls
- Permission checking before agent execution

### Wave 2: Agent Implementation (3-4 days)

**Plan 03: SkepticResult**
- Pydantic model with validation
- Clarified validation behavior (null fields vs validation errors)

**Plan 04: SkepticComputeAgentPydantic (with user context)**
- Reference Pydantic AI implementation
- User context integration
- Shadow validation with statistical gates

### Wave 3: Service Integration (2-3 days)

**Plan 05: Service Registration (with per-user queues)**
- AlphaSwarm registration with feature gates
- Per-user request queues for isolation
- User context propagation from service to agents
- Per-user cost tracking metrics

### Wave 4: Genome Foundation (4-5 days) ⚡ **NEW**

**Plan 07: AgentGenome Foundation**
- Chromosome definitions (SystemPromptChromosome, ConfigChromosome, ToolSetChromosome, RulesChromosome)
- AgentGenome dataclass with genome_id (SHA256), parent_ids, generation
- Mutation and recombination operators (sexual reproduction foundation)
- Database migration: Add genome_id to llm_calls
- Unit tests for genome hashing and lineage tracking

**Plan 08: Promotion/Demotion Gates**
- PromotionGate: 4 automated criteria (sustained fitness, novelty, stability, regimes)
- DemotionGate: 4 trigger conditions (decay, returns, correlation, regime shift)
- Human review workflow (evaluate "why" not just "what")
- Soft death with genome preservation (agents/ directory)
- AlphaSwarm integration in shadow validation cycle

## Strategic Questions Answered

### 1. "Does this set us up for AI success with more complicated agents?"

**YES.** Phase 095 provides:

- ✅ Type-safe structured output (Pydantic AI)
- ✅ Clean adapter pattern (add new agent types easily)
- ✅ Per-user scoping (tool use, composition)
- ✅ Cost tracking (expensive multi-step reasoning)
- ✅ Quota enforcement (prevent runaway agent costs)
- ✅ Genome versioning (agent provenance tracking)
- ✅ Governance gates (promotion/demotion criteria)

**Still Missing (Future Phases):**
- Tool use implementation (Phase 095/096)
- Agent composition/chaining (Phase 095/096)
- Stateful sessions (Phase 095/096)
- Multi-step reasoning protocols (Phase 095/096)

### 2. "Do we have the foundation to run multiple instances of agents for multiple users?"

**YES.** Multi-tenant foundation provides:

- ✅ UserContext with user_id and tenant_id
- ✅ Per-user request queues (isolation)
- ✅ Per-user quotas (fair resource allocation)
- ✅ Per-user cost tracking (billing)
- ✅ Audit trail per user (llm_calls.user_id)

**Implementation Note:**
- Current design: Single AlphaSwarm service with per-user queues
- Future scaling: Per-user AlphaSwarm instances (kubernetes per user)
- Foundation supports both approaches

### 3. "Do we have a good foundation for our eAI ideas?"

**MOSTLY YES.** Phase 095 provides the critical building blocks:

- ✅ **Genome versioning** (AgentGenome with chromosome structure, lineage tracking)
- ✅ **Governance gates** (PromotionGate, DemotionGate with human review)
- ✅ **Reproductive operators** (mutation, recombination foundations in Plan 07)
- ✅ Per-user cost tracking (essential for eAI budgeting)
- ✅ Quota enforcement (prevent edge device exhaustion)
- ✅ UserContext metadata (device capabilities, network constraints)
- ✅ Request queues (progressive inference prioritization)

**Still Missing (eAI-Specific):**
- Composite fitness function (Phase 095) — accuracy, novelty, calibration, regime specificity, efficiency
- Gene bank and frozen archive (Phase 096) — extract best segments from dead agents
- Reproductive operators (Phase 097) — LLM-directed mutation, adaptive operator selection
- Offline support (cache agent results on device)
- Progressive inference (stream partial results)
- Resource optimization (token budgeting per request)
- Edge deployment (agent models on device)

## Alignment with Your eAI Research

Your research document recommends:

> "Phase 1 — LLM-directed prompt mutation (lowest risk, now)"

**Phase 095 Alignment:**
- ✅ Pydantic AI → Clean prompt versioning (SystemPromptChromosome)
- ✅ Multi-tenant → Per-user tracking for fitness
- ✅ Shadow validation → Safe incubation
- ✅ AgentGenome → Genome versioning with lineage tracking
- ✅ PromotionGate → Governance gates (automated + human review)
- ✅ DemotionGate → Soft death with genome preservation

**What Phase 095 Enables:**
Phase 095 provides the **provenance tracking** and **governance gates** required for your "Phase 1" eAI vision (LLM-directed prompt mutation).

**What Still Needed:**
Phase 095 (Composite Fitness Function) is required before reproductive operators (Phase 097). Your research is clear: **80% effort on fitness function, 20% on reproductive mechanics**.

## Updated Phase Roadmap

### Phase 095: Multi-Tenant + Pydantic AI + Genome Foundation (Current)

**Timeline:** ~16-20 days
**Risk:** LOW (feature gated, backward compatible)
**Strategic Value:** VERY HIGH

### Phase 095: Composite Fitness Function (NEW)

**Goal:** Build rigorous fitness evaluation before enabling evolution
**Timeline:** ~2-3 weeks
**Risk:** HIGH (critical to get right per your research)

**Plans:**
- Plan 01: Accuracy metrics (bootstrap CI, sharpe, win rate)
- Plan 02: Novelty metrics (decorrelation from agent population)
- Plan 03: Calibration metrics (confidence vs reality)
- Plan 04: Regime specificity (performance by market regime)
- Plan 05: Efficiency metrics (fitness per compute cost)
- Plan 06: Composite score integration (weighted combination)

### Phase 096: Genetic Infrastructure (Future Phase)

**Goal:** Gene bank, frozen archive, decomposition
**Timeline:** ~1-2 weeks
**Risk:** MEDIUM

### Phase 097: Reproductive Operators (Future Phase)

**Goal:** Mutation, recombination, LLM-directed operators
**Timeline:** ~2-3 weeks
**Risk:** HIGH (depends on validated fitness function)

## Feature Gates for Gradual Rollout

### Gate 1: ENABLE_MULTI_TENANT (default: false)
- **false:** Single-tenant mode (backward compatible)
  - All agents use UserContext.system()
  - No per-user quotas
  - No per-user queues
- **true:** Multi-tenant mode
  - User context loaded from auth/request
  - Per-user quotas enforced
  - Per-user queues for isolation

### Gate 2: ENABLE_PYDANTIC_SKEPTIC_SHADOW (default: false)
- **false:** Legacy skeptic_v1 only
- **true:** Both skeptic_v1 and skeptic_v2_pydantic (shadow mode)

### Gate 3: ENABLE_PROMOTION_DEMOTION_GATES (default: false)
- **false:** Manual agent management only
- **true:** Automated promotion/demotion checks in shadow validation cycle

### Rollout Strategy

**Phase 095 Completion:**
- ENABLE_MULTI_TENANT = false (single-tenant)
- ENABLE_PYDANTIC_SKEPTIC_SHADOW = true (shadow validation)
- ENABLE_PROMOTION_DEMOTION_GATES = false (manual management)

**Phase 095 (Composite Fitness Function):**
- ENABLE_PROMOTION_DEMOTION_GATES = true (automated gates)
- Monitor fitness metrics, promotion candidates, demotion triggers

**Phase 096/097 (Future):**
- ENABLE_MULTI_TENANT = true (gradual user rollout)
- Monitor quotas, costs, per-user metrics
- Enable reproductive operators with validated fitness function

## Conclusion

**Phase 095 is now complete with multi-tenant + genome foundation.**

- **Effort:** +6-8 days (16-20 days total vs 10-12 days)
- **ROI:** Prevents 2-3 weeks refactoring + enables user features + eAI foundation
- **Risk:** LOW (feature gated, backward compatible, governance before reproductive mechanics)
- **Strategic Value:** VERY HIGH (enables user features, prevents refactoring, foundation for complexity AND eAI)

The revised Phase 095 is now **future-proof** for:
- Multi-tenant, multi-user agent execution
- Complex agent development (tool use, composition, stateful sessions)
- Evolvable AI (genome versioning, promotion gates, lineage tracking)

**Recommendation:** Execute Phase 095 as planned (Plans 00-08), then proceed to Phase 095 (Composite Fitness Function) before enabling reproductive operators in Phase 097.

---

**Decision:** APPROVED — Phase 095 with multi-tenant + genome foundation
**Timeline:** ~16-20 days total (Wave 0: 2-3d, Wave 1: 4-5d, Wave 2: 3-4d, Wave 3: 2-3d, Wave 4: 4-5d)
**Next:** Execute Wave 0 (Plan 00) → Wave 1 (Plans 01-02) → Wave 2 (Plans 03-04) → Wave 3 (Plan 05) → Wave 4 (Plans 07-08)
