-- Migration 318: APR-back the two thresholds forward_return_writer.py's
-- has_gap_before_entry computation needs (todo 334).
--
-- has_gap_before_entry (boolean, migration 156) exists to flag entries where the
-- market-on-open entry bar (T+1) follows an unusually large elapsed gap from the
-- signal bar (T) -- a real data/microstructure quality concern (stale price, wide
-- spread, post-reconnect noise right at entry), not decoration. Confirmed live
-- 2026-08-16: this column had been permanently false for every one of 103M+ rows
-- since the table existed -- forward_return_writer.py never set it (zero commits
-- across all history, `git log -S has_gap_before_entry`), and its one downstream
-- consumer (ops_cost_hurdle_calibration.py Step 3, todo 030) has therefore been
-- structurally unable to detect gap contamination since it was written.
--
-- Considered and rejected: reusing market_data_gaps (BarAuditor's own gap-tracking
-- table). BarAuditor (indicagent-bar-auditor.service) is confirmed inactive/disabled
-- with no log file -- likely never run on this box -- and market_data_gaps is
-- empty. Wiring this column to that table would trade one silent-always-false bug
-- for another (empty upstream instead of never-read). Computed locally instead,
-- directly off the same market_data_ohlcv_tradeable rows the writer already reads
-- (LEAD(m.timestamp) alongside the existing LEAD(m.open) AS open_entry), reusing
-- src/core/service_utils.py's tf_to_seconds() as the interval source -- no new
-- join, no new dependency on a currently-dormant subsystem.
--
-- Two thresholds, not one, deliberately: gap_multiplier is a floor (elapsed time
-- must exceed N bar-intervals -- guards against 1-bar noise/rounding);
-- gap_max_seconds is a ceiling (elapsed time must stay under this -- guards
-- against flagging NORMAL overnight/weekend session closures as anomalous, the
-- exact mistake todo 208 already made once for complete_{scale} and had to
-- revert: "overnight/weekend gaps are a known, accepted market property").
--
-- gap_max_seconds default (14400s = 4h) is calibrated for equity/ETF RTH sessions
-- only -- confirmed live 2026-08-16 that all 231 symbols currently in
-- forward_returns are asset_class='equity'. The 4h ceiling comfortably clears any
-- equity overnight closure (~17.5h minimum) while catching genuine intrasession
-- anomalies (stuck IBKR connection, backfill hole, trading halt). NOT yet safe for
-- futures/fx symbols, whose short daily maintenance breaks (~1h, well inside this
-- window) would be misflagged as anomalous gaps -- asset-class-aware widening
-- needed before this column can be trusted for a mixed-asset-class run; not
-- implemented here since no futures/fx symbols exist in the corpus today (see
-- todo 334's follow-up note).
--
-- Not an ML learning target -- both are conventional/initial_estimate calibration
-- constants (bar-interval multiple and a session-safe ceiling), not something a
-- data-driven optimizer should tune.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description) VALUES
    ('alpha.forward_returns.gap_multiplier', 'float',
     '[conventional] has_gap_before_entry floor -- the elapsed time between the '
     'signal bar (T) and the entry bar (T+1 open) must exceed this many multiples '
     'of the timeframe''s nominal bar interval (tf_to_seconds()) before being '
     'flagged as an anomalous gap. Guards against 1-bar noise/rounding false '
     'positives. Not an ML learning target.'),
    ('alpha.forward_returns.gap_max_seconds', 'int',
     '[initial_estimate] has_gap_before_entry ceiling (seconds) -- elapsed time '
     'between signal bar and entry bar must stay under this to be flagged. '
     'Default (14400s = 4h) is calibrated for equity/ETF RTH sessions only '
     '(confirmed all 231 corpus symbols are asset_class=equity as of 2026-08-16) '
     '-- excludes normal overnight (~17.5h+) and weekend closures. NOT yet '
     'safe for futures/fx symbols (short daily maintenance breaks would be '
     'misflagged); needs asset-class-aware widening before a mixed-asset-class '
     'run can trust this column, per todo 334. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.forward_returns.gap_multiplier', '3', 1),
    ('alpha.forward_returns.gap_max_seconds', '14400', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
