-- Migration 062: Enforce NOT NULL on CIS fields in signal_ledger
-- Phase 61 — signal auditor + CIS contract enforcement
--
-- Pre-condition: signal_ledger must be empty (TRUNCATED in Task 0) or contain
-- only rows with non-null CIS scores. Run AFTER verifying one clean trading
-- session where DLQ counter stayed at 0.
--
-- Safe to run: if any null exists, the ALTER will fail with a loud error,
-- protecting the table from silently accepting a partial migration.

BEGIN;

ALTER TABLE signal_ledger
  ALTER COLUMN cis_score            SET NOT NULL,
  ALTER COLUMN raw_cis_score        SET NOT NULL,
  ALTER COLUMN filtered_cis_score   SET NOT NULL,
  ALTER COLUMN bucket_scores        SET NOT NULL,
  ALTER COLUMN weights_version      SET NOT NULL;

COMMENT ON COLUMN signal_ledger.cis_score IS
    'Kalman-filtered CIS score at time of signal. NOT NULL enforced Phase 61. '
    'CISScorer defaults bucket inputs to 0.0 when features absent — always computable.';

COMMENT ON COLUMN signal_ledger.raw_cis_score IS
    'Raw CIS score before Kalman filter. NOT NULL enforced Phase 61.';

COMMENT ON COLUMN signal_ledger.filtered_cis_score IS
    'Kalman-filtered CIS score. NOT NULL enforced Phase 61.';

COMMIT;
