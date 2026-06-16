-- Migration 140: Add composite (symbol, tf, ts DESC) index on signal_events.
--
-- The existing idx_signal_events_symbol_ts covers (symbol, ts DESC) but omits tf.
-- Every ML analysis and dashboard query filters by both instrument and timeframe
-- (e.g. "ES signals on 5m in the last 30 days"). Without tf in the index, Postgres
-- must scan all timeframes for a given symbol and post-filter — at 1.44M rows this
-- is a full segment scan on compressed chunks.
--
-- The new index replaces the old one as the primary symbol+timeframe access path.
-- Keep the old index until this one is confirmed used in production.

CREATE INDEX IF NOT EXISTS idx_signal_events_symbol_tf_ts
    ON signal_events (symbol, tf, ts DESC);
