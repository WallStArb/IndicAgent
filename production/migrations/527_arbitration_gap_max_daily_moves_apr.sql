-- Migration 527: the D-191-Q arbitration's overnight-gap bound for long pre-IBKR spans (todo 545,
-- third review H1)
--
-- Alpaca history before IBKR's first 1d bar serves only when it runs into that bar. For a span of
-- more than the basis window, the same-session test is not enough (SW: WestRock's history under
-- the reused ticker agrees with IBKR on IBKR's first session), so the span is admitted only when
-- Tradier corroborates Alpaca inside it, or the close-to-close gap at IBKR's first bar is at most
-- this many times the name's median absolute daily log move (IBKR's own closes). Read by
-- scripts/ops/bars/ops_d191q_arbitration.py; a failing span is held under an interim IBKR row.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.bar_integrity.arbitration_gap_max_daily_moves',
    'float', '4', 1, 50,
    '[initial_estimate] A pre-IBKR Alpaca span longer than the basis window, not corroborated by '
    'Tradier, is admitted only when the close-to-close gap at IBKR''s first 1d bar is at most this '
    'many median absolute daily log moves of the name (SW 7.9 and GRNT 6.8 held; SVRA 2.1 and '
    'ordinary handovers 1 to 4 admitted, 2026-10-28). Read by ops_d191q_arbitration.py. Not an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.bar_integrity.arbitration_gap_max_daily_moves', '4', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:527',
       'seed (todo 545, third review H1: pre-IBKR span gap bound)'
  FROM config_state s
 WHERE s.config_key = 'threshold.bar_integrity.arbitration_gap_max_daily_moves'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:527'
   );

COMMIT;
