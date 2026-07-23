-- Migration 251: ic_cell_fingerprints -- whole-cell skip/recompute gate for ic_engine.py
-- (Phase 162 Plan 03, todo 134 core; absorbs todo 122's checkpoint-APR-drift surface)
--
-- Plain table (not a hypertable) -- row count is O(symbols x tfs x pass_types x windows),
-- same order of magnitude as feature_ic_scores' own (symbol, tf, pass_type) grain, not a
-- time-series workload. Follows migration 156's plain-table columns/PK convention and
-- migration 225's idempotent-guard convention (CREATE TABLE IF NOT EXISTS, ON CONFLICT
-- DO NOTHING inserts, safe to re-run).
--
-- Cell identity: (symbol, tf, pass_type, training_window_end). pass_type is the same
-- 3-value vocabulary services/ic_engine.py::_resolve_regime_scope() already writes into
-- feature_ic_scores.regime_scope ('pooled' | 'symbol_hmm' | 'cross_sectional') -- reused
-- verbatim, not reinvented.
--
-- Cross-sectional rows: feature_ic_scores has no regime_group column (regime_group identity
-- stays implicit in regime_label string uniqueness across enabled groups -- see
-- _compute_cross_sectional_tf's docstring), and a cross-sectional feature_ic_scores row
-- always carries symbol='POOLED' regardless of which regime_group or regime_label produced
-- it. Reusing 'POOLED' literally in this table's symbol column for pass_type='cross_sectional'
-- would collapse every (regime_group, regime_label) cell for a tf into ONE fingerprint row --
-- silently merging distinct cells' validity decisions. This table's symbol column is
-- therefore NOT required to literally equal feature_ic_scores.symbol; for
-- pass_type='cross_sectional' rows, ic_engine.py synthesizes symbol as
-- '{regime_group}:{regime_label}' (colon-delimited, matching the cell granularity
-- _compute_cross_sectional_tf actually dispatches at: one cell per (regime_group, tf,
-- regime_label)). For pass_type IN ('pooled', 'symbol_hmm'), symbol is the real instrument
-- symbol, matching feature_ic_scores.symbol exactly.
--
-- A cell is skip-eligible ONLY when code_content_key AND apr_snapshot_key AND
-- upstream_watermark ALL match the freshly-computed current values -- a partial match
-- (e.g. code unchanged but watermark stale) is a full miss, never a partial skip. Crash-
-- loud, never silently partial-stale ("silent wrong answers are worse than loud crashes",
-- CLAUDE.md north star). See services/ic_engine.py::_fingerprint_is_valid.

BEGIN;

CREATE TABLE IF NOT EXISTS ic_cell_fingerprints (
    symbol               text          NOT NULL,
    tf                   text          NOT NULL,
    pass_type            text          NOT NULL
        CHECK (pass_type IN ('pooled', 'symbol_hmm', 'cross_sectional')),
    training_window_end  timestamptz   NOT NULL,
    code_content_key     text          NOT NULL,
    apr_snapshot_key     text          NOT NULL,
    upstream_watermark   jsonb         NOT NULL,
    computed_at          timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, pass_type, training_window_end)
);

COMMENT ON TABLE ic_cell_fingerprints IS
    'Whole-cell skip/recompute fingerprint for ic_engine.py (Phase 162 Plan 03, todo 134). '
    'A cell (one row) is skip-eligible for a re-run ONLY when ALL THREE of '
    'code_content_key, apr_snapshot_key, and upstream_watermark match the freshly-computed '
    'current values -- a partial match is a full miss (crash-loud, never silently partial-'
    'stale). code_content_key: SHA-256 of first-party src/services bytes actually imported '
    '(_checkpoint_content_key(), 12 hex). apr_snapshot_key: BaseBatch.content_key() over '
    'the sorted COMPUTATIONAL-only ICEngineConfig fields (_compute_apr_snapshot_key()) -- '
    'an OPERATIONAL field (thread counts, chunk sizes, throughput knobs) changing must '
    'NEVER move this key. upstream_watermark: per-table JSONB watermark (forward_returns '
    'MAX(computed_at) + feature_vectors/market_regimes/instrument_tags/feature_registry '
    'content hashes) that changes on an in-place VALUE mutation even when MAX(bar_ts)/'
    'COUNT(*) are unchanged (see _compute_upstream_watermark()). For '
    'pass_type=''cross_sectional'', symbol is a synthesized ''{regime_group}:{regime_label}'' '
    'key, NOT feature_ic_scores.symbol (which is always the ''POOLED'' sentinel for those '
    'rows) -- see this migration''s header comment for why.';

COMMIT;
