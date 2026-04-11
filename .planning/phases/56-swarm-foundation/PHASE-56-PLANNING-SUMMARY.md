# Phase 56: Swarm Foundation — Planning Summary

**Date:** 2026-04-09
**Status:** Ready for Implementation
**Design Doc:** `docs/plans/2026-04-09-phase-56-swarm-foundation-design.md`
**Plans:** 8 plans across 5 waves

---

## What's Being Built

Full swarm infrastructure: shared LLM layer, corrected DAG protocols, narrative refactor, shadow persistence, and the two new services that wire it all together.

## Wave Structure

| Wave | Plans | Gate |
|------|-------|------|
| 1 | 56-01 (LLM Move), 56-02 (Narrative Module) | — parallel |
| 2 | 56-03 (Protocol+Schema), 56-04 (Safety+Aggregator) | — parallel |
| 3 | 56-05 (Narrative Service) | 56-01 + 56-02 done |
| 4 | 56-06 (DB + Stream Keys) | 56-03 + 56-04 done |
| 5 | 56-07 (Swarm Services), 56-08 (PromotionAuditor) | 56-06 done — parallel |

## Plan Summaries

**56-01:** Move `src/intelligence/llm_providers.py` → `src/core/llm/providers.py`. Add `call_type` + Kafka audit. Backward-compat re-export stub. (10 tests)

**56-02:** Create `src/intelligence/narrative/` — pure prompt builders, parsers, `NarrativeOrchestrator`, `GroupSynthesizer`. All against real `BarIntelligenceRecord`/`IntelligenceEvent` schemas. (12 tests)

**56-03:** Fix `IAlphaContributor` protocol (`compute(SwarmContext)→AgentResult`), add `SwarmContext`/`SwarmContextCache`, extend `AgentResult`+`AlphaMultiplier` schemas, update 4 stub agents + contributor config. (8 tests)

**56-04:** Rewrite `SafeSwarmWrapper` (wraps instances, enforces timeout+bounds, reports violations). Create `SwarmAggregator`, `SwarmMetrics` (9 Golden Signal metrics via prometheus_client directly), `PromptRegistry` (bounded template lookup + sanitization), update `registry.py` with DI + protocol validation. (8 tests)

**56-05:** Write `services/ai_narrative_agent.py` (~200 lines) using `NarrativeOrchestrator`. Archive 1,327-line monolith. Update systemd unit. (2 tests)

**56-06:** Add 5 swarm stream key functions (`path_a`, `path_b`, `world_state`, 2×DLQ). Write `production/migrations/058_alpha_multiplier_shadow.sql` hypertable with regime-segmented partial index. (5 tests)

**56-07:** Create `SwarmOrchestratorAgent` (bar_loop + signal_loop, two-phase pub, `BoundedLRUSet` dedup, DLQ, backpressure) and `SwarmWriterAgent` (batch flush → `alpha_multiplier_shadow`, DLQ). Systemd units. Extend `alpha_promotion.py` with regime-segmented Pearson analysis. (6 tests)

## Success Criteria

1. `LLMProviderChain` in `src/core/llm/` — all imports updated
2. `ai_narrative_service.py` archived → `ai_narrative_agent.py` ≤ 210 lines
3. `IAlphaContributor.compute(SwarmContext)` is the only contract — no `get_multiplier` callers
4. `SafeSwarmWrapper` wraps instances, reports violations to Prometheus
5. `SwarmOrchestratorAgent` publishes Path A within 10ms of signal
6. `alpha_multiplier_shadow` hypertable exists and receives writes
7. All agents `shadow_only=True` — no production promotion without segment-level ρ ≥ 0.4
8. DLQ topics wired for both services
9. 49 TDD tests pass

## What Phase 66 Builds

**SkepticAgent** — `IAlphaContributor` that asks "what's wrong with this signal?" via LLM. Shadow-validates against `signal_ledger` outcomes.

Note: Phase 57 (IntelligencePipelineComputeAgent) and Phase 58 (Pipeline Parallelization) are already complete. Phase 66 is the next available number after Phase 65 (Gradient Audit).
