# Phase 185 plan 45: pre-registered rules and inventory

Committed before any removal. The plan asks for the rules in the SUMMARY, but
`services/rebuild_preconditions.py` treats the existence of `185-45-SUMMARY.md` as "185-45 landed" (a
186-26 rebuild precondition), so a partial SUMMARY would be a false landing marker. The rules and the
inventory live here; the SUMMARY repeats them when the plan is done.

## Pre-registered rules (committed before any removal)

1. No live consumer means all of:
   - `systemctl list-units --all 'indicagent-*'` shows no enabled or active unit running the code. A failed or inactive unit that nothing triggers counts as no consumer and is removed with the code.
   - `docker ps` shows no running container for a compose service.
   - `grep -rn` over services, src, scripts, production and tests finds no import or reference outside the code removed together. Reachability is checked with an AST import graph (static imports, lazy imports and dotted-name string literals) from every kept entry point: every `services/*.py`, `scripts/**/*.py` and `tools/*.py` not removed here, plus `src.api.main`. A module is removed only if no kept entry point reaches it.
   - For a table, no reader or writer remains after the code removal (the 185-44 reader guard, `tests/unit/test_table_and_apr_key_readers.py`, plus a grep over services, src, scripts and tools).
2. Redpanda: remove the service, its compose entry and production_redpanda-data only if no enabled or active unit produces to or consumes from Kafka and no live module imports the Kafka client outside code removed here. If any kept daemon depends on it, keep it and record the evidence. Topic data is never a reason to keep it.
3. Candidates found by the census but not named in the plan are listed, not removed; they go to a pending todo.
4. Live surfaces this plan does not own keep their dependencies. Two were found during inventory:
   - `services/feature_vector_pipeline.py` (v3 compute, enabled, out of scope by the plan). It imports `src.intelligence.pipeline`, whose `__init__` pulls in the executor, `register_plugins`, the I1-I7 plugin tree and `src/intelligence/archive/`. Its CacheManager also reads `signal_metrics`, `shadow_registry`, `cis_weights` and `calibration_curves`.
   - The running API (`indicagent-api`), which the running dashboard polls. `src/api/routes/signals.py`, `features.py`, `validation.py` and `drift.py` read `signal_events`, `trade_frames`, `trade_executions`, the `signal_ledger` view, `setup_performance`, `signal_metrics`, `signal_metrics_ic` and `intelligence_features`.
   Code and tables reached from either stay; they are listed for a follow-up todo (decouple the feature vector pipeline from the v2.x pipeline package, and retire the dashboard's v2.x signal panels with their routes).
5. API routes that exist only for the AI stack go with it: `narrative.py` (no dashboard caller; its LLM backend is the ollama container, exited for 4 weeks) and `ai_stats.py` (the dashboard swarm panel calls it, and both callers handle a non-OK response: `swarm-intelligence-panel.tsx` shows the HTTP error, `signal-swarm-breakdown.tsx` shows "No swarm data yet").
6. Order: archive first (Task 1), then one component per commit with the full unit suite and the 185-44 guards green before the next.

## Inventory (2026-10-07, before removal)

### Docker and databases

| Candidate | Evidence | Disposition |
|---|---|---|
| ollama compose service, `production_ollama-data` (6.228 GB) | container `Exited (0) 4 weeks ago`; started once for `ollama list` and stopped again; models qwen3.5:4b, nemotron-3-nano:4b | remove (a) |
| `indicagent_tempo-data` (0 B) | 0 links, no container; compose uses `production_tempo-data` | remove (b) |
| `langfuse` database | 42 tables, no application rows, not referenced anywhere in the repo; only connection is the TimescaleDB scheduler | remove (c) |
| Redpanda, `production_redpanda-data` (2.03 GB) | see Redpanda decision | keep |
| `indicagent_test` | test database | keep (plan) |
| `a6bfd2d6...` anonymous volume (0 B, 1 link) | attached to a running container, not named by the plan | listed, not touched |

### Units

| Unit | State | Code | Disposition |
|---|---|---|---|
| intelligence-pipeline (+ .d drop-in) | failed, enabled; last start 2026-10-01 14:17 EDT, failed 11 s later (ExecStart file deleted in cb8f581a) | already deleted | remove (e) |
| feature-writer (+ .d drop-in, /etc only) | inactive, disabled; no repo unit file | already deleted | remove (e) |
| lineage-writer | ACTIVE, enabled; consumes `intelligence.signal_lineage`, whose only producer is alpha_swarm (disabled); topic log start = high watermark 193958 (empty, 1-day retention), group lag 4 | services/lineage_writer.py | stop, disable, remove (d) |
| alpha-swarm, narrative-compute, llm-writer, swarm-ledger-writer | inactive, disabled | I8 AI services | remove (d) |
| memory-batch (+ timer, repo only) | not installed; ExecStart `scripts/ops/memory/ops_batch_agent_memory.py` does not exist | agent memory | remove (d) |
| signal-writer, signal-tracker-compute, lifecycle-writer, signal-metrics-compute, signal-metrics-writer, graduation-compute, graduation-writer, signal-auditor, signal-replay | inactive, disabled, no timer | v2.x signal path | remove (e) |
| shadow-auditor (+ timer), weight-updater (static, + timer), ml-signal-training-materialize (+ timer) | inactive; timers disabled | v2.x signal path | remove (e) |
| signal-probe-auditor, shadow-validator, confidence-calibration-monitor (+ timers, repo only) | not installed | v2.x signal path | remove (e) |
| feature-vector-pipeline | failed, enabled | v3 compute | keep (plan) |
| dividend-event-writer@ | live data path | | keep (plan) |

### Tables (all dumped, see data/backups/185-45/MANIFEST.md)

Every candidate table has 0 rows except `shadow_registry` (36 rows, newest 2026-06-27).

| Table | Readers or writers outside the removed code | Disposition |
|---|---|---|
| llm_calls, llm_model_scores, intelligence_ai_enrichment, signal_ai_enrichment, signal_lineage, swarm_agent_weights | only AI-stack code and ai_stats.py | drop with (d) if the guard confirms |
| memory_* (6 tables) | only src/core/memory and the agent memory scripts | drop with (d) if the guard confirms |
| intelligence_metrics, signal_metrics_dq_failures, signal_transform_log, transform_graduation, ml_signal_training, confidence_calibration, shadow_transition_log, pattern_reliability, tod_multipliers, drift_state | v2.x code only, to be confirmed by the guard after the code removal | drop with (e) if the guard confirms |
| intelligence_features, signal_events, trade_frames, trade_executions, signal_ledger (view), setup_performance, signal_metrics, signal_metrics_ic | the API routes and feature_vector_pipeline (rule 4) | keep, listed |
| shadow_registry, cis_weights, calibration_curves | feature_vector_pipeline's CacheManager (rule 4) | keep, listed |
| remediation_ledger, remediation_success_rates | src/self_healing (Phase 109 self-healing engine, not v2.x) | keep, listed |

### Redpanda decision (rule 2)

Keep. Evidence on 2026-10-07: consumer groups `feature_vector_writer_group` and `feature_vector_writer_config_consumer` (indicagent-feature-vector-writer, enabled and active, a v3 writer), `sse_broadcaster` (indicagent-api, enabled and active) and `compression_auditor_config_consumer` (indicagent-compression-auditor, enabled and active) are all Stable; `src/core/kafka_utils.py` is imported by kept modules (feature_vector_pipeline, the API, the fetcher and Tradier scripts). Every topic sampled is empty within its 1-day retention (log start = high watermark: market.bars 4454802, intelligence.i7.signals 2370694, llm.calls 84877, swarm.alpha 17184, intelligence.signal_lineage 193958), so nothing has produced in the last day, but kept daemons consume, so the rule says keep.
