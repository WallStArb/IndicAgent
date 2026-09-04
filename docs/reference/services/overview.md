<!-- generated-by: gsd-doc-writer -->
# Service Reference Overview

**Last Updated:** 2026-09-04
**Authoritative source:** `_DAG_ORDER` in `services/service_auditor.py` (topology) + `systemctl list-units --all | grep indicagent` (live state)

All services extend `BaseAgent`/`BaseDaemon` (`src/core/agent/base.py`). For role taxonomy and lifecycle contract see `docs/agents/agents-foundation.md`. For service mesh and DAG topology see `docs/agents/agents-operations.md`.

**This describes the live v3.0 topology.** The v2.x I1-I7 plugin pipeline (`indicagent-intelligence-pipeline.service`, `ExecStart=services/intelligence_pipeline.py`) is **archived** — that file was renamed to `feature_vector_pipeline.py` in commit `911a1668c` ("rename(v3.0): IntelligencePipeline -> FeatureVectorPipeline"), and the deployed unit is `failed` (confirmed via `systemctl status`, 2026-09-04: `Active: failed ... since Thu 2026-08-13`). Do not cite it as a running compute stage. Full archived-system detail: `src/intelligence/CLAUDE.md`.

Boot ordering runs through four `indicagent-waveN.target` gates (`indicagent-infrastructure.target` → `wave1` data ingestion → `wave2` intelligence pipeline → `wave3` persistence writers → `wave4` analytics/AI/audit/top-level) — all four targets verified `active` 2026-09-04.

---

## Provider Layer (Wave 1)

| Service | Unit | File | Publishes To | Live state (2026-09-04) |
|---------|------|------|---------------|--------------------------|
| IBKR Provider | `indicagent-ibkr-provider` | `services/ibkr_provider.py` | `market.bars.raw.ibkr` | `inactive (dead)` |
| Bar Replay Provider | `indicagent-bar-replay` | `services/bar_replay_provider.py` (oneshot) | `market.bars.raw.*` | `inactive (dead)` |
| Provider Merger | `indicagent-provider-merger` | `services/provider_merger.py` | `market.bars` | `inactive (dead)` |

Live IBKR ingestion is stalled (frozen since 2026-08-12 per project memory, todo 366, not urgent) — `inactive (dead)` here reflects that stall, not correct idle-between-runs behavior like the ML timer tier below. Historical backfill remains available via `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`.

## Bar Processing Tier (Wave 1-2)

| Service | Unit | File | Publishes To | Live state |
|---------|------|------|---------------|------------|
| Bar Aggregator | `indicagent-bar-aggregator` | `services/bar_aggregator.py` | `market.bars.htf` | `inactive (dead)` |
| Bar Writer | `indicagent-bar-writer` | `services/bar_writer.py` | `market_data_ohlcv` (DB) | `inactive (dead)` |
| Bar Auditor | `indicagent-bar-auditor` | `services/bar_auditor.py` | `market.events.gap_requests` | `inactive (dead)` |

> **Roll detection:** `indicagent-roll-batch.timer` (`scripts/ops/roll/ops_roll_batch.py`) is **confirmed `disabled`** (`systemctl is-enabled` → `disabled`, re-checked 2026-09-04) — do not assume it runs nightly. Verify with `systemctl list-timers --all | grep roll-batch` before citing as scheduled.

## Intelligence Compute Tier (Wave 2) — v3.0 Feature Factory

| Service | Unit | File | Consumes | Publishes To |
|---------|------|------|----------|---------------|
| Feature Vector Pipeline | `indicagent-feature-vector-pipeline` | `services/feature_vector_pipeline.py` | `market.bars`, `market.bars.htf`, `cross_asset`, `macro_signals`, `system_events` | `feature_vectors` (Kafka topic, `topic_feature_vectors`) |

Computes via `src/intelligence/feature_factory.py` — **not** `register_plugins.py`/the I1-I7 plugin DAG. Live 2026-09-04 (`active running`). DB-ignorant compute; persistence goes through the writer below (DAG Invariant 3). See `docs/architecture/architecture-dag-topology.md` §2 for wiring detail.

## Persistence Tier (Wave 3)

