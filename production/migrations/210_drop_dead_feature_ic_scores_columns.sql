-- Migration 210: drop dead decay columns on feature_ic_scores — Phase 143 Plan 02, D3
--
-- is_decaying, decay_detected_at, and recovery_eligible_at were added by migration 160
-- for an AlphaDecayMonitor design that was superseded by the feature_registry lifecycle
-- state machine (migration 172) and this phase's routing work (migrations 216/217).
-- 143-RESEARCH.md's "State of the Art" section confirms no live INSERT or UPDATE ever
-- writes these three columns — they are dead weight on a hypertable, not read by any
-- query. Lifecycle state lives on feature_registry.status +
-- feature_registry.consecutive_shadow_passes / observations_since_demotion (migration
-- 216) instead.

BEGIN;

ALTER TABLE feature_ic_scores
    DROP COLUMN IF EXISTS is_decaying,
    DROP COLUMN IF EXISTS decay_detected_at,
    DROP COLUMN IF EXISTS recovery_eligible_at;

COMMIT;
