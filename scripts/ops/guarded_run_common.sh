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
HWMON_ROOT=${DIMM_HWMON_ROOT:-/sys/class/hwmon}   # a test points this at a fake tree
POLL_S=${POLL_S:-20}                              # watchdog poll interval (seconds)
MAX_SENSOR_MISSES=3           # consecutive polls without two readable DIMM sensors before the run is killed
KILL_GRACE_S=30               # seconds between TERM and KILL when the group will not exit
MEM_FLOOR_KB=$((40 * 1024 * 1024))   # 40 GiB of MemAvailable, compared in kB (exact GiB in the message)
WINDOW_START_H=1; WINDOW_END_H=5     # UTC hours [start, end) refused for a start: the 04:40Z Alpaca nightly's lead-in
HEAVY_JOB_RE='python.*(run_spec|e17_null_battery|ic_measure|ops_corpus|ops_bar_nightly|ops_member_verdicts_1d|repro_frozen|services\.corpus_rerun|backfill_feature_factory|ic_sweep_recorder)'

log()  { echo "$(date -u +%FT%TZ) $*" >> "$STATUS"; }
fail() { log "ABORT $*"; exit 3; }

dimm_temps() {   # millidegrees of every readable spd5118 sensor, one per line; an empty or non-numeric read is dropped
  local h f
  for h in "$HWMON_ROOT"/hwmon*/; do
    [ "$(cat "$h/name" 2>/dev/null)" = spd5118 ] || continue
    for f in "$h"temp*_input; do cat "$f" 2>/dev/null; done
  done | grep -E '^[0-9]+$'
}
# Hottest DIMM in whole degrees C. Prints nothing and returns 1 unless both sensors give a number, so a lost
# sensor can never read as "cool" (an empty string would make every `[ "$t" -ge N ]` test false).
dimm_max_c() {
  local temps; temps=$(dimm_temps)
  [ "$(printf '%s\n' "$temps" | grep -c .)" -ge 2 ] || return 1
  printf '%s\n' "$temps" | sort -n | tail -1 | awk '{printf "%d", $1/1000}'
}

mem_available_kb() { awk '/^MemAvailable:/{print $2}' "${MEMINFO:-/proc/meminfo}"; }

mem_gate() {     # MemAvailable in kB against the floor in kB; the message gives the exact GiB
  local kb; kb=$(mem_available_kb)
  [ "${kb:-0}" -ge "$MEM_FLOOR_KB" ] || fail "only $(awk -v k="${kb:-0}" 'BEGIN{printf "%.2f", k/1048576}') GiB available, need $((MEM_FLOOR_KB / 1048576)) GiB"
}

# window_gate: refuse a start inside the nightly window, UTC hours [WINDOW_START_H, WINDOW_END_H); NOW_H injects the hour.
# The timer cluster after it (derivations 05:20 and 05:45Z, audits 06:00Z, dividends 06:30Z) is held off by hold_timers, which
# every counted launcher calls, so one window serves them all.
window_gate() {
  local h=${NOW_H:-$(date -u +%H)}; h=$((10#$h))
  { [ "$h" -lt "$WINDOW_START_H" ] || [ "$h" -ge "$WINDOW_END_H" ]; } || fail "inside the nightly window (${WINDOW_START_H}:00 to ${WINDOW_END_H}:00Z)"
}

blocking_timer_units() {   # the timers a corpus run quiesces (APR infra.corpus_rerun.blocking_timers), one per line
  PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "select config_value from config_state where config_key='infra.corpus_rerun.blocking_timers'" \
    | "$PY" -c 'import json,sys; print("\n".join(json.load(sys.stdin)))'
}

# timers_gate: refuse while the service of any blocking timer is running (a timer firing now rewrites the bars under the run).
# The service is read from systemd (Triggers), never guessed from the timer's name: the dividend timer starts the template
# instance indicagent-dividend-event-writer@yahoo.service, and `is-active` on a name that does not exist prints "inactive".
timers_gate() {
  local units u svc n=0
  units=$(blocking_timer_units) || fail "cannot read the blocking timers from APR"
  while read -r u; do
    [ -n "$u" ] || continue
    n=$((n + 1))
    [ "$(systemctl show -p LoadState --value "$u" 2>/dev/null)" = loaded ] || fail "$u is not loaded"
    svc=$(systemctl show -p Triggers --value "$u" 2>/dev/null)
    case "$svc" in
      ""|*" "*) fail "$u triggers '${svc:-no unit}', expected exactly one service";;
    esac
    case "$(systemctl is-active "$svc" 2>/dev/null)" in
      active|activating|reloading) fail "$svc is running (a blocking timer is firing)";;
    esac
  done <<< "$units"
  [ "$n" -gt 0 ] || fail "no blocking timers listed in APR"
}