| Service | Unit | File | Consumes | Writes To |
|---------|------|------|----------|-----------|
| Feature Vector Writer | `indicagent-feature-vector-writer` | `services/feature_vector_writer.py` | `feature_vectors` topic | `feature_vectors` hypertable |
| Signal Writer | `indicagent-signal-writer` | `services/signal_writer.py` | I7 signal topic | `signal_ledger` |
| Signal Tracker | `indicagent-signal-tracker-compute` | `services/signal_tracker.py` | `market.bars` | lifecycle transitions (Kafka) |
| Lifecycle Writer | `indicagent-lifecycle-writer` | `services/lifecycle_writer.py` | lifecycle transitions | `signal_ledger` |
| Lineage Writer | `indicagent-lineage-writer` | `services/lineage_writer.py` | signal lineage events | `signal_lineage` |
| CTX Writer | `indicagent-ctx-writer` | `services/context_writer.py` | qualitative context events | context snapshots (DB) |
| Graduation Writer | `indicagent-graduation-writer` | `services/graduation_writer.py` | graduation events | `transform_graduation` |
| LLM Writer | `indicagent-llm-writer` | `services/llm_writer.py` | `llm.calls` + `llm.outcomes` | `llm_calls` |

Live 2026-09-04: `feature-vector-writer` `active running`; `signal-writer`, `signal-tracker-compute`, `lifecycle-writer` `inactive (dead)` (downstream of the stalled ingestion chain above); `lineage-writer` and `ctx-writer` `active running` (these two run independent of live bar flow).

## Signal Metrics Tier

| Service | Unit | File | Purpose |
|---------|------|------|---------|
| Signal Metrics Compute | `indicagent-signal-metrics-compute` | `services/signal_metrics_analyzer.py` | Timer-triggered signal performance metrics |
| Signal Metrics Writer | `indicagent-signal-metrics-writer` | `services/signal_metrics_writer.py` | Persists metrics to `setup_performance` |

## Auditor / Quality Tier

| Service | Unit | File | Purpose |
|---------|------|------|---------|
| Signal Auditor | `indicagent-signal-auditor` | `services/signal_auditor.py` | Coverage validation + lag monitoring |
| Signal Replay | `indicagent-signal-replay` | `services/signal_replay_auditor.py` | Replay-based outcome recovery |
| Signal Probe Auditor | `indicagent-signal-probe-auditor` | `services/signal_probe_auditor.py` | Oneshot, timer-triggered |
| Feature Parity Auditor | `indicagent-feature-parity-auditor` | `services/feature_parity_auditor.py` | Oneshot, timer-triggered |
| Compression Auditor | `indicagent-compression-auditor` | `services/compression_auditor.py` | TimescaleDB compression drift + self-healing (todo 233) |
| Regime Coverage Auditor | `indicagent-regime-coverage-auditor` | `services/regime_coverage_auditor.py` | Daily 02:00 EDT / 06:00 UTC timer |
| Confidence Calibration Monitor | `indicagent-confidence-calibration-monitor` | `services/confidence_calibration_monitor.py` | Oneshot, timer-triggered |
| Service Auditor | `indicagent-service-auditor` | `services/service_auditor.py` | Pipeline health monitor / self-healer; canonical DAG registry lives here |
| Shadow Auditor | `indicagent-shadow-auditor` | `services/shadow_auditor.py` | Shadow governance |
| Shadow Validator | `indicagent-shadow-validator` | `services/shadow_validator.py` | Weekly Mon 07:00 UTC, 5-gate promotion-only |

Live 2026-09-04: `compression-auditor` `active running`. `regime-coverage-auditor.timer` is `enabled`/`active waiting` (fires daily 06:00 UTC per CLAUDE.md), but the service's most recent run **failed** (`Active: failed ... since Fri 2026-09-04 02:00:03 EDT`, exit code 1) — check `journalctl -u indicagent-regime-coverage-auditor` for cause before assuming it is healthy; this is a point-in-time observation, not a known/accepted issue.

## ML Tier (Timer-Based)

All ML services run on systemd timers (periodic oneshot), not continuous daemons. `inactive (dead)` between runs is correct — do not treat as failure.

| Service | Unit | File | Schedule |
|---------|------|------|---------|
| ML Training | `indicagent-ml-training` | `services/ml_training_agent.py` | Nightly |
| ML Data Quality | `indicagent-ml-data-quality` | `services/data_quality_auditor.py` | Weekly |
| ML Discovery | `indicagent-ml-discovery` | `services/ml_discovery_analyzer.py` | Weekly |
| ML Orchestrator | `indicagent-ml-orchestrator` | `services/ml_orchestrator.py` | Weekly |
| ML Signal Training Materialize | `indicagent-ml-signal-training-materialize` | `services/ml_signal_training_agent.py` | Nightly JOIN materialization |
| HMM Training | `indicagent-hmm-training` | `services/hmm_training_agent.py` | Monthly Baum-Welch retraining |
| Feature Validation | `indicagent-feature-validation` | `services/feature_validation_agent.py` | Daily IC/p-value decisions |
| Memory Batch | `indicagent-memory-batch` | `scripts/ops/memory/ops_batch_agent_memory.py` | Nightly 21:00 |
| Nightly Backfill | `indicagent-nightly-backfill` | `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py` | `.timer` `enabled`/`active waiting`, daily 05:00 UTC |
| Roll Batch | `indicagent-roll-batch` | `scripts/ops/roll/ops_roll_batch.py` | `.timer` **`disabled`** — see Roll detection note above |

