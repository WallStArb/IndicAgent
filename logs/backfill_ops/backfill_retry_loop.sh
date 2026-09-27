#!/bin/bash
# Retry wrapper for infrastructure_run_historical_pipeline.py --fetch-only.
# Handles IBKR Gateway's nightly IBC auto-restart (and any other transient
# disconnect) by re-invoking the same idempotent, gap-aware fetch command
# until the DB shows full 20yr depth across all 80 active equity symbols
# for 5m/15m/1h, and current depth for 1d.
#
# Lives under logs/backfill_ops/ (NOT /tmp/claude-*/scratchpad/) because a
# separate concurrent session observed the ephemeral scratchpad get wiped
# mid-run twice on 2026-07-05 (root cause unconfirmed) -- multi-day background
# job state belongs on the persistent project filesystem, not /tmp, regardless
# of the exact mechanism.
#
# Stall watchdog (added 2026-07-05): a live run hung for 25+ minutes with
# near-zero CPU and no timeout ever logged -- py-spy/strace confirmed the
# process was genuinely idle, not blocked, meaning ib_insync's own internal
# reqHistoricalDataAsync timeout didn't fire. This codebase already documents
# Python 3.14 asyncio.timeout()/wait_for reliability risk (see the
# nest_asyncio comment in src/providers/ibkr.py), so an in-process timeout
# fix alone can't be trusted as the sole safety net. This watchdog is
# external to that event loop: it polls real DB bar-count growth directly
# and force-kills the fetch process if nothing changes for too long,
# independent of whatever is or isn't firing inside the Python process.
#
# STALL_THRESHOLD_SEC (revised 2026-07-05 after a Fable review computed the real
# worst case from actual constants, not just the rate limiter): bars now persist
# per-chunk (see infrastructure_run_historical_pipeline.py's on_chunk callback),
# so DB growth is a true chunk-level heartbeat -- but a single unlucky chunk can
# still legitimately produce zero growth for: rate-limiter wait (up to
# _IBKR_HIST_WINDOW_S=600s) + 3 retry attempts each hitting the outer
# _HIST_REQUEST_TIMEOUT_SEC=90s timeout + 65s/130s backoffs between them =
# 600+90+65+90+130+90 = ~1065s worst case. 1500s gives ~40% margin above that
# without waiting unreasonably long on a genuine hang.
set -u
cd /home/bg/dev/indicagent

LOG_DIR=/home/bg/dev/indicagent/logs/backfill_ops
ATTEMPT=0
MAX_ATTEMPTS=50
STALL_THRESHOLD_SEC=1500
STALL_POLL_INTERVAL_SEC=120

check_gateway() {
  # [rca_analysis 2026-07-05, F6] ib.connect(timeout=10) relies on the same
  # asyncio timer machinery already flagged as unreliable elsewhere in this
  # investigation. `timeout 30` is an OS-level guard so a hang here can't stall
  # the whole retry loop before the watchdog even exists for this attempt.
  timeout 30 .venv/bin/python -c "
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_insync import IB
ib = IB()
try:
    ib.connect('127.0.0.1', 7497, clientId=40, timeout=10)
    ok = ib.isConnected()
    ib.disconnect()
    exit(0 if ok else 1)
except Exception:
    exit(1)
" 2>/dev/null
}

total_bar_count() {
  PGPASSWORD=postgres psql -tA -U postgres -h localhost -d indicagent -c \
    "SELECT count(*) FROM market_data_ohlcv WHERE timeframe IN ('5m','15m','1h','1d')" 2>/dev/null
}

