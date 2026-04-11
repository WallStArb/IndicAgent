# AI Layer Refactor Design v3 — Ideas + Data Validation

**Date:** 2026-04-08
**Status:** Ready for Implementation
**Phase:** v2.2 (Phase 57)
**Approach:** Build shared infrastructure → refactor narrative → build 1 idea at a time → validate with data

---

## Executive Summary

**Problem:** `ai_narrative_service.py` (1,327 lines) is a monolith. Swarm agents duplicate LLM infrastructure. No outcome tracking. 14 AI services proposed but no validation.

**Solution:** Shared infrastructure → narrative refactor → **6 prioritized ideas** (build 1 at a time) → validate with data → keep what works.

**Key Insight:** Humans generate ideas, data validates them. Don't build 14 things in parallel. Build 1, measure, then decide what's next.

---

## Phase 1: Shared Infrastructure (Week 1)

**Goal:** Eliminate duplication, standardize patterns, enable outcome tracking.

### Files to Create:
```
src/core/llm/
├── __init__.py           # Exports: LLMProviderChain, OutcomeTracker
├── providers.py          # LLMProvider classes with circuit breaker
├── outcomes.py           # OutcomeTracker (llm_calls → signal_ledger backfill)
└── circuit_breaker.py    # Existing circuit breaker logic
```

### Core Components:

#### 1. LLMProviderChain
```python
class LLMProviderChain:
    """Chain of LLM providers with fallback and circuit breaker.

    Simple, reliable:
    - Try providers in order (Ollama → OpenRouter → fallback)
    - Circuit breaker per provider (5 failures = open for 60s)
    - Track every call to llm.calls stream (for outcome analysis)
    """

    async def generate(self, prompt: str, call_type: str) -> LLMResponse:
        """Try each provider in sequence, track to llm.calls, return response."""
```

#### 2. OutcomeTracker
```python
class OutcomeTracker:
    """Backfill LLM outcomes from signal_ledger.

    Every 15 minutes:
    1. Query signal_ledger for resolved signals (with llm_call_id)
    2. Backfill llm_calls.outcome (pnl_r, mae, mfe, win)
    3. Compute per-model statistics (win_rate, avg_pnl_r)
    """
```

---

## Phase 2: Narrative Refactor (Week 1-2)

**Goal:** 1,327-line monolith → modular, testable components.

### Current State:
```python
# services/ai_narrative_service.py (1,327 lines)
class AINarrativeService:
    # Mixed concerns:
    # - Kafka consumer/producer logic
    # - LLM calling (duplicated!)
    # - Prompt building (scattered)
    # - Narrative generation (monolithic)
    # - Group synthesis (entangled)
```

### Future State:
```python
# services/ai_narrative_agent.py (~200 lines)
class AINarrativeAgent(BaseAgent):
    """Thin coordinator: Kafka I/O + orchestration."""

    def __init__(self):
        from src.core.llm import LLMProviderChain, OutcomeTracker
        from src.intelligence.narrative import (
            NarrativeOrchestrator,
            GroupSynthesizer,
        )

        self._llm_chain = LLMProviderChain([...])
        self._orchestrator = NarrativeOrchestrator(llm_chain=self._llm_chain)
        self._synthesizer = GroupSynthesizer(llm_chain=self._llm_chain)

# src/intelligence/narrative/
├── orchestrator.py    # NarrativeOrchestrator (per-signal narratives)
├── synthesizer.py     # GroupSynthesizer (cross-asset synthesis)
├── prompts.py          # All prompt building (extracted, testable)
└── parsers.py          # Signal parsing logic (extracted, reusable)
```

---

## Phase 3: 6 Prioritized Ideas (Week 2+)

**Build 1 at a time. Validate with data. Keep what works.**

### Priority 1: SkepticAgent (S6)
*"What's wrong with this signal?"*

**What it does:**
- Analyze signal features, predict failure probability
- "This signal has 30% fail risk because: [reasons]"

