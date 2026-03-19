-- Migration: Add CHECK constraint for signal_ledger.outcome column
-- Phase 39.1 — SignalOutcome enum enforcement
-- NOTE: outcome IS NULL until signal exits — NULL must be permitted

BEGIN;

ALTER TABLE signal_ledger
  ADD CONSTRAINT chk_signal_ledger_outcome
  CHECK (outcome IS NULL OR outcome IN (
    'never_activated',
    'stopped_at_entry',
    'stopped_in_trade',
    'target_1',
    'target_1_2',
    'target_full',
    'ttl_expired_ahead',
    'ttl_expired_behind'
  ));

COMMIT;
