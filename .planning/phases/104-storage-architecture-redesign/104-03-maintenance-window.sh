#!/bin/bash
# Phase 104-03 Task 2: Atomic Maintenance Window
# This script orchestrates the DDL migration and service restart

set -e

echo "=== PHASE 104-03 MAINTENANCE WINDOW ==="
echo "Started at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

# Variables
BACKUP_FILE="/tmp/indicagent-pre-migration-20260522175108.dump"
MIGRATION_092="/home/bg/dev/indicagent/db/migrations/092_rename_intelligence_feature_tiers.sql"
MIGRATION_093="/home/bg/dev/indicagent/db/migrations/093_slim_signal_ledger.sql"

# Services in reverse DAG order (stop order)
SERVICES_STOP=(
    "indicagent-signal-auditor"
    "indicagent-signal-metrics-compute"
    "indicagent-lifecycle-writer"
    "indicagent-signal-tracker-compute"
    "indicagent-signal-writer"
    "indicagent-feature-writer"
    "indicagent-intelligence-pipeline"
)

# Services in forward DAG order (start order)
SERVICES_START=(
    "indicagent-intelligence-pipeline"
    "indicagent-feature-writer"
    "indicagent-signal-writer"
    "indicagent-signal-tracker-compute"
    "indicagent-lifecycle-writer"
    "indicagent-signal-metrics-compute"
    "indicagent-signal-auditor"
)

echo "Step 1: Verify backup exists"
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi
echo "✓ Backup found: $BACKUP_FILE"
echo ""

echo "Step 2: Stop services (requires sudo)"
echo "Please run these commands manually:"
for svc in "${SERVICES_STOP[@]}"; do
    echo "  sudo systemctl stop $svc"
done
echo ""
read -p "Press Enter after stopping all services..."

echo ""
echo "Step 3: Verify all services stopped"
all_stopped=true
for svc in "${SERVICES_STOP[@]}"; do
    status=$(systemctl is-active "$svc" 2>&1)
    if [[ "$status" != "inactive" && "$status" != "unknown" ]]; then
        echo "✗ $svc: $status (still active)"
        all_stopped=false
    else
        echo "✓ $svc: $status"
    fi
done

if [ "$all_stopped" = false ]; then
    echo "ERROR: Not all services are stopped. Cannot proceed."
    exit 1
fi
echo ""

echo "Step 4: Apply migration 092 (column rename)"
echo "Running: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f $MIGRATION_092"
if PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f "$MIGRATION_092"; then
    echo "✓ Migration 092 applied successfully"
else
    echo "✗ Migration 092 FAILED. Check rollback procedure: logs/104-03-rollback.txt"
    exit 1
fi
echo ""

echo "Step 5: Verify column rename"
renamed=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_name='intelligence_features'
    AND column_name IN ('technical_indicators','market_context','pattern_detections','regime_features','confluence_scores','cross_timeframe_context','trading_signals','llm_narrative');
")
if [ "$renamed" -eq 8 ]; then
    echo "✓ All 8 columns renamed successfully"
else
    echo "✗ Column rename verification failed (expected 8, got $renamed)"
    exit 1
fi
echo ""

echo "Step 6: Apply migration 093 (slim signal_ledger)"
echo "WARNING: This may take 10-30 minutes due to chunk recompression"
echo "Running: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f $MIGRATION_093"
read -p "Press Enter to start slim migration..."
time PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f "$MIGRATION_093"
if [ $? -eq 0 ]; then
    echo "✓ Migration 093 applied successfully"
else
    echo "✗ Migration 093 FAILED. Check rollback procedure: logs/104-03-rollback.txt"
    exit 1
fi
echo ""

echo "Step 7: Verify slim schema"
column_count=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_name='signal_ledger';
")
echo "signal_ledger column count: $column_count (expected ~38-50)"
dropped_check=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_name='signal_ledger'
    AND column_name IN ('entry_price','stop_loss','confidence','cis_score','features_snapshot');
")
if [ "$dropped_check" -eq 0 ]; then
    echo "✓ Dropped columns successfully removed"
else
    echo "✗ Dropped columns still exist (count: $dropped_check)"
    exit 1
fi
echo ""

echo "Step 8: Restart services (requires sudo)"
echo "Please run these commands manually:"
for svc in "${SERVICES_START[@]}"; do
    echo "  sudo systemctl start $svc"
done
echo ""
read -p "Press Enter after starting all services..."

echo ""
echo "Step 9: Verify all services started"
all_started=true
for svc in "${SERVICES_START[@]}"; do
    status=$(systemctl is-active "$svc" 2>&1)
    if [ "$status" = "active" ]; then
        echo "✓ $svc: $status"
    else
        echo "✗ $svc: $status (not active)"
        all_started=false
    fi
done

if [ "$all_started" = false ]; then
    echo "WARNING: Not all services started successfully"
    echo "Check logs with: journalctl -u <service> -n 50"
fi
echo ""

echo "Step 10: Verify writes are landing"
sleep 5
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
    SELECT symbol, tf, MAX(ts) as last_ts
    FROM intelligence_features
    GROUP BY symbol, tf
    ORDER BY MAX(ts) DESC
    LIMIT 5;
"
echo ""

echo "=== MAINTENANCE WINDOW COMPLETE ==="
echo "Finished at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""
echo "Next steps:"
echo "1. Monitor logs for 60 seconds: tail -f logs/feature_writer_agent.log logs/signal_writer_agent.log"
echo "2. Verify dashboard: curl http://localhost:8000/api/signals/active"
echo "3. Continue to Task 3: Update read-path code"
