#!/usr/bin/env bash
# The lead launches one headless worker session (PLANNING-SYSTEM.md, "Spawning workers"; owner ruling 2026-11-27).
#
#   scripts/ops/spawn_worker.sh --name <name> --todo <N> --brief <file> --model <model> --permission-mode <mode>
#   scripts/ops/spawn_worker.sh --list     # every worker not yet reaped: alive or finished
#   scripts/ops/spawn_worker.sh --reap     # remove the clean, merged worktrees of finished workers
#
# A spawn makes a detached worktree off origin/main, starts `claude -p` in it with the brief on stdin (never in argv:
# a brief that names a heavy job would match the launchers' heavy-job probe), detached with setsid, logging to
# logs/agents/<name>.log, and appends the worker to logs/agents/workers.jsonl (append-only: spawn and reap records).
# Refusals, all reported at once (exit 3): the brief lacks one of the seven parts; the todo is not pending on
# origin/main, is claimed there or has a live worker; the name is already recorded; the live workers reach APR infra.spawn_worker.max_workers; MemAvailable
# is under APR infra.spawn_worker.mem_margin_gib plus, while a heavy job is live, the largest guarded-run floor
# (infra.run_guarded.mem_floor_gib.*). A missing or out-of-bounds APR key refuses (migration 625).
# The permission mode has no default: an unattended worker runs under the mode and settings the owner chooses.
# The registry and worktrees belong to the primary checkout, wherever the script runs from; one lock serialises
# spawn and reap, so two calls cannot both pass the cap or take one name.
# Collect mode (set before sourcing, and global, so fail() records and never writes the guarded-run status file).
COLLECT_REFUSALS=1
. "$(dirname "${BASH_SOURCE[0]}")/guarded_run_common.sh"   # REPO, fail, refusals_report, mem and heavy-job probes
main_checkout() { dirname "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)"; }
AGENTS=${SPAWN_AGENTS_DIR:-$(main_checkout)/logs/agents}
REGISTRY=$AGENTS/workers.jsonl
WT_ROOT=${SPAWN_WORKTREE_ROOT:-$(dirname "$(main_checkout)")}
CLAUDE=${CLAUDE_BIN:-claude}
PERMISSION_MODES="acceptEdits auto bypassPermissions dontAsk"   # the CLI's modes that act headless (not manual, plan)
BRIEF_PARTS=("goals?" "state" "scope" "failure modes?" "gates?" "boundary|boundaries" "reports?")   # case-insensitive EREs

