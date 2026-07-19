-- Migration 214: alpha_frames compression policy
--
-- alpha_frames (migration 214) was created without a compression policy -- an oversight,
-- not a deliberate exclusion. All 21 other hypertables in the DB already compress on
-- schedule (12hr policy_compression job); this closes the one gap.
--
-- compress_after is 60 days, not the 30-day convention used by its siblings alpha_events/
-- forward_returns. Rationale: unlike those two (write-once/append-only), alpha_frames rows
-- are UPDATEd in place by CounterfactualTracker as it scores each frame (status, closed_at,
-- counterfactual_* columns) until the frame reaches a terminal status. The longest
-- alpha.frame.hold_max_bars.* value across all (regime, tf) cells is 60 bars, and the
-- coarsest tf is 1d -- so 60 bars is a 60-day worst case before a frame is guaranteed
-- terminal. compress_after=60 days keeps the policy from ever compressing a chunk that
-- could still receive a tracker UPDATE, avoiding needless decompress-on-write churn.
--
-- segmentby/orderby mirror alpha_events and forward_returns exactly (their downstream/
-- upstream siblings in the same alpha lifecycle): segmentby (symbol, tf), orderby bar_ts DESC.
--
-- Apply only after CounterfactualTracker's backfill has fully closed the historical
-- open-frame backlog (10.2M+ rows dated back to 2007-07-25 were still open/never-measured
-- as of 2026-07-11) -- otherwise this policy would immediately attempt to compress ~990
-- chunks spanning nearly two decades, virtually all containing rows the backfill still needs
-- to UPDATE.

BEGIN;

ALTER TABLE alpha_frames SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, tf',
    timescaledb.compress_orderby = 'bar_ts DESC'
);

SELECT add_compression_policy('alpha_frames', compress_after => INTERVAL '60 days', if_not_exists => TRUE);

COMMIT;
