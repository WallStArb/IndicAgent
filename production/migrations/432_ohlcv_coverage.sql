-- Migration 432: ohlcv_coverage, the per-(symbol, timeframe) coverage ledger the single IBKR
-- history fetcher ranks its queue from (phase 189 plan 01; design
-- docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md, "Ground truth").
--
-- The design names this migration 430; 430 and 431 were taken by phase 186 (430
-- drop_forward_returns, 431 retire_cluster_max_corr) before this plan ran, so it lands as 432.
--
-- What it is (CD-03): a materialized rollup, not a second source of truth. ohlcv_request stays
-- the per-window answered-request log (_request_coverage.py reads it) and the bar tables stay
-- the bars. This table only makes prioritization an O(1) read instead of a full-window scan per
-- symbol per run (todo 387 measured ~500 ms per symbol for detect_gaps()).
--
-- Single writer: services/ohlcv_coverage_writer.py, called inside persist_chunk_atomically's
-- transaction (request rows -> bar rows -> coverage, one COMMIT, CD-04) or by the fetcher's
-- per-item outcome write. tests/unit/test_ohlcv_coverage_writer_boundary.py fences it.
--
-- consecutive_failures counts genuine failures only (timeout, connection drop). A no_data
-- answer is a correct empty result (venue-boundary names such as TLT, AMD, PEP) and resets it
-- (CD-05).
--
-- Bootstrap (one time, below): earliest/latest/row_count from the stored bars, last fetch from
-- ohlcv_request's SMART TRADES rows. For 15m/1h the archive and the grid are combined: fetched
-- 15m/1h live in ohlcv_intraday_raw_archive since 185-12 while older ones may remain in the
-- grid (HPQ 15m holds ~35k archive rows and 0 grid rows), so the union is the stored depth.
-- History before the ledger is not charged: every bootstrapped row starts at
-- consecutive_failures = 0. Measured before applying (performance SOP): the grid aggregate over
-- every timeframe runs in ~5 s and the archive aggregate in ~1 s (compressed-chunk counts), so
-- the scan is read-only and short. No decompress_chunk, no ALTER TYPE, so the
-- compressed-hypertable VACUUM rule does not apply.
--
-- Plain table, not a hypertable: about 2.5k rows today, one per series.

BEGIN;

SET LOCAL statement_timeout = 0;

-- ---------------------------------------------------------------------------
-- 1. The ledger
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ohlcv_coverage (
    symbol text NOT NULL,
    timeframe text NOT NULL,
    earliest_timestamp timestamptz,
    latest_timestamp timestamptz,
    row_count bigint NOT NULL DEFAULT 0,
    last_fetched_at timestamptz,
    last_fetch_status text,
    consecutive_failures integer NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe),
    CONSTRAINT ohlcv_coverage_status_check
        CHECK (last_fetch_status IS NULL OR last_fetch_status IN ('ok', 'no_data', 'error')),
    CONSTRAINT ohlcv_coverage_failures_check CHECK (consecutive_failures >= 0),
    CONSTRAINT ohlcv_coverage_row_count_check CHECK (row_count >= 0),
    CONSTRAINT ohlcv_coverage_bounds_check
        CHECK (earliest_timestamp IS NULL OR latest_timestamp IS NULL
               OR earliest_timestamp <= latest_timestamp)
);

COMMENT ON TABLE ohlcv_coverage IS
    'Materialized coverage rollup per (symbol, timeframe) for the IBKR history fetcher queue '
    '(migration 432, phase 189 CD-03). Single writer services/ohlcv_coverage_writer.py, written '
    'in the same transaction as the bars and their ohlcv_request rows. Not a competing truth: '
    'ohlcv_request and the bar tables remain authoritative.';
COMMENT ON COLUMN ohlcv_coverage.symbol IS 'instruments.symbol (base symbol).';
COMMENT ON COLUMN ohlcv_coverage.timeframe IS 'Bar timeframe code (1d, 1h, 15m, 5m, ...).';
COMMENT ON COLUMN ohlcv_coverage.earliest_timestamp IS
    'Earliest stored provider bar at the timeframe''s fetch destination; NULL when none stored.';
COMMENT ON COLUMN ohlcv_coverage.latest_timestamp IS
    'Latest stored provider bar at the timeframe''s fetch destination; NULL when none stored.';
COMMENT ON COLUMN ohlcv_coverage.row_count IS
    'Provider bars stored at the timeframe''s fetch destination (the archive for 15m/1h; '
    'tradeable rows, volume > 0, for grid timeframes).';
