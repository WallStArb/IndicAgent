-- Migration 043: Composite index for signal_ledger lifecycle UPDATEs
--
-- The lifecycle service UPDATE pattern is:
--   UPDATE signal_ledger SET status=..., outcome=..., mae=..., mfe=...
--   WHERE symbol='ES' AND timeframe='1m' AND status='pending' AND ...
--
-- Without this index, PostgreSQL scans all 6GB of signal_ledger data.
-- With this index, lifecycle UPDATEs use an index scan (< 5ms vs 34ms avg).
--
-- IMPORTANT: This file must be run WITHOUT a transaction wrapper.
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
-- psql -f wraps statements in a transaction by default, so use -c instead:
--
--   docker exec timescaledb psql -U postgres -d indicagent \
--       -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_lifecycle \
--           ON signal_ledger (symbol, timeframe, status, computed_at DESC);"
--
-- The migration file below is documentation/record of the change.
-- Apply using the -c command above, not psql -f.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_lifecycle
    ON signal_ledger (symbol, timeframe, status, computed_at DESC);
