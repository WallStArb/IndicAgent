# Guarded heavy runs: host gate (memory-fault signatures, DIMM temperature) and a process-group
# watchdog. Shared by family10_launch.sh, family10_block2_rerun.sh and corpus_pilot.sh; sourced, not executed.
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PY=$REPO/.venv/bin/python
SCRATCH=${GUARDED_RUN_DIR:-$REPO/logs/guarded_run}   # memtester_clean, worktrees and outputs
STATUS=$REPO/logs/family10_run_status.txt
TEMPLOG=$REPO/logs/family10_dimm_temp.log
WORKERS=${WORKERS:-4}         # owner raises to 8 once airflow is fixed and a run stays under 85C
mkdir -p "$SCRATCH"
GATE_C=60                     # start only if both DIMM sensors read this or less
STOP_C=92; RESUME_C=80; KILL_C=100; MAX_PAUSE_S=1200
MEM_FLOOR_KB=$((40 * 1024 * 1024))   # 40 GiB of MemAvailable, compared in kB (exact GiB in the message)

log()  { echo "$(date -u +%FT%TZ) $*" >> "$STATUS"; }
fail() { log "ABORT $*"; exit 3; }

dimm_temps() {   # millidegrees of every spd5118 sensor, one per line
  local h f
  for h in /sys/class/hwmon/hwmon*/; do
    [ "$(cat "$h/name" 2>/dev/null)" = spd5118 ] || continue
    for f in "$h"temp*_input; do cat "$f"; done
  done
}
dimm_max_c() { dimm_temps | sort -n | tail -1 | awk '{printf "%d", $1/1000}'; }

mem_available_kb() { awk '/^MemAvailable:/{print $2}' "${MEMINFO:-/proc/meminfo}"; }

mem_gate() {     # MemAvailable in kB against the floor in kB; the message gives the exact GiB
  local kb; kb=$(mem_available_kb)
  [ "${kb:-0}" -ge "$MEM_FLOOR_KB" ] || fail "only $(awk -v k="${kb:-0}" 'BEGIN{printf "%.2f", k/1048576}') GiB available, need $((MEM_FLOOR_KB / 1048576)) GiB"
}

host_gate() {    # refuse to start on a host that is not demonstrably healthy
  [ -f "$SCRATCH/memtester_clean" ] || fail "no memtester_clean file (operator records a clean pass)"
  pgrep -x memtester >/dev/null && fail "memtester still running"
  pgrep -f 'python.*(run_spec|e17_null_battery|ic_measure|ops_corpus|ops_bar_nightly|repro_frozen)' >/dev/null && fail "another heavy job is live"
  [ "$(cat /proc/sys/kernel/tainted)" = "0" ] || fail "kernel tainted: $(cat /proc/sys/kernel/tainted)"
  journalctl -k -b --no-pager 2>/dev/null | grep -q -E 'segfault|Bad page|Bad swap|general protection' && fail "kernel log shows memory-fault signatures this boot"
  local n; n=$(dimm_temps | wc -l); [ "$n" -ge 2 ] || fail "expected 2 spd5118 sensors, found $n"
  local t; t=$(dimm_max_c); [ "$t" -le "$GATE_C" ] || fail "DIMM at ${t}C, gate ${GATE_C}C"
  mem_gate
}

# run_guarded <outfile> <cmd...>: runs cmd in its own process group with the temperature
# watchdog; returns cmd's exit code, or 143 when the watchdog killed it (ABORT already logged).
run_guarded() {
  local out=$1; shift
  setsid "$@" > "$out" 2>&1 &
  local pid=$!; local pgid=""; local i
  for i in 1 2 3 4 5; do pgid=$(ps -o pgid= -p "$pid" | tr -d ' '); [ -n "$pgid" ] && break; sleep 0.2; done
  [ -n "$pgid" ] || { log "ABORT cannot read pgid of $pid"; kill "$pid" 2>/dev/null; return 1; }
  local paused_at=0 killed=0 t now
  while kill -0 "$pid" 2>/dev/null; do
    t=$(dimm_max_c); now=$(date +%s)
    rss_mb=$(ps -eo pgid=,rss= | awk -v p="$pgid" '$1==p{s+=$2} END{printf "%d", s/1024}')
    echo "$(date -u +%FT%TZ) pid=$pid max_c=$t rss_mb=$rss_mb paused=$([ $paused_at -gt 0 ] && echo 1 || echo 0)" >> "$TEMPLOG"
    if [ "$t" -ge "$KILL_C" ] || { [ $paused_at -gt 0 ] && [ $((now - paused_at)) -gt $MAX_PAUSE_S ]; }; then
      kill -CONT -- "-$pgid" 2>/dev/null; kill -TERM -- "-$pgid" 2>/dev/null
      log "ABORT watchdog killed pgid $pgid at ${t}C (paused_at=$paused_at)"; killed=1; break
    elif [ "$t" -ge "$STOP_C" ] && [ $paused_at -eq 0 ]; then
      kill -STOP -- "-$pgid"; paused_at=$now; log "watchdog STOP at ${t}C"
    elif [ "$t" -le "$RESUME_C" ] && [ $paused_at -gt 0 ]; then
      kill -CONT -- "-$pgid"; paused_at=0; log "watchdog CONT at ${t}C"
    fi
    sleep 20
  done
  [ $killed -eq 1 ] && { wait "$pid" 2>/dev/null; return 143; }
  wait "$pid"
}

# verdict_preflight: refuse when member 1d verdicts are older than the d2_landed freshness window
# (APR threshold.bar_integrity.report_max_age_hours, read by verdict_gate.load_report_max_age_hours).
# Read-only. The producer of dead members' verdicts is ops_member_verdicts_1d.py (no timer; the
# 06:00Z bar-reconciliation audit judges active names only), so a pause of more than the window
# between its last run and a pin gate refuses the run (pilot 7c5612f0, 2026-11-24: 11,350 of 12,857).
verdict_preflight() {
  local out limit stale total
  out=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAF' ' -c "
    WITH m AS (SELECT DISTINCT symbol || '|1d' AS subject FROM universe_membership),
         v AS (SELECT subject, max(evaluated_at) AS at FROM integrity_monitor
               WHERE monitor_type = 'bar_integrity' AND metric_name = 'proven_start_1d'
                 AND subject IN (SELECT subject FROM m) GROUP BY subject),
         l AS (SELECT config_value::float AS h FROM config_state
               WHERE config_key = 'threshold.bar_integrity.report_max_age_hours')
    SELECT (SELECT h FROM l),
           count(*) FILTER (WHERE v.at IS NULL OR v.at < now() - (SELECT h FROM l) * interval '1 hour'),
           count(*)
    FROM m LEFT JOIN v USING (subject)") || fail "verdict preflight query failed"
  read -r limit stale total <<< "$out"
  [ -n "${stale:-}" ] || fail "verdict preflight read nothing"
  [ "$stale" -eq 0 ] || fail "$stale of $total member 1d verdicts are older than ${limit} h; refresh: cd $REPO && setsid -f $PY scripts/ops/bars/ops_member_verdicts_1d.py --apply > logs/member_verdicts_1d_\$(date -u +%F).out 2>&1 (about 1 h), then relaunch"
}