die() { echo "spawn_worker: $*" >&2; exit 2; }
# git and psql never inherit the lock fd: a daemonized `git gc --auto` would hold the lock after this script exits.
git() { command git "$@" 9>&-; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
psql_q() { PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAF'|' -c "$1" 9>&-; }

# apr_int <key> <var>: sets var to the integer value of an APR key inside its config_schema bounds, or records a
# refusal and returns 1 (never a default). Not called in $(...): a refusal recorded in a subshell would be lost.
apr_int() {
  local row value lo hi
  row=$(psql_q "select s.config_value, c.min_value, c.max_value from config_state s join config_schema c using (config_key) where s.config_key = '$1'") \
    || { fail "cannot read APR $1"; return 1; }
  IFS='|' read -r value lo hi <<< "$row"
  [[ $value =~ ^[0-9]{1,4}$ && $lo =~ ^[0-9]+(\.0+)?$ && $hi =~ ^[0-9]+(\.0+)?$ ]] \
    || { fail "APR $1 is missing or not an integer with schema bounds"; return 1; }
  ((10#$value >= ${lo%%.*} && 10#$value <= ${hi%%.*})) || { fail "APR $1 = $value is outside [$lo, $hi]"; return 1; }
  printf -v "$2" '%d' $((10#$value))
}

# open_workers: spawn records with no reap record of the same name, one line each: name todo pid pid_start worktree
# started, split by US (\x1f, not a tab: an empty pid_start must stay a field). Fails on an unreadable registry.
US=$'\x1f'
open_workers() {
  [ -f "$REGISTRY" ] || return 0
  jq -rs '(map(select(.event == "reaped") | .name)) as $gone
          | .[] | select(.event == "spawned" and (.name | IN($gone[]) | not))
          | [.name, .todo, .pid, .pid_start, .worktree, .started] | map(tostring) | join("\u001f")' "$REGISTRY"
}
# start_ticks <pid>: the process start time in clock ticks since boot (/proc/<pid>/stat field 22, read after the
# comm field, which may hold spaces); independent of TZ and locale. Empty when the process is gone.
start_ticks() { local stat; stat=$(cat "/proc/$1/stat" 2>/dev/null) && awk '{print $20}' <<< "${stat##*) }"; }
# alive <pid> <pid_start>: the recorded process still runs (its start time guards against a reused pid), or a
# process it left in its group (setsid made the worker its group's leader) does.
# A live pid with another start time is a reused pid, and Linux never reuses a pid that is still a live pgid.
alive() {
  local now; now=$(start_ticks "$1")
  if [ -n "$now" ]; then [ "$now" = "$2" ]; else group_alive "$1"; fi
}
# in_use <dir>: some process works in dir, runs a path in it or holds a file in it open (a job the worker detached
# from its group).
in_use() {
  local proc link
  for proc in /proc/[0-9]*; do
    for link in "$proc/cwd" "$proc/exe" "$proc"/fd/*; do
      case "$(readlink "$link" 2>/dev/null)/" in "$1"/*) return 0;; esac
    done
    tr '\0' '\n' < "$proc/cmdline" 2>/dev/null | grep -qF "$1/" && return 0
  done
  return 1
}
append() { jq -cn "$@" >> "$REGISTRY"; }
lock() {
  mkdir -p "$AGENTS" || die "cannot create $AGENTS"
  exec 9>> "$AGENTS/.lock"
  flock -n 9 || die "another spawn or reap holds $AGENTS/.lock"
}

# brief_gate <file>: each of the seven parts opens a line (case-insensitive, after optional #, * or a number),
# followed by a colon (a few words may come first: "State with ids:"), an opening parenthesis or the end of the line.
brief_gate() {
  local part missing=()   # a missing part is named by its stem, e.g. "gate"
  for part in "${BRIEF_PARTS[@]}"; do
    grep -qiE "^[#*[:space:]0-9.()-]*(${part})([[:space:]][^:]{0,40})?[*[:space:]]*:|^[#*[:space:]0-9.()-]*(${part})[*[:space:]]*(\(|$)" "$1" \
      || missing+=("${part%%[?|]*}")
  done
  [ "${#missing[@]}" -eq 0 ] || fail "the brief lacks the seven-part section(s): ${missing[*]}"
}

mem_floor_gate() {
  local margin floor=0 keys key gib
  apr_int infra.spawn_worker.mem_margin_gib margin || return 1
  if heavy_job_live; then
    keys=$(psql_q "select config_key from config_state where config_key like 'infra.run_guarded.mem_floor_gib.%'") \
      && [ -n "$keys" ] || { fail "cannot read the guarded-run floors while a heavy job is live"; return 1; }
    while read -r key; do
      apr_int "$key" gib || return 1
      ((gib > floor)) && floor=$gib
    done <<< "$keys"
  fi
  MEM_FLOOR_KB=$(((floor + margin) * 1024 * 1024))
  mem_gate
}

spawn() {
  local name="" todo="" brief="" model="" mode=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --name) name=${2:-};; --todo) todo=${2:-};; --brief) brief=${2:-};; --model) model=${2:-};;
      --permission-mode) mode=${2:-};;
      *) die "unknown argument $1";;
    esac
    shift 2 || die "$1 needs a value"
  done
  [[ $name =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || die "--name must be lower-case letters, digits and dashes"
  [[ $todo =~ ^[0-9]+$ ]] || die "--todo must be a todo number"
  [ -r "$brief" ] || die "--brief $brief is not a readable file"
  [ -n "$model" ] || die "--model is required (the lead chooses it per lane)"
  [[ " $PERMISSION_MODES " == *" $mode "* ]] || die "--permission-mode is required, one of: $PERMISSION_MODES (the owner chooses it for unattended workers)"
  brief=$(realpath "$brief")

  lock
  git -C "$REPO" fetch -q origin || die "git fetch failed"
  command -v "$CLAUDE" > /dev/null || fail "no claude binary at $CLAUDE"
  brief_gate "$brief"
  local todo_path
  todo_path=$(git -C "$REPO" ls-tree --name-only origin/main .planning/todos/pending/ | grep -E "/${todo}-[^/]*\.md$")
  if [ -z "$todo_path" ]; then
    fail "todo $todo is not in .planning/todos/pending/ on origin/main"
  elif git -C "$REPO" show "origin/main:$todo_path" | awk 'NR == 1 && !/^---$/ {exit} NR > 1 && /^---$/ {exit} NR > 1' \
    | grep -q '^claimed_by:'; then
    fail "todo $todo is claimed by another session on origin/main"
  fi
  if [ -f "$REGISTRY" ]; then
    jq -e --arg n "$name" 'select(.event == "spawned" and .name == $n)' "$REGISTRY" > /dev/null
    case $? in
      0) fail "worker name $name is already recorded";;
      4) ;;   # no match
      *) fail "cannot read $REGISTRY";;
    esac
  fi
  local cap rows live=0 w_name w_todo w_pid w_start w_rest
  if apr_int infra.spawn_worker.max_workers cap; then
    if rows=$(open_workers); then
      while IFS=$US read -r w_name w_todo w_pid w_start w_rest; do
        [ -n "$w_name" ] || continue
        [ "$w_todo" != "$todo" ] || fail "worker $w_name holds todo $todo until it is reaped"
        alive "$w_pid" "$w_start" && live=$((live + 1))
      done <<< "$rows"
      ((live < cap)) || fail "$live live worker(s), cap infra.spawn_worker.max_workers = $cap"
    else
      fail "cannot read $REGISTRY"
    fi
  fi
  mem_floor_gate
  refusals_report || exit 3

  local wt=$WT_ROOT/indicagent-wt-$name log=$AGENTS/$name.log base pid
  base=$(git -C "$REPO" rev-parse origin/main) || die "cannot resolve origin/main"
  git -C "$REPO" worktree add -q --detach "$wt" "$base" || die "git worktree add $wt failed"
  # The worker is a peer session, not a child of the caller's: drop the caller's Claude session identity.
  ( exec 9>&-; unset CLAUDECODE CLAUDE_PID CLAUDE_EFFORT $(compgen -v CLAUDE_CODE_); cd "$wt" && exec setsid "$CLAUDE" -p --model "$model" --permission-mode "$mode" -n "$name" < "$brief" > "$log" 2>&1 ) &
  pid=$!
  local start; start=$(start_ticks "$pid")   # exec keeps the start time; empty if it already exited
  append --arg name "$name" --argjson todo "$todo" --arg worktree "$wt" --argjson pid "$pid" --arg pid_start "$start" \
    --arg started "$(now_utc)" --arg model "$model" --arg mode "$mode" --arg brief "$brief" --arg log "$log" --arg base "$base" \
    '{event: "spawned", name: $name, todo: $todo, worktree: $worktree, pid: $pid, pid_start: $pid_start, started: $started,
      model: $model, permission_mode: $mode, brief: $brief, log: $log, base: $base}' \
    || { kill -TERM "$pid" 2>/dev/null; kill -TERM -- "-$pid" 2>/dev/null   # before and after its setsid
         sleep 2; kill -KILL "$pid" 2>/dev/null; kill -KILL -- "-$pid" 2>/dev/null
         git -C "$REPO" worktree remove --force "$wt" && die "cannot record the worker in $REGISTRY: stopped group $pid, removed $wt"
         die "cannot record the worker in $REGISTRY: stopped group $pid; removing $wt failed, remove it by hand"; }
  echo "spawned $name (todo $todo, pid $pid) in $wt, log $log"
}

list() {
  local rows name todo pid start wt at n=0
  rows=$(open_workers) || die "cannot read $REGISTRY"
  while IFS=$US read -r name todo pid start wt at; do
    [ -n "$name" ] || continue
    n=$((n + 1))
    printf '%s\ttodo %s\tpid %s\t%s\tstarted %s\t%s\n' "$name" "$todo" "$pid" \
      "$(alive "$pid" "$start" && echo alive || echo finished)" "$at" "$wt"
  done <<< "$rows"
  echo "$n worker(s) not reaped"
}

# reap: a finished worker's worktree goes only when no process runs in it, it is clean (no ignored file either, bar
# tool caches: a worker's results may sit under an ignored path such as logs/), unlocked, and every commit on it has
# landed on origin/main (by merge, rebase or cherry-pick: `git cherry` lists none with a +). A local branch the
# worker made goes with it when git deems it merged.
CACHE_RE='^!! (.*/)?(__pycache__|\.ruff_cache|\.mypy_cache|\.pytest_cache)/$'

reap() {
  local rows name todo pid start wt at why locked unlanded branch
  lock
  rows=$(open_workers) || die "cannot read $REGISTRY"
  git -C "$REPO" fetch -q origin || die "git fetch failed"
  locked=$(git -C "$REPO" worktree list --porcelain | awk '/^worktree /{w = substr($0, 10)} /^locked/{print w}')
  while IFS=$US read -r name todo pid start wt at; do
    [ -n "$name" ] || continue
    if alive "$pid" "$start"; then echo "keep $name: still running"; continue; fi
    if [ -d "$wt" ]; then
      why=""
      in_use "$wt" && { echo "keep $name: a process runs in $wt"; continue; }
      [ -z "$(git -C "$wt" status --porcelain --ignored 2>&1 | grep -vE "$CACHE_RE")" ] || why="dirty or ignored files present"
      unlanded=$(git -C "$wt" cherry origin/main HEAD 2>&1) && ! grep -q '^+' <<< "$unlanded" \
        || why="${why:+$why, }not landed on origin/main"
      grep -qFx "$wt" <<< "$locked" && why="${why:+$why, }locked"
      if [ -n "$why" ]; then echo "keep $name: $why ($wt)"; continue; fi
      branch=$(git -C "$wt" symbolic-ref -q --short HEAD)
      git -C "$REPO" worktree remove --force "$wt" || { echo "keep $name: git worktree remove failed"; continue; }
      [ -z "$branch" ] || git -C "$REPO" branch -d "$branch" || echo "$name: branch $branch kept (not merged)"
    else
      echo "$name: worktree $wt was already gone"
      git -C "$REPO" worktree prune
    fi
    append --arg name "$name" --arg at "$(now_utc)" '{event: "reaped", name: $name, reaped: $at}' \
      || die "cannot record the reap of $name in $REGISTRY"
    echo "reaped $name"
  done <<< "$rows"
}

case "${1:-}" in
  --list) list;;
  --reap) reap;;
  --name|--todo|--brief|--model|--permission-mode) spawn "$@";;
  *) die "usage: $0 --name <name> --todo <N> --brief <file> --model <model> --permission-mode <mode> | --list | --reap";;
esac
