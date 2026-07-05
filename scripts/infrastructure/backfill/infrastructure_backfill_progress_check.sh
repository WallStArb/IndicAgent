#!/usr/bin/env bash
#
# infrastructure_backfill_progress_check.sh — one-shot health check for the
# IBKR historical backfill retry loop (backfill_retry_loop.sh ->
# infrastructure_run_historical_pipeline.py).
#
# Reports: process liveness (flags stray /tmp/claude-* duplicates without
# killing them), market_data_ohlcv bar-count deltas vs the last run of this
# script, fetch process CPU time + wchan, watchdog stall detections, and
# whether the current attempt log shows completion or a fetch error.
#
# Baseline bar counts persist between runs in $STATE_FILE so deltas are
# automatic across separate invocations (e.g. one every 10 minutes).

set -uo pipefail

OPS_DIR="logs/backfill_ops"
STATE_FILE="$OPS_DIR/.progress_baseline"

echo "=== process ==="
ps aux | grep -E "backfill_retry_loop\.sh|infrastructure_run_historical_pipeline" | grep -v grep
STRAY=$(ps aux | grep "infrastructure_run_historical_pipeline" | grep "/tmp/claude" | grep -v grep || true)
if [ -n "$STRAY" ]; then
    echo "!! STRAY /tmp/claude-* PROCESS FOUND -- do not kill, ask the user first:"
    echo "$STRAY"
fi

FETCH_PID=$(ps aux | grep "infrastructure_run_historical_pipeline" | grep -v grep | awk '{print $2}' | head -1)

echo ""
echo "=== bar counts (market_data_ohlcv) ==="
COUNTS=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tA -c "
SELECT timeframe, count(*) FROM market_data_ohlcv WHERE timeframe IN ('5m','15m','1h','1d') GROUP BY timeframe ORDER BY timeframe;
")
echo "$COUNTS"

if [ -f "$STATE_FILE" ]; then
    echo ""
    echo "=== delta vs last check ==="
    join -t'|' -a1 -a2 -e0 -o0,1.2,2.2 <(sort "$STATE_FILE") <(echo "$COUNTS" | sort) | \
        awk -F'|' '{printf "%-4s %+d (was %s, now %s)\n", $1, $3-$2, $2, $3}'
else
    echo "(no prior baseline -- this is the first check)"
fi
echo "$COUNTS" > "$STATE_FILE"

if [ -n "$FETCH_PID" ]; then
    echo ""
    echo "=== fetch process CPU/state ==="
    ps -o pid,stat,etime,time,pcpu,wchan:20,cmd -p "$FETCH_PID"
fi

echo ""
echo "=== watchdog stalls ==="
STALL=$(grep "WATCHDOG_STALL_DETECTED" "$OPS_DIR"/backfill_watchdog_attempt*.log 2>/dev/null)
if [ -n "$STALL" ]; then
    echo "$STALL"
else
    echo "none"
fi

echo ""
echo "=== current attempt log ==="
LOG=$(ls -t "$OPS_DIR"/backfill_run_attempt*.log 2>/dev/null | head -1)
if [ -n "$LOG" ]; then
    echo "log: $LOG"
    grep -E "Backfill complete\.|FETCH ERROR" "$LOG" || true
    tail -6 "$LOG"
else
    echo "no attempt log found"
fi
