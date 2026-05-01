-- Phase 78 P78-MATH-PLUGINS: remove shadow_registry entries for the
-- LLM agents replaced by pipeline-tier features (volume_zscore in I1
-- and corr_z in CrossAssetComputeAgent). Idempotent — safe to run
-- multiple times. DELETE on absent rows is a no-op.
--
-- Run on the production host AFTER deploying Phase 78 swarm changes:
--   docker exec -i timescaledb psql -U postgres -d indicagent \
--       < production/scripts/p78_remove_legacy_alpha_shadow_entries.sql
--
-- D-22 (correlation_v1 / volume_v1 retired) — see 78-CONTEXT.md.

DELETE FROM shadow_registry
 WHERE component_name IN ('correlation_v1', 'volume_v1');
