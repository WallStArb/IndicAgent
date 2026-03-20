-- Phase 40.5 PERF-04: Expire 328K stale pending signals older than 48h
-- These accumulated from contract rolls — old symbol signals never expired
-- because signal_lifecycle_service only evaluates signals matching incoming bar TF
--
-- Note: status must be 'expired' per chk_signal_ledger_status constraint.
-- exit_reason='bulk_cleanup_stale_pending' identifies this cleanup batch.

SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;

UPDATE signal_ledger
SET status = 'expired',
    exit_at = NOW(),
    exit_reason = 'bulk_cleanup_stale_pending'
WHERE status = 'pending'
  AND exit_at IS NULL
  AND timestamp < NOW() - INTERVAL '48 hours';
