-- 405: verify-only venue fallback for 5m and the intraday recovery locks (phase 185 plan 20).
--
-- D3 extends to intraday as far as D-19 allows. 5m joins infra.ibkr.venue_fallback.timeframes:
-- former venues are asked for the uncovered 5m head, their answers recorded in ohlcv_request,
-- and the provider still never returns venue bars. Storing recovered intraday history is a
-- separate act behind two locks (scripts/ops/bars/ops_intraday_venue_recovery.py refuses
-- until both open, the venue study's 5m verdict passed, and no rebuild or run is live or
-- resumable): intraday_recovery_unlocked, set by phase 186's rebuild completion, and
-- rebuild_state_table, the JSON the rebuild's close-out sets to
-- {"table": ..., "target_tables": [...]} so the tool can count incomplete units. Idempotent.

BEGIN;

UPDATE config_state
   SET config_value = '["1d", "5m"]', version = version + 1, updated_at = NOW()
 WHERE config_key = 'infra.ibkr.venue_fallback.timeframes'
   AND config_value = '["1d"]';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.venue_fallback.timeframes', version, config_value, 'migration_405',
       'Verify-only 5m venue fallback: answers recorded, no venue bars returned (plan 185-20, D-20)'
  FROM config_state
 WHERE config_key = 'infra.ibkr.venue_fallback.timeframes'
   AND config_value = '["1d", "5m"]'
   AND NOT EXISTS (
       SELECT 1 FROM config_history
        WHERE config_key = 'infra.ibkr.venue_fallback.timeframes' AND changed_by = 'migration_405'
   );

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    (
        'infra.bar_derivation.intraday_recovery_unlocked',
        'bool',
        'false',
        '[user_preference] D-19 lock: recovered listing-venue intraday history may be stored only when true. Set by phase 186 when its feature_vectors rebuild completes (plan 186-27); the recovery tool also refuses while any rebuild or corpus run is live or resumable. Not an ML learning target.'
    ),
    (
        'infra.bar_derivation.rebuild_state_table',
        'text',
        '',
        '[user_preference] D-19 lock: JSON {"table": <state table>, "target_tables": [...]} naming where phase 186''s resumable rebuild records units. Empty means the rebuild has not landed and intraday recovery refuses. Set by plan 186-27. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_derivation.intraday_recovery_unlocked', 'false', 1),
    ('infra.bar_derivation.rebuild_state_table', '', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.bar_derivation.intraday_recovery_unlocked', 1, 'false', 'migration_405', 'Initial value [user_preference] intraday recovery locked until 186''s rebuild completes'),
    (NOW(), 'infra.bar_derivation.rebuild_state_table', 1, '', 'migration_405', 'Initial value [user_preference] empty until 186''s rebuild lands')
ON CONFLICT DO NOTHING;

COMMIT;