COMMENT ON COLUMN ohlcv_coverage.last_fetched_at IS
    'When the latest fetch of this series was answered (or failed).';
COMMENT ON COLUMN ohlcv_coverage.last_fetch_status IS
    'Outcome of the latest fetch: ok (bars), no_data (correct empty answer) or error.';
COMMENT ON COLUMN ohlcv_coverage.consecutive_failures IS
    'Genuine failures (timeout, connection drop) since the last ok or no_data answer. no_data '
    'never increments it (CD-05). Past infra.backfill.max_consecutive_failures the series '
    'leaves the queue until reset with the fetcher''s --reset-failures flag.';

-- ---------------------------------------------------------------------------
-- 2. Grants: the coverage write runs under the bar-writer role in the bars' transaction.
--    No DELETE, no TRUNCATE, nothing for ohlcv_observation_writer.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON ohlcv_coverage TO bar_derivation_writer;

-- ---------------------------------------------------------------------------
-- 3. APR keys the fetcher reads (infra.*). None is an ML learning target.
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.history_request_timeout',
    'float',
    '900',
    120, NULL,
    '[initial_estimate] Per-queue-item stall bound in seconds: the fetcher cancels an item when no IBKR request has been answered for this long. It must exceed infra.ibkr.rate_limit_window_sec (600 s, the longest legitimate silent wait in the pre-emptive rate limiter) plus infra.ibkr.historical_request_timeout_sec (90 s per request); todo 488 suggested 300 s, which would cancel healthy items during a rate-limit sleep. Distinct from infra.ibkr.historical_request_timeout_sec, which bounds one reqHistoricalDataAsync call inside ibkr.py. Not an ML learning target.'
),
(
    'infra.ibkr.history_request_retries',
    'int',
    '2',
    0, 10,
    '[initial_estimate] Reconnect-and-retry attempts for a stalled queue item before it is recorded as an error. Not an ML learning target.'
),
(
    'infra.backfill.max_consecutive_failures',
    'int',
    '5',
    1, NULL,
    '[initial_estimate] A (symbol, timeframe) whose ohlcv_coverage.consecutive_failures exceeds this is excluded from the fetcher queue (replaces todo 484''s quarantine file); reset with the fetcher''s --reset-failures flag. Not an ML learning target.'
),
(
    'infra.backfill.max_staleness_days_before_preempt',
    'int',
    '3',
    1, NULL,
    '[initial_estimate] Calendar days since a covered series'' latest bar beyond which it preempts backlog work. 3 lets a normal Friday-to-Monday weekend pass without preempting; a series missing about two sessions mid-week preempts. Not an ML learning target.'
),
(
    'infra.backfill.priority_tf_order',
    'json',
    '["15m", "1h"]',
    NULL, NULL,
    '[user_preference] Timeframes ranked ahead of the rest within a priority band (todo 449 owner decision: 15m/1h before 5m). Not an ML learning target.'
),
(
    'infra.backfill.default_scopes',
    'json',
    '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}',
    NULL, NULL,
    '[user_preference] The (eligibility dimension -> timeframes) union the fetcher queues when run without --dimension/--timeframes/--symbols. Mirrors today''s nightly legs (compute full stack, compute_1d-only at 1d) plus the todo 449 HTF campaign; 1m is dropped (todo 455); 5m for the backfill dimension stays out until todo 462 lands (today''s PAUSE_5M state) and is added by an APR edit, not code. Not an ML learning target.'
),
(
    'infra.backfill.run_budget_minutes',
    'int',
    '240',
    5, NULL,
    '[initial_estimate] Wall-clock minutes after which a fetcher run stops taking new queue items; the timer''s next fire continues the queue. Not an ML learning target.'
),
(
    'infra.ibkr.inter_item_pause_s',
    'float',
    '2.0',
    0, NULL,
    '[conventional] Pause in seconds between fetcher queue items, carried over from the inline asyncio.sleep(2) IBKR pacing pause between instruments in infrastructure_run_historical_pipeline.py (APR migrate-as-you-go). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.history_request_timeout', '900', 1),
    ('infra.ibkr.history_request_retries', '2', 1),
    ('infra.backfill.max_consecutive_failures', '5', 1),
    ('infra.backfill.max_staleness_days_before_preempt', '3', 1),
    ('infra.backfill.priority_tf_order', '["15m", "1h"]', 1),
    ('infra.backfill.default_scopes',
     '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}', 1),
    ('infra.backfill.run_budget_minutes', '240', 1),
    ('infra.ibkr.inter_item_pause_s', '2.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.history_request_timeout', 1, '900', 'migration_432',
     'Initial value: 900 s per-item stall bound, above the 600 s rate-limit window plus one 90 s request [initial_estimate]'),
    (NOW(), 'infra.ibkr.history_request_retries', 1, '2', 'migration_432',
     'Initial value: 2 reconnect-and-retry attempts per stalled item [initial_estimate]'),
    (NOW(), 'infra.backfill.max_consecutive_failures', 1, '5', 'migration_432',
     'Initial value: exclude a series after more than 5 consecutive genuine failures [initial_estimate]'),
    (NOW(), 'infra.backfill.max_staleness_days_before_preempt', 1, '3', 'migration_432',
     'Initial value: 3 calendar days, clears a normal weekend [initial_estimate]'),
    (NOW(), 'infra.backfill.priority_tf_order', 1, '["15m", "1h"]', 'migration_432',
     'Initial value: 15m/1h before 5m, todo 449 owner decision [user_preference]'),
    (NOW(), 'infra.backfill.default_scopes', 1,
     '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}',
     'migration_432',
     'Initial value: nightly legs plus the todo 449 HTF campaign, no 1m, no backfill 5m [user_preference]'),
    (NOW(), 'infra.backfill.run_budget_minutes', 1, '240', 'migration_432',
     'Initial value: 240 minute run budget [initial_estimate]'),
    (NOW(), 'infra.ibkr.inter_item_pause_s', 1, '2.0', 'migration_432',
     'Initial value: the old loop''s inline 2 s per-instrument pacing sleep [conventional]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. One-time bootstrap from stored state (ON CONFLICT DO NOTHING: a re-run never overwrites
--    rows the writer has since maintained).
-- ---------------------------------------------------------------------------

