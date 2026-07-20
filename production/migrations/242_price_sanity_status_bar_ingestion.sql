-- Migration 242: price_sanity_status bar-ingestion guard (todo 149)
--
-- Corrupt IBKR prints (e.g. open=1000 on a ~$25 ETF) flow completely unguarded through
-- market_data_ohlcv into every consumer that reads OHLCV directly (feature computation,
-- regime models) -- todo 148's return_{scale}_suspect guard only protects forward_returns,
-- a derived table computed from open alone, and does nothing for a corrupted high/low/close
-- that doesn't happen to distort the open-based return. This migration adds the bar-level
-- signal so protection is inherited by every consumer for free, mirroring how
-- market_data_ohlcv_tradeable's existing volume > 0 filter already protects against
-- synthetic calendar-fill bars.
--
-- price_sanity_status is a nullable STATUS column, not a boolean -- classify_candidate_bar()
-- (todo 151) returns 4 states (PLAUSIBLE/AMBIGUOUS/CONFIRMED_CORRUPT/MARKET_EVENT), and
-- AMBIGUOUS is explicitly a "cannot conclude" state that must never be silently collapsed
-- into "checked, fine" (a silent wrong answer) nor left forever NULL (an infinite-rescan
-- bug that would defeat the NULL-as-watermark design below). NULL = not yet audited; this
-- IS the watermark -- no separate table needed, and unlike a MAX(bar_ts)-based watermark
-- (which silently failed to backfill a historical gap earlier in this same project, costing
-- an unplanned 17-minute full recompute to fix), a NULL doesn't care whether it arrived via
-- live trickle or a bulk historical backfill landing anywhere in history. Values:
-- 'plausible' | 'confirmed_corrupt' | 'market_event' | 'ambiguous'.
--
-- The view predicate uses IS DISTINCT FROM, not a bare inequality: NOT is_suspect-style
-- boolean logic (or a plain != 'confirmed_corrupt') evaluates to NULL against a NULL column,
-- which is falsy in a WHERE clause -- that would make every newly-inserted LIVE bar
-- invisible to every downstream consumer until the audit gets to it (5-10 min later),
-- injecting unintended read-latency into the real-time pipeline. IS DISTINCT FROM passes
-- NULL, 'plausible', 'market_event', and 'ambiguous' through unchanged; only a confirmed
-- verdict excludes. Never drop data on an unaudited or inconclusive signal.
--
-- The partial index only covers unaudited rows (WHERE price_sanity_status IS NULL) --
-- it self-shrinks as the backlog clears (rows exit the NULL set permanently once classified),
-- bounding the audit task's candidate-discovery query cost independent of total table size
-- (market_data_ohlcv is a 215M+ row hypertable; an unindexed full-table NULL scan every
-- 5-minute audit tick would be a real, unbounded cost).
--
-- Reconciliation: todo 151's --apply step (run earlier the same day this migration was
-- written) corrected 18 confirmed-corrupt rows by zeroing volume, reusing the view's
-- PRE-EXISTING volume > 0 filter (a pragmatic "no new schema" choice at the time, before
-- this column existed). Shipping price_sanity_status as a SECOND, independent signal for
-- the same job without reconciling those 18 rows would permanently blind this migration's
-- own audit task to them -- its candidate-discovery query only sees rows the tradeable view
-- includes (volume > 0), and those 18 rows are now excluded from that view by volume=0, so
-- their price_sanity_status would sit NULL forever. This UPDATE closes that gap once.
-- Going forward (see todo-149 plan Task 4), the correction tool stamps price_sanity_status
-- directly and no longer touches volume, so this reconciliation is a one-time event, not a
-- pattern.
--
-- APR thresholds carry forward classify_candidate_bar()'s existing, already-tuned CLI
-- defaults (10.0x magnitude, 2.0x neighbor-agreement) verbatim -- these were validated
-- against the Flash Crash cluster and real corrupt prints earlier the same day; this
-- migration only changes WHERE the default lives (APR, not a hardcoded Python constant),
-- not the value, since classify_candidate_bar() is now embedded in an always-on daemon
-- (CLAUDE.md's migrate-as-you-go rule). infra.bar_auditor.price_sanity_batch_size is new --
-- [initial_estimate] 500, small enough to keep one audit tick's classification + writeback
-- well under BarAuditor's 300s cycle interval even on a cold-start backlog, generous enough
-- that a normal live trickle (a handful of new bars per symbol per cycle) clears in one tick.

-- Decompress the 2007-2008 chunks the reconciliation UPDATE below touches -- run OUTSIDE
-- the migration's own transaction (TimescaleDB compression functions are not always safe
-- inside the same multi-statement transaction as other DDL in every version, and this step
-- is idempotent/one-time regardless). Found empirically during Task 1's execution: 248/250
-- of market_data_ohlcv's chunks are TimescaleDB-compressed; an UPDATE touching even one row
-- in a compressed chunk requires decompressing that whole chunk first, and 25 chunks fall in
-- the 2007-2009 range these 18 known rows occupy. Without this, the reconciliation UPDATE's
-- write path (not just its read/match path -- a read-only SELECT with the identical join
-- ran in 0.5s) took 90s+ and had to be bounded/killed during testing. Decompressing these 25
-- chunks took ~90s (one-time, empirically timed); the reconciliation UPDATE then completed
-- in the same run as the rest of this migration, ~40s total. Left decompressed afterward
-- (not recompressed) -- storage-hygiene follow-up, not a correctness requirement; 25 chunks
-- of ~17-19-year-old data is a small fraction of the table.
--
--   DO $$
--   DECLARE chunk_rec record;
--   BEGIN
--       FOR chunk_rec IN
--           SELECT format('%I.%I', chunk_schema, chunk_name)::regclass AS full_name
--           FROM timescaledb_information.chunks
--           WHERE hypertable_name = 'market_data_ohlcv'
--             AND range_start < '2009-01-01' AND range_end > '2007-01-01'
--             AND is_compressed
--       LOOP
--           PERFORM decompress_chunk(chunk_rec.full_name);
--       END LOOP;
--   END $$;

