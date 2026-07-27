-- Migration 264: alert.lag.feature-vector-writer APR key
--
-- Found while investigating a live production gap: feature_vectors had stalled at
-- bar_ts ~2026-07-07 across every timeframe (15m/1h/1d/5m) while raw market_data_ohlcv
-- was current to 2026-07-24 -- an 18+ day compute-to-persistence gap and growing. Root
-- cause: services/feature_vector_writer.py (the v3.0 FeatureVectorWriter, a complete
-- BaseWriter subclass consuming topic_feature_vectors) was never deployed as a systemd
-- unit at all. Compounding this, service_auditor.py's _DAG_ORDER/_AGENT_ID_TO_UNIT (and
-- this project's original migration 103 alert.lag seed) conflated it with the archived
-- v2.x indicagent-feature-writer.service (Redpanda -> intelligence_features, confirmed
-- inactive/dead per CLAUDE.md) -- so the auditor was silently monitoring a unit that was
-- SUPPOSED to be dead, never alerting on the real outage.
--
-- migration 103's 'alert.lag.feature-writer' key (value 1000) is left in place, now
-- orphaned (no code references it after this fix) rather than deleted -- consistent with
-- this project's practice of not blind-deleting config_state history. Its config_schema
-- description IS updated below to mark it superseded, since that description is the only
-- thing an operator sees on the /config/parameters dashboard -- without it, a live-looking
-- lag threshold for a permanently-archived unit is a standing trap.
--
-- Same threshold value (1000) as the original mislabeled key and its sibling bar-writer:
-- no live evidence yet to justify a different number, this is an [initial_estimate]
-- carried forward, not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alert.lag.feature-vector-writer',
    'int',
    '1000',
    100, 10000,
    '[initial_estimate] Consumer lag threshold for indicagent-feature-vector-writer '
    '(v3.0 FeatureVectorWriter, topic_feature_vectors -> feature_vectors). Replaces the '
    'mislabeled migration-103 alert.lag.feature-writer key, which pointed at the archived '
    'v2.x indicagent-feature-writer.service and masked this unit never being deployed. '
    'Same threshold value as bar-writer''s sibling key; not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alert.lag.feature-vector-writer', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alert.lag.feature-vector-writer', 1, '1000', 'migration_264',
     'Seed lag threshold for the newly-deployed FeatureVectorWriter systemd unit, '
     'correcting a service-registry naming collision with the archived v2.x feature-writer '
     'that left this writer undeployed and unmonitored for weeks. [initial_estimate]')
ON CONFLICT DO NOTHING;

UPDATE config_schema
SET description = '[ORPHANED, migration 264] Superseded by alert.lag.feature-vector-writer '
    '-- this key was mislabeled at the archived v2.x indicagent-feature-writer.service '
    '(Redpanda -> intelligence_features, permanently dead) and masked the v3.0 '
    'FeatureVectorWriter never being deployed. No code path reads this key anymore.'
WHERE config_key = 'alert.lag.feature-writer';

COMMIT;
