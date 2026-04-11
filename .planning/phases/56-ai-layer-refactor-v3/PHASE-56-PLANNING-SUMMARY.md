# Phase 56: AI Layer Refactor v3 — Planning Summary

**Date:** 2026-04-08
**Status:** Ready for Implementation
**Plans:** 3 plans (2,438 total lines)
**Design Doc:** `docs/plans/2026-04-08-ai-layer-refactor-design-v3.md`

---

## Executive Summary

Phase 56 implements the **AI Layer Refactor v3** design — a pragmatic, data-driven approach to building AI capabilities. Instead of building 14 services in parallel, we're creating shared infrastructure and building **1 idea at a time**, validating with data, and iterating based on what works.

**Core Principle:** Humans generate ideas, data validates them.

## What's Being Built

### Phase 1: Shared Infrastructure (Plan 56-01)
**Goal:** Eliminate LLM infrastructure duplication

**Deliverables:**
- `src/core/llm/providers.py` — LLMProviderChain with circuit breaker
- `src/core/llm/circuit_breaker.py` — CircuitBreaker with OPEN/CLOSED/HALF_OPEN states
- `src/core/llm/__init__.py` — Module exports
- Comprehensive TDD tests (10 tests total)

**Key Features:**
- Provider chain: Ollama → OpenRouter fallback
- Circuit breaker: Opens after 5 failures, closes after success
- All LLM calls tracked to `llm.calls` topic
- Thread-safe asyncio operations

**Success Criteria:**
- LLMProviderChain can call Ollama and fallback to OpenRouter
- Circuit breaker opens after 5 failures, closes after 60s
- Every LLM call publishes to llm.calls topic
- 10 TDD tests pass

### Phase 2: Narrative Refactor (Plan 56-02)
**Goal:** Extract narrative logic from 1,327-line monolith

**Deliverables:**
- `src/intelligence/narrative/prompts.py` — Testable prompt building
- `src/intelligence/narrative/parsers.py` — Signal parsing utilities
- `src/intelligence/narrative/orchestrator.py` — Single-signal narratives
- `src/intelligence/narrative/synthesizer.py` — Multi-signal synthesis
- `src/intelligence/narrative/__init__.py` — Module exports
- Comprehensive TDD tests (10 tests total)

**Key Features:**
- Pure functions (no Kafka/infrastructure in narrative module)
- NarrativeOrchestrator uses LLMProviderChain
- GroupSynthesizer for multi-signal aggregation
- Reusable across future AI agents

**Success Criteria:**
- Narrative logic extracted to src/intelligence/narrative/
- Prompts and parsers are pure functions (testable)
- NarrativeOrchestrator uses LLMProviderChain
- 10 TDD tests pass

### Phase 3: Service Refactor (Plan 56-03)
**Goal:** Reduce ai_narrative_service from 1,327 → ~200 lines

**Deliverables:**
- `services/ai_narrative_agent.py` — Thin coordinator (~200 lines)
- `services/_archived_ai_narrative_service.py` — Archived monolith
- `production/systemd/indicagent-ai-narrative.service` — Updated unit
- TDD tests (2 tests)

**Key Features:**
- Agent is thin coordinator (Kafka I/O + orchestration)
- All narrative logic delegated to src/intelligence/narrative/
- LLM calls use LLMProviderChain
- 85% code reduction (1,327 → ~200 lines)

**Success Criteria:**
- ai_narrative_agent.py ~200 lines
- No narrative logic in agent (delegated to module)
- ai_narrative_service.py archived
- Systemd unit updated
- 2 TDD tests pass

---

## Wave Structure

| Wave | Plans | Parallel? | Dependencies |
|------|-------|-----------|--------------|
| 1 | 56-01, 56-02 | Yes | 56-02 → 56-01 (LLM infrastructure) |
| 2 | 56-03 | No | 56-03 → 56-01, 56-02 |

**Wave 1 Execution:**
- Plan 56-01 creates `src/core/llm/` infrastructure
- Plan 56-02 creates `src/intelligence/narrative/` module
- Both can run independently (no file overlap)

**Wave 2 Execution:**
- Plan 56-03 refactors service to use modules from Wave 1
- Must wait for both 56-01 and 56-02 to complete

---

## Dependency Graph

```
56-01 (LLM Infrastructure)
    ↓
56-02 (Narrative Module) → 56-03 (Service Refactor)
```

**File Ownership:**
- Wave 1: No overlap (different modules)
- Wave 2: Depends on Wave 1 outputs (LLM chain, narrative module)

---

## Success Criteria (Phase Level)

1. ✅ Shared LLM infrastructure created (`src/core/llm/`)
2. ✅ Narrative service refactored (1,327 → ~200 lines)
3. ✅ Narrative logic extracted to `src/intelligence/narrative/`
4. ✅ LLM calls tracked to `llm.calls` topic
5. ✅ Circuit breaker prevents cascading failures
6. ✅ All components unit-tested (22 TDD tests)
7. ✅ Foundation ready for Priority 1 (SkepticAgent)

---

## What's Next (After Phase 56)

