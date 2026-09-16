-- Migration 344: retire the dead infra.ibkr.nightly_backfill_completeness_threshold APR key.
--
-- Companion to today's fix in scripts/infrastructure/backfill/infrastructure_nightly_backfill.py.
-- That key drove a hard `WHERE row_count < threshold` exclusion filter in the nightly
-- candidate-selection query -- a symbol's row count only grows, so any symbol that ever
-- crossed 150,000 1h rows became PERMANENTLY invisible to the nightly job, forever,
-- regardless of how stale its most recent bar got. Verified live 2026-09-16: 168 of 273
-- active instruments had silently stopped receiving updates this way, the bulk frozen
-- since 2026-08-10, while the systemd service logged status=success every night (the
-- ~20-40 still-under-threshold symbols kept it busy and green).
--
-- The fix replaces row-count-below-a-threshold with direct staleness ranking
-- (MAX(timestamp) ascending, no hard filter) -- every active symbol is a candidate every
-- night. That makes this key's entire reason to exist gone, not just its current value
-- wrong: no code path reads it anymore. Deleting rather than leaving it registered-but-
-- unused, per this project's own bias against config knobs that look like they do
-- something but don't (exactly the class of silent-wrong-answer this key itself was).
--
-- infra.ibkr.nightly_backfill_batch_size (migration 304's other key) is untouched -- still
-- the live, load-bearing per-night batch cap.
--
-- Idempotent: DELETE on a primary key, safe to re-run (zero rows deleted on a re-run).

BEGIN;

DELETE FROM config_history WHERE config_key = 'infra.ibkr.nightly_backfill_completeness_threshold';
DELETE FROM config_state WHERE config_key = 'infra.ibkr.nightly_backfill_completeness_threshold';
DELETE FROM config_schema WHERE config_key = 'infra.ibkr.nightly_backfill_completeness_threshold';

COMMIT;
