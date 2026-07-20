-- Migration 240: alpha.quant.cross_symbol_corroboration.min_symbols APR key (todo 152)
--
-- Todo 148's return_{scale}_suspect guard flags any return whose magnitude exceeds a
-- per-tf ceiling as suspect, excluding it from mean-based consumers. Investigating all
-- 76 currently-flagged rows against actual market history found two conflated
-- populations: genuine corrupt IBKR prints (UUP/XRT/VWO -- no economic basis) and real,
-- documented crisis events (the May 6 2010 Flash Crash across CWB/ITA/RSP/VTV/VUG/VYM,
-- the Aug 24 2015 ETF flash crash, 2008 Lehman-aftermath KRE volatility) that were
-- silently excluded from mean-based consumers -- a real defect per this project's
-- Renaissance data-retention principle ("never drop data that could contain signal"),
-- not a conservative default.
--
-- A magnitude-only ceiling structurally cannot make this distinction: a real Flash
-- Crash return and a fabricated $1000-print return can share the same magnitude. The
-- distinguishing signal is cross-symbol simultaneity -- corruption doesn't hit N
-- unrelated symbols at the identical historical minute; a market-wide liquidity vacuum
-- does. This key is the minimum distinct-symbol count (INCLUDING the subject symbol
-- itself) required at an identical (tf, bar_ts) to treat a flagged move as a
-- corroborated market event rather than a corrupt print.
--
-- Seed 4 is [initial_estimate]: the confirmed Flash Crash cluster hit 6 unrelated ETFs
-- simultaneously (well clear of this floor); the confirmed isolated corrupt prints
-- (UUP/XRT/VWO) each affected exactly 1 symbol. A floor of 4 (self + 3 others) sits
-- comfortably between those two populations with no known borderline case. Shared by
-- both todo 152 (services/forward_return_writer.py, corrective UPDATE on
-- forward_returns.return_{scale}_suspect) and todo 151
-- (scripts/ops/corpus/ops_known_corrupt_print_cleanup.py, CONFIRMED_CORRUPT ->
-- MARKET_EVENT downgrade) -- same underlying signal, two different data models. Not an
-- ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.quant.cross_symbol_corroboration.min_symbols',
    'int',
    '4',
    2, 20,
    '[initial_estimate] Minimum distinct symbols (including the subject itself) showing '
    'an implausible move at the identical (tf, bar_ts) to treat a price-sanity-flagged '
    'return as a corroborated real market event (Flash Crash, ETF flash crash) rather '
    'than a corrupt print (todo 152). Used by services/forward_return_writer.py (clears '
    'return_{scale}_suspect) and scripts/ops/corpus/ops_known_corrupt_print_cleanup.py '
    '(downgrades CONFIRMED_CORRUPT to MARKET_EVENT). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.quant.cross_symbol_corroboration.min_symbols', '4', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.quant.cross_symbol_corroboration.min_symbols', 1, '4', 'migration_240',
     'Seed cross-symbol corroboration threshold, todo 152 [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
