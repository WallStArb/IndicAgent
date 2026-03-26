# Refactor Plan: Decoupling I2-I6 Warmup Logic (`WarmupProvider`)

## Objective
Decouple `IntelligenceComputeAgent` from legacy database-dependent `_warmup_bar_history()` logic. Transition to a `WarmupProvider` that utilizes the standardized `FeatureSnapshotRepository`.

## Scope & Impact
- **Affected File:** `services/intelligence_compute_agent.py`
- **Impact:** Removes direct DB `SELECT` queries from the agent initialization, making it fully "DB-ignorant" during its runtime loop.
- **Principle:** "Separation of Concerns." Compute agents should not be responsible for fetching their own historical state—they should be seeded by a dedicated provider.

## Implementation Steps
1. **Define WarmupProvider:** Create `src/persistence/logic/warmup_provider.py` which interfaces with `FeatureSnapshotRepository`.
2. **Inject WarmupProvider:** Update `IntelligenceComputeAgent` to accept an injected `WarmupProvider` at startup.
3. **Decouple Initialization:** Remove `DatabaseManager` and SQL `SELECT` logic from `IntelligenceComputeAgent.__init__` and `_warmup_bar_history()`.
4. **Resilience:** The provider should handle backoff/retries for historical data fetching, ensuring the Agent only starts once the "Warmup" state is ready.

## Verification
- **Functional Check:** Agent starts correctly and is fully primed with historical features before the Kafka consumer loop begins.
- **Isolation:** `IntelligenceComputeAgent` has no DB connection objects or SQL strings; it is purely Kafka/Repository-interfaced.
- **Parity:** Validate that the "warmed up" state is identical to the legacy implementation.
