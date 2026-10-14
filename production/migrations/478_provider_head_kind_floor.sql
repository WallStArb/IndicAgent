-- Migration 478: ohlcv_provider_head.head_kind, seeded tape floors are floors not heads
-- (phase 191 plan 06 review fixes, finding 3)
--
-- Migration 465 seeded every active name with an ibkr 5m row (2006-07-01 22:00 UTC) and an
-- ibkr 1d row (2000-01-03) so the table would carry the measured tape starts. The fetcher read
-- them as verified heads (fresh for 90 days), so it never ran get_head_timestamp, floored
-- every window at the tape start, and asked 2000-2006 for names listed in 2020 or later. The
-- vendor answered failed/timeout for those windows, a failed answer never confirms an empty
-- span, and the consecutive-failure counter walked the series to its exclusion threshold.
--
-- A seeded floor is a one-direction fact (nothing exists before it); a head is the symbol's
-- own first trade. head_kind separates them: 'verified' is a successful lookup, 'floor' is a
-- seed. The fetcher runs the head lookup whenever no verified head exists for the
-- (symbol, timeframe) and uses a floor only as the fallback bound.
--
-- Repair: a series whose failures were asks wholly before the vendor's own first 1d raw bar
-- was shut out by the seeded floor, not by a live fault. Its counter resets here, in the same
-- statement list that removes the cause, so it cannot re-exclude on the next run. Selected by
-- evidence (a failed or timed-out 1d request ending at or before the vendor's first own raw
-- bar), not by name; a series excluded for another reason (no such request) keeps its counter.
-- Small tables (ohlcv_provider_head ~3k rows, ohlcv_coverage ~3k rows, ohlcv_request ~48k
-- rows); no heavy scan; no ohlcv_raw or ohlcv_revision DDL.

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE ohlcv_provider_head ADD COLUMN IF NOT EXISTS head_kind text NOT NULL DEFAULT 'verified';

ALTER TABLE ohlcv_provider_head DROP CONSTRAINT IF EXISTS ohlcv_provider_head_kind_check;
ALTER TABLE ohlcv_provider_head
    ADD CONSTRAINT ohlcv_provider_head_kind_check CHECK (head_kind IN ('verified', 'floor'));

-- The rows migration 465 seeded (its single statement time, exact seed values). A verified
-- lookup row always won over the seed (ON CONFLICT DO NOTHING), so no real head matches.
UPDATE ohlcv_provider_head
SET head_kind = 'floor'
WHERE provider = 'ibkr'
  AND verified_at >= TIMESTAMPTZ '2026-10-10 11:57:35+00'
  AND verified_at < TIMESTAMPTZ '2026-10-10 11:57:36+00'
  AND ((timeframe = '5m' AND head_ts = TIMESTAMPTZ '2006-07-01 22:00:00+00')
    OR (timeframe = '1d' AND head_ts = TIMESTAMPTZ '2000-01-03 00:00:00+00'));

COMMENT ON COLUMN ohlcv_provider_head.head_kind IS
    'verified: a successful get_head_timestamp lookup (the symbol''s own first trade). floor: a '
    'seeded tape start (migration 465): nothing exists before it, never where the symbol''s '
    'history begins. Only verified rows stop the head lookup; a floor bounds a window when no '
    'head is known. Migration 478.';

-- Reset the counters of series shut out by the seeded floor.
UPDATE ohlcv_coverage c
SET consecutive_failures = 0
WHERE c.provider = 'ibkr'
  AND c.timeframe = '1d'
  AND c.consecutive_failures >=
      (SELECT config_value::int FROM config_state
       WHERE config_key = 'infra.backfill.max_consecutive_failures')
  AND EXISTS (
      SELECT 1 FROM ohlcv_request r
      WHERE r.symbol = c.symbol AND r.timeframe = '1d' AND r.source = 'ibkr'
        AND r.outcome IN ('failed', 'timeout')
        AND r.window_end <= (
            SELECT min(m."timestamp") FROM ohlcv_raw m
            WHERE m.symbol = c.symbol AND m.timeframe = '1d' AND m.vendor = 'ibkr'
        )
  );

COMMIT;