### Week 2: Build Priority 1 (SkepticAgent)
- **What:** "What's wrong with this signal?" — predict failure probability
- **Build Time:** 2-3 days
- **Validation:** 7-14 days (wait for outcomes)
- **Question:** Do high fail-prob signals actually fail more?

### Week 3-4: Validate SkepticAgent
- **Goal:** 100+ predictions, 30+ resolved signals
- **Decision:** If p < 0.05, keep it → build Priority 2
- **Decision:** If p > 0.05, kill it → re-prioritize

### Week 5+: Build Next Priority
- If SkepticAgent worked → Build Priority 2 (Volume Profile Anomaly)
- If SkepticAgent failed → Ask humans: what do you want?
- If humans request X → Build X (not on list)

---

## Renaissance Principles Applied

**Before Building:**
- [x] What problem? Monolithic ai_narrative_service (1,327 lines), duplicated LLM logic
- [x] Simplest thing? Shared infrastructure + module extraction
- [x] Measure success? p < 0.05, n ≥ 30 for each AI idea
- [x] What will we learn? Which AI ideas actually work (data validation)

**Before Keeping:**
- [ ] Does it work? (After Phase 56: SkepticAgent validation)
- [ ] 30+ samples? (After 7-14 days of tracking)
- [ ] p < 0.05? (Statistical significance test)
- [ ] Adds value? (Not just complexity)

---

## Files Modified (3 Plans)

### Plan 56-01 (Infrastructure)
- `src/core/llm/__init__.py` (new)
- `src/core/llm/providers.py` (new)
- `src/core/llm/circuit_breaker.py` (new)
- `tests/unit/test_llm_providers.py` (new)
- `tests/unit/test_circuit_breaker.py` (new)

### Plan 56-02 (Narrative Module)
- `src/intelligence/narrative/__init__.py` (new)
- `src/intelligence/narrative/prompts.py` (new)
- `src/intelligence/narrative/parsers.py` (new)
- `src/intelligence/narrative/orchestrator.py` (new)
- `src/intelligence/narrative/synthesizer.py` (new)
- `tests/unit/test_narrative_prompts.py` (new)
- `tests/unit/test_narrative_parsers.py` (new)
- `tests/unit/test_narrative_orchestrator.py` (new)

### Plan 56-03 (Service Refactor)
- `services/ai_narrative_agent.py` (new, ~200 lines)
- `services/_archived_ai_narrative_service.py` (archived, 1,327 lines)
- `production/systemd/indicagent-ai-narrative.service` (updated)
- `tests/unit/service_tests/test_ai_narrative_agent.py` (new)

---

## Testing Strategy

**TDD Coverage:**
- Plan 56-01: 10 tests (7 circuit breaker + 3 provider)
- Plan 56-02: 10 tests (4 prompts + 4 parsers + 2 orchestrator)
- Plan 56-03: 2 tests (agent initialization + signal processing)
- **Total: 22 TDD tests**

**Integration Tests (Manual):**
- Start ai_narrative_agent.py
- Verify Kafka connection (topics_consumed)
- Check logs for "AI Narrative Agent initialized"
- Verify narrative generation (check narratives:SYMBOL:TF topic)

---

## Risk Mitigation

**Risk 1:** LLM provider outage
- **Mitigation:** Circuit breaker opens after 5 failures, falls back to next provider

**Risk 2:** Narrative quality regression
- **Mitigation:** All prompts/parsers unit-tested, direct deployment (no shadow mode needed for refactor)

**Risk 3:** Service deployment downtime
- **Mitigation:** Refactor is drop-in replacement (same Kafka topics, same systemd unit)

**Risk 4:** SkepticAgent doesn't work
- **Mitigation:** Build 1 at a time, validate with data, kill if p > 0.05

---

## Execution Instructions

### Wave 1 (Parallel Execution)

**Terminal 1:**
```bash
/gsd-execute-phase 56 --plan 01
```

**Terminal 2 (simultaneous):**
```bash
/gsd-execute-phase 56 --plan 02
```

### Wave 2 (After Wave 1 Complete)

```bash
/gsd-execute-phase 56 --plan 03
```

### Verification

```bash
# Run all tests
.venv/bin/pytest tests/unit/test_llm_providers.py tests/unit/test_circuit_breaker.py tests/unit/test_narrative_*.py tests/unit/service_tests/test_ai_narrative_agent.py -v

# Verify code reduction
wc -l services/ai_narrative_agent.py  # Should be ~200
wc -l services/_archived_ai_narrative_service.py  # Should be 1,327

# Verify no broken imports
grep -r "from services.ai_narrative_service" . --include="*.py"
# Should return nothing

# Start agent
python services/ai_narrative_agent.py
```

---

## References

- **Design Doc:** `docs/plans/2026-04-08-ai-layer-refactor-design-v3.md`
- **ROADMAP:** `.planning/ROADMAP.md` (Phase 56)
- **STATE:** `.planning/STATE.md`
- **CLAUDE.md:** Renaissance principles, AI working rules

---

**Remember:** Humans generate ideas, data validates them. Build one thing at a time, measure it, then decide what's next.
