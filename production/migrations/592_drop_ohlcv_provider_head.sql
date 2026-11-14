-- Migration 592: drop ohlcv_provider_head with the IBKR removal (owner 2026-11-13).
--
-- The table held the provider's verified earliest-data timestamp per (symbol, provider,
-- timeframe): 3,060 rows over 1,529 symbols, verified 2026-09-24 to 2026-11-10, all IBKR heads.
-- Its one writer (scripts/infrastructure/backfill/_empty_history.py record_head_per_tf, driven by
-- the deleted history fetcher) is gone and nothing reads it. Derived data is cache: every row is
-- reproducible from the vendor's own first bar, and the Massive archive and the Alpaca capture carry
-- their own heads. No view depends on it. Not compressed, so no VACUUM clause is owed.
--
-- Rerun semantics: IF EXISTS.

BEGIN;

DROP TABLE IF EXISTS ohlcv_provider_head;

COMMIT;
