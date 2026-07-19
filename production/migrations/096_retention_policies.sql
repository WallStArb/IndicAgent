-- Phase 104 Plan 01: retention policies for hypertables missing them
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/090_retention_policies.sql

BEGIN;

-- intelligence_features: 2 years (canonical feature vectors)
SELECT add_retention_policy('intelligence_features', INTERVAL '2 years', if_not_exists => true);

-- signal_ledger: 1 year (lifecycle/outcome tracking)
SELECT add_retention_policy('signal_ledger', INTERVAL '1 year', if_not_exists => true);

-- llm_calls: 90 days (audit log, high growth)
SELECT add_retention_policy('llm_calls', INTERVAL '90 days', if_not_exists => true);

-- signal_lineage: 90 days (agent predictions per winner)
SELECT add_retention_policy('signal_lineage', INTERVAL '90 days', if_not_exists => true);

-- signal_transform_log: 90 days
SELECT add_retention_policy('signal_transform_log', INTERVAL '90 days', if_not_exists => true);

-- market_data_ohlcv: 2 years (raw OHLCV bars)
SELECT add_retention_policy('market_data_ohlcv', INTERVAL '2 years', if_not_exists => true);

-- macro_features: 1 year
SELECT add_retention_policy('macro_features', INTERVAL '1 year', if_not_exists => true);

-- ctx_events: 30 days (short-lived context events)
SELECT add_retention_policy('ctx_events', INTERVAL '30 days', if_not_exists => true);

-- alpha_multiplier_shadow: 30 days
SELECT add_retention_policy('alpha_multiplier_shadow', INTERVAL '30 days', if_not_exists => true);

COMMIT;
