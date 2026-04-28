-- Phase 076: Fix lifecycle constraints + backfill corrupted signal outcomes
--
-- Three changes:
-- 1. Backfill correction for 2,744 mislabeled signals
-- 2. Update status/outcome CHECK constraints for completeness
-- 3. Add labeling integrity constraint to prevent future corruption

-- ---------------------------------------------------------------------------
-- 1. Backfill correction
-- ---------------------------------------------------------------------------

-- 1a. Fix 2,430 impossible activations: activated_at < signal timestamp
--     These signals were activated on bars from before they were fired (stale HTF bars
--     or restart race). Clear all activation fields -- treat as never activated.
UPDATE signal_ledger
SET activated_at = NULL,
    activation_price = NULL,
    zone_entry_pct = NULL,
    bars_to_activation = NULL
WHERE activated_at IS NOT NULL
  AND activated_at < timestamp
  AND exit_at IS NOT NULL;

-- 1b. Fix 314 post-fire mislabeling: activated_at >= timestamp but outcome = never_activated
--     These were activated but TTL expired after tracker restart lost in-memory state.
--     Recompute outcome from mfe:
--       - mfe > 0 -> ttl_expired_ahead (signal moved in favor at some point)
--       - mfe <= 0 or NULL -> ttl_expired_behind
UPDATE signal_ledger
SET outcome = CASE
        WHEN mfe IS NOT NULL AND mfe > 0 THEN 'ttl_expired_ahead'
        ELSE 'ttl_expired_behind'
    END
WHERE activated_at IS NOT NULL
  AND outcome = 'never_activated'
  AND exit_reason = 'ttl_expired'
  AND exit_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. Index + constraint updates (from original migration)
-- ---------------------------------------------------------------------------

-- Add signal_id index for batch lifecycle updates (UPDATE ... WHERE signal_id = $1)
-- On TimescaleDB hypertables, CONCURRENTLY is not supported.
CREATE INDEX IF NOT EXISTS idx_signal_ledger_signal_id ON signal_ledger (signal_id);

-- Update status constraint to include target hit statuses
ALTER TABLE signal_ledger DROP CONSTRAINT IF EXISTS chk_signal_ledger_status;
ALTER TABLE signal_ledger ADD CONSTRAINT chk_signal_ledger_status
  CHECK (status IN (
    'pending', 'active', 'regime_suppressed', 'expired',
    'target_1_hit', 'target_2_hit', 'target_3_hit',
    'target_4_hit', 'target_5_hit'
  ));

-- Update outcome constraint to include condition_expired
ALTER TABLE signal_ledger DROP CONSTRAINT IF EXISTS chk_signal_ledger_outcome;
ALTER TABLE signal_ledger ADD CONSTRAINT chk_signal_ledger_outcome
  CHECK (outcome IS NULL OR outcome IN (
    'never_activated', 'stopped_at_entry', 'stopped_in_trade',
    'target_1', 'target_1_2', 'target_full',
    'ttl_expired_ahead', 'ttl_expired_behind',
    'condition_expired'
  ));

-- ---------------------------------------------------------------------------
-- 3. Labeling integrity constraint (prevents future corruption)
-- ---------------------------------------------------------------------------

-- A resolved signal that was activated should never have outcome = never_activated.
-- This catches the D-02 bug class at the DB level.
-- Note: This is a SOFT constraint -- it only fires for rows where exit_at IS NOT NULL
-- (fully resolved). Active signals still in flight may temporarily have activated_at
-- without a final outcome.
ALTER TABLE signal_ledger DROP CONSTRAINT IF EXISTS chk_signal_ledger_labeling_integrity;
ALTER TABLE signal_ledger ADD CONSTRAINT chk_signal_ledger_labeling_integrity
  CHECK (
    NOT (activated_at IS NOT NULL
         AND outcome = 'never_activated'
         AND exit_at IS NOT NULL)
  );
