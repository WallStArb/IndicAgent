-- 062_market_data_gaps.sql
-- Track detected data completeness gaps for ML training exclusion.
-- bar_auditor_agent writes here on each audit cycle.
-- ML training JOINs this table to exclude contaminated windows.

CREATE TABLE IF NOT EXISTS market_data_gaps (
    id            BIGSERIAL    PRIMARY KEY,
    symbol        TEXT         NOT NULL,
    tf            TEXT         NOT NULL,
    gap_start_ts  TIMESTAMPTZ  NOT NULL,
    gap_end_ts    TIMESTAMPTZ,               -- NULL while gap is ongoing
    bars_expected INT          NOT NULL,
    bars_missing  INT          NOT NULL,
    detected_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ,               -- set when bar_auditor confirms filled
    UNIQUE (symbol, tf, gap_start_ts)
);

CREATE INDEX IF NOT EXISTS market_data_gaps_symbol_tf_start
    ON market_data_gaps (symbol, tf, gap_start_ts);

COMMENT ON TABLE market_data_gaps IS
    'Detected data completeness gaps per (symbol, tf). '
    'Used by ML training pipelines to exclude contaminated windows. '
    'Written by bar_auditor_agent on each audit cycle. '
    'Populated from Phase 67 onward — no historical backfill.';
