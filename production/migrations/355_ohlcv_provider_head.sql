-- Migration 355: ohlcv_provider_head -- the provider's earliest-data timestamp per symbol.
--
-- Companion to migration 354 (ohlcv_empty_history). Requests for history before a contract's
-- head timestamp (the provider's earliest data point) are answered by IBKR with "API
-- historical data query cancelled", not "no data", on every retry with 65s/130s backoffs
-- (GEV, listed 2024-03-27, requested back to 2006 every night). Migration 354 correctly
-- refuses to treat a cancellation as evidence, so it cannot remove these; the head can.
--
-- The head is a floor in one direction only: nothing can exist before the earliest data
-- point, so skipping requests older than it cannot lose data. It is NOT a promise that data
-- exists after it (IBKR reports ODFL's head as 1991-10-24 but serves daily bars only from
-- 2024-05-07); migration 354's evidence covers that side. Validated 2026-09-24 across all
-- 273 active equity symbols: 0 of 685 symbol/timeframe pairs hold a stored bar dated before
-- the head; 112 of 273 lookups failed ("Query failed"), so a failure is stored as a row
-- with head_ts NULL, meaning "no floor", and is not retried until it is stale.
--
-- Re-verified after infra.backfill.empty_history_reverify_days (migration 354), same as
-- ohlcv_empty_history. No compressed hypertable is touched; no VACUUM step required.

BEGIN;

CREATE TABLE IF NOT EXISTS ohlcv_provider_head (
    symbol       text        NOT NULL,
    provider     text        NOT NULL,
    head_ts      timestamptz,           -- NULL: lookup failed, no floor
    lookup_error text,
    verified_at  timestamptz NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, provider),
    CHECK ((head_ts IS NULL) = (lookup_error IS NOT NULL))
);

COMMENT ON TABLE ohlcv_provider_head IS
    'Provider earliest-data timestamp per symbol, used by the historical backfill as a floor '
    'in the safe direction only (never requests older history; never implies data exists '
    'after it). head_ts NULL = lookup failed = no floor. Re-verified after '
    'infra.backfill.empty_history_reverify_days. Migration 355.';

COMMIT;
