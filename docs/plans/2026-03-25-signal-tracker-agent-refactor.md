# Refactor Plan: SignalTrackerAgent (I7 Lifecycle Tracking)

## Objective
Convert `SignalLifecycleService` into a standardized `SignalTrackerAgent`. Remove DB-coupling and enable Agentic scaling (HPA/OTel/SIGTERM).

## Scope & Impact
- **Affected File:** `services/signal_lifecycle_service.py` -> `services/signal_tracker_agent.py`
- **Impact:** Decouples state tracking from SQL logic; aligns with the Agentic DAG pattern.
- **Principle:** "Separation of Concerns." The Agent tracks logic and lifecycle state; the `SignalLedgerRepository` handles the database implementation.

## Implementation Steps
1. **Rename:** `services/signal_lifecycle_service.py` to `services/signal_tracker_agent.py`.
2. **Standardize Init:** Inject `SignalLedgerRepository` (remove `DatabaseManager` entirely).
3. **Agentic Lifecycle:**
   - Add `async def start()` / `stop()` methods with `SIGTERM` drainage.
   - Instrument with `persistence_batch_latency` and `persistence_consumer_lag`.
   - Add DLQ logic for unprocessable signals.
4. **Resilience:** Wrap DB interactions in `try/except` with DLQ routing.

## Verification
- **Scaling:** Verify independence via `consumer_lag` monitoring.
- **Integrity:** Ensure tracking state (MAE/MFE) is correctly serialized and persists across re-runs.
- **Naming:** Verify all loggers and metric labels use `signal_tracker_agent`.