# Runs as a background watchdog for a single fetch attempt. Polls total bar
# count every STALL_POLL_INTERVAL_SEC; if it hasn't moved for
# STALL_THRESHOLD_SEC while the fetch PID is still alive, kills it (SIGTERM,
# then SIGKILL if it doesn't die within 10s) so the outer loop relaunches.
watchdog() {
  local fetch_pid="$1"
  local watchdog_log="$2"
  local last_count=""
  local last_change_ts=$(date +%s)

  while kill -0 "$fetch_pid" 2>/dev/null; do
    sleep "$STALL_POLL_INTERVAL_SEC"
    if ! kill -0 "$fetch_pid" 2>/dev/null; then
      break
    fi
    current_count=$(total_bar_count)
    now=$(date +%s)
    if [ -z "$current_count" ]; then
      # DB unreachable this poll -- don't treat as a stall, just skip.
      continue
    fi
    if [ "$current_count" != "$last_count" ]; then
      last_count="$current_count"
      last_change_ts=$now
    else
      elapsed=$((now - last_change_ts))
      echo "$(date -u +%FT%TZ) WATCHDOG_NO_PROGRESS elapsed=${elapsed}s count=$current_count" >> "$watchdog_log"
      if [ "$elapsed" -ge "$STALL_THRESHOLD_SEC" ]; then
        echo "$(date -u +%FT%TZ) WATCHDOG_STALL_DETECTED killing pid $fetch_pid after ${elapsed}s with no bar growth (count=$current_count)" >> "$watchdog_log"
        kill "$fetch_pid" 2>/dev/null
        sleep 10
        if kill -0 "$fetch_pid" 2>/dev/null; then
          echo "$(date -u +%FT%TZ) WATCHDOG_SIGKILL pid $fetch_pid still alive after SIGTERM" >> "$watchdog_log"
          kill -9 "$fetch_pid" 2>/dev/null
        fi
        break
      fi
    fi
  done
}

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
  ATTEMPT=$((ATTEMPT+1))
  echo "=== ATTEMPT $ATTEMPT at $(date -u +%FT%TZ) ==="

  gw_wait=0
  until check_gateway; do
    gw_wait=$((gw_wait+1))
    if [ $gw_wait -gt 24 ]; then
      echo "GATEWAY_UNREACHABLE after $((gw_wait*5))s, giving up this attempt"
      break
    fi
    sleep 5
  done

  if ! check_gateway; then
    echo "GATEWAY_STILL_DOWN, sleeping 60s before retry"
    sleep 60
    continue
  fi

  RUN_LOG="$LOG_DIR/backfill_run_attempt${ATTEMPT}.log"
  WATCHDOG_LOG="$LOG_DIR/backfill_watchdog_attempt${ATTEMPT}.log"
  echo "Launching fetch attempt $ATTEMPT -> $RUN_LOG (watchdog: $WATCHDOG_LOG)"

  # -u: unbuffered stdout/stderr. [rca_analysis 2026-07-05, F6] block-buffered
  # output meant a SIGTERM/SIGKILL discarded whatever hadn't been flushed yet,
  # leaving blind post-mortems (attempt logs showing only 4 startup lines
  # despite hours of runtime).
  .venv/bin/python -u -m scripts.infrastructure.backfill.infrastructure_run_historical_pipeline \
    --client-id 40 --fetch-only --timeframes 5m,15m,1h,1d \
    > "$RUN_LOG" 2>&1 &
  FETCH_PID=$!

  watchdog "$FETCH_PID" "$WATCHDOG_LOG" &
  WATCHDOG_PID=$!

  wait "$FETCH_PID"
  rc=$?

  # Fetch process exited (naturally or via watchdog kill) -- stop the watchdog too.
  kill "$WATCHDOG_PID" 2>/dev/null
  wait "$WATCHDOG_PID" 2>/dev/null

  echo "Attempt $ATTEMPT exited rc=$rc"
  tail -5 "$RUN_LOG"
  if [ -f "$WATCHDOG_LOG" ] && grep -q "WATCHDOG_STALL_DETECTED" "$WATCHDOG_LOG"; then
    echo "Attempt $ATTEMPT was killed by the stall watchdog -- see $WATCHDOG_LOG"
  fi

  if [ $rc -eq 0 ] && grep -q "Backfill complete." "$RUN_LOG" && ! grep -q "skipped (qualify failed)" "$RUN_LOG"; then
    echo "CLEAN_COMPLETION on attempt $ATTEMPT"
    exit 0
  fi
done

echo "MAX_ATTEMPTS_REACHED without completion"
exit 1
