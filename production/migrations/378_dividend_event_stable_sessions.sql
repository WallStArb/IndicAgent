-- Migration 378: IBKR dividend derivation requires the two series in lockstep (todo 428)
--
-- services/dividend_event_writer.py derives IBKR dividends from ADJUSTED_LAST / TRADES ratio
-- steps. The rounding bound it tests against assumes both series use the same close. In parts
-- of IBKR's early history they do not: NVR 2004's ratio wanders 0.3% a day, up to 150x the
-- bound, and the first full pass (2026-09-26) derived hundreds of false events on names that
-- paid nothing then (NVR, AXON, MRVL, EQIX 2004). A step now counts only if the ratio is flat
-- within the bound for this many rows on each side. The false IBKR rows were deleted and
-- re-derived under this rule the same day.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.dividend_event.stable_sessions',
    'int',
    '3',
    '1', '10',
    '[rca_analysis] Rows on each side of an IBKR ADJUSTED_LAST / TRADES ratio step over which the ratio must stay within the rounding bound for the step to count as a dividend (the series in lockstep). 3 keeps weekly payers (5 sessions apart) detectable. Changing it changes which IBKR events are derived. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.dividend_event.stable_sessions', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'threshold.dividend_event.stable_sessions', 1, '3', 'migration_378', 'Initial value: false IBKR events where the two series use different closes [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
