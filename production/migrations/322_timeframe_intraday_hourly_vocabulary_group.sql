-- Migration 322: `timeframe` CVR group for the intraday+hourly subset (todo 329)
--
-- services/signal_auditor.py's `_COVERAGE_TFS` and
-- src/intelligence/services/feature_validation_analyzer.py's `_TIMEFRAMES` both hardcode
-- the byte-identical literal subset ("1m", "5m", "15m", "1h") -- exactly D-07's own
-- admission condition (a fixed code set independently hardcoded in >=2 files). Todo 327
-- gave both an `assert_known_subset()` startup guard, which catches a literal referencing
-- a CVR code that doesn't exist, but not the two literals silently drifting apart from
-- each other, and doesn't make the subset relationship registry-visible anywhere
-- queryable. CVR already has the mechanism for exactly this shape
-- (`vocabulary_group`/`vocabulary_group_member`, used today for `regime_hmm` and the
-- cross-sectional regime groups) -- this migration adds a `timeframe` group and repoints
-- both call sites at it instead.
--
-- Zero behavior change: same 4 timeframes either way.

BEGIN;

INSERT INTO vocabulary_group (namespace, group_name, label, description, sort_order) VALUES
('timeframe', 'intraday_plus_hourly', 'Intraday + Hourly',
 'The 1m/5m/15m/1h subset used by signal-coverage and feature-validation auditing; '
 'deliberately excludes 1d/4h (todo 327 preserved this pre-existing scoping without '
 'evidence it was accidental).', 1)
ON CONFLICT (namespace, group_name) DO NOTHING;

INSERT INTO vocabulary_group_member (namespace, group_name, code) VALUES
('timeframe', 'intraday_plus_hourly', '1m'),
('timeframe', 'intraday_plus_hourly', '5m'),
('timeframe', 'intraday_plus_hourly', '15m'),
('timeframe', 'intraday_plus_hourly', '1h')
ON CONFLICT (namespace, group_name, code) DO NOTHING;

COMMIT;
