-- Migration 458: drop the tables of the archived v2.x I1-I7 signal path and the dormant I8 AI
-- stack (phase 185 plan 45; owner decision 2026-10-07: "clean it").
--
-- Every table below was dumped before this migration was written, each verified with
-- pg_restore -l, and restore-tested in a scratch database (langfuse, shadow_registry,
-- intelligence_features, llm_calls). The dumps, their sha256 and the restore commands are in
-- data/backups/185-45/MANIFEST.md (gitignored, kept 30 days); the code is tagged
-- archive/v2x-ai-stack-2026-10. Restore one table:
--   pg_restore -U postgres -h localhost -d indicagent --no-owner data/backups/185-45/<table>.dump
-- (hypertables come back as plain tables; re-run create_hypertable as the manifest says).
--
-- PRECONDITIONS (185-45, recorded in 185-45-INVENTORY.md and 185-45-SUMMARY.md):
--   1. Every table had 0 rows on 2026-10-07.
--   2. No reader or writer remains in services/, src/, scripts/ or tools/ after the 185-45
--      code removal (the 185-44 reader guard plus a whole-word grep; for llm_calls and
--      signal_lineage the only remaining hits are Kafka topic names and comments).
--   3. No view, materialized view or foreign key depends on any of them (pg_depend and
--      pg_constraint checked before the apply).
--   4. Their writers' units were disabled and uninstalled first.
--
-- Dumps (data/backups/185-45/<table>.dump):
--   AI stack:  llm_calls, llm_model_scores, intelligence_ai_enrichment, signal_ai_enrichment,
--              signal_lineage, swarm_agent_weights, memory_calibration_promoted,
--              memory_calibration_spc, memory_episodes_labeled, memory_episodes_raw,
--              memory_regime_transitions, memory_system_state
--   v2.x:      intelligence_metrics, signal_metrics_dq_failures, transform_graduation,
--              ml_signal_training, confidence_calibration, shadow_transition_log,
--              pattern_reliability, tod_multipliers
--   IF EXISTS, absent from the live DB but still created in the migration catalog (no dump):
--              signal_narratives (migration 086), signal_probe_results
--
-- Kept (a live surface still reads or writes them; 185-45 rule 4): intelligence_features,
-- signal_events, trade_frames, trade_executions, the signal_ledger view, setup_performance,
-- signal_metrics, signal_metrics_ic, shadow_registry, cis_weights, calibration_curves,
-- signal_transform_log, drift_state, remediation_ledger. Raw market data is not touched.
--
-- None of these tables is compressed with data (all empty), and a plain DROP decompresses
-- nothing, so no VACUUM is required.

BEGIN;

DROP TABLE IF EXISTS llm_calls;
DROP TABLE IF EXISTS llm_model_scores;
DROP TABLE IF EXISTS intelligence_ai_enrichment;
DROP TABLE IF EXISTS signal_ai_enrichment;
DROP TABLE IF EXISTS signal_lineage;
DROP TABLE IF EXISTS swarm_agent_weights;
DROP TABLE IF EXISTS memory_calibration_promoted;
DROP TABLE IF EXISTS memory_calibration_spc;
DROP TABLE IF EXISTS memory_episodes_labeled;
DROP TABLE IF EXISTS memory_episodes_raw;
DROP TABLE IF EXISTS memory_regime_transitions;
DROP TABLE IF EXISTS memory_system_state;
DROP TABLE IF EXISTS signal_narratives;

DROP TABLE IF EXISTS intelligence_metrics;
DROP TABLE IF EXISTS signal_metrics_dq_failures;
DROP TABLE IF EXISTS transform_graduation;
DROP TABLE IF EXISTS ml_signal_training;
DROP TABLE IF EXISTS confidence_calibration;
DROP TABLE IF EXISTS shadow_transition_log;
DROP TABLE IF EXISTS pattern_reliability;
DROP TABLE IF EXISTS tod_multipliers;
DROP TABLE IF EXISTS signal_probe_results;

COMMIT;
