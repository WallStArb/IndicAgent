-- Migration 462: drop the v2.x SLA husk tables (phase 186-45 stragglers).
--
-- All nine are zero-row remnants the 185-45 sweep missed (migration 458 dropped
-- the AI-stack tables; these are the I1-I7 Signal Ledger Architecture tables).
-- The pre-removal tree is the local tag archive/v2x-ai-stack-2026-10 and dumps
-- live in data/backups/185-45/ (about 2026-11-06 expiry), so nothing is lost:
-- every table here had count(*) = 0 on 2026-10-09.
--
-- signal_ledger is the registry's own "SLA query surface (v2.x, archived)"
-- join view and depends on three of them; it drops first.
--
-- feature_vectors_v2 is an empty hypertable (0 chunks); plain DROP TABLE
-- removes it through the TimescaleDB extension hooks. No compressed-column
-- type change is involved, so the VACUUM template rule does not apply.

BEGIN;

DROP VIEW IF EXISTS public.signal_ledger;

DROP TABLE IF EXISTS public.trade_executions;  -- child first: FK into trade_frames
DROP TABLE IF EXISTS public.signal_events;
DROP TABLE IF EXISTS public.trade_frames;
DROP TABLE IF EXISTS public.alpha_multiplier_shadow;
DROP TABLE IF EXISTS public.signal_transform_log;
DROP TABLE IF EXISTS public.intelligence_features;
DROP TABLE IF EXISTS public.feature_vectors_v2;
DROP TABLE IF EXISTS public.signal_metrics;
DROP TABLE IF EXISTS public.signal_metrics_ic;

COMMIT;
