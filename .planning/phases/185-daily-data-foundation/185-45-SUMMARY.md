---
phase: 185-daily-data-foundation
plan: 45
subsystem: repo hygiene / dormant v2.x and AI stack removal
tags: [deletion, D-26, ai-stack, v2x, ollama, langfuse, archive, gap_closure]
requires: [185-42, 185-44]
provides:
  - "the I8 AI stack is gone from the tree, Docker and the database (ollama service, volume and image, langfuse database, BaseAIWorker, swarm, LLM chain, agent memory, five units, twelve tables)"
  - "every v2.x I1-I7 service, script, tool and unit with no live consumer is gone, with eight more tables (migration 458)"
  - "archive: git tag archive/v2x-ai-stack-2026-10 (local) plus data/backups/185-45 (dumps, ollama volume tar, /etc unit copies, MANIFEST.md with sha256 and restore commands)"
  - "todo 509: what stays because feature_vector_pipeline or the dashboard still reads it, and the ML batch chain"
affects: [185-43, 186-26, todo 056, todo 223, todo 509]
tech-stack:
  added: []
  patterns:
    - "removal scoped by an AST import graph from every kept entry point (services, scripts, tools, src.api.main): a module goes only if no kept root reaches it"
    - "a removal's newly unused names are deleted when nothing references them anywhere, else whitelisted with the reason (archive copies are excluded from vulture)"
key-files:
  created:
    - production/migrations/458_drop_v2x_ai_stack_tables.sql
    - .planning/phases/185-daily-data-foundation/185-45-INVENTORY.md
    - .planning/todos/pending/509-v2x-remainder-after-185-45-fvp-coupling-dashboard-surface-ml-chain.md
  modified:
    - production/docker-compose.yml
    - production/systemd/indicagent-wave2.target
    - production/systemd/indicagent-wave3.target
    - production/systemd/indicagent-wave4.target
    - services/service_auditor.py
    - src/api/main.py
    - src/config/settings.py
    - src/config/runtime_defaults.py
    - src/config/config_service.py
    - src/config/config_consumer.py
    - src/core/agent/base.py
    - src/core/ml/registry.py
    - src/core/service_utils.py
    - src/core/stream_keys.py
    - src/intelligence/schemas.py
    - src/intelligence/services/ml_trainer.py
    - src/observability/metrics.py
    - src/observability/spans.py
    - src/persistence/repository/signal_events_repository.py
    - scripts/ops/ops_complexity_census.py
    - tests/unit/test_table_and_apr_key_readers.py
    - tests/unit/test_market_data_ohlcv_boundary.py
    - tools/vulture_whitelist.py
    - tools/glossary_baseline.json
    - tools/scan_binary_patterns.py
    - pyproject.toml
  deleted: "288 files: 20 services, src/core/{ai,llm,memory}, src/intelligence/{ai,swarm,metrics,confluence}, src/validation, two API routes, the I7 plugin and SMC duplicates and other unreached v2.x modules, 12 scripts and tools, 22 unit and timer files, their tests"
decisions:
  - "Rules and inventory were committed in 185-45-INVENTORY.md, not the SUMMARY: services/rebuild_preconditions.py treats the existence of 185-45-SUMMARY.md as '185-45 landed' (a 186-26 precondition), so a partial SUMMARY would be a false landing marker"
  - "Rule 4 (added at inventory time, before any removal): code and tables reached by feature_vector_pipeline (v3, out of scope) or served by the running API to the running dashboard stay; listed in todo 509"
  - "The AI-only API routes narrative.py (no caller, its LLM backend down 4 weeks) and ai_stats.py (both dashboard callers handle a non-OK reply) went with the AI stack"
  - "Redpanda kept: three enabled and active units consume Kafka (feature-vector-writer, api SSE, compression-auditor)"
  - "ml_models and roll_events go to the reader guard's _KEEP_TABLES (it accepts only plan ids in retire clauses), each citing todo 509"
metrics:
  duration: about 50 minutes (23:05Z to 23:55Z)
  completed: 2026-10-07
  tasks: 2
  files: 327
---

# Phase 185 plan 45: remove the dormant AI stack and the archived v2.x I1-I7 pipeline

