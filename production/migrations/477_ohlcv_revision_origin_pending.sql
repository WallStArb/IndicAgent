-- Migration 477: ohlcv_revision.origin admits 'pending' (phase 191 plan 05, review finding 4)
--
-- A refusal must outlast the call that made it. When a vendor restates more of its own stored raw
-- rows than threshold.bar_integrity.max_revision_ratio allows, the ingress contract no longer
-- replaces the raw current rows. It logs the offered values that differ from the stored rows as
-- ohlcv_revision rows of origin 'pending' (under the refused ohlcv_load row) and leaves ohlcv_raw
-- untouched, so selection, which reads only current raw, cannot promote them. For origin
-- 'pending' the old_* columns hold the OFFERED value that was held, not a replaced one. A pending
-- row is never a vendor restatement: readers of restatement history filter origin <> 'pending'.
-- Only an explicit decision (a waived write) replaces the stored row.
-- Constraint change only; idempotent; no row is touched.

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE ohlcv_revision DROP CONSTRAINT IF EXISTS ohlcv_revision_origin_check;
ALTER TABLE ohlcv_revision
    ADD CONSTRAINT ohlcv_revision_origin_check
    CHECK (origin IN ('load', 'archive_segment', 'raw', 'pending'));

COMMENT ON COLUMN ohlcv_revision.origin IS
    'load / archive_segment / raw: the old values of a replaced row. pending: a refused offer held '
    'instead of written; old_* are the offered values and the stored raw row is unchanged.';

COMMIT;
