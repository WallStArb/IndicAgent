-- Migration 147: Fix exit_reason aliasing for target hits
--
-- Bug (Phase 135): lifecycle_replay.py set exit_reason = outcome for target exits
-- (target_1 / target_1_2 / target_full) because market_entry_exit_reason was None
-- and the write path fell back to `or m_outcome`. This means exit_reason and outcome
-- carried identical values for target hits but different values for stops
-- (exit_reason='stop_loss', outcome='stopped_in_trade'), introducing representational
-- bias: any model using exit_reason as a feature is exposed to an information leak
-- (it encodes the outcome before the feature is consumed).
--
-- Fix:
--   1. Backfill 56,527 target rows to exit_reason='target_hit'
--   2. Drop old chk_te_exit_reason constraint (included target_1/target_1_2/target_full)
--   3. Add new constraint with 'target_hit' as the canonical target exit reason
--
-- Code fixes applied in the same session:
--   - lifecycle_replay.py: m_exit_reason = "target_hit" for is_stop=False (not None)
--   - lifecycle_tracker.py: _make_exit() exit_reason="target_hit" for zone target exits

BEGIN;

-- Step 1: Drop old constraint first (UPDATE would violate it since 'target_hit' is not in it)
ALTER TABLE trade_executions DROP CONSTRAINT IF EXISTS chk_te_exit_reason;

-- Step 2: Backfill existing target exit rows
UPDATE trade_executions
SET exit_reason = 'target_hit'
WHERE exit_reason IN ('target_1', 'target_1_2', 'target_full');

-- Step 3: New constraint — exit_reason is an operational exit code, not an outcome label
ALTER TABLE trade_executions
    ADD CONSTRAINT chk_te_exit_reason
    CHECK (exit_reason IS NULL OR exit_reason IN (
        'stop_loss',
        'chandelier_stop',
        'condition_expired',
        'ttl_expired',
        'ttl_expired_ahead',
        'ttl_expired_behind',
        'target_hit'
    ));

COMMIT;
