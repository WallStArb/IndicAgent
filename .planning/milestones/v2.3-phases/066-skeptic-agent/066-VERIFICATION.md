---
phase: 066-skeptic-agent
verified: 2026-04-24T23:15:00Z
status: human_needed
score: 16/16 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Deploy indicagent-swarm-dispatch.service and send a test signal through intelligence.i7.signals"
    expected: "SwarmDispatchService consumes signal, dispatches to all 3 agents, records results to alpha_multiplier_shadow, publishes to swarm results topic"
    why_human: "Requires running Kafka + TimescaleDB + LLM providers; cannot verify full end-to-end flow with grep"
  - test: "Run validate_skeptic.py after 30+ days of shadow data collection"
    expected: "Per-segment Pearson rho reported; graduation gate evaluation outputs pass/fail per segment"
    why_human: "Requires 30+ days of accumulated shadow predictions matched to resolved signal_ledger outcomes"
  - test: "Verify LLM prompt quality -- inspect actual prompt sent to LLM for a real signal"
    expected: "All SwarmContext fields populated with real data; lead_context and volume_profile enrichment visible when available"
    why_human: "LLM prompt quality and response parsing can only be validated with real LLM responses, not mocks"
---

# Phase 066: Swarm Intelligence Agents Verification Report

**Phase Goal:** Single SwarmDispatchService running Skeptic, Correlation, and Volume agents as pure compute classes. LLM-powered signal analysis consuming intelligence.i7.signals, recording to alpha_multiplier_shadow. Consolidated architecture: 1 service, 3 agents, shared infrastructure. 4 plans.
**Verified:** 2026-04-24T23:15:00Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SwarmContext has lead_context and volume_profile optional fields (no object.__setattr__ hacks) | VERIFIED | context.py lines 71-73: proper Pydantic fields. model_copy in service line 287. No __setattr__ anywhere. |
| 2 | SwarmDispatchService owns all infrastructure: one Kafka bar consumer, one signal consumer, one DB pool, one ShadowRecorder, one LLMProviderChain, one SwarmContextCache | VERIFIED | service.py lines 79-95: shared infra. _setup() lines 97-137: initializes all. Dual-loop lines 149-157. |
| 3 | SkepticAgentComputeAgent is a pure compute class extending SwarmBaseAgent -- no Kafka/DB/infrastructure code | VERIFIED | skeptic_agent.py: no Kafka/DB imports. Extends SwarmBaseAgent. Only LLM call + JSON parse. |
| 4 | All 3 agents registered in agent list, run via asyncio.gather per signal | VERIFIED | service.py lines 86-90: 3 agents in _agents. Line 215: asyncio.gather(*[agent.compute(enriched)...]). |
| 5 | 5m+ TF filter only -- 1m signals skipped | VERIFIED | service.py line 43: _ELIGIBLE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"}). Line 197: if tf not in _ELIGIBLE_TFS: return. |
| 6 | LLM returns structured JSON with failure_probability, confidence, risk_factors, reasoning | VERIFIED | All 3 agents: _parse_*_response() functions handle clean JSON, preamble, markdown blocks. _validate_*_fields() enforces types and clamps. |
| 7 | Transfer function multiplier = (1.0 - failure_probability) * llm_confidence | VERIFIED | skeptic_agent.py:81, correlation_agent.py:76, volume_agent.py:75 -- identical formula. |
| 8 | All predictions persisted to alpha_multiplier_shadow via shared ShadowRecorder | VERIFIED | service.py lines 221-231: _recorder.record() called for each result with all fields. |
| 9 | On LLM failure/timeout: SwarmBaseAgent returns neutral (multiplier=1.0) | VERIFIED | base_agent.py: timeout + exception isolation. _neutral() returns multiplier=1.0, confidence=0.0. Each agent calls _neutral() on empty/parse-failed responses. |
| 10 | Prompt version tracked in every prediction's features JSONB | VERIFIED | skeptic:94, correlation:89, volume:92 -- "prompt_version": ACTIVE_VERSION in metadata dict. |
| 11 | _find_lead_context() builds a real SwarmContext from cache data (not a stub returning None) | VERIFIED | service.py lines 292-387: constructs full SwarmContext from cache SimpleNamespace proxies using _safe() helper. Test test_find_lead_context_builds_from_cache passes. |
| 12 | SwarmContext seeded from DB on startup via seed_from_db_row | VERIFIED | service.py lines 415-438: _seed_context_cache queries intelligence_features, calls seed_from_db_row. Test test_seed_context_cache passes. |
| 13 | CorrelationAgent reads context.lead_context (not _lead_ctx) for lead index data | VERIFIED | correlation_agent.py:91-92: context.lead_context.symbol. No _lead_ctx anywhere in codebase. |
| 14 | VolumeAgent reads context.volume_profile (not _volume_data) for VP fields | VERIFIED | volume_agent.py:78-79: context.volume_profile. No _volume_data anywhere in codebase. |
| 15 | Neither CorrelationAgent nor VolumeAgent has Kafka/DB/infrastructure code -- pure compute only | VERIFIED | Both files: only imports are LLMProviderChain, SwarmBaseAgent, AgentResult, SwarmContext. No Kafka/DB/asyncpg imports. |
| 16 | Both agents produce AgentResult with prompt_version in metadata | VERIFIED | correlation_agent.py:89, volume_agent:92 -- "prompt_version": ACTIVE_VERSION. |

