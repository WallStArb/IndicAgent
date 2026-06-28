#!/usr/bin/env bash
# Backfill missing timeframes for ETFs with gaps in market_data_ohlcv.
# Usage: bash scripts/infrastructure/backfill/infrastructure_backfill_missing_timeframes.sh

set -euo pipefail

SCRIPT="scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py"
PYTHON=".venv/bin/python"
CLIENT_ID=41
LOG_DIR="logs/backfill"
mkdir -p "$LOG_DIR"

# Days back for each timeframe (aligned with v3.0 Phase A spec)
declare -A DAYS_BY_TF=(
    [5m]=1825    # 5 years
    [15m]=3650   # 10 years
    [1h]=5500    # 15 years (IBKR practical limit ~2011)
)

# Target symbols and which TFs they need.
# Last audited: 2026-06-23
declare -A MISSING_TFS=(
    [XLU]="5m,15m,1h"
    [XLV]="5m,15m,1h"
    [XLY]="5m,15m,1h"
    [XOP]="5m,15m,1h"
    [XRT]="5m,15m,1h"
    [VTV]="5m,15m"
    [IBIT]="5m,15m"   # launched 2024-01-11; will fetch all available
    [IEF]="15m"
)

total_stored=0
errors=()

run_backfill() {
    local symbol=$1
    local tf=$2
    local days=$3
    local logfile="$LOG_DIR/${symbol}_${tf}_$(date +%Y%m%d_%H%M%S).log"

    echo "  -> $symbol/$tf ($days days)..."
    PYTHONUNBUFFERED=1 "$PYTHON" "$SCRIPT" \
        --fetch-only \
        --symbols "$symbol" \
        --timeframes "$tf" \
        --client-id "$CLIENT_ID" \
        --days "$days" \
        > "$logfile" 2>&1

    local stored
    stored=$(grep -oP "stored \K[0-9,]+" "$logfile" | tr -d ',' | tail -1 || echo 0)
    local earliest
    earliest=$(grep -oP "fetching full window \K[0-9-]+" "$logfile" || echo "unknown")

    if grep -q "fetch error" "$logfile"; then
        echo "     ERROR - see $logfile"
        errors+=("$symbol/$tf")
    else
        echo "     OK: $stored bars (from $earliest)"
        total_stored=$((total_stored + stored))
    fi
}

echo "======================================"
echo " Missing Timeframes Backfill"
echo " $(date)"
echo "======================================"
echo
echo "Target: 8 symbols with gaps (audited 2026-06-23)"
echo "  - XLU,XLV,XLY,XOP,XRT: need 5m,15m,1h"
echo "  - VTV,IBIT: need 5m,15m"
echo "  - IEF: need 15m"
echo

for sym in "${!MISSING_TFS[@]}"; do
    echo "=== $sym ==="
    IFS=',' read -ra tfs <<< "${MISSING_TFS[$sym]}"
    for tf in "${tfs[@]}"; do
        days=${DAYS_BY_TF[$tf]}
        run_backfill "$sym" "$tf" "$days"
    done
    echo
done

echo "======================================"
echo " Done: $total_stored total bars stored"
if [ ${#errors[@]} -gt 0 ]; then
    echo " Errors: ${errors[*]}"
else
    echo " All backfills completed successfully"
fi
echo " $(date)"
echo "======================================"
