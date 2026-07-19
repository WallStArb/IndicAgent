-- Macro factors hypertable
-- Stores computed macro factors (yield curve, flight-to-quality, USD strength)
-- Time partitioned by ts (1 day chunks)

CREATE TABLE IF NOT EXISTS macro_features (
    ts TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,

    -- Yield curve slope factor (Plan 64-03A)
    yield_curve_slope DOUBLE PRECISION,
    yield_curve_regime VARCHAR(32),

    -- Flight-to-quality factor (Plan 64-03B)
    ftq_score DOUBLE PRECISION,
    ftq_regime VARCHAR(32),

    -- USD strength factor (Plan 64-03C - future)
    -- usd_strength_score DOUBLE PRECISION,
    -- usd_strength_regime VARCHAR(32),

    PRIMARY KEY (ts, symbol, timeframe)
);

-- Create hypertable
SELECT create_hypertable('macro_features', 'ts',
  chunk_time_interval => INTERVAL '1 day',
  if_not_exists => TRUE
);

-- Indexes for queries
CREATE INDEX IF NOT EXISTS idx_macro_features_symbol
  ON macro_features(symbol, ts DESC);

CREATE INDEX IF NOT EXISTS idx_macro_features_timeframe
  ON macro_features(timeframe, ts DESC);

-- Add comment
COMMENT ON TABLE macro_features IS 'Macro factors: yield curve, flight-to-quality, USD strength';
