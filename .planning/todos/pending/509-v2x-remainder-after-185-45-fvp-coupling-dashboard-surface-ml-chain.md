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

## 1. feature_vector_pipeline imports the v2.x pipeline package (DONE 2026-10-26)

Done 2026-10-26. `src/intelligence/pipeline/__init__.py` exports only OutputQueue,
PerKeyWorkerManager and PluginStateManager. CacheManager is deleted: its v2.x loaders read tables
with no writer and its cross-asset and macro caches were write-only (nothing called `snapshot()`),
so the service no longer subscribes to topic_cross_asset or topic_macro_signals. Its one live job,
LISTEN instruments into `invalidate_active_contracts_cache`, is now
`src/config/instruments_listener.py` with its two timings in APR (migration 503). An AST
reachability check from every service, script, tool and `src.api.main` then freed 194 modules,
all deleted: the executor and signal stages, `register_plugins`, `src/intelligence/archive/`,
`composites/`, `context/`, `plugins/`, `features/i1_indicators/`, `features/i3_structure/`,
`features/smc_context/`, all of `trading/` except `signal_outcome` (item 2 reads it),
`utils/common`, `src/monitoring/`, `core/ml/transform_recorder`, `observability/circuit_breaker`
and `plugin_observer`. Names left unused by the deletion were removed where they were plain
dead code (20 metric constants, six v2.x Settings fields, the tick-size and plugin-skip helpers,
a stream key) and whitelisted for vulture where they belong to items 2 and 3 (schema and
repository fields, `core/ml/features`). 41 test files that covered only deleted code were
removed; the instrument-row builder's tests moved to `tests/unit/config/test_instruments_listener.py`.

Original text:


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

Owner decision 2026-10-26: delete the v2.x signal panels, their API routes and the empty tables
(each dumped already in `data/backups/185-45/`); phase 188's forward runner builds its own views.

DONE 2026-10-26 (migration 521): signal, features, validation and drift routes, the signal events
repository, `src/intelligence/trading/`, the feature-validation service, the dashboard's signal,
narrative, AI swarm and landing surfaces; `drift_state`, `setup_performance` and ten
`ui.signals.*` keys dropped. The dashboard-side follow-ups closed with cockpit slice 1
(2026-10-26): the SSE bridge, `topic_signals_aggregated` and the signal scorecard frames,
`use-market-stream.ts`, `use-observability-stream.ts`, `use-demo-data.ts` and ProfileChip are
gone; `dashboard/src/hooks/` holds only `use-api.ts`. Still open (checked 2026-10-27): the I7
regime_type step in `.github/workflows/ci.yml`, the matching `tools/pre-commit.hook` check,
`tools/check_plugin_invariants.sh`, `tools/scan_binary_patterns.py` and two
`tools/duplicate_test_allowlist.txt` lines still target the deleted `src/intelligence/trading/`
and pass vacuously; procedure `weekly_db_maintenance` still runs `ANALYZE setup_performance`
(unscheduled; drop it); `shadow_registry` (36 rows of plugin settings, dumped) awaits an owner
drop-or-keep call.

This remainder rode with the dashboard lane until the owner closed that lane on 2026-10-27; it has
no lane now and sits below the build lanes as cleanup.

## 4. Smaller items

- `roll_events` (written by `ops_roll_batch.py`) lost its only readers (v2.x replay scripts); in
  `_KEEP_TABLES` until someone owes it a reader or it retires.
- DONE 2026-10-26: Kafka leftovers. Eight dead DLQ builders, the I8 narrative topics, the legacy
  Redis key helpers, `topic_market_ticks` and `topic_intelligence_shadow` deleted from
  `stream_keys`; `dlq_writer` reads the eight live DLQs (it had never read
  `intelligence.feature_vectors.dlq`); `infrastructure_ensure_topics.sh` owns DLQ provisioning at
  7 days, and the empty retired DLQ topics were deleted from Redpanda; SSE subscribes only to
  topics with a producer or a pending item 2 decision (`intelligence`, `intelligence.journal`,
  `signals.aggregated`). Left for item 2: those three topics, and the dashboard's dead
  `narrative_data`, `tick_data` and `indicator_data` listeners in `use-market-stream.ts`.
- DONE 2026-10-26: alert rules and Grafana panels on metrics nothing emits. Six Prometheus rules,
  three Grafana rules and eleven dashboard panels deleted, the signals-I8, plugin-latency and
  shadow-validation dashboards deleted, the gap-fill DLQ rule and panel fixed (they queried the
  counter without its `_total` and never saw a value), the signal DLQ panel retargeted to
  `dlq_messages_total` by topic, and the dead shadow, config and CIS instruments in `metrics.py`
  deleted.
  `tests/unit/observability/test_alert_and_dashboard_metric_refs.py` now fails on any queried
  metric the code does not declare under its exported name. Left for when alerting is wired
  (deferred, UAT): consumer lag and provider-bars stoppage each alert in both Prometheus
  (`ConsumerLagHigh`, `ProviderDataStoppage`) and Grafana (`consumer_lag_writer`,
  `provider_dead`, which also lacks the session-hours gate); pick one home per condition.
  For item 2: `dashboard/src/hooks/use-observability-stream.ts` (the v2.x pipeline-flow view:
  I1/I7 latency, swarm age) still links its plugin and signal nodes to the deleted Grafana
  dashboards; the hub and panel navigation links were removed.
- APR keys `alert.lag.<unit>` for the removed units (alpha-swarm, narrative-compute, llm-writer,
  swarm-ledger-writer, lineage-writer, intelligence-pipeline, feature-writer,
  signal-tracker-compute, signal-writer, lifecycle-writer, signal-metrics-writer,
  graduation-compute, graduation-writer): the reader guard counts the service auditor's
  `"alert.lag." + unit` prefix as a reader, so they are not in `_PENDING_RETIREMENT`; 185-43 can
  retire them with the other keys.
- Live/batch cache asymmetry in `feature_vector_pipeline._get_cache` (found 2026-10-26, todo 529
  review): its warm-up replays the buffered history from that buffer's bar 0 and calls
  `update_wk_vwap`, not `advance_bar`, while `compute_batch` starts at bar 1 and advances per
  bar; nor does it follow `compute_batch`'s `refresh_regime` cadence. The unit parity tests
  (`tests/unit/intelligence/live_parity.py`) mirror `compute_batch`, so they cannot see it.
  Decide with item 1's successor whether the streaming path survives; fix or delete with it.
- `src/self_healing` and `remediation_ledger` (Phase 109 self-healing engine, unit inactive): not
  v2.x, not named, kept.
- DONE 2026-10-26: the unreached non-v2.x modules (`src/persistence/logic/`, `src/persistence/writer/`,
  `parity_repository.py`, `feature_snapshot_repository.py`, `src/core/schemas/parity.py`,
  `src/intelligence/dag.py`) deleted with their tests; only tests and the vulture whitelist
  imported them, and every table they touched keeps another reader.

Supersedes the remaining scope of todos 056 and 223 (both written before the owner's 2026-10-07
"clean it" decision, which replaced their archive-in-tree approach with the tag-plus-dumps archive).
