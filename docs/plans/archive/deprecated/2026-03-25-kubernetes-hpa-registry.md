# Plan: Kubernetes HPA Registry Specification

## Objective
Centralize HPA (Horizontal Pod Autoscaler) policies for the Agentic DAG. Every Agent (Persistence, Compute, Inference) must have a predefined scaling threshold based on `consumer_lag_records`.

## Design
- **Registry Structure:** A central YAML/Config manifest defining:
    - Agent ID
    - Kafka Topic
    - HPA Threshold (e.g., `50,000` for `WriterAgent`, `100` for `SignalGeneratorAgent`).
    - Max Replica Count (Prevent runaway pods).
- **HPA Logic:** 
    - Deployment manifests must include an HPA definition pointing to the `consumer_lag_records` Prometheus metric.

## Implementation Steps
1. **Define Registry:** Create `config/hpa_registry.yaml` mapping all Agents to their lag-scaling thresholds.
2. **Infrastructure Hook:** Configure the K8s HPA controller to monitor `consumer_lag_records` for each Agent deployment.
3. **Automated Deployment:** CI pipeline validates that every Agent deployment has a corresponding HPA entry.

## Verification
- **Stress Testing:** Manually simulate a lag spike and confirm the HPA controller triggers pod provisioning.
- **Independence:** Verify that scaling the `SignalLedgerWriterAgent` does *not* trigger auto-scaling for the `IndicatorComputeAgent`.