The I8 AI stack and every v2.x I1-I7 component with no live consumer are out of the tree, Docker and the database, recoverable from a local git tag and verified dumps. What a live surface still reads stays and is listed in todo 509.

## Pre-registered rules

Committed in `185-45-INVENTORY.md` (7f065befa) before any removal; repeated here.

1. No live consumer means all of: no enabled or active unit running the code (a failed or inactive unit nothing triggers counts as no consumer and goes with the code); no running container for a compose service; no import or reference from kept code, checked with an AST import graph (static and lazy imports, dotted-name string literals) from every kept entry point (`services/*.py`, `scripts/**/*.py` and `tools/*.py` not removed here, and `src.api.main`); for a table, no reader or writer after the code removal (the 185-44 reader guard plus a whole-word grep over services, src, scripts and tools).
2. Redpanda: removed only if no enabled or active unit produces to or consumes from Kafka and no live module imports the Kafka client outside the removed code.
3. Candidates found but not named in the plan are listed, not removed (todo 509).
4. Live surfaces this plan does not own keep their dependencies: `services/feature_vector_pipeline.py` (its `from src.intelligence.pipeline import ...` pulls in the executor, `register_plugins`, the I1-I7 plugin tier and `src/intelligence/archive/`; its CacheManager reads `signal_metrics`, `shadow_registry`, `cis_weights`, `calibration_curves`) and the running API serving the running dashboard (`signals.py`, `features.py`, `validation.py`, `drift.py`).
5. AI-only API routes go with the AI stack: `narrative.py` (no dashboard caller; LLM backend was the exited ollama container) and `ai_stats.py` (the two dashboard callers handle a non-OK reply).
6. Archive first, then one component per commit, full unit suite and the 185-44 guards green before the next.

## Archive (data/backups/185-45/, 5.6 GB, keep until about 2026-11-06)

| What | Size | Verified |
|---|---|---|
| git tag `archive/v2x-ai-stack-2026-10` on 12518ef9d (pre-removal HEAD) | local tag | the commit is on origin/main, so the tree is recoverable off-machine without pushing the tag |
| 35 table dumps (`pg_dump -Fc -t`), every v2.x and AI candidate including the kept ones | 2 to 8 KB each (all 0 rows except shadow_registry, 36 rows) | `pg_restore -l` on every file; restore-tested into a scratch database: shadow_registry 36 rows, intelligence_features and llm_calls clean |
| `langfuse.dump` (`pg_dump -Fc -d langfuse`) | 161 KB, 42 tables, no application rows | restored all 42 tables into the scratch database |
| `globals.sql` (roles) | 1 KB | |
| `ollama-data.tgz` (tar of production_ollama-data) | 5.98 GB (6.23 GB on disk) | `tar tzf` lists both model manifests |
| `ollama_models.txt` (`ollama list` plus manifests) | qwen3.5:4b (3.4 GB), nemotron-3-nano:4b (2.8 GB) | container started for the listing and stopped again |
| `etc-systemd/` (copies of every installed indicagent unit, timer, target and drop-in before removal) | 77 files | |
| `MANIFEST.md`, `SHA256SUMS` | | `sha256sum -c` clean |

## Components