INSERT INTO ohlcv_coverage (
    symbol, timeframe, earliest_timestamp, latest_timestamp, row_count,
    last_fetched_at, last_fetch_status, consecutive_failures
)
WITH grid AS (
    SELECT symbol, timeframe,
           min("timestamp") AS earliest, max("timestamp") AS latest, count(*) AS n
    FROM market_data_ohlcv_tradeable
    GROUP BY symbol, timeframe
),
archive AS (
    SELECT symbol, timeframe,
           min("timestamp") AS earliest, max("timestamp") AS latest, count(*) AS n
    FROM ohlcv_intraday_raw_archive
    GROUP BY symbol, timeframe
),
bars AS (
    -- 15m/1h: union of archive and grid depth. Every other timeframe: the grid alone.
    SELECT coalesce(g.symbol, a.symbol) AS symbol,
           coalesce(g.timeframe, a.timeframe) AS timeframe,
           LEAST(g.earliest, a.earliest) AS earliest,
           GREATEST(g.latest, a.latest) AS latest,
           GREATEST(coalesce(g.n, 0), coalesce(a.n, 0)) AS n
    FROM grid g
    FULL OUTER JOIN archive a
      ON a.symbol = g.symbol AND a.timeframe = g.timeframe
    WHERE coalesce(g.timeframe, a.timeframe) IN ('15m', '1h')
    UNION ALL
    SELECT symbol, timeframe, earliest, latest, n
    FROM grid
    WHERE timeframe NOT IN ('15m', '1h')
),
requests AS (
    SELECT DISTINCT ON (symbol, timeframe)
           symbol, timeframe, answered_at,
           CASE outcome
               WHEN 'bars' THEN 'ok'
               WHEN 'no_data' THEN 'no_data'
               ELSE 'error'
           END AS status
    FROM ohlcv_request
    WHERE route = 'SMART'
      AND what_to_show = 'TRADES'
      AND outcome IN ('bars', 'no_data', 'timeout', 'failed')
    ORDER BY symbol, timeframe, answered_at DESC
)
SELECT coalesce(b.symbol, r.symbol),
       coalesce(b.timeframe, r.timeframe),
       b.earliest,
       b.latest,
       coalesce(b.n, 0),
       r.answered_at,
       r.status,
       0
FROM bars b
FULL OUTER JOIN requests r
  ON r.symbol = b.symbol AND r.timeframe = b.timeframe
ON CONFLICT (symbol, timeframe) DO NOTHING;

COMMIT;
