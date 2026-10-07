---
status: pending
priority: P2
filed: 2026-10-07
source: plan 185-45 (pre-registered rules 3 and 4: candidates kept because a live surface still reads them, or found but not named)
owner: owner call on the dashboard surface and the ML batch chain; the rest is mechanical once those are decided
---

# v2.x remainder after 185-45: the feature vector pipeline's coupling, the dashboard's signal surface, the ML batch chain

Plan 185-45 removed the I8 AI stack and every v2.x service, unit, script and table with no live
consumer (archive: git tag `archive/v2x-ai-stack-2026-10`, dumps in `data/backups/185-45/`). What
stays, and why, with the step that would free it:

## 1. feature_vector_pipeline imports the v2.x pipeline package

`services/feature_vector_pipeline.py` (v3 compute, enabled, failed) imports four names from
`src.intelligence.pipeline` (CacheManager, OutputQueue, PerKeyWorkerManager, PluginStateManager).
The package `__init__` also imports the executor, which imports `register_plugins`, which imports the
whole I1-I7 plugin tier and `src/intelligence/archive/`. CacheManager reads `signal_metrics`,
`shadow_registry`, `cis_weights` and `calibration_curves`; the pipeline stages write
`signal_transform_log` through TransformRecorder.

Step: trim `src/intelligence/pipeline/__init__.py` to the four names (and move CacheManager's v2.x
loaders out), then rerun the 185-45 import-graph check. Expected to free the executor,
signal_processor, quality_gate, ranker, regime_gate, calibrator, winner_selector, register_plugins,
`src/intelligence/archive/`, most of `src/intelligence/trading/` and the five tables above. The
185-45 vulture whitelist block (names whose only users were removed) shrinks with it.

## 2. The dashboard's v2.x signal panels and their API routes

The running dashboard polls `src/api/routes/signals.py` (signal_events, trade_frames,
trade_executions, the signal_ledger view, setup_performance, signal_metrics, signal_metrics_ic,
intelligence_features), and the API also serves `features.py`, `validation.py` and `drift.py`
(intelligence_features, drift_state). All of these tables are empty and have no writer since
185-45. The swarm panel (`swarm-intelligence-panel.tsx`, `signal-swarm-breakdown.tsx`) now gets
HTTP 404 from the removed `/api/ai/stats` and `/api/signals/{id}/ai`; both handle it (error text,
"No swarm data yet").

Step: owner decides whether the dashboard keeps any signal view. If not, delete the panels and the
routes, then drop the tables (each dumped already in `data/backups/185-45/`).

## 3. The ML batch chain

`ml_trainer` (ml-training), ml-orchestrator, ml-discovery, ml-data-quality and `hmm_trainer` train
on v2.x signal outcomes or `intelligence_features`. 185-45 removed the alpha swarm reload signal
from `ml_trainer`; `hmm_trainer.emit_sigusr1` still targets the uninstalled
`indicagent-intelligence-pipeline.service` and degrades to a logged skip. `ml_models` is kept in
the reader guard's `_KEEP_TABLES` until this is decided.

## 4. Smaller items

- `roll_events` (written by `ops_roll_batch.py`) lost its only readers (v2.x replay scripts); in
  `_KEEP_TABLES` until someone owes it a reader or it retires.
- Kafka leftovers for removed producers: `dlq_writer.py`'s lineage, LLM, signal and lifecycle DLQ
  topics and their stream keys; `infrastructure_init_kafka_topics.py` and
  `infrastructure_ensure_topics.sh` topic lists; the SSE broadcaster's narratives subscription.
- Alert rules and Grafana panels on metrics no service emits now:
  `production/alertmanager-rules.yml` (signal_tracker, signal_replay_auditor, lifecycle_writer),
  `production/grafana/provisioning/alerting/alert-rules.yml` (signal_writer), dashboards
  operations, pipeline-health, signals-i8.
- APR keys `alert.lag.<unit>` for the removed units (alpha-swarm, narrative-compute, llm-writer,
  swarm-ledger-writer, lineage-writer, intelligence-pipeline, feature-writer,
  signal-tracker-compute, signal-writer, lifecycle-writer, signal-metrics-writer,
  graduation-compute, graduation-writer): the reader guard counts the service auditor's
  `"alert.lag." + unit` prefix as a reader, so they are not in `_PENDING_RETIREMENT`; 185-43 can
  retire them with the other keys.
- `src/self_healing` and `remediation_ledger` (Phase 109 self-healing engine, unit inactive): not
  v2.x, not named, kept.
- Modules nothing reaches that are not v2.x or AI: `src/persistence/logic/`,
  `src/persistence/writer/`, `src/persistence/repository/parity_repository.py`,
  `feature_snapshot_repository.py`, `src/core/schemas/parity.py`,
  `src/intelligence/composites/common.py`, `src/intelligence/context/vix_context.py`,
  `src/intelligence/dag.py`.

Supersedes the remaining scope of todos 056 and 223 (both written before the owner's 2026-10-07
"clean it" decision, which replaced their archive-in-tree approach with the tag-plus-dumps archive).