| Component | Evidence of no live consumer | Commit | Rollback |
|---|---|---|---|
| (a) ollama compose service, `production_ollama-data` (6.23 GB) and the `ollama/ollama:rocm` image (4.68 GB) | container `Exited (0) 4 weeks ago`; only AI-stack code called it; `compose up -d --remove-orphans --dry-run` showed only ollama removed, every other container `Running` | d3c96b9c6 | restore the compose entry from the tag, `docker volume create`, untar `ollama-data.tgz` (MANIFEST.md), `compose up -d ollama` |
| (b) `indicagent_tempo-data` (0 B) | 0 links, no container (compose uses `production_tempo-data`) | no repo change | `docker volume create indicagent_tempo-data` |
| (c) `langfuse` database | not referenced anywhere in the repo; only connection the TimescaleDB scheduler; `DROP DATABASE langfuse WITH (FORCE)` | no repo change | `createdb` then `pg_restore langfuse.dump` |
| (d) I8 AI stack: alpha_swarm, narrative_swarm, llm_writer, swarm_ledger_writer, lineage_writer; `src/core/{ai,llm,memory}`, `src/intelligence/ai`; routes narrative, ai_stats; two agent-memory debug scripts, two skeptic tools; units alpha-swarm, narrative-compute, llm-writer, swarm-ledger-writer, lineage-writer, memory-batch (+timer) | four units inactive and disabled; lineage-writer was ACTIVE but its only producer (alpha_swarm's LineageRecorder) disabled and its topic empty (log start = high watermark 193958, 1-day retention): stopped and disabled first; memory-batch never installed; import graph: no kept root reaches the removed modules except `src.intelligence.swarm` (graduation_analyzer, moved to (e)) | 0fd0bc46b | `git checkout archive/v2x-ai-stack-2026-10 -- <paths>`, reinstall units from `production/systemd` (or `etc-systemd/`), daemon-reload |
| (e) v2.x signal path: 15 services (signal_tracker, signal_writer, lifecycle_writer, signal_metrics_analyzer/writer, graduation_analyzer/writer, signal, replay and probe auditors, shadow validator/auditor, confidence_calibration_monitor, ml_signal_training_agent, quality_floor_bootstrap) and weight_updater; their src modules; the unreached I7 plugin and SMC duplicates and helpers; 7 debug/ops scripts and 6 tools; 16 units with timers and drop-ins (intelligence-pipeline, feature-writer /etc only, and the rest) | intelligence-pipeline failed (ExecStart deleted in cb8f581a), the others inactive and disabled or never installed; no timer enabled; import graph clean from every kept root | 45e42b554 | `git checkout archive/v2x-ai-stack-2026-10 -- <paths>`; reinstall units; pg_restore the dumps |
| (e) tables, migration 458 (applied live) | 20 empty tables with no reader or writer left, no dependent view or foreign key: llm_calls, llm_model_scores, intelligence_ai_enrichment, signal_ai_enrichment, signal_lineage, swarm_agent_weights, six memory_* tables, intelligence_metrics, signal_metrics_dq_failures, transform_graduation, ml_signal_training, confidence_calibration, shadow_transition_log, pattern_reliability, tod_multipliers; signal_narratives and signal_probe_results IF EXISTS (absent live) | 45e42b554 | `pg_restore` each dump; `create_hypertable` for the eight hypertables (MANIFEST.md) |
| (f) Redpanda, `production_redpanda-data` (2.03 GB) | KEPT by rule 2, see below | none | |

Kept and listed (rule 4, todo 509): intelligence_features, signal_events, trade_frames, trade_executions, the signal_ledger view, setup_performance, signal_metrics, signal_metrics_ic, shadow_registry, cis_weights, calibration_curves, signal_transform_log, drift_state; remediation_ledger (self-healing engine, not v2.x); `src/intelligence/pipeline/`, `register_plugins.py`, `src/intelligence/archive/`, the kept `src/intelligence/trading/` utilities, composites, context, I1 and I3 features (reached by feature_vector_pipeline).

`systemctl list-units --all 'indicagent-*'` shows no unit for removed code (26 units listed, none of the removed names).

## Redpanda decision (rule 2): keep

Evidence 2026-10-07: consumer groups `feature_vector_writer_group` and `feature_vector_writer_config_consumer` (indicagent-feature-vector-writer, enabled and active), `sse_broadcaster` (indicagent-api, enabled and active) and `compression_auditor_config_consumer` (indicagent-compression-auditor, enabled and active) are Stable; `src/core/kafka_utils.py` is imported by kept modules (feature_vector_pipeline, the API, the fetcher and Tradier scripts). Every sampled topic is empty within its 1-day retention (log start = high watermark: market.bars 4454802, intelligence.i7.signals 2370694, llm.calls 84877, swarm.alpha 17184, intelligence.signal_lineage 193958), so nothing produced in the last day, but kept daemons consume. The `lineage_writer_*` groups belonged to the unit stopped in (d) and expire with their sessions.

## Verification

- Full `pytest tests/unit`: baseline 5 skipped, green; after (d) 8,024 passed, 5 skipped (one stale metric test fixed and re-run); after (e) 7,277 passed, 5 skipped, 0 failed. The 185-44 guards (reader, expiry, single-writer registry) pass after each commit.
- Plan verify (Task 2): suite green, `langfuse` absent from `psql -l`, `production_ollama-data` absent, `market_data_ohlcv` 1d rows 7,108,885 (unchanged). All raw market data tables and `bar_source_policy` present and untouched.
- vulture against the pre-plan baseline (102 findings): 0 new, 0 gone after each commit except the transient one between (d) and (e) (30 `shadow_only` findings in the I7 plugin duplicates that (e) deleted). Newly unused names were deleted when nothing referenced them anywhere (AI and v2.x metrics, stream keys, repository methods, settings fields, `tf_to_seconds`, `get_point_value`, `is_signal_stale`, `signal_dict_to_ranked`, `ModelRegistry.load_latest`), otherwise whitelisted with a 185-45 block (record fields, `BaseDaemon.get_config`, trading helpers the vulture-excluded archive copies call).
- Glossary (`--all` against the baseline), plugin invariant guards, ruff, black, pre-commit 9/9 clean on every commit.
- No edit under `src/intelligence/research/` or `statistics/`: repro_frozen does not apply.
- Census after the plan (`ops_complexity_census.py`): scripts_total 83 (scripts_ops 28), tables_public 80, views_public 15, apr_keys_without_reader 211 of 858, services_without_live_consumer 21, todos_pending 97. These counts include other plans' changes since the 185-44 baseline.
- Diff 12518ef9d..45e42b554: 327 files, +520, -59,720 lines.
- Disk: `/` 301 GB used before, 296 GB after, with the 5.6 GB archive added (Docker freed 6.23 GB volume plus 4.68 GB image).

## Deviations from plan

1. [Rule 1] Rules and inventory committed in `185-45-INVENTORY.md`, not the SUMMARY (see decisions: a SUMMARY is the 186-26 landing marker).
2. [Rule 4 pre-registered] The plan expected the plugin tier code and the named v2.x tables (intelligence_features, the Signal Ledger tables, signal_metrics and signal_metrics_ic) to go. The inventory found two live surfaces the plan did not own that still read them: feature_vector_pipeline (through the `src.intelligence.pipeline` package import) and the dashboard through the API. Per the consumer rule they stay; todo 509 has the decoupling step and the owner call on the dashboard surface. Named tables dropped: llm_calls, llm_model_scores, intelligence_ai_enrichment, signal_ai_enrichment, intelligence_metrics, signal_lineage, signal_metrics_dq_failures; signal_transform_log stays (TransformRecorder in the kept pipeline writes it); remediation_ledger stays (self-healing engine, not v2.x).
3. [Scope, rule 1] Siblings dropped with them because their only readers and writers were removed here: six memory_* tables, swarm_agent_weights, transform_graduation, ml_signal_training, confidence_calibration, shadow_transition_log, pattern_reliability, tod_multipliers.
4. [Scope] The `ollama/ollama:rocm` image (4.68 GB) was removed with the service; restore commands pull it again.
5. [Rule 3] `docker compose up -d --remove-orphans` was dry-run first: ib-gateway's container was created from a worktree compose file, so a recreate would have touched it; the dry run showed none.
6. [Rule 2] Kept code edited where it pointed at removed units: `ml_trainer` no longer sends SIGUSR1 to the removed alpha-swarm unit; the census `DORMANT_UNITS` list is empty; wave targets lost their `After=` lines for removed units and were reinstalled; the `swarm.` and `ai.` prefixes left `ConfigService.OPS_PREFIXES` and the `runtime_defaults` swarm fallbacks went, so the reader guard sees those keys as orphaned. `hmm_trainer.emit_sigusr1` still targets the uninstalled intelligence-pipeline unit and degrades to a logged skip (todo 509).
7. [Side effect] A global `systemctl reset-failed` after the unit removals also cleared the failed marker on indicagent-feature-vector-pipeline and indicagent-dividend-event-writer@yahoo (now inactive). No unit was started or stopped by it; timers are unchanged. Their next failure sets it again.
8. [Orchestrator instruction vs plan] The orchestrator listed "git tag pushed" as an archive precondition; the plan says "local tag; do not push without the owner". The tag stays local. The tagged commit 12518ef9d is on origin/main, so the pre-removal tree is recoverable off-machine; `git push origin archive/v2x-ai-stack-2026-10` publishes the tag when the owner wants it.
9. The test-hit scanner first missed `from src.api.routes import ai_stats` in the route smoke test (collection error on the first (d) suite run); fixed and re-run green. The (a) suite run's summary line was swallowed by `-q -q`; later runs use the plain summary.
10. CLAUDE.md files (root "Archived and dormant" line, `src/intelligence/CLAUDE.md`'s AI and plugin sections) still describe removed code. Not edited here: instruction files are outside an executor's remit; 185-43 owns the docs.

## For 185-43

- APR keys in `_PENDING_RETIREMENT` (`retire: 185-43`): `swarm.max_concurrent_calls`, `swarm.min_confidence`, `swarm.min_tf_minutes`, `swarm.weight_floor`, `swarm.weight_min_samples`; `ai.agent.{correlation_v1,counterfactual_v1,ml_scorer_v1,regime_coherence_v1}.shadow_mode`; `alpha.frame.{cluster_radius_atr,min_width_atr,proximity_weight,single_level_radius_atr,strength_weight,zone_buffer_atr}`; `feature.lifecycle_writer.{batch_size,flush_interval_secs,max_buffer_size}`; `feature.signal_writer.{batch_size,flush_interval_secs,max_buffer_size}`; `feature.signal_tracker.{bootstrap_active_window_days,bootstrap_dedup_window_days,bootstrap_max_attempts,bootstrap_pending_window_days}`; `feature.signal_auditor.audit_lookback_hours`; `infra.signal_auditor.audit_interval_seconds`; `threshold.signal_tracker.staleness_score` (28 keys, all present in config_state).
- Not in the guard (the service auditor's `"alert.lag." + unit` prefix counts as a reader) but orphaned: `alert.lag.{alpha-swarm,narrative-compute,llm-writer,swarm-ledger-writer,lineage-writer,intelligence-pipeline,feature-writer,signal-tracker-compute,signal-writer,lifecycle-writer,signal-metrics-writer,graduation-compute,graduation-writer}`. Retire them in the same migration.
- Tables: migration 458 is applied and committed; `_KEEP_TABLES` now holds `ml_models` and `roll_events` (todo 509). No further 185-45 table is pending.
- Units: none left to retire; `_DAG_ORDER` lost 21 entries, `_AGENT_ID_TO_UNIT` 14, `_ONESHOT_UNITS` 7. The census `services_without_live_consumer` fell from 38 (baseline) to 21.
- Docs naming removed code: root CLAUDE.md "Archived and dormant", `src/intelligence/CLAUDE.md` (AI stack, plugin authoring, LLM chain, Signal Ledger sections), `src/intelligence/archive/README.md`, `services/README.md`, glossary entries for the AI stack if any. The vulture whitelist's 185-45 block names what stays because of rule 4.
- Backups: `data/backups/185-45/` (5.6 GB) can be deleted about 2026-11-06.

## Known stubs

None.

## Threat flags

None. T-185-45-01 mitigated by the pre-registered consumer rule, the import graph and the suite after each commit (two live surfaces found and respected); T-185-45-02 by the tag, the restore-tested dumps, the volume tar and the manifest before any removal; T-185-45-03: raw market data tables untouched, 1d row count unchanged.

## Self-Check: PASSED

- FOUND commits on main: 7f065befa, d3c96b9c6, 0fd0bc46b, 45e42b554.
- FOUND: production/migrations/458_drop_v2x_ai_stack_tables.sql, 185-45-INVENTORY.md, todo 509, data/backups/185-45/MANIFEST.md (sha256sum -c clean).
- GONE: services/alpha_swarm.py, services/signal_tracker.py, src/core/ai, src/intelligence/ai, src/validation; the langfuse database; production_ollama-data; the twenty dropped tables.
