# Intelligence Swarm Evolution: Legacy Deprecation & Framework Wiring

## 1. Legacy Deprecation (Back-end)
The goal is to replace manual/hardcoded AI-narrative injection with the new `AlphaContributor` harness and `IAlphaContributor` interface.

- [ ] **Remove Hardcoded LLM Injection:** Locate `ai_narrative_service` references in `SignalLifecycleService` (or any service that manually triggers LLM calls). Replace with `_invoke_intelligence_harness`.
- [ ] **Clean Up Registry:** Remove manual registration code in `SignalLifecycleService.start()` (Already partially done; ensure no lingering `register_alpha_contributor` calls exist).
- [ ] **Archive Legacy Services:** Deprecate `indicagent-llm-writer.service` and `indicagent-ai-narrative.service` in favor of the new swarm-agent registry system.

## 2. Framework Wiring (The "Observer" Integration)
Now that the harness exists, we must "wire up" the data to the contributors.

- [ ] **Context Enrichment (The "Hub"):**
    - Inside `SignalLifecycleService._evaluate_signals_against_bar`, update the `context` dictionary.
    - **Requirement:** Populate `context` with real-time state from service caches (`_chandelier_state`, `_active_index`, `_staleness_consecutive`).
    - **Requirement:** Inject cross-asset and microstructure features (OFI, CVD, GARCH sigma) so agents have sufficient intelligence to compute meaningful multipliers.

- [ ] **Kafka Stream Bridge:**
    - **Requirement:** Implement a dedicated consumer in `NarrativeMarketAgent` (and other Path B agents) that subscribes directly to the `intelligence:SYMBOL:TF` topics.
    - **Note:** This bypasses the service-level context dictionary and provides raw event-stream data to agents for asynchronous reasoning.

- [ ] **Shadow-Table Schema Sync:**
    - **Requirement:** Update the PostgreSQL `alpha_multiplier_shadow` table schema to ensure it captures the full Pydantic JSON dump of `AgentResult.metadata` for every swarm agent.
    - **Requirement:** Validate that `scripts/alpha_promotion.py` handles these JSONB metadata fields correctly when calculating correlation.

## 3. Operational Requirements for Next Session
When you resume, have these resources ready:
- **Environment:** Access to the `indicagent` database instance.
- **Tools:** Ensure `pytest` and `pandas` are updated in `.venv`.
- **Goal:** Run `SignalLifecycleService` in shadow-mode and verify logs in `logs/signal_lifecycle_service.log` for successful `AlphaMultiplier` generation.
