#!/usr/bin/env bash
# ops_pipeline_monitor.sh — health check for ops_corpus_pipeline_run.sh.
# Verdict (last line): PIPELINE_RUNNING <step> | STEP_STALLED <step> | COMPLETED | FAILED | DEAD
# On stall: captures py-spy stacks + DB state to logs/pipeline_wedge_diag_<ts>.txt and ESCALATES
#   (does NOT auto-restart — restarting a multi-hour pipeline mid-run wastes progress).
set -u
cd /home/bg/dev/indicagent
MAIN_LOG=logs/corpus_pipeline_run.log
SUDO_PASS="${SUDO_PASS:?set via environment (see ~/.claude memory user_sudo_password.md) — do not hardcode here}"
PYSPY=/home/bg/.local/bin/py-spy
SERVICE_PATTERN='services/(backfill_feature_factory|regime_writer|forward_return_writer|ic_engine|ensemble_trainer|alpha_publisher)\.py'

pg() { PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "$1" 2>/dev/null; }

orch_alive() { pgrep -f "ops_corpus_pipeline_run.sh" >/dev/null 2>&1; }

if ! orch_alive; then
  # did it finish?
  if tail -n 50 "$MAIN_LOG" 2>/dev/null | grep -qE "Pipeline (complete|Done)|all 6 steps"; then
    echo "COMPLETED — verify row counts then commit planning docs"
  elif tail -n 50 "$MAIN_LOG" 2>/dev/null | grep -qiE "error|failed|aborted|traceback"; then
    echo "FAILED — inspect $MAIN_LOG tail"; tail -n 15 "$MAIN_LOG" 2>/dev/null
  else
    echo "DEAD — orchestrator gone, no completion marker; inspect $MAIN_LOG"
  fi
  exit 0
fi

# current step
STEP_LINE=$(grep -E "Step [0-9]/6" "$MAIN_LOG" 2>/dev/null | tail -1)
STEP=$(echo "$STEP_LINE" | grep -oE "Step [0-9]/6[^ ]* — [a-z_]+" | head -1)
# last step status line age
LAST_TS=$(grep -oE "^[A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9 ]+:([0-9]{2}:){2}[0-9]{2}" "$MAIN_LOG" 2>/dev/null | tail -1)

# sample CPU of the active compute python procs — one `ps` call for all matched PIDs,
# not one fork per PID.
sample_cpu() {
  local pids s
  pids=$(pgrep -f "$SERVICE_PATTERN" | paste -sd, -)
  [[ -z "$pids" ]] && { echo 0; return; }
  s=$(ps -o times= -p "$pids" 2>/dev/null | tr -d ' ' | paste -sd+ - | bc 2>/dev/null)
  echo "${s:-0}"
}

# DB-write progress fallback: catches phases where the writer is I/O-bound on
# execute_batch (network round-trip to Postgres) rather than CPU-bound, so
# client-side CPU ticks don't advance even though rows are landing (e.g.
# regime_writer's main thread blocked in psycopg2 execute_batch — a single
# symbol/TF batch write can take minutes, so a row-count delta over a short
# poll window is usually 0 even mid-write). An active (non-idle) backend query
# present at both sample points is direct evidence the writer is doing DB work.
db_active_query() { pg "SELECT string_agg(pid::text,',') FROM pg_stat_activity WHERE datname='indicagent' AND state='active' AND query NOT ILIKE '%pg_stat_activity%';"; }

CPU0=$(sample_cpu); DBACT0=$(db_active_query)

# Fast path: DB write already active on the first sample — no need to burn a 10s
# sleep proving what we already know.
if [[ -n "$DBACT0" ]]; then
  FV=$(pg "SELECT count(*) FROM feature_vectors;")
  echo "PIPELINE_RUNNING step='${STEP:-?}' feature_vectors=${FV} db_active=${DBACT0}"
  exit 0
fi

sleep 10
CPU1=$(sample_cpu); DBACT1=$(db_active_query)

if (( CPU1 - CPU0 > 0 )) || [[ -n "$DBACT1" ]]; then
  FV=$(pg "SELECT count(*) FROM feature_vectors;")
  echo "PIPELINE_RUNNING step='${STEP:-?}' feature_vectors=${FV} cpu_delta=$((CPU1-CPU0)) db_active=${DBACT1:-none}"
  exit 0
fi

# stalled — capture evidence
FV=$(pg "SELECT count(*) FROM feature_vectors;")
TS=$(date -u +%Y%m%dT%H%M%SZ)
DIAG=logs/pipeline_wedge_diag_${TS}.txt
{
  echo "=== pipeline_wedge_diag $TS ==="
  echo "step=$STEP feature_vectors=$FV last_mainlog_ts=$LAST_TS"
  echo ""; echo "=== main log tail ==="; tail -n 20 "$MAIN_LOG" 2>/dev/null
  echo ""; echo "=== active python stacks ==="
  for p in $(pgrep -f "$SERVICE_PATTERN"); do
    echo "--- pid $p ($(ps -o args= -p $p 2>/dev/null | cut -c1-60)) ---"
    echo "$SUDO_PASS" | /usr/bin/sudo.ws -S "$PYSPY" dump --pid "$p" 2>/dev/null
  done
  echo ""; echo "=== pg_stat_activity ==="
  PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT pid,state,wait_event_type,extract(epoch from now()-query_start)::int AS age_s,left(query,60) FROM pg_stat_activity WHERE datname='indicagent' AND state<>'idle';"
} > "$DIAG" 2>&1
echo "STEP_STALLED '${STEP:-?}' diag=$DIAG — do NOT auto-restart; root-cause via the diag file (likely the regime step-2 wedge recurring)"
exit 0
