# Refactor Plan: BaseAgent Bootstrap Standard

## Objective
Standardize Agent lifecycle, OTel instrumentation, and scaling (systemd) by creating a `BaseAgent` class in `src/core/agent/base.py`. This ensures every new Agent inherits the required Renaissance operational behavior.

## Scope & Impact
- **Affected Domain:** All Agents (I1-I8, Persistence, Inference, Training, Swarm).
- **Impact:** Eliminates manual repetition of `SIGTERM` handlers, OTel metric registration, and `consumer_lag` reporting.
- **Principle:** "Reuse over Repetition." Every Agent inherits its "life-support" systems from the `BaseAgent`.

## Implementation Steps
1. **Define `BaseAgent`:** Implement `BaseAgent` class in `src/core/agent/base.py`.
   - `start()`/`stop()`: Standardized lifecycle hooks with `SIGTERM` drainage.
   - `register_metrics()`: Automatic OTel instrumentation for Golden Signals.
   - `lag_reporter()`: Default task to publish `persistence_consumer_lag`.
2. **Systemd Integration:** Ensure agents export `persistence_consumer_lag` to Prometheus for `systemd`/local process monitoring.
3. **Refactor Existing Agents:** Update `DataWriterAgent`, `SignalGeneratorAgent`, etc., to inherit from `BaseAgent`.
4. **Registry:** Implement `AgentRegistry` to track live agents, their Kafka topics, and resource thresholds.

## Verification
- **Inheritance Check:** All Agents must satisfy `isinstance(agent, BaseAgent)`.
- **Operational Parity:** New agents automatically report `persistence_consumer_lag` without manual instrumentation, enabling `systemd` monitoring.
