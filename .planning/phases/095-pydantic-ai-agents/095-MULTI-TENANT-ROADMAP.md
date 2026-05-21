# Phase 095: Multi-Tenant Foundation - Complete Roadmap

**Updated:** 2026-05-21
**Decision:** Add multi-tenant foundation to Phase 095
**Rationale:** ~2 days effort prevents weeks of refactoring later

## Overview

Phase 095 now includes **multi-tenant foundation** alongside Pydantic AI agent migration.
This sets up IndicAgent for future user-facing features, per-user quotas, and cost tracking.

**Key Decision:** Build multi-tenant now, not later.
- AgentDeps is frozen=True (hard to add fields later)
- llm_calls migration easier with less data
- User context infrastructure needed for complex agents anyway

## Updated Wave Structure

### Wave 0: Multi-Tenant Foundation (NEW) ⚡ **2-3 days**

**Plan 00: UserContext + Multi-Tenant Support**
- UserContext dataclass with user_id, tenant_id, quotas, permissions
- AgentLimits for quota enforcement (requests, cost, concurrency)
- Database migration: Add user_id and tenant_id to llm_calls
- Unit tests for quota enforcement
- Feature gate: ENABLE_MULTI_TENANT defaults false
- **Deliverable:** Foundation for per-user agent execution

**Why Wave 0:**
- Must come first (other plans depend on UserContext)
- Minimal risk (feature gated, backward compatible)
- Sets foundation for entire phase

### Wave 1: Core Infrastructure (4-5 days)

**Plan 01: AgentDeps (UPDATED with user_context)**
- AgentDeps dataclass with user_context parameter
- Package exports and unit tests
- **DELTA:** Updated to include UserContext from Plan 00
- **Deliverable:** Type-safe dependency injection with multi-tenant awareness

**Plan 02: PydanticAIAdapter (UPDATED with quota enforcement)**
- Adapter bridge with audit trail preservation
- **DELTA:** Quota enforcement via AgentLimits
- **DELTA:** User context propagation to llm_calls
- **DELTA:** Permission checking before agent execution
- **Deliverable:** Protocol-aware adapter with multi-tenant support

### Wave 2: Agent Implementation (3-4 days)

**Plan 03: SkepticResult**
- Pydantic model with validation
- **DELTA:** No changes (data model independent of users)
- **Deliverable:** Structured output schema for Skeptic agent

**Plan 04: SkepticComputeAgentPydantic (UPDATED for user context)**
- Reference Pydantic AI implementation
- **DELTA:** Accepts user_context parameter
- **DELTA:** Inherits quota enforcement from PydanticAIAdapter
- **Deliverable:** Shadow-mode Skeptic agent with multi-tenant support

### Wave 3: Service Integration (2-3 days)

**Plan 05: Service Registration (UPDATED with per-user queues)**
- AlphaSwarm registration with feature gates
- **DELTA:** Per-user request queues for isolation
- **DELTA:** User context propagation from service to agents
- **DELTA:** Per-user cost tracking metrics
- **Deliverable:** Multi-tenant service orchestration

### Wave 4: Genome Foundation (4-5 days) ⚡ **NEW**

**Plan 07: AgentGenome Foundation (NEW)**
- Chromosome definitions (SystemPromptChromosome, ConfigChromosome, ToolSetChromosome, RulesChromosome)
- AgentGenome dataclass with genome_id, parent_ids, generation
- Mutation and recombination operators (sexual reproduction foundation)
- Database migration: Add genome_id to llm_calls
- Unit tests for genome hashing and lineage tracking
- **Deliverable:** Genome versioning and lineage tracking infrastructure

**Plan 08: Promotion/Demotion Gates (NEW)**
- PromotionGate: Automated criteria (sustained fitness, novelty, stability)
- DemotionGate: Triggers (fitness decay, correlation rise, regime shifts)
- Human review workflow (evaluate "why" not just "what")
- Soft death with genome preservation (agents/ directory)
- AlphaSwarm integration in shadow validation cycle
- Unit tests for all gate criteria and triggers
- **Deliverable:** Governance gates for agent lifecycle management

## Total Timeline

**Without Multi-Tenant + Genome:** ~10-12 days
**With Multi-Tenant Only:** ~12-15 days (+2-3 days)
**With Multi-Tenant + Genome:** ~16-20 days (+6-8 days total)

**ROI:** Prevents 2-3 weeks of refactoring later + enables user-facing features

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

### Rollout Strategy

**Phase 095 Completion:**
- ENABLE_MULTI_TENANT = false (single-tenant)
- ENABLE_PYDANTIC_SKEPTIC_SHADOW = true (shadow validation)

**Phase 095/096 (Future):**
- ENABLE_MULTI_TENANT = true (gradual user rollout)
- Monitor quotas, costs, per-user metrics

## Foundation Achievements

### ✅ Multi-Tenant Capabilities

**Per-User Quotas:**
- Request quotas (requests per day)
- Cost quotas (USD budget per user)
- Concurrency limits (max concurrent requests)
- Permission system (agent access control)

**Per-User Isolation:**
- Request queues per user
- Cost tracking per user
- Metrics per user
- Audit trail per user (user_id in llm_calls)

**Backward Compatibility:**
- Feature gated (ENABLE_MULTI_TENANT defaults false)
- UserContext.system() provides single-tenant defaults
- No behavioral changes to existing agents
- Migration preserves existing data (DEFAULT 'system')

