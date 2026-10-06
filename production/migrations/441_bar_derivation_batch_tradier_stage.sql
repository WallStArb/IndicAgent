-- 441: bar_derivation_batch admits stage 'tradier' (phase 185 plan 27, VERIFICATION gap A).
--
-- The Tradier daily loader (scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py)
-- stays the second 1d writer (owner decision 2026-10-03, migration 438), but its write path now
-- does what D2 does for IBKR names: canonical_bar_lineage to the raw D1 observation under rule
-- tradier-v1, the D2a scrub over the names it changed, and fresh 1d bar_content_digest rows.
-- Every loader write run is one bar_derivation_batch row with its own stage, so the D2 daily
-- stage's changed-since watermark (max finished_at of stage 'daily') never moves on a loader run.
--
-- Constraint change only, no data change. Idempotent.

BEGIN;

ALTER TABLE bar_derivation_batch DROP CONSTRAINT IF EXISTS bar_derivation_batch_stage_check;
ALTER TABLE bar_derivation_batch
    ADD CONSTRAINT bar_derivation_batch_stage_check
    CHECK (stage IN ('scrub', 'grid', 'daily', 'seam_audit', 'listing_venue', 'legacy', 'tradier'));

COMMENT ON TABLE bar_derivation_batch IS 'Provenance for every derivation-side run (scrub, grid, daily, seam audit, listing venue, legacy imports, Tradier daily loads): stage, rule version, code commit, APR snapshot, status. Single writer role bar_derivation_writer.';

COMMIT;