BEGIN;

-- Invalidation contract (documented, not enforced by a trigger in this migration --
-- no code path today mutates OHLC on an already-audited row, so this is a stated rule
-- for future correction tools, not an active bug): any process that mutates a bar's
-- open/high/low/close after price_sanity_status has been set MUST reset that column
-- to NULL in the same transaction, so the row re-enters the audit queue rather than
-- carrying a stale verdict computed against since-changed values.
ALTER TABLE market_data_ohlcv
    ADD COLUMN IF NOT EXISTS price_sanity_status text;

CREATE INDEX IF NOT EXISTS idx_market_data_ohlcv_price_sanity_unaudited
    ON market_data_ohlcv (symbol, timeframe, timestamp)
    WHERE price_sanity_status IS NULL;

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT *
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt';

-- Drives from integrity_monitor (18 rows for this monitor_type), NOT from
-- market_data_ohlcv WHERE volume=0 -- volume=0 also matches every synthetic-fill/
-- flat-carry-forward placeholder bar in the ENTIRE table (~82% of intraday rows,
-- tens of millions of rows), and a per-row correlated EXISTS subquery driven from
-- that population is a catastrophic, unbounded full-table operation. Extracting
-- symbol/tf/ts from integrity_monitor's own subject string and joining directly on
-- market_data_ohlcv's primary-key columns bounds this to exactly 18 index lookups.
-- Disaster-recovery note: on a fresh-database replay, if the 2007-2009 chunks this
-- UPDATE touches happen to be compressed, run the commented-out decompression block
-- above first -- this UPDATE will be extremely slow (or need to be killed) otherwise.
UPDATE market_data_ohlcv m
SET price_sanity_status = 'confirmed_corrupt'
FROM (
    SELECT
        substring(subject FROM 'symbol=([^|]+)') AS symbol,
        substring(subject FROM 'tf=([^|]+)') AS tf,
        substring(subject FROM 'ts=(.+)$')::timestamptz AS ts
    FROM integrity_monitor
    WHERE monitor_type = 'price_sanity_ohlcv_correction'
) corrected
WHERE m.symbol = corrected.symbol
  AND m.timeframe = corrected.tf
  AND m.timestamp = corrected.ts
  AND m.timestamp BETWEEN '2007-01-01' AND '2009-01-01';
-- The literal BETWEEN bound is a historical FACT about this one-time reconciliation's
-- fixed, already-known row set (verified: min/max ts of the 18 rows is 2007-03-02 to
-- 2008-09-19), not a tunable parameter -- it does not go through APR. It helped the
-- planner but did not fully solve the cost problem on its own (see decompression note
-- above) -- both fixes were needed together.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.price_sanity.magnitude_threshold',
    'float',
    '10.0',
    2.0, 100.0,
    '[initial_estimate] Order-of-magnitude ratio vs. neighbor reference price to flag an '
    'OHLC field implausible (todo 149/151). Carries forward classify_candidate_bar()''s '
    'existing CLI default verbatim, validated against real corrupt prints and the Flash '
    'Crash cluster. Used by src/intelligence/statistics/price_sanity.py '
    'classify_candidate_bar() -- both the BarAuditor live audit task and the ad hoc '
    '(CLI-overridable) ops_known_corrupt_print_cleanup.py script. Not an ML learning target.'
),
(
    'alpha.quant.price_sanity.neighbor_agreement_threshold',
    'float',
    '2.0',
    1.1, 10.0,
    '[initial_estimate] Max ratio between prev_close and next_open for the two neighbor '
    'bars to be trusted as a reference (todo 149/151). Carries forward '
    'classify_candidate_bar()''s existing CLI default verbatim. Not an ML learning target.'
),
(
    'infra.bar_auditor.price_sanity_batch_size',
    'int',
    '500',
    50, 5000,
    '[initial_estimate] Max unaudited bars BarAuditor''s price-sanity task classifies per '
    'audit tick (todo 149). Bounds per-cycle cost independent of total backlog size -- a '
    'large backlog (e.g. after a bulk historical backfill) drains over multiple ticks '
    'rather than blocking one cycle. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.price_sanity.magnitude_threshold', '10.0', 1),
    ('alpha.quant.price_sanity.neighbor_agreement_threshold', '2.0', 1),
    ('infra.bar_auditor.price_sanity_batch_size', '500', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.price_sanity.magnitude_threshold', 1, '10.0', 'migration_242',
     'Seed bar-ingestion price-sanity magnitude threshold, todo 149 [initial_estimate]'),
    (NOW(), 'alpha.quant.price_sanity.neighbor_agreement_threshold', 1, '2.0', 'migration_242',
     'Seed bar-ingestion price-sanity neighbor-agreement threshold, todo 149 [initial_estimate]'),
    (NOW(), 'infra.bar_auditor.price_sanity_batch_size', 1, '500', 'migration_242',
     'Seed BarAuditor price-sanity audit batch size, todo 149 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