**Score:** 16/16 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/swarm/context.py` | SwarmContext with lead_context + volume_profile fields | VERIFIED | Lines 71-73: proper Pydantic optional fields on frozen model |
| `src/intelligence/swarm/agents/skeptic_prompts.py` | Prompt registry with versioning | VERIFIED | PROMPT_REGISTRY dict, ACTIVE_VERSION="skeptic_v1", build_skeptic_prompt() |
| `src/intelligence/swarm/agents/skeptic_agent.py` | SkepticAgentComputeAgent (SwarmBaseAgent subclass) | VERIFIED | 151 lines, extends SwarmBaseAgent, implements _compute(), JSON parsing, clamping |
| `services/swarm_dispatch_service.py` | Single shared service with agent registry + context enrichment | VERIFIED | 449 lines, 3 agents registered, _enrich_context via model_copy, asyncio.gather dispatch |
| `services/indicagent-swarm-dispatch.service` | Systemd unit for SwarmDispatchService | VERIFIED | After=swarm-orchestrator, PYTHONUNBUFFERED=1, no WatchdogSec |
| `tests/unit/test_skeptic_agent.py` | Agent + prompt unit tests | VERIFIED | 7 tests: version check, prompt building, JSON parse, validation, clamping |
| `tests/unit/test_swarm_dispatch.py` | Service-level tests | VERIFIED | 8 tests: TF filter, enrichment, lead context, cache seeding, index mapping |
| `src/intelligence/swarm/agents/correlation_prompts.py` | Correlation prompt registry | VERIFIED | PROMPT_REGISTRY, build_correlation_prompt(), lead index context fields |
| `src/intelligence/swarm/agents/correlation_agent.py` | CorrelationAgentComputeAgent | VERIFIED | Extends SwarmBaseAgent, reads context.lead_context, prompt_version in metadata |
| `src/intelligence/swarm/agents/volume_prompts.py` | Volume prompt registry | VERIFIED | PROMPT_REGISTRY, build_volume_prompt(), VP fields |
| `src/intelligence/swarm/agents/volume_agent.py` | VolumeAgentComputeAgent | VERIFIED | Extends SwarmBaseAgent, reads context.volume_profile, prompt_version in metadata |
| `tests/unit/test_correlation_agent.py` | CorrelationAgent + prompt tests | VERIFIED | 10 tests including lead_context usage verification |
| `tests/unit/test_volume_agent.py` | VolumeAgent + prompt tests | VERIFIED | 9 tests including volume_profile usage verification |
| `tests/unit/test_swarm_dispatch_integration.py` | Integration tests for multi-agent dispatch | VERIFIED | 9 tests: concurrent dispatch, TF filter, enrichment, neutral fallback, independent recording |
| `scripts/compute_skeptic_baseline.py` | Naive baseline failure rates per segment | VERIFIED | Queries signal_ledger, groups by (hmm_regime, tf, regime_type, plugin), computes failure_rate |
| `scripts/validate_skeptic.py` | Statistical validation with graduation gate | VERIFIED | JOINs alpha_multiplier_shadow + signal_ledger, pearsonr per segment, gate: rho>=0.3, p<0.05, N>=30 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/swarm_dispatch_service.py` | `src/intelligence/swarm/agents/skeptic_agent.py` | agent registry import | WIRED | Line 37: `from ...skeptic_agent import SkepticAgentComputeAgent` |
| `services/swarm_dispatch_service.py` | `src/intelligence/swarm/agents/correlation_agent.py` | agent registry import | WIRED | Lines 34-36: `from ...correlation_agent import CorrelationAgentComputeAgent` |
| `services/swarm_dispatch_service.py` | `src/intelligence/swarm/agents/volume_agent.py` | agent registry import | WIRED | Line 38: `from ...volume_agent import VolumeAgentComputeAgent` |
| `services/swarm_dispatch_service.py` | `src/intelligence/swarm/context.py` | SwarmContextCache + _enrich_context | WIRED | Line 39: imports SwarmContext + SwarmContextCache. Lines 271-290: _enrich_context. |
| `skeptic_agent.py` | `src/core/swarm/base_agent.py` | extends SwarmBaseAgent | WIRED | `class SkepticAgentComputeAgent(SwarmBaseAgent)` |
| `correlation_agent.py` | `src/core/swarm/base_agent.py` | extends SwarmBaseAgent | WIRED | `class CorrelationAgentComputeAgent(SwarmBaseAgent)` |
| `volume_agent.py` | `src/core/swarm/base_agent.py` | extends SwarmBaseAgent | WIRED | `class VolumeAgentComputeAgent(SwarmBaseAgent)` |
| All 3 agents | `src/core/llm/chain.py` | LLMProviderChain.generate() | WIRED | Each agent stores self._llm = llm_chain, calls self._llm.generate() |
| `services/swarm_dispatch_service.py` | `src/core/ml/shadow.py` | ShadowRecorder.record() | WIRED | Line 27: import. Lines 129-131: init. Lines 221-231: per-result recording. |
| `correlation_agent.py` | `context.py` SwarmContext.lead_context | reads field | WIRED | Line 91-92: `context.lead_context.symbol` |
| `volume_agent.py` | `context.py` SwarmContext.volume_profile | reads field | WIRED | Lines 78-79: `context.volume_profile is not None` |
| `scripts/validate_skeptic.py` | `alpha_multiplier_shadow` | SQL JOIN | WIRED | Lines 66-67: FROM alpha_multiplier_shadow s JOIN signal_ledger l |
| `scripts/validate_skeptic.py` | `signal_ledger` | SQL JOIN on signal_id | WIRED | Line 67: JOIN signal_ledger l ON s.signal_id::uuid = l.signal_id::uuid |
| `scripts/compute_skeptic_baseline.py` | `signal_ledger` | historical outcome query | WIRED | Lines 57-58: FROM signal_ledger WHERE... |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `swarm_dispatch_service.py` | `ctx` (SwarmContext) | SwarmContextCache.build() | From Kafka bar events + DB seed | FLOWING |
| `swarm_dispatch_service.py` | `enriched` | model_copy with lead_context + volume_profile | From cache lookup (real SwarmContext construction) | FLOWING |
| `swarm_dispatch_service.py` | `results` | asyncio.gather of agent.compute() | LLM responses parsed to AgentResult | FLOWING |
| `skeptic_agent.py` | `multiplier` | (1.0 - failure_prob) * llm_confidence | From LLM JSON response | FLOWING |
| `validate_skeptic.py` | Pearson rho | pearsonr(failure_prob, win) | From alpha_multiplier_shadow JOIN signal_ledger | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Service import resolves | `python -c "from services.swarm_dispatch_service import SwarmDispatchService"` | Service import OK | PASS |
| All 3 agent imports resolve | `python -c "from ...skeptic_agent import SkepticAgentComputeAgent"` (+ corr, vol) | All 3 OK | PASS |
| Prompt versions exist | `python -c "from ...skeptic_prompts import ACTIVE_VERSION, PROMPT_REGISTRY"` | skeptic_v1, correlation_v1, volume_v1 | PASS |
| compute_skeptic_baseline.py --help | `python scripts/compute_skeptic_baseline.py --help` | Usage displayed, --days and --symbol-filter args | PASS |
| validate_skeptic.py --help | `python scripts/validate_skeptic.py --help` | Usage displayed, --agent required, --days and --symbol-filter | PASS |
| All 43 unit tests pass | `.venv/bin/pytest tests/unit/test_skeptic_agent.py test_swarm_dispatch.py test_correlation_agent.py test_volume_agent.py test_swarm_dispatch_integration.py -v` | 43 passed in 0.50s | PASS |
| Ruff lint clean | `.venv/bin/ruff check` on all 10 phase files | All checks passed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| D-01 | 066-01 | Full SwarmContext dump as structured JSON input | SATISFIED | build_skeptic_prompt(), build_correlation_prompt(), build_volume_prompt() all format all available fields |
| D-02 | 066-01 | LLM returns structured JSON (failure_probability, confidence, risk_factors, reasoning) | SATISFIED | _parse_*_response() functions in all 3 agents, _validate_*_fields() enforces types |
| D-03 | 066-01 | Prompt versioning in code with module-level registry | SATISFIED | PROMPT_REGISTRY in all 3 prompt files, ACTIVE_VERSION constants |
| D-04 | 066-01 | Linear transfer function multiplier = (1.0 - failure_probability) * llm_confidence | SATISFIED | Identical formula in all 3 agents |
| D-05 | 066-01 | Confidence-weighted -- llm_confidence modulates the multiplier | SATISFIED | Part of D-04 formula: low confidence => multiplier closer to 0 |
| D-06 | 066-01 | Never overwrite existing confidence; raw values in metadata | SATISFIED | All 3 agents store failure_probability, confidence, risk_factors, reasoning in metadata dict |
| D-07 | 066-02 | Single SwarmDispatchService, pure compute agents | SATISFIED | service.py: 3 agents in registry, no per-agent services |
| D-08 | 066-01 | SwarmContext seeded from DB on startup | SATISFIED | _seed_context_cache() queries intelligence_features, calls seed_from_db_row() |
| D-09 | 066-01 | 5m+ TF filter only, skip 1m | SATISFIED | _ELIGIBLE_TFS frozenset, if tf not in _ELIGIBLE_TFS: return |
| D-10 | 066-01 | Shadow-only mode, all predictions tracked to alpha_multiplier_shadow | SATISFIED | shadow_only=True on all agents, _recorder.record() for every result |
| D-11 | 066-01 | SwarmBaseAgent handles timeout + exception isolation + neutral fallback | SATISFIED | base_agent.py compute() has asyncio.timeout + try/except, _neutral() returns multiplier=1.0 |
| D-12 | 066-03 | Naive baseline per-segment failure rates from signal_ledger | SATISFIED | compute_skeptic_baseline.py: groups by (hmm_regime, tf, regime_type, plugin), computes failure_rate |
| D-13 | 066-03 | Pearson correlation per segment between failure_probability and outcome | SATISFIED | validate_skeptic.py compute_segment_stats(): pearsonr() per (tf, hmm_regime) segment |
| D-14 | 066-03 | Graduation gate: rho>=0.3, p<0.05, N>=30 per segment; global rho>=0.2 | SATISFIED | validate_skeptic.py: passes_gate check, global gate rho>=0.2 |
| D-15 | 066-01, 066-02 | Single service, asyncio.gather dispatch, shared infrastructure | SATISFIED | service.py: 1 service, 3 agents, asyncio.gather, shared cache/recorder/LLM/DB |
| D-16 | 066-01, 066-02 | SwarmContext enrichment fields (lead_context, volume_profile) | SATISFIED | context.py: proper Pydantic fields, service.py: _enrich_context via model_copy |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/intelligence/swarm/context.py` | 84 | `self._cache: dict[...] = {}` empty dict init | Info | Standard cache initialization pattern, populated by update() and seed_from_db_row(). Not a stub. |
| `services/swarm_dispatch_service.py` | 408 | `vp = {}` empty dict init | Info | Inside _extract_volume_profile(), populated by loop over _VOLUME_PROFILE_FIELDS. Returns None if empty. Not a stub. |
| `scripts/validate_skeptic.py` | 86 | `segments = []` empty list init | Info | Standard accumulator pattern in compute_segment_stats(), populated by loop. Not a stub. |

No blockers or warnings found. All empty initializers are standard accumulation patterns that get populated in the normal code flow.

### Human Verification Required

### 1. End-to-End Service Deployment Test

**Test:** Deploy `indicagent-swarm-dispatch.service` via systemd, verify it starts and consumes from `intelligence.i7.signals`
**Expected:** Service starts, seeds context cache from DB, consumes signals, dispatches to all 3 agents, records results to `alpha_multiplier_shadow`, publishes to `topic_swarm_results`
**Why human:** Requires running Kafka, TimescaleDB, and at least one LLM provider (OpenRouter or Ollama). Cannot verify full e2e flow with static code analysis.

### 2. LLM Prompt Quality Verification

**Test:** Send a real signal through the pipeline and inspect the prompt sent to the LLM
**Expected:** All SwarmContext fields populated with real data; `lead_context` shows lead index data for NQ/ES; `volume_profile` shows VAH/VAL for signals where data is available
**Why human:** LLM prompt quality and response parsing correctness can only be validated with actual LLM responses, not mocks. Need to verify that real LLM output parses correctly through _parse_*_response().

### 3. Statistical Validation (30+ Day Gate)

**Test:** Run `python scripts/validate_skeptic.py --agent skeptic_v1` after 30+ days of shadow data
**Expected:** Per-segment Pearson rho reported; graduation gate evaluation outputs pass/fail per segment and global
**Why human:** Requires 30+ days of accumulated shadow predictions matched to resolved signal_ledger outcomes. Cannot be tested immediately.

### Gaps Summary

No code-level gaps found. All 16 observable truths verified through code inspection, test execution (43/43 passing), import resolution, and wiring verification. The consolidated single-service architecture is fully implemented: 1 SwarmDispatchService, 3 pure compute agents (Skeptic, Correlation, Volume), shared infrastructure, and statistical validation scripts.

The only items requiring human verification are operational (service deployment, LLM response quality, and the 30-day data accumulation gate for statistical validation) -- these require running infrastructure and accumulated data, not code changes.

Note: Plan 03 (validation scripts) was executed and committed (79b1ff35) but the 066-03-SUMMARY.md was never created. This is a documentation gap, not a code gap -- the scripts exist on disk and pass --help verification.

---

_Verified: 2026-04-24T23:15:00Z_
_Verifier: Claude (gsd-verifier)_
