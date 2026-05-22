-- Phase 104 Plan 02 Task 2: drop shadow table + create freshness function
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/091_drop_feature_snapshots_shadow.sql

-- Freshness check: returns rows for any (symbol, tf) with no new bar in 10+ minutes
CREATE OR REPLACE FUNCTION check_feature_pipeline_freshness()
RETURNS TABLE(symbol text, tf text, last_ts timestamptz, gap_minutes float)
LANGUAGE sql AS $$
    SELECT symbol, tf, MAX(ts) as last_ts,
           EXTRACT(EPOCH FROM (NOW() - MAX(ts))) / 60.0 as gap_minutes
    FROM intelligence_features
    WHERE ts > NOW() - INTERVAL '30 minutes'
    GROUP BY symbol, tf
    HAVING MAX(ts) < NOW() - INTERVAL '10 minutes'
    ORDER BY gap_minutes DESC;
$$;

-- Drop the shadow table (byte-for-byte duplicate of intelligence_features)
DROP TABLE IF EXISTS feature_snapshots_shadow CASCADE;

-- Drop the violations tracking table (was 40 KB, never had a real violation)
DROP TABLE IF EXISTS feature_parity_violations;
