#!/usr/bin/env bash
# ops_regime_monitor.sh — instrumented health check for regime_writer --refit.
# Renaissance principle: silent failures are worse than loud crashes. When the
# refit wedges, capture EVIDENCE (worker stacks + DB locks + RSS) before acting,
# so the root cause is diagnosable instead of guessed.
#
# Verdict (last line): RUNNING_HEALTHY | STALLED_RESTARTED | STALLED_ESCALATE | COMPLETED | DEAD
# Side effects on stall: writes logs/regime_wedge_diag_<ts>.txt, bumps logs/regime_wedge_count,
#   restarts refit if wedge_count < 2 (else escalates — do NOT blindly loop).

set -u
cd /home/bg/dev/indicagent
LOG=logs/regime_writer.log
WEDGE_COUNT_FILE=logs/regime_wedge_count
if [[ -z "${SUDO_PASS:-}" ]]; then
  echo "SUDO_PASS not set in environment (expected export in ~/.bashrc) -- refusing to run" >&2
  exit 1
fi
PYSPY=/home/bg/.local/bin/py-spy

main_pid() { pgrep -f "regime_writer.py --refit" | head -1; }
worker_pids() { pgrep -f "regime_writer.py --refit" | tail -n +2; }

# --- is the process alive at all? ---
MPID="$(main_pid)"
if [[ -z "$MPID" ]]; then
  # did it finish cleanly?
  if tail -n 200 "$LOG" 2>/dev/null | grep -q "regime_writer.done\|regime_writer.refit_complete\|all.*symbol.*done"; then
    echo "COMPLETED"
    exit 0
  fi
  echo "DEAD — no regime_writer process and no completion event in log; inspect $LOG"
  exit 0
fi

# --- worker CPU advancement over ~12s ---
# Use `ps -o times=` (cumulative CPU seconds) — robust vs /proc/stat field parsing.
# Compare the SUM across workers: if it doesn't grow, no worker is computing.
sample_cpu() { local s=0; for p in $(worker_pids); do t=$(ps -o times= -p "$p" 2>/dev/null | tr -d ' '); s=$((s + ${t:-0})); done; echo "$s"; }
CPU0="$(sample_cpu)"; sleep 12; CPU1="$(sample_cpu)"
CPU_ADVANCED=0
if [[ $((CPU1 - CPU0)) -gt 0 ]]; then CPU_ADVANCED=1; fi

# --- log freshness: age of last symbol_tf_done ---
LAST_TS="$(grep -oE '"event": "regime_writer.symbol_tf_done".*"timestamp": "[^"]*"' "$LOG" 2>/dev/null | tail -1 | grep -oE '2026-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}')"
LOG_STALE=0
if [[ -n "$LAST_TS" ]]; then
  NOW_EPOCH=$(date -u +%s)
  LAST_EPOCH=$(date -u -d "$LAST_TS" +%s 2>/dev/null || echo 0)
  AGE=$((NOW_EPOCH - LAST_EPOCH))
  # stale if no symbol completion in >15 min AND CPU not advancing
  if [[ $AGE -gt 900 && $CPU_ADVANCED -eq 0 ]]; then LOG_STALE=1; fi
fi

# --- RSS (track the suspected memory-accumulation precursor) ---
RSS_KB=$(ps -p "$MPID" -o rss= 2>/dev/null | tr -d ' ')

if [[ $CPU_ADVANCED -eq 1 ]]; then
  echo "RUNNING_HEALTHY main_pid=$MPID rss_mb=$((RSS_KB/1024)) last_done_ago_s=${AGE:-na} wedge_count=$(cat $WEDGE_COUNT_FILE 2>/dev/null || echo 0)"
  exit 0
fi

# ================= STALLED — capture evidence =================
TS=$(date -u +%Y%m%dT%H%M%SZ)
DIAG=logs/regime_wedge_diag_${TS}.txt
{
  echo "=== regime_wedge_diag $TS ==="
  echo "main_pid=$MPID rss_mb=$((RSS_KB/1024)) last_symbol_done_ts=$LAST_TS last_done_ago_s=${AGE:-na}"
  echo ""
  echo "=== main process stack ==="
  echo "$SUDO_PASS" | /usr/bin/sudo.ws -S "$PYSPY" dump --pid "$MPID" 2>/dev/null
  echo ""
  echo "=== worker stacks ==="
  for p in $(worker_pids); do
    echo "--- worker $p ---"
    echo "$SUDO_PASS" | /usr/bin/sudo.ws -S "$PYSPY" dump --pid "$p" 2>/dev/null
  done
  echo ""
  echo "=== pg_stat_activity (indicagent) ==="
  PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
    SELECT pid, state, wait_event_type, wait_event,
           extract(epoch from now()-query_start)::int AS age_s, left(query,70) AS query
    FROM pg_stat_activity WHERE datname='indicagent' ORDER BY query_start;"
  echo ""
  echo "=== blocking chains ==="
  PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
    SELECT blocked.pid, blocking.pid, left(blocking.query,50)
    FROM pg_stat_activity blocked, pg_stat_activity blocking
    WHERE blocking.pid = ANY(pg_blocking_pids(blocked.pid));"
} > "$DIAG" 2>&1

WEDGE_COUNT=$(($(cat $WEDGE_COUNT_FILE 2>/dev/null || echo 0) + 1))
echo "$WEDGE_COUNT" > "$WEDGE_COUNT_FILE"

if [[ $WEDGE_COUNT -lt 2 ]]; then
  echo "STALLED_RESTARTED wedge_count=$WEDGE_COUNT diag=$DIAG — killing group and restarting refit"
  pkill -f "regime_writer.py --refit"; sleep 4
  nohup .venv/bin/python services/regime_writer.py --refit --workers 12 >> "$LOG" 2>&1 &
  echo "restarted pid $!"
else
  echo "STALLED_ESCALATE wedge_count=$WEDGE_COUNT diag=$DIAG — wedged twice, do NOT auto-restart; root-cause via /gsd-debug using $DIAG"
fi
exit 0
