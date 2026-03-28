---
created: 2026-03-28T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: Intelligence swarm evolution — legacy deprecation and framework wiring
area: intelligence
priority: 25
tier: deferred
files:
  - services/ai_narrative_service.py
  - services/signal_tracker_agent.py
---

## Context

This is a forward-looking design document describing an evolution of the intelligence swarm architecture. It references `SignalLifecycleService` (now renamed `SignalTrackerAgent` in `services/signal_tracker_agent.py`) and `AlphaContributor` harness concepts that are partially or not yet implemented. Treat as a design sketch — validate all class/method references against actual code before executing.

## 1. Legacy Deprecation (Back-end)

The goal is to replace manual/hardcoded AI-narrative injection with the `AlphaContributor` harness and `IAlphaContributor` interface.

- [ ] **Remove Hardcoded LLM Injection:** Locate `ai_narrative_service` references in `SignalTrackerAgent` (formerly `SignalLifecycleService`) or any service that manually triggers LLM calls. Replace with `_invoke_intelligence_harness`.
- [ ] **Clean Up Registry:** Remove manual registration code in `SignalTrackerAgent.start()` (ensure no lingering `register_alpha_contributor` calls exist).
- [ ] **Archive Legacy Services:** Deprecate `indicagent-llm-writer.service` and `indicagent-ai-narrative.service` in favor of the new swarm-agent registry system (when swarm is proven in shadow mode).

## 2. Framework Wiring (The "Observer" Integration)

Now that the harness exists, we must wire data to the contributors.

- [ ] **Context Enrichment (The "Hub"):**
    - Inside `SignalTrackerAgent._evaluate_signals_against_bar`, update the `context` dictionary.
    - **Requirement:** Populate `context` with real-time state from service caches (`_chandelier_state`, `_active_index`, `_staleness_consecutive`).
    - **Requirement:** Inject cross-asset and microstructure features (OFI, CVD, GARCH sigma) so agents have sufficient intelligence to compute meaningful multipliers.

- [ ] **Kafka Stream Bridge:**
    - **Requirement:** Implement a dedicated consumer in `NarrativeMarketAgent` (and other Path B agents) that subscribes directly to the `intelligence:SYMBOL:TF` topics.
    - **Note:** This bypasses the service-level context dictionary and provides raw event-stream data to agents for asynchronous reasoning.

- [ ] **Shadow-Table Schema Sync:**
    - **Requirement:** Update the PostgreSQL `alpha_multiplier_shadow` table schema to ensure it captures the full Pydantic JSON dump of `AgentResult.metadata` for every swarm agent.
    - **Requirement:** Validate that `scripts/alpha_promotion.py` handles these JSONB metadata fields correctly when calculating correlation.

## 3. Operational Requirements

When resuming this work:
- **Environment:** Access to the `indicagent` database instance.
- **Tools:** Ensure `pytest` and `pandas` are updated in `.venv`.
- **Goal:** Run `SignalTrackerAgent` in shadow-mode and verify logs in `logs/signal_tracker_agent.log` for successful `AlphaMultiplier` generation.
- **Verify all class references** (`AlphaContributor`, `IAlphaContributor`, `NarrativeMarketAgent`, `alpha_multiplier_shadow` table) exist in codebase before starting implementation.
