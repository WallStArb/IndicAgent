-- 401: D3 venue validation study switches (phase 185 plan 13, D-17, D-18).
-- Two operator-visible gates for venue-routed bars. Both seed false: venue bars stay
-- stored and unused until the listing-venue validation study passes its
-- pre-registered thresholds for that timeframe. Only scripts/ops/bars/ops_venue_study.py
-- --apply-verdict moves them (changed_by 'venue_study_185', reason cites the verdict
-- file sha); D7 (plan 23) reports any switch that disagrees with the verdict file.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    (
        'infra.bar_derivation.venue_bars_1d',
        'bool',
        'false',
        '[user_preference] D-17 gate: when true the D2 rule may use listing-venue 1d bars. Set only by the D3 venue validation study verdict for 1d (ops_venue_study.py --apply-verdict); false leaves venue bars stored and unused. Not an ML learning target.'
    ),
    (
        'infra.bar_derivation.venue_bars_intraday',
        'bool',
        'false',
        '[user_preference] D-17 gate: when true intraday features may read recovered listing-venue intraday bars. Set only by the D3 venue validation study verdict for 5m (ops_venue_study.py --apply-verdict); false leaves them unused (D-18). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_derivation.venue_bars_1d', 'false', 1),
    ('infra.bar_derivation.venue_bars_intraday', 'false', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.bar_derivation.venue_bars_1d', 1, 'false', 'migration_401', 'Initial value [user_preference] venue bars unused until the D3 study passes'),
    (NOW(), 'infra.bar_derivation.venue_bars_intraday', 1, 'false', 'migration_401', 'Initial value [user_preference] venue bars unused until the D3 study passes')
ON CONFLICT DO NOTHING;

COMMIT;
