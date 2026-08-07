#!/usr/bin/env bash
# Samples client-43 OHLCV backfill completion (all 5 timeframes present per newly-added
# instrument) and appends one row to a CSV so average per-symbol backfill duration can be
# tracked over the run. Ad-hoc measurement tool for the 2026-08-05/06 universe expansion
# backfill (todo 259) -- not a permanent service, safe to delete once client-43 finishes.
#
# Backs out the nightly IBKR gateway blackout (8pm ET, ~4h) from elapsed time so
# avg_seconds_per_symbol isn't inflated by downtime the process spends idle/reconnecting.
# Uses America/New_York for the boundary so DST transitions don't need manual adjustment.
#
# Usage: ./infrastructure_client43_progress_sample.sh
set -euo pipefail

PID=3159680
LOG_CSV="/home/bg/dev/indicagent/logs/backfill_ops/client43_completion_samples.csv"
BLACKOUT_HOURS=4

if [ ! -f "$LOG_CSV" ]; then
    echo "sampled_at_utc,elapsed_seconds,complete,partial,not_started,total,avg_seconds_per_symbol,active_seconds,active_avg_seconds_per_symbol" > "$LOG_CSV"
fi

ELAPSED_SECONDS=$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ' || echo "")
if [ -z "$ELAPSED_SECONDS" ]; then
    echo "process $PID not running -- backfill has stopped or finished" >&2
    exit 1
fi

# Sum full/partial 8pm-ET blackout windows that fall within [start, now).
NOW_EPOCH=$(date +%s)
START_EPOCH=$((NOW_EPOCH - ELAPSED_SECONDS))
BLACKOUT_SECONDS=0
DAY=$(TZ=America/New_York date -d "@${START_EPOCH}" +%Y-%m-%d)
BOUND_EPOCH=$(TZ=America/New_York date -d "${DAY} 20:00" +%s)
if [ "$BOUND_EPOCH" -lt "$START_EPOCH" ]; then
    BOUND_EPOCH=$(TZ=America/New_York date -d "${DAY} 20:00 +1 day" +%s)
fi
while [ "$BOUND_EPOCH" -lt "$NOW_EPOCH" ]; do
    BLACKOUT_END=$((BOUND_EPOCH + BLACKOUT_HOURS * 3600))
    if [ "$BLACKOUT_END" -le "$NOW_EPOCH" ]; then
        BLACKOUT_SECONDS=$((BLACKOUT_SECONDS + BLACKOUT_HOURS * 3600))
    else
        BLACKOUT_SECONDS=$((BLACKOUT_SECONDS + NOW_EPOCH - BOUND_EPOCH))
    fi
    BOUND_EPOCH=$((BOUND_EPOCH + 86400))
done
ACTIVE_SECONDS=$((ELAPSED_SECONDS - BLACKOUT_SECONDS))

read -r COMPLETE PARTIAL NOT_STARTED TOTAL <<< "$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -A -F' ' -c "
WITH new_syms AS (
  SELECT symbol FROM instruments WHERE is_active = true AND created_at >= '2026-08-05'
),
tf_counts AS (
  SELECT s.symbol, count(DISTINCT o.timeframe) AS n_tf
  FROM new_syms s LEFT JOIN market_data_ohlcv o ON o.symbol = s.symbol
  GROUP BY s.symbol
)
SELECT
  count(*) FILTER (WHERE n_tf >= 5),
  count(*) FILTER (WHERE n_tf > 0 AND n_tf < 5),
  count(*) FILTER (WHERE n_tf = 0),
  count(*)
FROM tf_counts;
")"

SAMPLED_AT=$(date -u -d "@${NOW_EPOCH}" +%Y-%m-%dT%H:%M:%SZ)

if [ "$COMPLETE" -gt 0 ]; then
    AVG_SEC=$(echo "scale=1; $ELAPSED_SECONDS / $COMPLETE" | bc)
    ACTIVE_AVG_SEC=$(echo "scale=1; $ACTIVE_SECONDS / $COMPLETE" | bc)
else
    AVG_SEC="NA"
    ACTIVE_AVG_SEC="NA"
fi

echo "${SAMPLED_AT},${ELAPSED_SECONDS},${COMPLETE},${PARTIAL},${NOT_STARTED},${TOTAL},${AVG_SEC},${ACTIVE_SECONDS},${ACTIVE_AVG_SEC}" | tee -a "$LOG_CSV"