heavy_job_live() { pgrep -f "$HEAVY_JOB_RE" >/dev/null; }

# Memory-fault signatures in this boot's kernel log. Bad page, Bad swap and general protection always refuse.
# A segfault refuses unless its fault address equals its stack pointer (compared as numbers; sp is zero-padded):
# a write to the page below the stack is a runaway recursion overflowing it (bash, 2026-11-26 15:15Z), not
# corrupted memory. That line is disclosed in the status file, never hidden. An unparsable segfault refuses.
kernel_fault_gate() {
  local klog line addr sp
  klog=$(journalctl -k -b --no-pager 2>/dev/null)
  [ -n "$klog" ] || fail "kernel log unreadable (journalctl -k -b returned nothing)"
  grep -q -E 'Bad page|Bad swap|general protection' <<< "$klog" && fail "kernel log shows memory-fault signatures this boot"
  while IFS= read -r line; do
    addr=$(sed -n 's/.*segfault at \([0-9a-f]\{1,16\}\) ip [0-9a-f]\+ sp \([0-9a-f]\{1,16\}\) error .*/\1/p' <<< "$line")
    sp=$(sed -n 's/.*segfault at \([0-9a-f]\{1,16\}\) ip [0-9a-f]\+ sp \([0-9a-f]\{1,16\}\) error .*/\2/p' <<< "$line")
    if [ -n "$addr" ] && [ -n "$sp" ] && [ $((16#$addr)) -eq $((16#$sp)) ]; then
      log "ignored stack-overflow segfault: $line"
    else
      fail "kernel log shows memory-fault signatures this boot"
    fi
  done < <(grep 'segfault' <<< "$klog")
}

host_gate() {    # refuse to start on a host that is not demonstrably healthy
  [ -f "$SCRATCH/memtester_clean" ] || fail "no memtester_clean file (operator records a clean pass)"
  pgrep -x memtester >/dev/null && fail "memtester still running"
  heavy_job_live && fail "another heavy job is live"
  window_gate
  timers_gate
  [ "$(cat /proc/sys/kernel/tainted)" = "0" ] || fail "kernel tainted: $(cat /proc/sys/kernel/tainted)"
  kernel_fault_gate
  local n; n=$(dimm_temps | wc -l); [ "$n" -ge 2 ] || fail "expected 2 spd5118 sensors, found $n"
  local t; t=$(dimm_max_c); [ "$t" -le "$GATE_C" ] || fail "DIMM at ${t:-no reading}C, gate ${GATE_C}C"
  mem_gate
}

# group_alive <pgid>: true while the process group has a member that is not a zombie.
group_alive() { ps -eo pgid=,stat= | awk -v p="$1" '$1 == p && $2 !~ /^Z/ {f = 1} END {exit !f}'; }

# stop_group <pgid>: CONT then TERM, KILL after KILL_GRACE_S, then check that nothing is left.
stop_group() {
  local pgid=$1 i
  kill -CONT -- "-$pgid" 2>/dev/null; kill -TERM -- "-$pgid" 2>/dev/null
  for ((i = 0; i < KILL_GRACE_S; i++)); do group_alive "$pgid" || return 0; sleep 1; done
  kill -KILL -- "-$pgid" 2>/dev/null; log "watchdog escalated to KILL for pgid $pgid"; sleep 1
  ! group_alive "$pgid" || log "ABORT pgid $pgid still has live members after KILL"
}

# run_guarded <outfile> <cmd...>: runs cmd in its own process group with the temperature
# watchdog; returns cmd's exit code, or 143 when the watchdog killed it (ABORT already logged).
# Fail closed: a poll without two readable DIMM sensors stops the group, and MAX_SENSOR_MISSES in a row kill it.
run_guarded() {
  local out=$1; shift
  setsid "$@" > "$out" 2>&1 &
  local pid=$!; local pgid=""; local i
  for i in 1 2 3 4 5; do pgid=$(ps -o pgid= -p "$pid" | tr -d ' '); [ -n "$pgid" ] && break; sleep 0.2; done
  [ -n "$pgid" ] || { log "ABORT cannot read pgid of $pid"; kill "$pid" 2>/dev/null; return 1; }
  local paused_at=0 killed=0 misses=0 t now why
  # A launcher that dies (TERM, INT, HUP) must not leave a run unprotected or a group stopped for good.
  trap 'log "ABORT launcher signalled: stopping pgid $pgid"; stop_group "$pgid"; exit 143' TERM INT HUP
  while kill -0 "$pid" 2>/dev/null; do
    now=$(date +%s)
    if t=$(dimm_max_c); then misses=0; else t=""; misses=$((misses + 1)); fi
    rss_mb=$(ps -eo pgid=,rss= | awk -v p="$pgid" '$1==p{s+=$2} END{printf "%d", s/1024}')
    echo "$(date -u +%FT%TZ) pid=$pid max_c=${t:-none} rss_mb=$rss_mb paused=$([ $paused_at -gt 0 ] && echo 1 || echo 0)" >> "$TEMPLOG"
    if [ -n "$t" ] && [ "$t" -ge "$KILL_C" ]; then
      why="DIMM at ${t}C"; killed=1; break
    elif [ $paused_at -gt 0 ] && [ $((now - paused_at)) -gt $MAX_PAUSE_S ]; then
      why="paused more than ${MAX_PAUSE_S}s"; killed=1; break
    elif [ -z "$t" ]; then
      [ "$misses" -lt "$MAX_SENSOR_MISSES" ] || { why="DIMM sensors unreadable for $misses polls"; killed=1; break; }
      [ $paused_at -gt 0 ] || { kill -STOP -- "-$pgid"; paused_at=$now; log "watchdog STOP: DIMM sensors unreadable"; }
    elif [ "$t" -ge "$STOP_C" ] && [ $paused_at -eq 0 ]; then
      kill -STOP -- "-$pgid"; paused_at=$now; log "watchdog STOP at ${t}C"
    elif [ "$t" -le "$RESUME_C" ] && [ $paused_at -gt 0 ]; then
      kill -CONT -- "-$pgid"; paused_at=0; log "watchdog CONT at ${t}C"
    fi
    sleep "$POLL_S"
  done
  if [ $killed -eq 1 ]; then
    log "ABORT watchdog killed pgid $pgid: $why (paused_at=$paused_at)"
    trap - TERM INT HUP
    stop_group "$pgid"; wait "$pid" 2>/dev/null; return 143
  fi
  wait "$pid"; local rc=$?
  trap - TERM INT HUP
  return "$rc"
}

# hold_timers: quiesce the blocking timers for the life of this launcher and release them on ANY exit (the exit trap), so a
# failed launch never leaves the nightly capture off. For launchers whose run is not resumable (counted runs, batteries); the
# corpus pilot and IC measure hold the timers on failure on purpose, because a resumed run needs the bars unchanged.
# The command runs from $REPO: a launcher may be sitting in a pinned worktree whose services are older.
release_timers() { log "timers released (exit trap)"; ( cd "$REPO" && $PY -m services.corpus_rerun --release >> "$STATUS" 2>&1 ); }
hold_timers() {
  log "quiesce"
  ( cd "$REPO" && $PY -m services.corpus_rerun --quiesce >> "$STATUS" 2>&1 ) || { release_timers; fail "quiesce failed"; }
  trap release_timers EXIT
}

# verdict_preflight: refuse when member 1d verdicts are older than the d2_landed freshness window
# (APR threshold.bar_integrity.report_max_age_hours, read by verdict_gate.load_report_max_age_hours).
# Read-only; refuses first while the last completed session's bars are not captured (ops_capture_delivered.py).
# The producer of dead members' verdicts is ops_member_verdicts_1d.py (no timer; the
# 06:00Z bar-reconciliation audit judges active names only), so a pause of more than the window
# between its last run and a pin gate refuses the run (pilot 7c5612f0, 2026-11-24: 11,350 of 12,857).
verdict_preflight() {
  local out limit stale total delivered
  # A verdict taken before the nightly capture delivers the last completed session judges it
  # missing for every name (todo 675; pilot run 0e020c5a), so check that first.
  delivered=$($PY "$REPO/scripts/ops/ops_capture_delivered.py") || fail "${delivered:-ops_capture_delivered.py failed, see its stderr}"
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
  [ "$stale" -eq 0 ] || fail "$stale of $total member 1d verdicts are older than ${limit} h; refresh: cd $REPO && setsid -f $PY scripts/ops/bars/ops_member_verdicts_1d.py --apply > logs/member_verdicts_1d_\$(date -u +%F).out 2>&1 (about 1.8 h measured 2026-11-25; the report logs progress and an ETA), then relaunch"
}
