-- Migration 423: macro_series_observations + coverage + APR keys (todo 480)
--
-- FRED reference data: credit spreads, Treasury yields, real yields. Raw and permanent; nothing
-- here is a price and no bar reads it. Written only by services/macro_series_writer.py.
--
-- Point in time. Each row records WHEN the value became knowable (available_at) and on what
-- basis:
--   assumed_lag  the first fetch of a series (a backfill): FRED serves today's values, so the
--                true publication time is unknown; available_at = observation date + the APR
--                lag. A series that FRED revises has as-revised history here, which a reader
--                must not treat as point in time (the series' APR revision field says which).
--   fetch        every later run: a new observation, or a changed value for a stored one, is
--                stamped with the fetch time, an upper bound on when it was knowable.
-- A revision is a NEW row (same series and observation date, later available_at); rows are never
-- updated or deleted (trigger below). A reader as of t takes, per observation date, the row with
-- the latest available_at <= t. Missing days stay absent: no forward-fill in the store.
--
-- macro_series_coverage records the span each series' last fetch examined, the difference
-- between "no observation" and "never fetched". FRED may serve less history over time (the ICE
-- BofA spread series are limited to a trailing window); rows already stored are kept.

BEGIN;

-- LEDGER-EXCEPTION: macro reference data (published rates and spreads), not a counterfactual
-- trade claim; nothing here is a frame or a hypothesis.
CREATE TABLE IF NOT EXISTS macro_series_observations (
    series_id TEXT NOT NULL,
    observation_date DATE NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    availability_basis TEXT NOT NULL CHECK (availability_basis IN ('assumed_lag', 'fetch')),
    compute_version TEXT NOT NULL,
    derived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, observation_date, available_at),
    -- NaN compares equal to itself in Postgres, so test for it explicitly.
    CONSTRAINT macro_series_observations_finite CHECK (
        value <> 'NaN' AND value <> 'Infinity' AND value <> '-Infinity'
    )
);

COMMENT ON TABLE macro_series_observations IS
    'FRED observations, append-only (todo 480). A revision is a new row with a later '
    'available_at. Readers take the latest available_at <= t per observation date; use '
    'macro_series_current for the latest known value.';

CREATE OR REPLACE FUNCTION macro_series_observations_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'macro_series_observations is append-only (todo 480); a revision is a new row';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS macro_series_observations_append_only ON macro_series_observations;
CREATE TRIGGER macro_series_observations_append_only
    BEFORE UPDATE OR DELETE ON macro_series_observations
    FOR EACH ROW EXECUTE FUNCTION macro_series_observations_append_only();

CREATE TABLE IF NOT EXISTS macro_series_coverage (
    series_id TEXT PRIMARY KEY,
    covered_from DATE NOT NULL,
    covered_to DATE NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE macro_series_coverage IS
    'Span of observation dates a series'' last fetch examined (todo 480). A day outside it is '
    'unknown, not missing.';

CREATE OR REPLACE VIEW macro_series_current AS
SELECT DISTINCT ON (series_id, observation_date)
       series_id, observation_date, value, available_at, availability_basis
FROM macro_series_observations
ORDER BY series_id, observation_date, available_at DESC;

COMMENT ON VIEW macro_series_current IS
    'Latest known value per series and observation date (todo 480). Not point in time: for a '
    'read as of t, filter macro_series_observations on available_at <= t first.';

-- APR keys.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.fred.series',
    'json',
    '[{"series_id": "BAMLH0A0HYM2", "revision": "none", "consumer": "credit_spread_screen"}, {"series_id": "BAMLC0A0CM", "revision": "none", "consumer": "credit_spread_screen"}, {"series_id": "BAMLH0A3HYC", "revision": "none", "consumer": "credit_spread_screen"}, {"series_id": "BAMLC0A4CBBB", "revision": "none", "consumer": "credit_spread_screen"}, {"series_id": "BAA10Y", "revision": "none", "consumer": "credit_spread_screen"}, {"series_id": "DGS10", "revision": "none", "consumer": "rate_level_screen"}, {"series_id": "DGS2", "revision": "none", "consumer": "rate_level_screen"}, {"series_id": "T10Y2Y", "revision": "none", "consumer": "rate_level_screen"}, {"series_id": "DFII10", "revision": "none", "consumer": "rate_level_screen"}, {"series_id": "THREEFYTP10", "revision": "model_revised", "consumer": "rate_level_screen"}]',
    NULL, NULL,
    '[initial_estimate] FRED series macro_series_writer.py fetches (todo 480): list of '
    '{series_id, revision, consumer}. revision is none (observed market rate, never revised) '
    'or model_revised (history is as-revised, not point in time). Every entry names a consumer. '
    'Behavioral list, not an ML learning target.'
),
(
    'infra.fred.assumed_lag_days',
    'int', '1', 0, 10,
    '[conventional] Days between a FRED daily observation date and its publication, used as '
    'available_at for a series'' first-fetch history (availability_basis assumed_lag). FRED '
    'daily rate series post the next business day. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
SELECT config_key, default_value, 1 FROM config_schema
WHERE config_key IN ('infra.fred.series', 'infra.fred.assumed_lag_days')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, 1, s.default_value, 'migration_423',
       'Initial value [initial_estimate]: FRED reference data (todo 480)'
FROM config_schema s
WHERE s.config_key IN ('infra.fred.series', 'infra.fred.assumed_lag_days')
  AND NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = s.config_key AND h.changed_by = 'migration_423'
);

COMMIT;
