#!/usr/bin/env bash
# Backfill missing 1d and 1h bars for ETFs not yet in market_data_ohlcv.
# Runs one symbol/TF at a time sequentially. Safe to re-run (ON CONFLICT DO NOTHING).
# Usage: bash production/scripts/backfill_missing_etfs.sh

set -euo pipefail

SCRIPT="production/scripts/run_historical_pipeline.py"
PYTHON=".venv/bin/python"
CLIENT_ID=41
LOG_DIR="logs/backfill"
mkdir -p "$LOG_DIR"

# Symbol → days back to fetch.
# Set to just past inception so IBKR doesn't waste time on pre-existence chunks.
declare -A DAYS_1D=(
    # Pre-2007 (IBKR has ~20yr for these)
    [IEF]=8800   # launched 2002-07-22
    [SHY]=8800
    [TLT]=8800
    [PFF]=7300   # launched 2007-03-26
    [XLU]=7300   # launched 1998; IBKR data starts ~2006
    [XLV]=7300
    [XLY]=7300
    [XOP]=7300   # launched 2006-06-22
    [XRT]=7300

    # 2011-2013 era
    [OIH]=5400   # restructured 2011-12-21
    [SMH]=5400   # restructured 2011-12-21
    [USMV]=5400  # launched 2011-10-21
    [SCHD]=5400  # launched 2011-10-21
    [INDA]=5300  # launched 2012-02-13
    [KWEB]=4800  # launched 2013-08-01
    [MTUM]=4900  # launched 2013-04-16
    [QUAL]=4800  # launched 2013-07-16

    # 2014-2016 era
    [ARKK]=4300  # launched 2014-10-31
    [CIBR]=4000  # launched 2015-07-08
    [XLRE]=3950  # launched 2015-10-07

    # 2018+
    [XLC]=3000   # launched 2018-06-18

    # 2024
    [IBIT]=900   # launched 2024-01-11
)

# 1h: all missing symbols use 5500d (IBKR's practical limit for ETF hourly data ~2011)
# Symbols that already have 1h (OIH, SCHD, SMH, USMV) are skipped below.
DAYS_1H=5500

MISSING_1D=(ARKK CIBR IBIT IEF INDA KWEB MTUM OIH PFF QUAL SCHD SHY SMH TLT USMV XLC XLRE XLU XLV XLY XOP XRT)
MISSING_1H=(ARKK CIBR IBIT IEF INDA KWEB MTUM PFF QUAL SHY TLT XLC XLRE XLU XLV XLY XOP XRT)

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
echo " ETF Backfill — 1d then 1h"
echo " $(date)"
echo "======================================"
echo

echo "=== Stage 1: 1d bars ==="
for sym in "${MISSING_1D[@]}"; do
    days=${DAYS_1D[$sym]:-7300}
    run_backfill "$sym" "1d" "$days"
done

echo
echo "=== Stage 2: 1h bars ==="
for sym in "${MISSING_1H[@]}"; do
    run_backfill "$sym" "1h" "$DAYS_1H"
done

echo
echo "======================================"
echo " Done: $total_stored total bars stored"
if [ ${#errors[@]} -gt 0 ]; then
    echo " Errors: ${errors[*]}"
fi
echo " $(date)"
echo "======================================"
