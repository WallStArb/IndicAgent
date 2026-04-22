# Service Reference Overview

**Last Updated:** 2026-04-21
**Authoritative source:** `systemctl list-units --all | grep indicagent`

All services extend `BaseAgent` (`src/core/agent/base.py`). For role taxonomy see `docs/architecture/agent-standard.md`. For full DAG wiring see `docs/architecture/dag-topology.md`.

---

## Provider Layer

| Service | Unit | File | Role | Publishes To |
|---------|------|------|------|-------------|
| IBKR Provider | `indicagent-ibkr-provider` | `ibkr_provider_agent.py` | `ProviderAgent` | `market.bars.raw.ibkr` |
| Provider Merger | `indicagent-provider-merger` | `provider_merger_agent.py` | `MergerAgent` | `market.bars` |

## Bar Processing Tier

| Service | Unit | File | Role | Publishes To |
|---------|------|------|------|-------------|
| Bar Aggregator | `indicagent-bar-aggregator` | `bar_aggregator_agent.py` | `ComputeAgent` | `market.bars.htf` |
| Bar Writer | `indicagent-bar-writer` | `bar_writer_agent.py` | `WriterAgent` | `market_data_ohlcv` (DB) |
| Bar Auditor | `indicagent-bar-auditor` | `bar_auditor_agent.py` | `AuditorAgent` | `market.events.gap_requests` |
| Roll Compute | `indicagent-roll-compute` | `roll_compute_agent.py` | `ComputeAgent` | `market.events.roll` |
| Contract Metadata Writer | `indicagent-contract-metadata-writer` | `contract_metadata_writer_agent.py` | `WriterAgent` | `contract_metadata` (DB) |

## Intelligence Compute Tier

| Service | Unit | File | Role | Publishes To |
|---------|------|------|------|-------------|
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | `intelligence_pipeline_agent.py` | `ComputeAgent` | `intelligence.journal`, `intelligence.i7.signals` |

Runs I1→I7 entirely in-process (128 plugins). DB-ignorant. See `docs/architecture/dag-topology.md` §2.

## Persistence Tier

| Service | Unit | File | Role | Consumes From | Writes To |
|---------|------|------|------|--------------|-----------|
| Feature Writer | `indicagent-feature-writer` | `feature_writer_agent.py` | `WriterAgent` | `intelligence.journal` | `intelligence_features` |
| Signal Writer | `indicagent-signal-writer` | `signal_writer_agent.py` | `WriterAgent` | `intelligence.i7.signals` | `signal_ledger` |
| Signal Tracker | `indicagent-signal-tracker-compute` | `signal_tracker_compute_agent.py` | `TrackerAgent` (compute) | `market.bars` | lifecycle transitions (Kafka) |
| Lifecycle Writer | `indicagent-lifecycle-writer` | `lifecycle_writer_agent.py` | `WriterAgent` | lifecycle transitions | `signal_ledger` |
| LLM Writer | `indicagent-llm-writer` | `llm_writer_service.py` | `WriterAgent` | `llm.calls` + `llm.outcomes` | `llm_calls`, `llm_model_scores` |

## Signal Metrics Tier

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| Signal Metrics Compute | `indicagent-signal-metrics-compute` | `signal_metrics_compute_agent.py` | `ComputeAgent` | Timer-triggered signal performance metrics |
| Signal Metrics Writer | `indicagent-signal-metrics-writer` | `signal_metrics_writer_agent.py` | `WriterAgent` | Persists metrics to `setup_performance` |

## Auditor / Quality Tier

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| Signal Auditor | `indicagent-signal-auditor` | `signal_auditor_agent.py` | `AuditorAgent` | Coverage validation + lag monitoring |
| Parity Auditor | `indicagent-parity-auditor` | `parity_auditor_agent.py` | `AuditorAgent` | 5-min parity comparison; certifies after 60 clean cycles |
| Feature Snapshot Writer | `indicagent-feature-snapshot-writer` | `feature_snapshot_writer_agent.py` | `WriterAgent` | Shadow dual-write → `feature_snapshots_shadow` |
| Service Auditor | `indicagent-service-auditor` | `service_auditor_agent.py` | `AuditorAgent` | Pipeline health monitor and self-healer |

## ML Tier (Timer-Based)

All ML services run on systemd timers (periodic oneshot), not continuous daemons.

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| ML Data Quality | `indicagent-ml-data-quality` | `ml_data_quality_agent.py` | `AuditorAgent` | Audits `intelligence_features` for training data quality |
| ML Discovery | `indicagent-ml-discovery` | `ml_discovery_agent.py` | `ComputeAgent` | Discovers ML training signal patterns |
| ML Orchestrator | `indicagent-ml-orchestrator` | `ml_orchestrator_agent.py` | `ComputeAgent` | Orchestrates ML training pipeline |

## Swarm Tier

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| Swarm Orchestrator | `indicagent-swarm-orchestrator` | `swarm_orchestrator_agent.py` | `ComputeAgent` | Routes swarm tasks to specialist agents |
| Swarm Writer | `indicagent-swarm-writer` | `swarm_writer_agent.py` | `WriterAgent` | Persists swarm outputs to DB |

## AI / API Tier

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| AI Narrative | `indicagent-ai-narrative` | `ai_narrative_agent.py` | — | I8: Ollama LLM → `narratives:SYMBOL:TF` |
| Cross Asset | `indicagent-cross-asset` | `cross_asset_service.py` | — | Cross-asset spread dynamics |
| API | `indicagent-api` | `src/api/main.py` | — | FastAPI + SSE on :8000 |
| Dashboard | `indicagent-dashboard` | `dashboard/` | — | Next.js dev server on :3000 |

---

**Guide:** [Running Services](../guides/running-services.md) · **DAG wiring:** [DAG Topology](../architecture/dag-topology.md)
