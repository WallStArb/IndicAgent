-- Migration 479: complete-bar settle delay, request-to-load match tolerance, partial bars on the
-- request ledger (phase 191, second review of plan 07, findings 1 and 5)
--
-- Finding 5: the complete-bar rule moves out of the IBKR leaf into the shared fetch layer
-- (src/intelligence/bars/complete_bars.py), so every vendor gets it. A bar is a complete vendor
-- answer only when its grid block ended at or before the request end and before the answer
-- time; a bar that ends at or after its NYSE session close (the closing auction prints arrive
-- after the close: ADM 2026-10-12 19:55 UTC moved from 380,459 to 380,759) is final only once
-- the answer came at least `threshold.bar_integrity.session_close_settle_s` after the close.
-- A dropped partial bar is recorded on its request row (`ohlcv_request.partial_bars`, keys and
-- values), never silently dropped, and the gap planner does not count its slot as answered.
--
-- Finding 1: a later vendor serve excuses a refused value only on exact-key evidence; one form
-- is the request window of the applied load. Legacy loads carry no request id, so a load is
-- matched to the request answered at most `infra.selection_gate.request_load_match_s` before
-- it (measured 2026-10-14 on 7 series: applied loads land 0.04 s median, 0.21 s max after
-- their answer; refused loads 1.2 s median, 2.3 s max, after the archive write).
--
-- Small table DDL (ohlcv_request ~48k rows, nullable column, no rewrite).

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE ohlcv_request ADD COLUMN IF NOT EXISTS partial_bars jsonb;

COMMENT ON COLUMN ohlcv_request.partial_bars IS
    'Bars this answer served that were not complete vendor answers (straddling the request end, '
    'still forming at answered_at, or a session-closing bar answered before the settle delay), '
    'as a JSON array of {t, o, h, l, c, v}; they were not offered to ohlcv_raw. NULL when none '
    'were dropped or the row predates the rule. The gap planner treats these slots as not '
    'answered. Migration 479.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.bar_integrity.session_close_settle_s',
        'int',
        '1800',
        0,
        86400,
        '[initial_estimate] Seconds after the NYSE session close before a bar ending at or after '
        'the close counts as a complete vendor answer: closing auction prints revise the last '
        'bar after the close (ADM 2026-10-12 19:55 UTC, 380,459 then 380,759). Applies to every '
        'vendor through src/intelligence/bars/complete_bars.py. Not an ML learning target.'
    ),
    (
        'infra.selection_gate.request_load_match_s',
        'int',
        '5',
        1,
        600,
        '[rca_analysis] Largest gap, in seconds, between a request''s answered_at and the '
        'ohlcv_load row that persisted it, for loads that carry no request id (the retired '
        'fetch path). Measured 2026-10-14: applied 0.21 s max, refused 2.3 s max. Used by the '
        'selection gate and the raw repair for exact-key re-serve evidence. Not an ML learning '
        'target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.session_close_settle_s', '1800', 1),
    ('infra.selection_gate.request_load_match_s', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:479',
       'seed (phase 191, second review of plan 07, findings 1 and 5)'
  FROM config_state s
 WHERE s.config_key IN (
           'threshold.bar_integrity.session_close_settle_s',
           'infra.selection_gate.request_load_match_s'
       )
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:479'
   );

COMMIT;
