# Phase 107 Service Inventory

**Generated:** 2026-05-25 17:50:18 UTC
**Total services:** 40

## Compliance Matrix

| Service | BaseAgent | DB Pool | agent_id | Flush Span | Metric Types | Notes |
|---------|-----------|---------|----------|------------|--------------|-------|
| indicagent-alerting-agent | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-alpha-swarm | RED | N/A | GREEN | N/A | GREEN |  |
| indicagent-api | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-bar-aggregator | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-bar-auditor | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-bar-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-contract-metadata-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-cross-asset | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-ctx-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-dashboard | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-dlq-drain | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-feature-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-graduation-compute | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-graduation-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-ibkr-provider | RED | N/A | GREEN | N/A | GREEN |  |
| indicagent-intelligence-pipeline | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-lifecycle-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-lineage-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-llm-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-macro-compute | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-ml-data-quality | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-ml-discovery | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-ml-orchestrator | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-ml-signal-training-materialize | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-ml-training | RED | N/A | GREEN | N/A | GREEN |  |
| indicagent-narrative-compute | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-provider-merger | GREEN | N/A | GREEN | N/A | GREEN |  |
| indicagent-redpanda-ready | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-redpanda-watchdog | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-roll-compute | GREEN | RED | GREEN | N/A | GREEN |  |
| indicagent-service-auditor | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-shadow-auditor | RED | GREEN | GREEN | N/A | GREEN |  |
| indicagent-signal-auditor | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-signal-metrics-compute | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-signal-metrics-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-signal-replay | ERROR | ERROR | ERROR | N/A | ERROR | File not found |
| indicagent-signal-tracker-compute | GREEN | GREEN | GREEN | N/A | GREEN |  |
| indicagent-signal-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-swarm-ledger-writer | GREEN | GREEN | GREEN | RED | GREEN |  |
| indicagent-weight-updater | ERROR | ERROR | ERROR | N/A | ERROR | File not found |

## Summary Statistics

**BaseAgent:** 28/32 compliant
**DatabaseManager:** 20/21 compliant
**agent_id label:** 32/32 consistent
**Flush span coverage:** 0/11 writers
**Metric types:** 32/32 compliant
**Missing files:** 8 services