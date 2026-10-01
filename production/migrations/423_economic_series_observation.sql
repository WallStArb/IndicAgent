-- Migration 423: economic_series_observation, its coverage and current view, APR keys (todo 480)
--
-- Published economic series from FRED and the NY Fed: credit spreads, Treasury yields, real
-- yields, reference rates and their distribution. Quant data
-- with external provenance, market-wide or economy-wide only (the key has no symbol: per-symbol
-- external data, such as short volume or dividends, gets its own table). Raw and permanent; nothing
-- here is a price and no bar reads it. Written only by services/economic_series_writer.py.
--
-- Point in time. Each row records WHEN the value became knowable (available_at) and on what
-- basis:
--   assumed_lag  the first fetch of a series (a backfill): FRED serves today's values, so the
--                true publication time is unknown; available_at = the end of the business day
--                the APR lag after the observation date. A series that FRED revises has
--                as-revised history here, which a reader must not treat as point in time
--                (the series' APR revision field says which).
--   fetch        every later run: a new observation, or a changed value for a stored one, is
--                stamped with the fetch time, an upper bound on when it was knowable.
-- A revision is a NEW row (same series and observation date, later available_at); rows are never
-- updated or deleted (trigger below). A reader as of t takes, per observation date, the row with
-- the latest available_at <= t. Missing days stay absent: no forward-fill in the store.
--
-- economic_series_observation_coverage records the span of observation dates any fetch of a
-- series has examined (the union across fetches), the difference between "no observation" and "never fetched". FRED may serve less history over time (the ICE
-- BofA spread series are limited to a trailing window); rows already stored are kept.

BEGIN;

-- LEDGER-EXCEPTION: economic reference series (published rates and spreads), not a counterfactual
-- trade claim; nothing here is a frame or a hypothesis.
CREATE TABLE IF NOT EXISTS economic_series_observation (
    source TEXT NOT NULL CHECK (source IN ('fred', 'nyfed')),
    series_id TEXT NOT NULL,
    observation_date DATE NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    availability_basis TEXT NOT NULL CHECK (availability_basis IN ('assumed_lag', 'fetch')),
    compute_version TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, observation_date, available_at),
    -- NaN compares equal to itself in Postgres, so test for it explicitly.
    CONSTRAINT economic_series_observation_finite CHECK (
        value <> 'NaN' AND value <> 'Infinity' AND value <> '-Infinity'
    )
);

COMMENT ON TABLE economic_series_observation IS
    'FRED observations, append-only (todo 480). A revision is a new row with a later '
    'available_at. Readers take the latest available_at <= t per observation date; use '
    'economic_series_observation_current for the latest known value.';

CREATE OR REPLACE FUNCTION economic_series_observation_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'economic_series_observation is append-only (todo 480); a revision is a new row';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS economic_series_observation_append_only ON economic_series_observation;
CREATE TRIGGER economic_series_observation_append_only
    BEFORE UPDATE OR DELETE ON economic_series_observation
    FOR EACH ROW EXECUTE FUNCTION economic_series_observation_append_only();

CREATE TABLE IF NOT EXISTS economic_series_observation_coverage (
    series_id TEXT PRIMARY KEY,
    covered_from DATE NOT NULL,
    covered_to DATE NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE economic_series_observation_coverage IS
    'Span of observation dates a series'' last fetch examined (todo 480). A day outside it is '
    'unknown, not missing.';

CREATE OR REPLACE VIEW economic_series_observation_current AS
SELECT DISTINCT ON (series_id, observation_date)
       source, series_id, observation_date, value, available_at, availability_basis
FROM economic_series_observation
ORDER BY series_id, observation_date, available_at DESC;

COMMENT ON VIEW economic_series_observation_current IS
    'Latest known value per series and observation date (todo 480). Not point in time: for a '
    'read as of t, filter economic_series_observation on available_at <= t first.';

-- APR keys.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.economic_series.sources',
    'json',
    '[{"source": "fred", "series_id": "BAMLH0A0HYM2", "revision": "none", "consumer": "credit_spread_screen"}, {"source": "fred", "series_id": "BAMLC0A0CM", "revision": "none", "consumer": "credit_spread_screen"}, {"source": "fred", "series_id": "BAMLH0A3HYC", "revision": "none", "consumer": "credit_spread_screen"}, {"source": "fred", "series_id": "BAMLC0A4CBBB", "revision": "none", "consumer": "credit_spread_screen"}, {"source": "fred", "series_id": "BAA10Y", "revision": "none", "consumer": "credit_spread_screen"}, {"source": "fred", "series_id": "DGS10", "revision": "none", "consumer": "rate_level_screen"}, {"source": "fred", "series_id": "DGS2", "revision": "none", "consumer": "rate_level_screen"}, {"source": "fred", "series_id": "T10Y2Y", "revision": "none", "consumer": "rate_level_screen"}, {"source": "fred", "series_id": "DFII10", "revision": "none", "consumer": "rate_level_screen"}, {"source": "fred", "series_id": "THREEFYTP10", "revision": "model_revised", "consumer": "rate_level_screen"}, {"source": "nyfed", "series_id": "SOFR", "revision": "revised", "consumer": "funding_stress_screen"}, {"source": "nyfed", "series_id": "TGCR", "revision": "revised", "consumer": "funding_stress_screen"}, {"source": "nyfed", "series_id": "BGCR", "revision": "revised", "consumer": "funding_stress_screen"}, {"source": "nyfed", "series_id": "SOFRAI", "revision": "revised", "consumer": "funding_stress_screen"}, {"source": "nyfed", "series_id": "EFFR", "revision": "revised", "consumer": "funding_stress_screen"}, {"source": "nyfed", "series_id": "OBFR", "revision": "revised", "consumer": "funding_stress_screen"}]',
    NULL, NULL,
    '[initial_estimate] Series economic_series_writer.py fetches (todo 480): list of '
    '{source, series_id, revision, consumer}; source is fred (series_id is the FRED id) or nyfed '
    '(series_id is the NY Fed rate type, expanded to one series per published field, named '
    'NYFED_<type>_<field>). revision is none (observed rate, never revised), revised (the '
    'publisher flags revisions) or model_revised (history is as-revised, not point in time). '
    'Every entry names a consumer. Behavioral list, not an ML learning target.'
),
(
    'infra.economic_series.assumed_lag_business_days',
    'int', '1', 0, 10,
    '[conventional] Business days between an observation date and its publication; available_at '
    'for a series'' first-fetch history (availability_basis assumed_lag) is the end of that '
    'business day. FRED daily series and NY Fed reference rates post the next business day; '
    'exchange holidays are not modeled. Not an ML learning target.'
),
(
    'infra.economic_series.http_timeout_sec',
    'int', '60', 5, 600,
    '[initial_estimate] Per-request HTTP timeout for the FRED and NY Fed fetches in '
    'economic_series_writer.py (a full-history response is a few MB). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
SELECT config_key, default_value, 1 FROM config_schema
WHERE config_key IN ('infra.economic_series.sources', 'infra.economic_series.assumed_lag_business_days',
                    'infra.economic_series.http_timeout_sec')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, 1, s.default_value, 'migration_423',
       'Initial value [initial_estimate]: economic series reference data (todo 480)'
FROM config_schema s
WHERE s.config_key IN ('infra.economic_series.sources', 'infra.economic_series.assumed_lag_business_days',
                    'infra.economic_series.http_timeout_sec')
  AND NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = s.config_key AND h.changed_by = 'migration_423'
);

COMMIT;
