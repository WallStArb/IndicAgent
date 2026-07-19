-- Migration 025: Index audit and optimization pass (2026-03-11)
--
-- FINDINGS (from EXPLAIN analysis and pg_stat_statements):
--
-- 1. signals API query (WHERE symbol=$1 ORDER BY ts DESC LIMIT N) was using
--    signal_ledger_timestamp_idx with a Filter on symbol instead of an Index Cond.
--    Root cause: no (symbol, ts DESC) composite index. Planner chose the pure
--    timestamp index + symbol filter as a fast-first LIMIT strategy — acceptable
--    now (36 MB) but degrades linearly as signals accumulate.
--    Fix: add idx_ledger_sym_ts (symbol, timestamp DESC). Drop signal_ledger_timestamp_idx.
--
-- 2. Migration 022 attempted to DROP three redundant indexes but they still exist
--    in the live database. Re-drop them here.
--
-- 3. idx_ledger_status: partial WHERE status IN ('pending','active') is wrong —
--    misses 'regime_suppressed'. The live lifecycle query always uses
--    idx_ledger_open_signals which correctly includes all 3 open statuses.
--    idx_ledger_status is dead weight with a misleading filter.
--
-- 4. idx_ledger_feature_ts: single-column btree(feature_ts) is fully covered
--    by idx_ledger_feature_join (symbol, feature_ts, feature_tf). Any query
--    using feature_ts benefits more from the composite.
--
-- 5. idx_llm_calls_signal_id: not partial. The outcome UPDATE is:
--      WHERE signal_id = $1 AND outcome IS NULL
--    A partial index WHERE outcome IS NULL shrinks as outcomes are back-filled,
--    making the UPDATE lookup progressively faster as data accumulates.
--
-- PHILOSOPHY: Index storage and write amplification are not free.
-- Every index on intelligence_features (379 chunks, 1661 MB) and signal_ledger
-- must earn its keep through measurable query benefit.

-- ─── 1. Re-drop indexes migration 022 failed to remove ───────────────────────

-- Covered by PK (ts, symbol, tf) — any time-only range query hits chunk exclusion
DROP INDEX IF EXISTS intelligence_features_ts_idx;

-- Covered by unique index uq_technical_indicators_ts_symbol_tf_name
DROP INDEX IF EXISTS technical_indicators_timestamp_idx;

-- ─── 2. Drop wrong-filter and redundant signal_ledger indexes ─────────────────

-- Wrong partial filter: misses 'regime_suppressed'. idx_ledger_open_signals covers
-- the actual hot pattern: WHERE status IN ('pending','active','regime_suppressed') AND symbol=$1
DROP INDEX IF EXISTS idx_ledger_status;

-- Fully covered by idx_ledger_feature_join (symbol, feature_ts, feature_tf).
-- A composite always beats a single-column when the wider columns appear in the JOIN.
DROP INDEX IF EXISTS idx_ledger_feature_ts;

-- ─── 3. Replace timestamp-only index with (symbol, timestamp DESC) ────────────
-- signal_ledger_timestamp_idx was chosen by planner for the API signals query:
--   WHERE symbol=$1 ORDER BY timestamp DESC LIMIT N
-- Using it requires a Filter (not Index Cond) — O(N_all) scan, not O(N_symbol).
-- idx_ledger_sym_ts gives O(log N + K) where K = LIMIT.
-- signal_ledger_timestamp_idx becomes fully redundant once idx_ledger_sym_ts exists.

DROP INDEX IF EXISTS signal_ledger_timestamp_idx;

CREATE INDEX IF NOT EXISTS idx_ledger_sym_ts
    ON signal_ledger (symbol, timestamp DESC);

-- ─── 4. Replace llm_calls signal_id index with partial version ────────────────
-- The UPDATE pattern: WHERE signal_id=$1 AND outcome IS NULL
-- A partial index WHERE outcome IS NULL shrinks as calls get their outcomes
-- back-filled, so lookup cost decreases over time rather than growing with
-- total call volume. Non-partial would scan all resolved rows unnecessarily.

DROP INDEX IF EXISTS idx_llm_calls_signal_id;

CREATE INDEX IF NOT EXISTS idx_llm_calls_signal_id_pending
    ON llm_calls (signal_id)
    WHERE outcome IS NULL;
