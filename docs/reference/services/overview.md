<!-- generated-by: gsd-doc-writer -->
# Service Reference Overview

**Last Updated:** 2026-05-27
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

> **Roll detection:** `indicagent-roll-compute` and `indicagent-contract-metadata-writer` daemons have been replaced by the nightly `indicagent-roll-batch` systemd timer (runs at 8pm via `production/scripts/roll_batch.py`). `inactive (dead)` between runs is correct — do not treat as failure. Monitor: `systemctl list-timers --all | grep roll-batch`.

## Intelligence Compute Tier

| Service | Unit | File | Role | Publishes To |
|---------|------|------|------|-------------|
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | `intelligence_pipeline_agent.py` | `ComputeAgent` | `intelligence.journal`, `intelligence.i7.signals` |

Runs I1→I7 entirely in-process (132 plugins). DB-ignorant. See `docs/architecture/dag-topology.md` §2.

## Persistence Tier

| Service | Unit | File | Role | Consumes From | Writes To |
|---------|------|------|------|--------------|-----------|
| Feature Writer | `indicagent-feature-writer` | `feature_writer_agent.py` | `WriterAgent` | `intelligence.journal` | `intelligence_features` |
| Signal Writer | `indicagent-signal-writer` | `signal_writer_agent.py` | `WriterAgent` | `intelligence.i7.signals` | `signal_ledger` |
| Signal Tracker | `indicagent-signal-tracker-compute` | `signal_tracker_compute_agent.py` | `TrackerAgent` (compute) | `market.bars` | lifecycle transitions (Kafka) |
| Lifecycle Writer | `indicagent-lifecycle-writer` | `lifecycle_writer_agent.py` | `WriterAgent` | lifecycle transitions | `signal_ledger` / `signal_outcomes` |
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
| Signal Replay | `indicagent-signal-replay` | `signal_replay_agent.py` | `AuditorAgent` | Replay-based TTL evaluation (batch size: `REPLAY_BATCH_SIZE` default 100, interval: `REPLAY_INTERVAL_SECONDS` default 300s) |
| Parity Auditor | `indicagent-parity-auditor` | `parity_auditor_agent.py` | `AuditorAgent` | 5-min parity comparison; certifies after 60 clean cycles |
| Feature Snapshot Writer | `indicagent-feature-snapshot-writer` | `feature_snapshot_writer_agent.py` | `WriterAgent` | Shadow dual-write |
| Service Auditor | `indicagent-service-auditor` | `service_auditor_agent.py` | `AuditorAgent` | Pipeline health monitor and self-healer |

## ML Tier (Timer-Based)

All ML services run on systemd timers (periodic oneshot), not continuous daemons. `inactive (dead)` between runs is correct.

| Service | Unit | File | Role | Schedule |
|---------|------|------|------|---------|
| ML Training | `indicagent-ml-training` | `ml_training_agent.py` | `ComputeAgent` | Nightly 11pm |
| ML Data Quality | `indicagent-ml-data-quality` | `ml_data_quality_agent.py` | `AuditorAgent` | Weekly Monday |
| ML Discovery | `indicagent-ml-discovery` | `ml_discovery_agent.py` | `ComputeAgent` | Weekly Monday |
| ML Orchestrator | `indicagent-ml-orchestrator` | `ml_orchestrator_agent.py` | `ComputeAgent` | Weekly Monday |
| Roll Batch | `indicagent-roll-batch` | `roll_batch.py` | Timer | Nightly 8pm |

## AI / LLM Tier (L7)

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| Alpha Swarm | `indicagent-alpha-swarm` | `alpha_swarm_compute_agent.py` | `ComputeAgent` | Multi-agent LLM swarm analysis |
| Narrative Compute | `indicagent-narrative-compute` | `narrative_compute_agent.py` | `ComputeAgent` | I8: Ollama LLM narrative generation |
| LLM Writer | `indicagent-llm-writer` | `llm_writer_service.py` | `WriterAgent` | Persists LLM calls to `llm_calls` |
| Swarm Ledger Writer | `indicagent-swarm-ledger-writer` | `swarm_ledger_writer_agent.py` | `WriterAgent` | Persists swarm outputs |

## API / Infrastructure

| Service | Unit | File | Role | Purpose |
|---------|------|------|------|---------|
| Cross Asset | `indicagent-cross-asset` | `cross_asset_service.py` | `ComputeAgent` | Cross-asset spread dynamics |
| Macro Compute | `indicagent-macro-compute` | `macro_compute_agent.py` | `ComputeAgent` | Macro factor computation |
| API | `indicagent-api` | `src/api/main.py` | FastAPI | REST + SSE on :8000 |
| Dashboard | `indicagent-dashboard` | `dashboard/` | Next.js | Dev server on :3000 |

---

**Guide:** [Running Services](../guides/running-services.md) · **DAG wiring:** [DAG Topology](../architecture/dag-topology.md)
