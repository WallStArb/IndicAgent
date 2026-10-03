-- 438: Tradier becomes the primary daily source; D1 becomes mutable (owner decisions 2026-10-03).
--
-- 1. D1 (ohlcv_request, ohlcv_observation) drops its append-only guards. Nothing in phase 185 is canonical
--    and the permanence cost (space, effort to correct a bad load) is not worth the guarantee. The writer
--    role gains UPDATE and DELETE; the derivation role stays read-only. The request source CHECK admits
--    'tradier' for any later raw capture.
-- 2. ohlcv_load: one row per Tradier (or later vendor) daily load of one symbol. It replaces per-bar
--    lineage for these names: what was fetched, what it covered, how many bars it added or changed.
-- 3. ohlcv_revision: the replaced values of any canonical bar a load changed ("flag, never delete" at the
--    cost of changed rows only).
-- 4. APR keys for the loader (infra.tradier.*).
-- A name uses one daily source for its whole history (Tradier volume is ~1.25x IBKR SMART volume).
-- Idempotent.

BEGIN;

DROP TRIGGER IF EXISTS trg_ohlcv_request_append_only ON ohlcv_request;
DROP TRIGGER IF EXISTS trg_ohlcv_request_no_truncate ON ohlcv_request;
DROP TRIGGER IF EXISTS trg_ohlcv_observation_append_only ON ohlcv_observation;
DROP TRIGGER IF EXISTS trg_ohlcv_observation_no_truncate ON ohlcv_observation;
DROP FUNCTION IF EXISTS ohlcv_d1_append_only();

GRANT UPDATE, DELETE ON ohlcv_request, ohlcv_observation TO ohlcv_observation_writer;

ALTER TABLE ohlcv_request DROP CONSTRAINT IF EXISTS ohlcv_request_source_check;
ALTER TABLE ohlcv_request
    ADD CONSTRAINT ohlcv_request_source_check CHECK (source IN ('ibkr', 'tradier'));

CREATE TABLE IF NOT EXISTS ohlcv_load (
    load_id         uuid PRIMARY KEY,
    symbol          text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    timeframe       text NOT NULL CHECK (timeframe = '1d'),
    source          text NOT NULL CHECK (source IN ('tradier')),
    requested_start date NOT NULL,
    requested_end   date NOT NULL,
    outcome         text NOT NULL CHECK (outcome IN ('loaded', 'short_history', 'no_data', 'failed', 'gated')),
    n_bars          integer NOT NULL CHECK (n_bars >= 0),
    n_new           integer NOT NULL DEFAULT 0 CHECK (n_new >= 0),
    n_changed       integer NOT NULL DEFAULT 0 CHECK (n_changed >= 0),
    first_bar       date,
    last_bar        date,
    detail          text,
    caller          text NOT NULL,
    loaded_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_load_symbol ON ohlcv_load (symbol, loaded_at DESC);

CREATE TABLE IF NOT EXISTS ohlcv_revision (
    load_id     uuid NOT NULL REFERENCES ohlcv_load(load_id) ON DELETE CASCADE,
    symbol      text NOT NULL,
    timeframe   text NOT NULL,
    "timestamp" timestamptz NOT NULL,
    old_open    double precision NOT NULL,
    old_high    double precision NOT NULL,
    old_low     double precision NOT NULL,
    old_close   double precision NOT NULL,
    old_volume  bigint NOT NULL,
    old_source  text NOT NULL,
    PRIMARY KEY (load_id, symbol, timeframe, "timestamp")
);

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.tradier.history_start', 'string', '2000-01-01', NULL, NULL,
 '[initial_estimate] First date requested from Tradier daily history; Tradier serves a name back to its listing or 2000, whichever is later. Not an ML learning target.'),
('infra.tradier.request_timeout_s', 'float', '30', 5, NULL,
 '[initial_estimate] HTTP timeout in seconds for one Tradier history request (measured 0.3 to 2 s). Not an ML learning target.'),
('infra.tradier.concurrency', 'int', '4', 1, 16,
 '[initial_estimate] Concurrent Tradier history requests in the daily loader; Tradier allows about 120 requests a minute on a production token (sandbox unverified), and measured latency is about 0.45 s. Not an ML learning target.'),
('infra.tradier.min_session_ratio', 'float', '0.95', 0.5, 1,
 '[initial_estimate] A Tradier history is accepted only when its bar count is at least this share of the weekdays between its first and last bar (US holidays remove about 3.5% of weekdays). Below it the load is recorded short_history and nothing is written. Not an ML learning target.'),
('infra.tradier.first_date_tolerance_days', 'int', '7', 0, 3650,
 '[initial_estimate] When canonical already holds earlier bars for the name, Tradier history must start no later than that first bar plus this many days, else the name stays on its existing source (the PEP short-history case, 2026-10-03). Not an ML learning target.'),
('infra.tradier.max_changed_bar_ratio', 'float', '0.02', 0, 1,
 '[initial_estimate] A reload from the same source fails with outcome gated when more than this share of existing bars change (a vendor split back-adjustment or bad payload); a deliberate source change passes --rebase. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.tradier.history_start', '2000-01-01', 1),
    ('infra.tradier.request_timeout_s', '30', 1),
    ('infra.tradier.concurrency', '4', 1),
    ('infra.tradier.min_session_ratio', '0.95', 1),
    ('infra.tradier.first_date_tolerance_days', '7', 1),
    ('infra.tradier.max_changed_bar_ratio', '0.02', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_438',
       'Initial value for the Tradier daily loader [initial_estimate]'
  FROM config_state
 WHERE config_key LIKE 'infra.tradier.%'
ON CONFLICT DO NOTHING;

COMMIT;
