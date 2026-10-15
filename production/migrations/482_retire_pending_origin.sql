-- Migration 482: retire the `pending` revision origin (phase 191, D-191-N)
--
-- Owner decision 2026-10-14: nothing is held pending. scripts/ops/bars/ops_pending_release.py
-- released every pending row (4,572 offers written to raw last-wins with the displaced values
-- logged, 80 superseded by a later serve and kept as ordinary origin raw revisions;
-- logs/pending_release_191_apply.json), so no row carries the origin and no code writes it.
-- The check constraint drops the value so none can appear again. Migration 477 added it.
--
-- Constraint swap on ohlcv_revision; the new constraint is validated against the table (no row
-- has the removed value, checked first).

BEGIN;

SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ohlcv_revision WHERE origin = 'pending') THEN
        RAISE EXCEPTION 'pending revision rows remain: run ops_pending_release.py --apply first';
    END IF;
END $$;

ALTER TABLE ohlcv_revision DROP CONSTRAINT ohlcv_revision_origin_check;
ALTER TABLE ohlcv_revision ADD CONSTRAINT ohlcv_revision_origin_check
    CHECK (origin = ANY (ARRAY['load'::text, 'archive_segment'::text, 'raw'::text]));

COMMIT;
