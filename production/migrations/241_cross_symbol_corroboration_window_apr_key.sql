-- Migration 241: alpha.quant.cross_symbol_corroboration.window_minutes APR key (todo 152)
--
-- Task 3's live verification against the 2010-05-06 Flash Crash cluster
-- (CWB/ITA/VTV/VUG/VYM) found migration 240's exact-bar_ts, same-scale corroboration
-- match never fires: the six symbols' suspect flags stagger across bar_ts 18:20-18:55
-- and across all four scales (fast/mid/slow/extended) rather than sharing one exact
-- (tf, bar_ts, scale) triple. No two symbols share an identical bar_ts in the live
-- data. A real market-wide event's extreme-return signature is not minute-aligned
-- across symbols -- each ETF's specific price action during a live crash (bid-ask
-- bounce, HFT withdrawal timing, sequential circuit breakers) lands on a slightly
-- different bar.
--
-- This key widens the corroboration match from exact bar_ts equality to a
-- +/- window_minutes range, pooled across all four scales (services/forward_return_writer.py
-- now treats "was this symbol suspect on ANY scale near this time" as the
-- per-symbol corroboration signal, not "was this specific scale suspect at this
-- specific minute").
--
-- Seed 60 is [rca_analysis]: verified directly against the live Flash Crash rows --
-- a +/-60-minute window clusters the 18:20-18:55 rows into one corroborated window
-- (5 distinct symbols, clears the min_symbols=4 floor) while correctly leaving ITA's
-- unrelated 17:00/17:05 rows (90+ minutes away, a different and unresolved question)
-- untouched. Also matches the todo 152 investigation's own characterization of the
-- cluster as "the SAME 17:00-19:00 UTC window" (a 2-hour span).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.cross_symbol_corroboration.window_minutes',
    'int',
    '60',
    5, 240,
    '[rca_analysis] Time window (+/- minutes) within which another symbol''s '
    'ANY-scale suspect flag counts toward cross-symbol corroboration (todo 152). '
    'Verified against the live 2010-05-06 Flash Crash cluster (CWB/ITA/VTV/VUG/VYM), '
    'whose suspect rows stagger across bar_ts and scale rather than sharing one exact '
    '(tf, bar_ts, scale) triple -- an exact match never corroborates real events. Used '
    'by services/forward_return_writer.py alongside '
    'alpha.quant.cross_symbol_corroboration.min_symbols. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.cross_symbol_corroboration.window_minutes', '60', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.cross_symbol_corroboration.window_minutes', 1, '60', 'migration_241',
     'Seed cross-symbol corroboration time window, todo 152 empirical correction [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
