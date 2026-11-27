#!/usr/bin/env bash
# run_resource: the true memory peak of one run, from the run's own cgroup (todo 681, part A).
#
# A run executes inside a transient systemd user scope with memory accounting. The process that stays
# alive after the job exits reads the scope's memory.peak, memory.swap.peak, memory.events (oom_kill)
# and the processes left in cgroup.procs, then writes one node_exporter textfile per workload and stage and one
# status line. The cgroup counts every process of the run once (pool workers and orphans included) and
# keeps memory.peak after a child dies by SIGKILL, so a killed run still leaves its peak.
#
# Wrapper mode:  run_resource.sh <workload> <stage> <run_id> -- cmd args...
# Sourced:       run_resource_scope <argv...>   re-exec argv inside a user scope (exit 3 when none)
#                run_resource_emit <workload> <stage> <run_id> <rc>
#
# Series: one run_resource_info{workload,stage,run_id} 1 per run and six gauges labelled workload and stage only, so
# a run costs one extra series, not seven. The file is overwritten per workload and node_exporter serves a finished
# run's values until the next one: alert on them together with time() - run_resource_end_timestamp_seconds.
# oom_kill counts the kernel OOM killer only; exit_code 137 with oom_kill 0 is a SIGKILL from elsewhere (systemd-oomd,
# cgroup.kill, the DIMM watchdog), so read the two together.
#
# Environment: CGROUP_ROOT (default /sys/fs/cgroup), RUN_RESOURCE_CGROUP (the scope's path under it;
# default read from /proc/self/cgroup), TEXTFILE_DIR (default /var/lib/node-exporter-textfile),
# RUN_RESOURCE_STATUS (a file that also receives the status line), RUN_RESOURCE_START (epoch seconds). RUN_RESOURCE_REEXEC=1 is set only for the process
# run_resource_scope re-executes and is consumed (unset) on entry, so a job never inherits it.
# Never `job` as a label: Prometheus renames it to exported_job on the node scrape.

RUN_RESOURCE_PREFIX=run_resource

run_resource_fail() { echo "run_resource: $*" >&2; return 1; }

# Labels land inside a quoted exposition-format string: refuse anything outside a safe alphabet.
run_resource_label_ok() { [[ $1 =~ ^[A-Za-z0-9_.:-]+$ ]]; }

