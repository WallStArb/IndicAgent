-- Migration 056: Add idx_signal_ledger_lifecycle (applied 2026-03-31)
--
-- Migration 043 documented this index but used CONCURRENTLY (not valid for
-- hypertables) and referenced a non-existent column name ('computed_at'
-- instead of 'signal_computed_at'). The index was never created.
--
-- WITHOUT this index, lifecycle UPDATEs in SignalTrackerAgent do a seq scan
-- on the full signal_ledger table (6 GB+):
--   UPDATE signal_ledger SET status=..., outcome=..., mae=..., mfe=...
--   WHERE symbol=$1 AND timeframe=$2 AND status='pending' AND ...
--
-- WITH this index the planner uses an index scan on a small set of open signals
-- per (symbol, timeframe, status), reducing UPDATE latency from ~34 ms to < 5 ms.
--
-- Applied directly (not via psql -f) because TimescaleDB hypertables do not
-- support CREATE INDEX CONCURRENTLY:
--
--   docker exec timescaledb psql -U postgres -d indicagent \
--       -c "CREATE INDEX IF NOT EXISTS idx_signal_ledger_lifecycle \
--           ON signal_ledger (symbol, timeframe, status, signal_computed_at DESC);"

CREATE INDEX IF NOT EXISTS idx_signal_ledger_lifecycle
    ON signal_ledger (symbol, timeframe, status, signal_computed_at DESC);