**Complexity:** Low (prompt LLM with signal features)
**Value:** High (prevent bad trades)
**Testable:** Do high fail-prob signals actually fail more?

**Build time:** 2-3 days
**Validation time:** 7-14 days (wait for outcomes)

---

### Priority 2: Volume Profile Anomaly (S2)
*"Price rejected at VAH/VAL — reversal coming?"*

**What it does:**
- Detect volume profile rejections (price touches VAH/VAL and reverses)
- "VP rejection at VAH — potential reversal incoming"

**Complexity:** Medium (detect VP rejections)
**Value:** High (VP rejection = strong signal)
**Testable:** Do VP rejections correlate with reversals?

**Build time:** 3-4 days
**Validation time:** 7-14 days

---

### Priority 3: Regime Explainer (N6)
*"Why was this signal suppressed?"*

**What it does:**
- Explain regime gating logic
- "Signal suppressed: trend filter (-0.3), regime disagreement (0.2)"

**Complexity:** Low (explain regime gating logic)
**Value:** High (humans confused when signals disappear)
**Testable:** Do humans understand system better?

**Build time:** 1-2 days
**Validation time:** 3-5 days (human feedback)

---

### Priority 4: Trade Journal (Service 4)
*Daily summary: signals taken, outcomes, lessons learned*

**What it does:**
- Aggregate signal_ledger daily
- "Today: 12 signals, 8 winners, +2.3R. Top signal: CIS +1.8R"

**Complexity:** Low (aggregate signal_ledger daily)
**Value:** High (humans want this)
**Testable:** Do humans who read it improve faster?

**Build time:** 2-3 days
**Validation time:** 14-30 days (human improvement)

---

### Priority 5: Counterfactual Narratives (N5)
*"What if we'd taken the other signal?"*

**What it does:**
- Compare 2 signals with outcomes
- "You took CIS (+1.2R). Alpha setup (-0.8R). Correct decision."

**Complexity:** Medium (compare 2 signals with outcomes)
**Value:** High (humans learn from "what if")
**Testable:** Do humans make better decisions after seeing these?

**Build time:** 3-4 days
**Validation time:** 14-30 days (human behavior change)

---

### Priority 6: Correlation Cluster (S1)
*"Equities decoupled — regime breakdown?"*

**What it does:**
- Track equity correlations, detect breakdowns
- "ES/NQ decorrelation (0.12) → potential regime change"

**Complexity:** Medium (track equity correlations)
**Value:** High (early warning of regime change)
**Testable:** Do decorrelation periods predict regime changes?

**Build time:** 4-5 days
**Validation time:** 14-30 days (need multiple cycles)

---

## Implementation Timeline

### Week 1: Infrastructure + Narrative Refactor
- **Days 1-2:** Extract `src/core/llm/`
  - `providers.py` (LLMProviderChain)
  - `outcomes.py` (OutcomeTracker)
  - `circuit_breaker.py`

- **Days 3-4:** Refactor narrative service
  - Extract `src/intelligence/narrative/`
  - Rewrite `ai_narrative_agent.py` as thin coordinator

- **Days 5:** Deploy + validate
  - Unit tests for each component
  - Integration tests for end-to-end flow
  - Deploy alongside existing service (no shadow mode needed for refactor)

### Week 2: Build Priority 1 (SkepticAgent)
- **Days 1-3:** Build SkepticAgent
  - Use `LLMProviderChain` for LLM calls
  - Track to `llm.calls` stream
  - Store predictions to `signal_ledger`

- **Days 4-5:** Deploy + validate
  - Run on all signals
  - Track predictions vs outcomes

### Week 3-4: Validate SkepticAgent
- **Goal:** Wait for outcomes, measure performance
- **Question:** Do high fail-prob signals actually fail more?
- **Decision:**
  - If p < 0.05, n ≥ 30 → Keep it, build Priority 2
  - If p > 0.05 → Kill it, reconsider priority list

