# Plan: HPA Hardening & Observability

## Objective
Enable fully autonomous scaling of the `PersistenceAgent` cluster based on Kafka lag metrics (`consumer_lag_records`).

## Scope
- All Agents in `src/persistence/writer/` and `src/intelligence/compute/`.

## Implementation Steps
1. **Instrument Lag Metrics:** Add a generic lag-tracker utility to `KafkaConsumerClient` that exports the `consumer_lag_records` metric.
2. **Kubernetes Policy:** Define HPA specs for `persistence-agent` deployments targeting the Kafka lag metric.
3. **Graceful Drain:** Ensure all agents implement the `SIGTERM` handler for "Flush-before-exit."

## Verification
- **Load Simulation:** Use a Kafka producer to inject high-volume payloads into `intelligence.i1` and verify the `PersistenceAgent` group lag grows.
- **HPA Trigger:** Confirm the K8s HPA controller detects the lag spike and provisions new pods.