## IC / Alpha Pipeline (Batch — orchestrator-driven, not systemd units)

The v3.0 alpha chain (`FeatureVectorWriter → forward_return_writer → ic_engine → ensemble_trainer/EnsembleICEngine → alpha_publisher → alpha_events`, per root `CLAUDE.md`) runs as sequential batch steps invoked by `scripts/ops/corpus/ops_corpus_pipeline_run.sh`, **not** as always-on or timer-triggered systemd units — no `production/systemd/indicagent-*.service` file exists for any of these (verified 2026-09-04).

| Step | File | Writes To |
|------|------|-----------|
| Regime Writer | `services/regime_writer.py` | `feature_vectors.regime*` |
| Forward Return Writer | `services/forward_return_writer.py` | `forward_returns` |
| IC Engine | `services/ic_engine.py` | `feature_ic_scores` |
| Ensemble Trainer | `services/ensemble_trainer.py` | `ensemble_weights`, `ensemble_alpha` |
| Alpha Publisher | `services/alpha_publisher.py` | `alpha_events` (DB + Kafka; sole `alpha_events` writer) |
| Ensemble IC Engine | `services/ensemble_ic_engine.py` | `alpha_ensemble_ic` |
| Alpha Frame Writer | `services/alpha_frame_writer.py` | `alpha_frames` |
| Counterfactual Tracker | `services/counterfactual_tracker.py` | counterfactual PnL scoring on `alpha_frames` |

## AI / LLM Tier (dormant, see root CLAUDE.md)

`BaseAIWorker`/`alpha_swarm`/`narrative_swarm` have had zero commits since the v3.0 rebuild started 2026-06-20. This is target-state, not confirmed-running.

| Service | Unit | File | Live state |
|---------|------|------|------------|
| Alpha Swarm | `indicagent-alpha-swarm` | `services/alpha_swarm.py` | not loaded (never started this boot); unit `disabled` |
| Narrative Compute | `indicagent-narrative-compute` | `services/narrative_swarm.py` | not loaded; unit `disabled` |
| Swarm Ledger Writer | `indicagent-swarm-ledger-writer` | `services/swarm_ledger_writer.py` | not loaded; unit `disabled` |

## API / Infrastructure

| Service | Unit | File | Purpose | Live state |
|---------|------|------|---------|------------|
| Cross Asset | `indicagent-cross-asset` | `services/cross_asset_analyzer.py` | Cross-asset spread dynamics | `inactive (dead)` |
| Macro Compute | `indicagent-macro-compute` | `services/macro_analyzer.py` | Macro factor computation | `inactive (dead)` |
| Config Service | `indicagent-config-service` | `services/config_service.py` | APR HTTP API, port 9001 | not loaded |
| Outbox Dispatcher | `indicagent-outbox-dispatcher` | `services/outbox_dispatcher_agent.py` | Transactional outbox → Kafka | not loaded |
| Self-Healing Agent | `indicagent-self-healing-agent` | `services/self_healer.py` | Alertmanager webhook + remediation | not loaded |
| Alerting Agent | `indicagent-alerting-agent` | `services/alert_monitor.py` | Kafka → Telegram/Discord dispatcher | not loaded |
| DLQ Drain | `indicagent-dlq-drain` | `services/dlq_writer.py` | Consumes DLQ topics → `dlq_events` | not loaded |
| API | `indicagent-api` | `src/api/main.py` | FastAPI REST + SSE, `:8000` | `active running` |
| Dashboard | `indicagent-dashboard` | `dashboard/` (Next.js) | Dev/prod server, `:3000` | `active running` |

"Not loaded" means the unit has not been started this boot (no `systemctl start` since last boot/reload) — distinct from `inactive (dead)`, which means it was started and then stopped/exited. Both need `systemctl start` (or ingestion resuming, for the ingestion-dependent tiers) to become live.

---

**Guide:** [Infrastructure Operations](../../operations/operations-infrastructure.md) (`docs/guides/running-services.md` referenced by an earlier version of this doc does not exist — `docs/guides/` itself is gone) · **DAG registry:** `services/service_auditor.py::_DAG_ORDER` · **Full wiring:** [DAG Topology](../../architecture/architecture-dag-topology.md) (renamed from `dag-topology.md`)
