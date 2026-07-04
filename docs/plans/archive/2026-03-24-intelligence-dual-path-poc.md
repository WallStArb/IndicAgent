# Design Plan: POC Dual-Path Alpha Intelligence

**Last Updated:** 2026-05-02

## Objective
Establish a framework that integrates two distinct methodologies for calculating `AlphaMultiplier` values into the `SignalLifecycleService`:
1.  **Path A (Deterministic DAG):** High-performance, low-latency numeric feature extractors (Rust/Python-hybrid).
2.  **Path B (LLM-based Swarm - "The Observer"):** Reasoning-based intelligence for contextual market interpretation.

The goal is to enable side-by-side performance evaluation in shadow mode (no production impact) before deciding which path (or combination) to promote to full production.

## Scope & Impact
- **Service:** `services/signal_lifecycle_service.py`
- **Data Contract:** `src/intelligence/schemas/alpha_multiplier.py`
- **Infrastructure:** Dual-path shadow-logging to a PostgreSQL table (`alpha_multiplier_shadow`).
- **Dependencies:** `PydanticAI` (Path B), custom numeric engine (Path A).

## Proposed Solution

### 1. Unified Interface (`IAlphaContributor`)
All intelligence contributors (deterministic or LLM) must implement a common interface to decouple the `SignalLifecycleService` from the underlying methodology.

```python
class IAlphaContributor(Protocol):
    async def get_multiplier(self, sid: str, context: dict) -> float:
        ...
```

### 2. Service Integration (`SignalLifecycleService`)
Update the service to:
1. Iterate through registered contributors via a `ContributionHarness`.
2. **Path A (Deterministic):** Execute synchronously or with minimal async overhead; used for real-time `effective_confidence` modulation.
3. **Path B (LLM-Swarm):** Execute as a non-blocking `asyncio.Task` (`_spawn_task`) to log to the shadow-tracking table, preventing any impact on signal processing latency.
4. Log all outputs to the `alpha_multiplier_shadow` table for correlation analysis.

### 3. Shadow Harness
The system will run both paths, log outputs, and perform offline correlation analysis against `Realized_PnL` to identify the most robust signals.

## Alternatives Considered
- **Direct LLM Injection:** Rejected due to latency and reliability concerns in real-time execution.
- **Purely Deterministic:** Rejected because it misses out on complex narrative context (e.g., macro-contagion analysis) that LLMs excel at parsing.

## Implementation Steps (Phased)

### Phase 1: Infrastructure & Contract
- Define `AlphaMultiplier` Pydantic schemas.
- Implement the `IAlphaContributor` interface.
- Register contributors in `SignalLifecycleService`.

### Phase 2: Dual-Path Development
- Implement `DeterministicTrendContributor` (Path A).
- Implement `SMCReasoningContributor` (Path B, using `PydanticAI`).

### Phase 3: Shadow Logging & Validation
- Update `SignalLifecycleService` to invoke both paths in a non-blocking `async` harness.
- Create a Postgres table `alpha_multiplier_shadow` to record inputs and outputs for analysis.

## Verification
- Unit test registration and execution of both paths.
- Verify zero-latency impact on `SignalLifecycleService` production path.
- Shadow data validation: Confirm log consistency in PostgreSQL.

## Migration & Rollback
- Path is currently read-only (Shadow-only). Rollback is simply disabling the `ShadowHarness` configuration in `config/`.