run_resource_cgroup_dir() {
  local rel=${RUN_RESOURCE_CGROUP:-}
  if [[ -z $rel ]]; then
    local line
    while IFS= read -r line; do
      [[ $line == 0::* ]] && rel=${line#0::}
    done < /proc/self/cgroup
  fi
  [[ -n $rel ]] || { run_resource_fail "no cgroup v2 path for this process"; return 1; }
  printf '%s%s' "${CGROUP_ROOT:-/sys/fs/cgroup}" "$rel"
}

# A counter file holds one integer ("max" is not valid for a peak); events hold "key value" lines.
run_resource_read_int() {
  local value
  { read -r value < "$1"; } 2>/dev/null || return 1
  [[ $value =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$value"
}

run_resource_event() {   # run_resource_event <events file> <key>: 0 when the key is absent; 1 when the file is unreadable
  local key value
  [[ -r $1 ]] || return 1
  while read -r key value; do
    [[ $key == "$2" ]] && { printf '%s' "$value"; return 0; }
  done < "$1"
  printf 0
}

# Processes of the cgroup that are not this shell or one of its descendants (the subshells of the emit itself,
# and any child the caller still owns): whatever the job left behind, such as pool workers orphaned to the
# user manager. The members are listed first and the process table read after, so a member that exited in
# between (a short-lived helper) is absent from the table and /proc and is not counted.
run_resource_leftovers() {
  [[ -r $1/cgroup.procs ]] || return 1
  local members; members=$(cat "$1/cgroup.procs")
  ps -eo pid=,ppid= | awk -v root="$$" -v members="$members" '
    { parent[$1] = $2 }
    END {
      n = 0
      split(members, list, "\n")
      for (i in list) {
        p = list[i]
        if (p == "") continue
        if (!(p in parent)) { if (system("[ -d /proc/" p " ]") == 0) n++; continue }
        q = p; own = 0
        for (depth = 0; depth < 64 && q in parent; depth++) {
          if (q == root) { own = 1; break }
          q = parent[q]
        }
        if (q == root) own = 1
        if (!own) n++
      }
      print n
    }'
}

run_resource_emit() {
  local workload=$1 stage=$2 run_id=$3 rc=$4 label
  for label in "$workload" "$stage" "$run_id"; do
    run_resource_label_ok "$label" || { run_resource_fail "unsafe label '$label'"; return 2; }
  done
  local dir peak swap oom left
  dir=$(run_resource_cgroup_dir) || return 3
  peak=$(run_resource_read_int "$dir/memory.peak") \
    || { run_resource_fail "cannot read $dir/memory.peak (not run in a user scope?)"; return 3; }
  # a kernel without swap accounting has no swap peak: NaN, never a made-up zero
  swap=$(run_resource_read_int "$dir/memory.swap.peak") || swap=NaN
  oom=$(run_resource_event "$dir/memory.events" oom_kill) \
    || { run_resource_fail "cannot read $dir/memory.events"; return 3; }
  left=$(run_resource_leftovers "$dir") \
    || { run_resource_fail "cannot read $dir/cgroup.procs"; return 3; }

  local out=${TEXTFILE_DIR:-/var/lib/node-exporter-textfile}
  local file=$out/${RUN_RESOURCE_PREFIX}_${workload}_$stage.prom end start
  end=$(date +%s)
  start=${RUN_RESOURCE_START:-$end}
  local labels="workload=\"$workload\",stage=\"$stage\""
  local tmp
  tmp=$(mktemp "$out/.${RUN_RESOURCE_PREFIX}_${workload}_$stage.XXXXXX") \
    || { run_resource_fail "cannot write under $out"; return 3; }
  {
    local name help value
    printf '# HELP %s_info Identity of the run the other series describe\n# TYPE %s_info gauge\n%s_info{%s,run_id="%s"} 1\n' \
      "$RUN_RESOURCE_PREFIX" "$RUN_RESOURCE_PREFIX" "$RUN_RESOURCE_PREFIX" "$labels" "$run_id"
    while IFS='|' read -r name help value; do
      printf '# HELP %s_%s %s\n# TYPE %s_%s gauge\n%s_%s{%s} %s\n' \
        "$RUN_RESOURCE_PREFIX" "$name" "$help" "$RUN_RESOURCE_PREFIX" "$name" \
        "$RUN_RESOURCE_PREFIX" "$name" "$labels" "$value"
    done <<METRICS
memory_peak_bytes|Peak memory of the run's cgroup, page cache included (upper bound on resident need)|$peak
swap_peak_bytes|Peak swap of the run's cgroup|$swap
oom_kill|Processes of the run killed by the kernel OOM killer (not systemd-oomd or cgroup.kill)|$oom
leftover_processes|Processes still in the run's cgroup after the job exited|$left
exit_code|Exit code of the run (128 plus the signal when it was signalled)|$rc
start_timestamp_seconds|Start of the run, epoch seconds|$start
end_timestamp_seconds|End of the run, epoch seconds|$end
METRICS
  } > "$tmp" && chmod 644 "$tmp" && mv "$tmp" "$file" \
    || { rm -f "$tmp"; run_resource_fail "cannot publish $file"; return 3; }

  local line
  line=$(awk -v p="$peak" -v s="$swap" 'BEGIN { printf "memory_peak_gib=%.2f swap_peak_gib=%s", p / 2^30, (s == "NaN" ? "NaN" : sprintf("%.2f", s / 2^30)) }')
  line="run_resource workload=$workload stage=$stage run_id=$run_id exit=$rc $line oom_kill=$oom leftover_processes=$left"
  echo "$line"
  [[ -n ${RUN_RESOURCE_STATUS:-} ]] && echo "$(date -u +%FT%TZ) $line" >> "$RUN_RESOURCE_STATUS"
  return 0
}

# Refuse before a long job when its report could not be written: the cgroup must expose memory.peak and the
# textfile directory must take a file. A failure after a multi-hour run is the failure this prevents.
run_resource_preflight() {
  local dir out=${TEXTFILE_DIR:-/var/lib/node-exporter-textfile}
  dir=$(run_resource_cgroup_dir) || return 3
  run_resource_read_int "$dir/memory.peak" >/dev/null \
    || { run_resource_fail "no readable $dir/memory.peak in this scope (memory accounting missing)"; return 3; }
  [[ -d $out && -w $out ]] || { run_resource_fail "$out is not a writable directory"; return 3; }
}

# Re-exec the given argv inside a transient user scope with memory accounting. Refuses loudly when no user
# manager answers: a run without its cgroup would leave no peak, and a silent gap is the failure. The re-executed
# process finds RUN_RESOURCE_REEXEC=1, consumes it (a job and any nested scope call never see it), probes the
# scope with run_resource_preflight and goes on.
run_resource_scope() {
  if [[ ${RUN_RESOURCE_REEXEC:-} == 1 ]]; then
    unset RUN_RESOURCE_REEXEC
    export -n RUN_RESOURCE_START   # kept for this shell's own report, not passed to the job
    run_resource_preflight || exit 3
    RUN_RESOURCE_SCOPED=1   # this shell owns its cgroup: guarded_emit may report it (not exported)
    return 0
  fi
  systemd-run --user --scope --quiet true 2>/dev/null \
    || { run_resource_fail "systemd-run --user failed (no user manager or no cgroup delegation)"; exit 3; }
  exec systemd-run --user --scope --collect --quiet -p MemoryAccounting=yes \
    --setenv=RUN_RESOURCE_REEXEC=1 --setenv=RUN_RESOURCE_START="$(date +%s)" -- "$@"
}

# The command runs in its own process group so a TERM, INT or HUP to the wrapper reaches the whole job; the
# wrapper outlives the job, so the scope (and its memory.peak) outlives it too. The job's own exit code is the
# wrapper's exit code; a failed report is printed and fails the run only when the job succeeded.
run_resource_main() {
  local workload=${1:-} stage=${2:-} run_id=${3:-}
  if [[ $# -lt 5 || ${4:-} != -- ]]; then
    echo "usage: run_resource.sh <workload> <stage> <run_id> -- command [args...]" >&2
    return 64
  fi
  shift 4
  local label
  for label in "$workload" "$stage" "$run_id"; do
    run_resource_label_ok "$label" || { run_resource_fail "unsafe label '$label'"; return 2; }
  done
  run_resource_scope bash "${BASH_SOURCE[0]}" "$workload" "$stage" "$run_id" -- "$@"
  local pid="" rc signal
  for signal in TERM INT HUP; do
    trap '[[ -z $pid ]] || kill -'"$signal"' -- "-$pid" 2>/dev/null' "$signal"
  done
  set -m
  "$@" < /dev/null &   # job control gives the job its own group; a background job must not read the terminal
  pid=$!
  wait "$pid"
  rc=$?
  # a trapped signal interrupts `wait` with 128+n while the child still runs (or is not yet reaped):
  # wait again until the child's own status comes back
  while kill -0 "$pid" 2>/dev/null; do
    wait "$pid"
    rc=$?
  done
  local emit_rc=0
  run_resource_emit "$workload" "$stage" "$run_id" "$rc" || emit_rc=$?
  trap - TERM INT HUP
  if [[ $emit_rc -ne 0 ]]; then
    run_resource_fail "report failed (exit $emit_rc); the job exited $rc" || true
    [[ $rc -ne 0 ]] || return "$emit_rc"
  fi
  return "$rc"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  run_resource_main "$@"
  exit $?
fi
