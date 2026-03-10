-- Version: 1.0.0
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Features table: raw I1 feature vectors
CREATE TABLE IF NOT EXISTS features (
    timestamp      timestamptz NOT NULL,
    symbol         text        NOT NULL,
    timeframe      text        NOT NULL,
    features       jsonb       NOT NULL,
    source         text        NOT NULL,
    PRIMARY KEY (timestamp, symbol, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_features_symbol_tf_ts
    ON features(symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_features_gin
    ON features USING GIN (features);

-- Intelligence table: composites, regimes, patterns, insights
CREATE TABLE IF NOT EXISTS intelligence (
    timestamp      timestamptz NOT NULL,
    symbol         text        NOT NULL,
    timeframe      text        NOT NULL,
    kind           text        NOT NULL, -- 'composite' | 'regime' | 'pattern' | 'insight'
    payload        jsonb       NOT NULL,
    source         text        NOT NULL,
    PRIMARY KEY (timestamp, symbol, timeframe, kind)
);

CREATE INDEX IF NOT EXISTS idx_intelligence_symbol_tf_ts
    ON intelligence(symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_intelligence_kind
    ON intelligence(kind);

CREATE INDEX IF NOT EXISTS idx_intelligence_payload_gin
    ON intelligence USING GIN (payload);


