-- Migration 024: Signal ledger cleanup and lifecycle query optimization (2026-03-08)
--
-- PROBLEMS:
-- 1. 1.8M pending signals stuck forever — all >24h old, all past their 10-bar TTL.
--    Lifecycle service loads ALL pending signals per symbol on every bar tick —
--    degrading performance with each new signal insertion.
-- 2. Lifecycle query has no partial index for open-signal lookup, causing full
--    hypertable scans on status IN ('pending', 'active', 'regime_suppressed').
-- 3. Feb 19-26 compressed chunk bloated to 36 GB: backfill inserted 327K rows
--    into an already-compressed chunk. TimescaleDB staged these as uncompressed
--    alongside the compressed data. Recompression consolidates them.
--
-- PHILOSOPHY: Expired pending signals are NOT dropped — they are updated to
-- status='expired', outcome='never_activated' and remain as labeled training
-- data in the signal_ledger forever (keep-forever policy).

-- ─── 1. Expire all pending signals past their TTL ───────────────────────────
-- Conservative cutoff: 10 bars × 1h max timeframe = 10 hours.
-- ALL 1.8M current pending signals are >24h old — all safely past TTL.
-- Status → 'expired', outcome → 'never_activated' (never entered zone).
-- Also expire regime_suppressed signals past cutoff (shadow signals with
-- identical TTL semantics but no status change to 'active').

-- Disable decompression limit for this session (default 100K blocks bulk UPDATEs)
SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;

UPDATE signal_ledger
SET
    status     = 'expired',
    outcome    = 'never_activated',
    exit_at    = NOW(),
    updated_at = NOW()
WHERE status = 'pending'
  AND timestamp < NOW() - INTERVAL '10 hours';

-- Regime_suppressed: same TTL semantics. Update outcome only (status intentionally
-- stays 'regime_suppressed' per design — lifecycle service shadow-tracks these).
UPDATE signal_ledger
SET
    outcome    = 'never_activated',
    exit_at    = NOW(),
    updated_at = NOW()
WHERE status = 'regime_suppressed'
  AND outcome IS NULL
  AND timestamp < NOW() - INTERVAL '10 hours';

-- ─── 2. Partial composite index for lifecycle open-signal query ──────────────
-- The lifecycle service runs this on every bar tick per symbol:
--   WHERE status IN ('pending', 'active', 'regime_suppressed') AND symbol = $1
-- With this partial index, TimescaleDB will:
--   - Skip all expired/resolved chunks entirely (partition pruning)
--   - Use the index to find open signals for a symbol in microseconds
-- CONCURRENTLY avoids locking the table during creation.

-- NOTE: CONCURRENTLY is not supported on hypertables.
-- TimescaleDB propagates this index to all existing and future chunks automatically.
CREATE INDEX IF NOT EXISTS idx_ledger_open_signals
ON signal_ledger (symbol, timestamp DESC)
WHERE status IN ('pending', 'active', 'regime_suppressed');

-- ─── 3. Recompress the anomalous 36 GB chunk ────────────────────────────────
-- The Feb 19-26 chunk was already compressed when the historical backfill ran
-- (2026-03-07). TimescaleDB staged the 327K backfill rows as uncompressed data
-- alongside the compressed portion, causing the chunk to balloon to 36 GB.
-- recompress_chunk consolidates staged rows back into columnar compression.
-- Expected result: ~1-2 GB (matching other weeks at similar signal volume).
-- NOTE: This is a CALL (procedure), not a function. It manages its own
-- transaction and may take several minutes on a 36 GB chunk.
-- If this migration is run inside a transaction block, extract this CALL
-- and run it separately:
--   CALL recompress_chunk('_timescaledb_internal._hyper_13_24260_chunk');

DO $$
BEGIN
  -- Only run if the chunk still exists and is showing high bloat
  IF EXISTS (
    SELECT 1 FROM timescaledb_information.chunks
    WHERE chunk_schema = '_timescaledb_internal'
      AND chunk_name = '_hyper_13_24260_chunk'
      AND is_compressed = true
  ) THEN
    RAISE NOTICE 'Chunk _hyper_13_24260_chunk found. Run separately:';
    RAISE NOTICE 'CALL recompress_chunk(''_timescaledb_internal._hyper_13_24260_chunk'');';
  END IF;
END $$;