### ✅ Foundation for Complex Agents

**Tool Use Ready:**
- UserContext provides scoping for tool permissions
- AgentLimits prevents tool abuse (quota enforcement)
- Per-user cost tracking for expensive tool calls

**Agent Composition Ready:**
- UserContext propagated through agent chains
- Quotas enforced per composed workflow
- Cost tracking across multi-step reasoning

**Session Management Ready:**
- UserContext can be extended with session_id
- Per-user queues provide session isolation
- Cost tracking per session for billing

### ✅ Foundation for eAI

**Genome Versioning:**
- AgentGenome with chromosome structure (Plan 07)
- SHA256-based deterministic genome identification (Plan 07)
- Lineage tracking (parent_ids, generation) (Plan 07)
- Mutation and recombination operators (Plan 07)
- Genome preservation in agents/ directory (Plan 08)

**Governance Gates:**
- PromotionGate with 4 automated criteria (Plan 08)
- DemotionGate with 4 trigger conditions (Plan 08)
- Human review workflow (evaluate "why" not "what") (Plan 08)
- Soft death with genome preservation (Plan 08)

**Resource Optimization:**
- Per-user cost tracking enables budget optimization
- Quota enforcement prevents runaway LLM costs
- Concurrency limits manage resource contention

**Progressive Inference:**
- UserContext metadata for edge/cLOUD decisions
- Per-user queues for request prioritization
- Cost-aware routing (cheap vs expensive models)

## Strategic Questions Answered

### 1. "Does this set us up for AI success with more complicated agents?"

**YES.** The foundation provides:
- ✅ Type-safe structured output (Pydantic AI)
- ✅ Clean adapter pattern (add new agent types easily)
- ✅ Per-user scoping (tool use, composition)
- ✅ Cost tracking (expensive multi-step reasoning)
- ✅ Quota enforcement (prevent runaway agent costs)

**Still Missing (Future Phases):**
- Composite fitness function (Phase 095) — accuracy, novelty, calibration, regime specificity, efficiency
- Reproductive operators (Phase 097) — mutation, recombination, LLM-directed
- Tool use implementation (Phase 095/096)
- Agent composition/chaining (Phase 095/096)
- Stateful sessions (Phase 095/096)
- Multi-step reasoning protocols (Phase 095/096)

### 2. "Do we have the foundation to run multiple instances for multiple users?"

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

**MOSTLY.** We have the critical building blocks:
- ✅ **Genome versioning** (AgentGenome with chromosome structure, lineage tracking)
- ✅ **Governance gates** (PromotionGate, DemotionGate with human review)
- ✅ Per-user cost tracking (essential for eAI budgeting)
- ✅ Quota enforcement (prevent edge device exhaustion)
- ✅ UserContext metadata (device capabilities, network constraints)
- ✅ Request queues (progressive inference prioritization)

**Still Missing (eAI-Specific):**
- Composite fitness function (Phase 095) — required before reproductive operators
- Gene bank and frozen archive (Phase 096) — extract best segments from dead agents
- Reproductive operators (Phase 097) — mutation, recombination, LLM-directed
- Offline support (cache agent results on device)
- Progressive inference (stream partial results)
- Resource optimization (token budgeting per request)
- Edge deployment (agent models on device)

## Recommended Next Steps

### Immediate (Phase 095)
1. **Approve Plans 00-08** - Complete Phase 095 with multi-tenant + genome foundation
2. **Execute Wave 0** - UserContext + migration (Plan 00)
3. **Execute Waves 1-3** - Updated plans with multi-tenant (Plans 01-05)
4. **Execute Wave 4** - Genome foundation (Plans 07-08)
5. **Feature gates disabled** - Ship single-tenant mode + manual agent management first

### Short-Term (Phase 095/096)
1. **Enable multi-tenant** - Flip ENABLE_MULTI_TENANT=true
2. **Add tool use** - Leverage UserContext for tool scoping
3. **Add agent composition** - Multi-step workflows with per-user quotas
4. **Add sessions** - Extend UserContext with session_id

### Long-Term (Phase 09X)
1. **eAI optimization** - Resource-aware routing, progressive inference
2. **Advanced composition** - Agent swarms, hierarchies
3. **Production multi-tenant** - Billing, admin dashboards

## Conclusion

**Adding multi-tenant + genome foundation to Phase 095 is the right strategic decision.**

- **Effort:** +6-8 days (16-20 days total vs 10-12 days without both)
- **ROI:** Prevents 2-3 weeks refactoring + enables user features + eAI foundation
- **Risk:** LOW (feature gated, backward compatible, governance before reproductive mechanics)
- **Foundation:** Sets up IndicAgent for complex agents, multi-user execution, AND evolvable AI

The revised Phase 095 is now **future-proof** for:
- Multi-tenant, multi-user agent execution
- Complex agent development (tool use, composition, stateful sessions)
- Evolvable AI (genome versioning, promotion gates, lineage tracking)

---

**Decision:** Proceed with Plans 00-08 (Multi-Tenant + Genome Foundation)
**Timeline:** ~16-20 days total (vs ~10-12 days without both additions)
**Risk:** LOW (feature gates, backward compatible)
**Strategic Value:** VERY HIGH (enables user features, prevents refactoring, foundation for complexity AND eAI)
