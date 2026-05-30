# Phase 095 Plan Revision Summary

**Revised:** 2026-05-29 (scope trim) / 2026-05-21 (original review fixes)
**Trigger:** Cross-AI review feedback (Gemini + Codex) + v2.7 retrospective scope correction
**Status:** Trimmed to core scope — Plans 01-05 only, ready for implementation

## Scope Change (2026-05-29)

Phase 095 was over-scoped during planning. Three plan groups extracted:

- **Plan 00 (multi-tenant UserContext/AgentLimits)** — deferred. No user boundary exists yet; adding it now is premature. Revisit when building user-facing APIs.
- **Plan 07 (AgentGenome)** — extracted to Phase 102 Plan 01. Genome infrastructure belongs in the genetic infrastructure phase, not the PydanticAI adapter phase.
- **Plan 08 (PromotionGate/DemotionGate)** — extracted to Phase 101. Promotion/demotion criteria belong alongside the composite fitness function, not here.

Also removed: `095-COMPLETE-FOUNDATION.md`, `095-MULTI-TENANT-ROADMAP.md` (reflected the over-scoped vision), misleading `095-08-SUMMARY.md` (Plan 08 was never executed).

**Active plans: 01-05.** Migration path bug (wrong `migrations/` path) was in deleted plans only — remaining plans are clean.

## Overview

All 5 plans (094-01 through 094-05) have been revised to incorporate comprehensive
review feedback. The revised plans fix critical bugs, address architectural concerns,
and make validation tests executable.

## Critical Issues Fixed

### Plan 01 (AgentDeps) - Minor Fixes
- **Added frozen=True** for immutability (per review suggestion)
- **Fixed tests** to use real fixtures instead of undefined mocks

### Plan 02 (PydanticAIAdapter) - CRITICAL BUG FIXES
- **FIXED: Async/await bug** - Changed `return self._to_agent_output(...)` to `return await self._to_agent_output(...)`
- **FIXED: LLM audit trail bypass** - Now routes through `BaseAIAgent._llm_generate()` for audit preservation
- **FIXED: Constructor params** - Accepts llm_chain, db_pool, memory_client (not hardcoded)
- **Added `_build_user_prompt()` hook** - For subclass prompt parity (e.g., build_skeptic_prompt())

### Plan 03 (SkepticResult) - Test Fixes
- **FIXED: Test instantiations** - All tests now include required fields (failure_probability, confidence, reasoning)
- **Clarified validation behavior** - Field(ge=0.0, le=1.0) REJECTS with ValidationError (does NOT clamp)
- **Clarified reasoning length** - max_length=500 ≈ 100 words (conservative cap)

### Plan 04 (SkepticComputeAgentPydantic) - MAJOR ARCHITECTURAL FIXES
- **FIXED: Dependency ordering** - pydantic-ai now added to requirements.txt in Task 0 (before agent code)
- **FIXED: Inheritance mismatch** - No longer calls `_build_multiplier_output()` (not inherited from BaseAIAgent)
- **FIXED: Manual AgentOutput construction** - `_to_agent_output()` manually constructs AgentOutput
- **FIXED: deps_type=AgentDeps** - No longer None, violates AGENT-EXEC-02
- **FIXED: Model configuration** - Uses Ollama model string (not llm_chain._llm, which doesn't exist)
- **FIXED: Prompt parity** - Uses `build_skeptic_prompt()` for legacy agent parity
- **FIXED: Test dependencies** - Tests avoid Pydantic AI runtime dependencies (mock results only)

### Plan 05 (Service Registration) - Validation Fixes
- **FIXED: Agent ID corrections** - Uses skeptic_v1 (legacy) and skeptic_v2_pydantic (new)
- **FIXED: Validation tests executable** - Added assertions to shadow validation tests
- **FIXED: Feature gate added** - ENABLE_PYDANTIC_SKEPTIC_SHADOW defaults to false
- **FIXED: Version pinning** - pydantic-ai>=0.0.13,<0.1.0 (not >=0.0.1)
- **NEW: Integration test** - Verifies actual service registration behavior
- **FIXED: BaseAIAgent preservation test** - Uses direct imports (not file I/O)

## Remaining Issues Addressed

### Wave Consolidation
- Plans reorganized into 3 waves to match ROADMAP.md:
  - **Wave 1**: Plans 01-02 (AgentDeps + PydanticAIAdapter)
  - **Wave 2**: Plans 03-04 (SkepticResult + SkepticComputeAgentPydantic)
  - **Wave 3**: Plan 05 (Service Registration + Validation)

### Documentation Improvements
- All threat models updated with FIXED annotations
- Test failures documented with root cause analysis
- API usage corrections documented (e.g., llm_chain._llm doesn't exist)

## Implementation Readiness

### Before Execution
1. **Verify pydantic-ai compatibility** - Test with existing pydantic>=2.12.0
2. **Pin exact version** - Replace >=0.0.13,<0.1.0 with tested version
3. **Configure Ollama** - Verify structured output support (Ollama v0.5.0+)
4. **Feature gate decision** - Determine if ENABLE_PYDANTIC_SKEPTIC_SHADOW should default false

### Risk Assessment (Post-Revision)
- **Overall Risk: LOW** (down from HIGH in Codex review)
- **Justification:** All implementation-breaking issues fixed; validation tests executable; feature gating prevents uncontrolled rollout

## Verification Checklist

Before marking phase complete:
- [ ] All unit tests pass (Plans 01-04)
- [ ] Integration tests pass (Plan 05)
- [ ] pydantic-ai installed and version pinned
- [ ] Feature gate configuration documented
- [ ] Shadow validation protocol documented in runbook
- [ ] BaseAIAgent preservation verified (not deleted)
- [ ] LLM audit trail preservation verified (llm_calls populated)

## Next Steps

1. **Review revised plans** - User approval of changes
2. **Begin Wave 1** - Execute Plans 01-02 in sequence
3. **Begin Wave 2** - Execute Plans 03-04 after Wave 1 complete
4. **Begin Wave 3** - Execute Plan 05 after Wave 2 complete
5. **Shadow validation** - Run skeptic_v2_pydantic in shadow mode until n >= 100
6. **Promotion decision** - Based on calibration metrics and parse_success_rate

---

**Revised by:** Claude Code (incorporating Gemini + Codex review feedback)
**Review source:** `.planning/phases/094-pydantic-ai-agents/094-REVIEWS.md`
**Plan files updated:** 094-01-PLAN.md through 094-05-PLAN.md
