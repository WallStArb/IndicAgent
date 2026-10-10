-- Migration 465: the two-tier ledger's breaking key swaps (phase 190 plan 02; design
-- docs/plans/2026-10-09-provider-history-plane-unification-design.md, "Two-tier ledger").
--
-- !! CUTOVER-WINDOW MIGRATION !! Applies at the phase 190 wave-5 cutover ONLY, executed by
-- plan 190-06 in the SAME shell breath as the coverage writer's conflict-target flip
-- (services/ohlcv_coverage_writer.py, _UPSERT_SQL/_OUTCOME_SQL/_REFRESH_1D_SQL/_REBUILD_SQL:
-- ON CONFLICT (symbol, timeframe) -> (symbol, timeframe, provider)), with the fetcher timer
-- AND service STOPPED first. A running drain holds the old conflict target in memory: once
-- the old PK drops, every chunk persist fails with 42P10 (there is no unique index on
-- (symbol, timeframe) to match anymore). NOT applied by plan 190-02; it sits in the repo
-- contract-tested but un-applied through waves 1-4.
--
-- Stored-state labeling rule (restated from migration 464): every ohlcv_coverage row is a
-- canonical-tier stored-state rollup and provider labels the authoring fetch plane, not a
-- per-vendor provenance claim over the stored bars; Tradier-era 1d bounds and 449-lane bars
-- ride under the ibkr label; vendor claims live in ohlcv_load.source and the per-provider
-- tier. NULL-timeframe labeling rule: pre-465 ohlcv_provider_head rows were the 1d
-- daily-bounds registry (migration 355 era), so every NULL-timeframe row is stored state
-- under the ibkr label and backfills to '1d', never a per-TF fact.
--
-- Single writers: services/ohlcv_coverage_writer.py (ohlcv_coverage);
-- scripts/infrastructure/backfill/_empty_history.py (ohlcv_provider_head). Plain tables, not
-- hypertables (2.5k and 703 rows); no compressed chunk is touched, no ALTER TYPE, so the
-- compressed-hypertable VACUUM rule does NOT apply. No new APR keys: the per-provider
-- infra.<provider>.* seeds land with the todo-521 leaf.
--
-- Semantics after this migration:
-- - ohlcv_coverage PK (symbol, timeframe, provider): one row per (symbol, timeframe,
--   authoring provider); a vendor's writes never clobber another vendor's row.
-- - ohlcv_provider_head PK (symbol, provider, timeframe): todo 526's per-TF floor registry.
--   consecutive_failures on ohlcv_coverage is per-provider row state from here on.

BEGIN;

SET LOCAL statement_timeout = 0;

-- ---------------------------------------------------------------------------
-- 1. ohlcv_provider_head: backfill the NULL-timeframe rows, re-key, seed measured floors
-- ---------------------------------------------------------------------------

UPDATE ohlcv_provider_head SET timeframe = '1d' WHERE timeframe IS NULL;

ALTER TABLE ohlcv_provider_head ALTER COLUMN timeframe SET NOT NULL;

ALTER TABLE ohlcv_provider_head DROP CONSTRAINT ohlcv_provider_head_pkey;
ALTER TABLE ohlcv_provider_head ADD PRIMARY KEY (symbol, provider, timeframe);

-- Measured per-TF floors ([measured], todo 526): IBKR's 5m tape starts 2006-07 (its first
-- session, Friday 2006-07-01, close of the UTC day) and its 1d tape starts 2000-01-03.
-- ON CONFLICT DO NOTHING: an existing verified head row (a successful get_head_timestamp
-- lookup, migration 355 semantics) always wins over the seed, which is only the floor when
-- nothing is verified yet.
INSERT INTO ohlcv_provider_head (symbol, provider, timeframe, head_ts, verified_at)
SELECT i.symbol, 'ibkr', '5m', '2006-07-01T22:00:00Z'::timestamptz, NOW()
FROM instruments i
WHERE i.is_active
ON CONFLICT (symbol, provider, timeframe) DO NOTHING;

INSERT INTO ohlcv_provider_head (symbol, provider, timeframe, head_ts, verified_at)
SELECT i.symbol, 'ibkr', '1d', '2000-01-03'::timestamptz, NOW()
FROM instruments i
WHERE i.is_active
ON CONFLICT (symbol, provider, timeframe) DO NOTHING;

COMMENT ON TABLE ohlcv_provider_head IS
    'Per-provider, per-timeframe earliest-data floor registry (migration 465, todo 526): the '
    'planning source of record for one vendor''s proven history, one row per (symbol, '
    'provider, timeframe). A floor is safe in one direction only: nothing exists before it, '
    'and it never implies data exists after it. Vendor A''s rows never answer vendor B''s '
    'planning reads. Migration 355.';

-- ---------------------------------------------------------------------------
-- 2. ohlcv_coverage: widen the PK with the provider dimension. Every existing row already
--    carries provider = 'ibkr' (migration 464's NOT NULL DEFAULT), so the swap is lossless.
-- ---------------------------------------------------------------------------

ALTER TABLE ohlcv_coverage DROP CONSTRAINT ohlcv_coverage_pkey;
ALTER TABLE ohlcv_coverage ADD PRIMARY KEY (symbol, timeframe, provider);

COMMENT ON CONSTRAINT ohlcv_coverage_pkey ON ohlcv_coverage IS
    'One row per (symbol, timeframe, authoring provider): a vendor''s coverage writes never '
    'clobber another vendor''s row. Until the wave-5 cutover the writer still targets '
    '(symbol, timeframe); the flip to this key happens in the same shell breath as this '
    'migration (plan 190-06), with the fetcher stopped.';

-- ---------------------------------------------------------------------------
-- 3. Grants: re-issue guarded by the role-creation guard (the 432 pattern), so a fresh
--    environment applying the family in order never misses the grant. No DELETE, no
--    TRUNCATE, nothing for ohlcv_observation_writer.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bar_derivation_writer') THEN
        CREATE ROLE bar_derivation_writer NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE ON ohlcv_coverage TO bar_derivation_writer;

COMMIT;
