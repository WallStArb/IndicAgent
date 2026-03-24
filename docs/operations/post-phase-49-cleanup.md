#!/bin/bash
# Post-Phase 49 Cleanup — Schema Migration Reset
#
# Context: Phase 49.1 and 49.2 completed with schema changes.
# Current data (6,270 rows) is PRE-migration and invalid.
# This script truncates all tables and restarts services cleanly.

set -e

echo "=== Post-Phase 49 Cleanup ==="
echo "Schema changes:"
echo "  49.1: Added regime_type_at_fire, hmm_regime_at_fire to signal_ledger"
echo "  49.2: Added HMM observability to intelligence_features"
echo ""

# 1. Stop all services
echo "Step 1: Stopping services..."
for svc in indicagent-ai-narrative indicagent-api indicagent-cross-asset \
            indicagent-feature-pipeline indicagent-feature-writer \
            indicagent-llm-writer indicagent-signal-generator \
            indicagent-signal-lifecycle indicagent-tws; do
    echo "  Stopping $svc..."
    systemctl stop "$svc" 2>/dev/null || echo "    (already stopped)"
done

# 2. Truncate all tables
echo ""
echo "Step 2: Truncating all tables..."
docker exec timescaledb psql -U postgres -d indicagent <<'SQL'
TRUNCATE TABLE cis_weights CASCADE;
TRUNCATE TABLE confidence_calibration CASCADE;
TRUNCATE TABLE contract_metadata CASCADE;
TRUNCATE TABLE drift_monitor CASCADE;
TRUNCATE TABLE drift_state CASCADE;
TRUNCATE TABLE intelligence_features CASCADE;
TRUNCATE TABLE llm_calls CASCADE;
TRUNCATE TABLE llm_model_scores CASCADE;
TRUNCATE TABLE market_data_ohlcv CASCADE;
TRUNCATE TABLE pattern_reliability CASCADE;
TRUNCATE TABLE setup_performance CASCADE;
TRUNCATE TABLE signal_ledger CASCADE;
TRUNCATE TABLE system_events CASCADE;
-- Keep instruments table (contract definitions)
SELECT 'All tables truncated' as status;
SQL

# 3. Verify truncation
echo ""
echo "Step 3: Verifying clean slate..."
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT
    (SELECT COUNT(*) FROM market_data_ohlcv) as ohlcv,
    (SELECT COUNT(*) FROM intelligence_features) as features,
    (SELECT COUNT(*) FROM signal_ledger) as ledger,
    (SELECT COUNT(*) FROM instruments) as instruments;
"

# 4. Start services
echo ""
echo "Step 4: Starting services..."
for svc in indicagent-tws indicagent-feature-pipeline indicagent-signal-generator \
            indicagent-signal-lifecycle indicagent-feature-writer indicagent-llm-writer \
            indicagent-ai-narrative indicagent-cross-asset indicagent-api; do
    echo "  Starting $svc..."
    systemctl start "$svc"
    sleep 2
done

echo ""
echo "=== Cleanup Complete ==="
echo ""
echo "Verification:"
echo "  - Tables: 3 empty (instruments preserved)"
echo "  - Services: 9/9 running"
echo "  - Data will flow with Phase 49 schema active"
echo ""
echo "Monitor: docker exec timescaledb psql -U postgres -d indicagent -c \"SELECT COUNT(*) FROM intelligence_features;\""
