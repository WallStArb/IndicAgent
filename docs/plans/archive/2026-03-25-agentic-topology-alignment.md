# Refactor Plan: Final Agentic Topology Alignment

**Last Updated:** 2026-05-02

## Objective
Standardize the primary pipeline services into the codified `Agent` taxonomy to match `docs/architecture/AGENT_STANDARD.md`.

## Proposed Taxonomy Alignment
1.  **`indicator_service.py`** → `services/indicator_compute_agent.py` (`IndicatorComputeAgent`)
2.  **`feature_pipeline_service.py`** → `services/feature_compute_agent.py` (`FeatureComputeAgent`)
3.  **`signal_generator_service.py`** → `services/signal_generator_agent.py` (`SignalGeneratorAgent`)

## Implementation Steps
1. **Rename Files:** Execute `git mv` for each service.
2. **Update Class Names:** Ensure the Python class definition matches the new taxonomy (e.g., `IndicatorComputeAgent`).
3. **Update Imports & Config:** Update `systemd` units, `docker-compose.yml`, and `register_plugins.py` references to point to the new Agent naming.
4. **Consistency Audit:** Verify all logging, metrics (OTel), and Kafka topic builders still resolve correctly.

## Verification
- **System Integrity:** Full `pytest` pass on integration and unit suites.
- **Log/Metric Parity:** Ensure log filenames (e.g., `logs/indicator_compute_agent.log`) and Prometheus labels match the new Agent IDs.
- **Service Continuity:** Verify `systemctl` recognizes the new unit names.