### Week 5+: Build Next Priority (or Pivot)
- **If SkepticAgent worked:** Build Priority 2 (Volume Profile Anomaly)
- **If SkepticAgent failed:** Re-prioritize list, build something else
- **If humans ask for X:** Build X (not on list)

---

## Success Criteria

### Week 1-2 (Infrastructure):
- ✅ Narrative service refactored (1,327 → 200 lines)
- ✅ Shared LLM infrastructure working
- ✅ No regression in narrative quality
- ✅ SkepticAgent tracking predictions

### Week 3-4 (Validation):
- ✅ 100+ SkepticAgent predictions tracked
- ✅ 30+ resolved signals with outcomes
- ✅ Statistical analysis complete

### Week 5+ (Decisions):
- ✅ Evidence-based decision on SkepticAgent
- ✅ Next priority selected (based on data or human feedback)
- ✅ Continue building → tracking → validating cycle

---

## What We're NOT Doing

**Premature Building:**
- ❌ Building 14 services in parallel — Build 1 at a time
- ❌ Shadow mode for new services — Just track and validate
- ❌ Complex routing — Manual selection until you have data

**Over-Engineering:**
- ❌ A/B testing frameworks — Manual analysis fine for now
- ❌ Auto-promotion logic — Human review after validation
- ❌ Complex metrics — Start simple: win_rate, avg_pnl_r

**Ideas We're Deferring:**
- ❌ N1-N4: Multi-signal, time-based, historical, portfolio narratives (lower value)
- ❌ S3-S5, S7: Options flow, macro events, earnings, execution quality (no data)
- ❌ Services 1-3, 5: Risk, sentiment, strategy, anomaly triage (unclear value)

---

## Renaissance Principles

**Before Building Anything:**
- [ ] What problem are we solving? (Be specific)
- [ ] What's the simplest thing that could work? (Avoid complexity)
- [ ] How will we measure success? (p < 0.05, n ≥ 30)
- [ ] What will we learn? (Every build is an experiment)

**Before Keeping Anything:**
- [ ] Does it work in practice? (Not theory)
- [ ] Do we have 30+ samples? (Statistical significance)
- [ ] Is p < 0.05? (Not random chance)
- [ ] Does it add value? (Not just complexity)

**Before Adding Complexity:**
- [ ] What's the maintenance burden? (Complexity = bugs)
- [ ] Can we achieve the same goal simpler? (KISS principle)
- [ ] What are we NOT building? (Opportunity cost)

---

## Key Differences from v1/v2

**v1/v2 approach:**
- 14 AI services defined upfront
- Build in parallel
- Shadow mode for everything
- Complex timeline

**v3 approach:**
- 6 prioritized ideas (menu, not build list)
- Build 1 at a time
- Track and validate (no shadow mode for new services)
- Iterate based on data + human feedback

---

## Decision Tree After Each Build

```
Build Priority N → Track → Validate
                     ↓
          ┌──────────┴──────────┐
          │                     │
       Worked               Failed
     (p < 0.05)            (p > 0.05)
          │                     │
          v                     v
    Keep it              Kill it
    Build next           Re-prioritize
    (Priority N+1)       (Ask humans: what do you want?)
```

---

## References

- **Renaissance Principles** — CLAUDE.md "Renaissance Principles" section
- **Agent DAG Pattern** — CLAUDE.md "Renaissance Agentic DAG Principles" section
- **Phase 57 Design** — Unified Intelligence Pipeline (I1-I7)
- **v2 Designs** — `docs/plans/2026-04-08-ai-layer-refactor-design-v2.md`

---

## Next Steps

1. ✅ **Review this design** — Approved 2026-04-08
2. **Archive v1/v2 designs** — Move to `docs/plans/archive/`
3. **Create GSD implementation plan** — Phase 57 (Week 1-2)
4. **Begin Week 1** — Extract shared infrastructure
5. **Build → Track → Validate → Iterate**

---

**Remember:** Humans generate ideas, data validates them. Build one thing at a time, measure it, then decide what's next.
