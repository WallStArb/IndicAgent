-- Migration 354: ohlcv_empty_history -- provider-verified empty history per (symbol, timeframe).
--
-- Gap detection (infrastructure_run_historical_pipeline.detect_gaps) counts every expected
-- session slot missing from market_data_ohlcv as a gap. Slots before a symbol's first
-- available bar (pre-listing history, or history the provider simply does not serve, e.g.
-- IBKR serves ODFL daily bars only from 2024-05-07 although its head timestamp is 1991)
-- are missing forever, so every nightly run re-requests them. The provider's backward walk
-- answers each with IBKR's definitive "no data" and stops after
-- infra.ibkr.no_data_confirmation_chunks chunks, so the same requests (plus throttling
-- cancellations and their 65s/130s retry backoffs) are spent night after night to learn
-- nothing new.
--
-- One row per (symbol, timeframe, provider) records the empty range learned from the last
-- walk that ended in definitive no-data answers. The pipeline subtracts a fresh row's range
-- from the detected gaps; a row older than infra.backfill.empty_history_reverify_days is
-- ignored, so the walk runs again and either refreshes the row or, if the provider has
-- since filled the history in, the row is deleted. No bar is ever deleted; only requests
-- are skipped.
--
-- Evidence, not assumption: only IBKR Error 162 "no data" answers attributed by reqId count
-- (timeouts and throttling cancellations never do). empty_from..verified_from may be
-- inferred rather than asked: when the walk stops on the confirmation threshold it never
-- requests anything older. That is exactly the range the walk already skips every night,
-- so recording it changes nothing about which history is fetched; reached_request_start
-- and verified_from keep the verified and inferred parts distinguishable.
--
-- No compressed hypertable is touched; no VACUUM step required.

BEGIN;

CREATE TABLE IF NOT EXISTS ohlcv_empty_history (
    symbol                text        NOT NULL,
    timeframe             text        NOT NULL,
    provider              text        NOT NULL,
    empty_from            timestamptz NOT NULL,  -- start of the fetch window (may be inferred)
    empty_through         timestamptz NOT NULL,  -- newest point the provider answered "no data" for
    verified_from         timestamptz NOT NULL,  -- oldest point actually asked and answered
    n_confirming_chunks   integer     NOT NULL CHECK (n_confirming_chunks > 0),
    reached_request_start boolean     NOT NULL,  -- true: the whole range was asked, none inferred
    verified_at           timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, timeframe, provider),
    CHECK (empty_from <= verified_from AND verified_from <= empty_through)
);

COMMENT ON TABLE ohlcv_empty_history IS
    'Provider-verified empty OHLCV history per (symbol, timeframe, provider), written by the '
    'historical backfill pipeline from definitive no-data answers only; the pipeline skips a '
    'fresh row''s range when fetching gaps and re-verifies it after '
    'infra.backfill.empty_history_reverify_days. Never used to delete or hide bars. '
    'Migration 354.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.backfill.empty_history_reverify_days',
    'int',
    '90',
    1, 3650,
    '[initial_estimate] Migration 354: age after which an ohlcv_empty_history row stops '
    'suppressing requests, so the backfill asks the provider again whether the history now '
    'exists (providers do fill history in: IBKR''s ODFL daily history starts 2024-05-07 '
    'despite a 1991 head timestamp). Lower = faster pickup of newly served history, more '
    'requests re-spent on confirmed-empty ranges. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.backfill.empty_history_reverify_days', '90', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
