#!/bin/bash
# Todo 449: one 5m backfill lane for names without intraday history, under a retry loop and an
# external stall watchdog. Adapted from backfill_retry_loop.sh in this directory (same rationale:
# the nightly 23:59 UTC gateway restart drops the socket, and in-process timeouts have hung before).
#
# Usage: intraday_5m_lane.sh <lane_name> <client_id> <symbols_csv_file>
#
# The fetch is gap-aware with ON CONFLICT DO NOTHING, and a finished (symbol, tf) is marked
# complete, so each retry skips what landed. A pass is clean only when it exits 0, prints
# "Backfill complete." and skipped no symbol: the script exits 0 even when a reconnect failure
# skipped names outright, so the skip lines are checked here.
#
# Heartbeat: the lane's own 5m row count, so one lane's stall is not masked by another's writes.
# STALL_THRESHOLD_SEC covers a worst-case chunk (rate-limiter wait + 3 timed-out retries with
# backoff, ~1065s, see backfill_retry_loop.sh).
set -u
cd /home/bg/dev/indicagent

# Pause marker (todo 462): while this file exists the lane does not start. Delete it, then relaunch
# `nohup bash logs/backfill_ops/intraday_chain.sh` (gap-aware; the htf lane finishes first).
PAUSE_MARKER=/home/bg/dev/indicagent/logs/backfill_ops/PAUSE_5M
if [ -e "$PAUSE_MARKER" ]; then
  echo "PAUSED $1: $PAUSE_MARKER exists ($(head -1 "$PAUSE_MARKER")); not starting"
  exit 0
fi

LANE="$1"
CLIENT_ID="$2"
SYMBOLS=$(tr -d '[:space:]' < "$3")
LOG_DIR=/home/bg/dev/indicagent/logs/backfill_ops/intraday_5m
mkdir -p "$LOG_DIR"
MAX_ATTEMPTS=50
STALL_THRESHOLD_SEC=1500
STALL_POLL_INTERVAL_SEC=300

check_gateway() {
  timeout 30 .venv/bin/python -c "
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_async import IB
ib = IB()
try:
    ib.connect('127.0.0.1', 7497, clientId=$CLIENT_ID, timeout=10)
    ok = ib.isConnected()
    ib.disconnect()
    exit(0 if ok else 1)
except Exception:
    exit(1)
" 2>/dev/null
}

lane_bar_count() {
  PGPASSWORD=postgres psql -tA -U postgres -h localhost -d indicagent -c \
    "SELECT count(*) FROM market_data_ohlcv WHERE timeframe = '5m'
     AND symbol = ANY(string_to_array('$SYMBOLS', ','))" 2>/dev/null
}

watchdog() {
  local fetch_pid="$1" watchdog_log="$2" last_count="" last_change_ts
  last_change_ts=$(date +%s)
  while kill -0 "$fetch_pid" 2>/dev/null; do
    sleep "$STALL_POLL_INTERVAL_SEC"
    kill -0 "$fetch_pid" 2>/dev/null || break
    local current_count now
    current_count=$(lane_bar_count)
    now=$(date +%s)
    [ -z "$current_count" ] && continue
    echo "$(date -u +%FT%TZ) count=$current_count" >> "$watchdog_log"
    if [ "$current_count" != "$last_count" ]; then
      last_count="$current_count"
      last_change_ts=$now
    elif [ $((now - last_change_ts)) -ge "$STALL_THRESHOLD_SEC" ]; then
      echo "$(date -u +%FT%TZ) WATCHDOG_STALL_DETECTED killing pid $fetch_pid" >> "$watchdog_log"
      kill "$fetch_pid" 2>/dev/null
      sleep 10
      kill -0 "$fetch_pid" 2>/dev/null && kill -9 "$fetch_pid" 2>/dev/null
      break
    fi
  done
}

for ATTEMPT in $(seq 1 $MAX_ATTEMPTS); do
  echo "=== $LANE ATTEMPT $ATTEMPT at $(date -u +%FT%TZ) ==="
  gw_wait=0
  until check_gateway; do
    gw_wait=$((gw_wait+1))
    [ $gw_wait -gt 24 ] && break
    sleep 5
  done
  if ! check_gateway; then
    echo "GATEWAY_STILL_DOWN, sleeping 60s"
    sleep 60
    continue
  fi

  RUN_LOG="$LOG_DIR/${LANE}_attempt${ATTEMPT}.log"
  WATCHDOG_LOG="$LOG_DIR/${LANE}_watchdog_attempt${ATTEMPT}.log"
  .venv/bin/python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py \
    --dimension backfill --timeframes 5m --real-bars-only --client-id "$CLIENT_ID" --symbols "$SYMBOLS" \
    > "$RUN_LOG" 2>&1 &
  FETCH_PID=$!
  watchdog "$FETCH_PID" "$WATCHDOG_LOG" &
  WATCHDOG_PID=$!
  wait "$FETCH_PID"
  rc=$?
  kill "$WATCHDOG_PID" 2>/dev/null
  wait "$WATCHDOG_PID" 2>/dev/null

  echo "$LANE attempt $ATTEMPT exited rc=$rc at $(date -u +%FT%TZ)"
  tail -5 "$RUN_LOG"
  if [ $rc -eq 0 ] && grep -q "Backfill complete." "$RUN_LOG" && ! grep -q "skipped (" "$RUN_LOG"; then
    echo "CLEAN_COMPLETION $LANE on attempt $ATTEMPT"
    exit 0
  fi
done

echo "MAX_ATTEMPTS_REACHED $LANE"
exit 1
