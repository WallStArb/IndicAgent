-- Migration 464: ohlcv_coverage gains the provider dimension, additively (phase 190 plan 02;
-- design docs/plans/2026-10-09-provider-history-plane-unification-design.md, "Two-tier ledger").
--
-- STRICTLY ADDITIVE and applied live while the IBKR 5m drain runs: the running fetcher holds
-- the old writer SQL in memory, so every commit boundary of phase 190 wave 1 must leave its
-- `ON CONFLICT (symbol, timeframe)` upsert working unchanged. Adding nullable-defaulted
-- columns and a named CHECK changes no key and no existing statement plan: the old queue SQL
-- and the old upsert keep working against this schema (verified by re-running the dry run
-- after applying). The breaking key swaps live in migration 465, which is committed un-applied
-- here and applies at the wave-5 cutover (plan 190-06) with the fetcher stopped, in the same
-- shell breath as the writer's conflict-target flip: a running drain would fail every chunk
-- persist with 42P10 once the old PK drops.
--
-- The stored-state labeling rule: every ohlcv_coverage row is a canonical-tier stored-state
-- rollup, and the new provider column labels the authoring fetch plane, NOT a per-vendor
-- provenance claim over the stored bars. Existing rows backfill to 'ibkr' because the ledger's
-- fetch bookkeeping (last_fetch_status from SMART TRADES requests) is IBKR-only today; the
-- Tradier-era 1d bounds and the todo-449-lane bars they roll up ride under the ibkr label as
-- stored state. Vendor claims about which tape produced which bars live in ohlcv_load.source
-- and in the per-provider tier (ohlcv_provider_head, ohlcv_empty_history), never here.
--
-- Single writer: services/ohlcv_coverage_writer.py (unchanged by this migration; its
-- provider parameterization is code-only in this plan and keeps the old conflict target).
--
-- Plain tables, not hypertables: ohlcv_coverage is about 2.5k rows (migration 432 header) and
-- ohlcv_provider_head is 703 rows (migration 355); no compressed chunk is touched, no ALTER
-- TYPE, so the compressed-hypertable VACUUM rule does NOT apply.
--
-- No new APR keys: infra.ibkr.* was seeded by migration 432; the alpaca keys land with the
-- todo-521 leaf (phase 190 wave 3), not here.

BEGIN;

SET LOCAL statement_timeout = 0;

-- ---------------------------------------------------------------------------
-- 1. ohlcv_coverage: the provider label (canonical tier, stored-state rule above)
-- ---------------------------------------------------------------------------

ALTER TABLE ohlcv_coverage ADD COLUMN provider text NOT NULL DEFAULT 'ibkr';

ALTER TABLE ohlcv_coverage ADD CONSTRAINT ohlcv_coverage_provider_check
    CHECK (provider <> '');

COMMENT ON COLUMN ohlcv_coverage.provider IS
    'Authoring fetch plane of this canonical-tier row (stored-state labeling, migration 464): '
    'which provider''s fetch path maintains the row, NOT a per-vendor provenance claim over '
    'the stored bars. Existing rows are ibkr-era stored-state rollups; Tradier-era 1d bounds '
    'and 449-lane bars ride under the ibkr label. Vendor claims live in ohlcv_load.source and '
    'the per-provider tier.';

-- ---------------------------------------------------------------------------
-- 2. ohlcv_provider_head: nullable timeframe column. The per-TF floor ROWS are seeded by
--    migration 465 after its PK swap at the wave-5 cutover (plan 190-06); here the column
--    only exists so 465 is a key swap plus data backfill, not a second schema change.
-- ---------------------------------------------------------------------------

ALTER TABLE ohlcv_provider_head ADD COLUMN timeframe text;

COMMENT ON COLUMN ohlcv_provider_head.timeframe IS
    'Bar timeframe code this head floor applies to (1d, 5m, ...); NULL until migration 465 '
    'backfills the 355-era rows to ''1d'' and re-keys the PK to (symbol, provider, timeframe) '
    'at the wave-5 cutover. Pre-465 rows were the 1d daily-bounds registry, so a NULL '
    'timeframe row is stored state under the ibkr label, never a per-TF fact.';

COMMIT;
