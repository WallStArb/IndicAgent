-- Migration 236: alpha_frames.is_shadow (todo 120)
--
-- alpha_events.is_shadow (migration 224, todo 011) lets alpha_publisher.py stamp every
-- emitted event with its shadow/live status. alpha_frames -- the actual Phase 142B
-- measurement surface AlphaFrameWriter/CounterfactualTracker populate, not the archived
-- v2.x trade_frames todo 011's Promotion Gate section originally named -- had no equivalent
-- column: once an operator flips alpha.publisher.is_shadow to false at Phase 144 promotion,
-- pre-promotion shadow frames and post-promotion live frames would silently mix in the same
-- table with no way to isolate the pre-promotion shadow window for the promotion-gate math.
--
-- Propagated from the joined alpha_events row at write time (AlphaFrameWriter), not
-- re-read from APR at query time -- a frame's shadow status is fixed at the moment its
-- parent event was emitted and must not drift if the APR flag changes later.
--
-- No backfill needed: alpha_frames has 0 rows as of this migration (truncated ahead of
-- the in-flight corpus rebuild by infrastructure_truncate_derived_tables.sh, not yet
-- repopulated -- AlphaFrameWriter runs downstream of alpha_publisher, which hasn't run
-- yet this rebuild). If this is ever re-run against a populated table, backfill via
-- `UPDATE alpha_frames af SET is_shadow = ae.is_shadow FROM alpha_events ae WHERE
-- ae.event_id = af.event_id AND ae.bar_ts = af.bar_ts` before dropping the default.

BEGIN;

ALTER TABLE alpha_frames ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
