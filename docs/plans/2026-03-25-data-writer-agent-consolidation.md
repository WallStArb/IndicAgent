# Refactor Plan: Consolidate Persistence Agents into `DataWriterAgent`

## Objective
Consolidate `SignalLedgerWriterAgent` and `FeatureHistorianAgent` into a single, domain-agnostic `DataWriterAgent`. This reduces code duplication, enforces uniform observability, and simplifies the deployment of persistence tasks across the pipeline.

## Scope & Impact
- **Affected Files:** `src/persistence/writer/signal_ledger_writer_agent.py`, `src/persistence/writer/feature_historian_agent.py`
- **New Structure:** `src/persistence/writer/data_writer_agent.py`
- **Impact:** Unified maintenance for all persistence consumers.

## Implementation Steps
1. **Develop `DataWriterAgent`:** Implement a generic agent that receives a `Repository` instance and a `KafkaTopicBuilder` at runtime (Dependency Injection).
2. **Standardize Metrics:** Ensure all instances report identical metric names (`persistence_consumer_lag`, `persistence_batch_latency`).
3. **Migrate Services:** Replace existing Agent references in systemd/K8s configs to point to the new unified `DataWriterAgent`.
4. **Cleanup:** Delete the redundant separate agent files.

## Verification
- Validate the generic agent with existing signal ledger tests.
- Run parity checks on feature persistence.
- Ensure Prometheus correctly buckets metrics by `agent_id` or `domain`.
