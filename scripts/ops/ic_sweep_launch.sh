#!/usr/bin/env bash
# IC sweep launcher (todo 690): the heavy steps of the first counted 1d sweep (todo 671's checklist), guarded: the host
# gate (memory-fault signatures, DIMM temperature, one heavy job, the nightly window), the DIMM watchdog and RSS log, one
# user scope (run_resource gauges).
#   dry-run      services.ic_sweep_recorder --tf 1d --dry-run <args>   (pilot gate b, the FILL numbers)
#   record       services.ic_sweep_recorder --tf 1d <args>             (--horizons, --declared-n-looks)
#   stepm-check  scripts/research/stepm_sweep_scale_check.py <args>    (todo 670; reads no bars)
# The recorder reads the stored features and the bars: it runs inside the window the corpus stage holds, after
# feature_complete and before the IC measure (lead ruling 2026-11-28), so the bars cannot move between the features
# and either reader. It therefore refuses unless every blocking timer is already quiesced, and it never quiesces or
# releases them: only ic_measure_launch.sh releases, on its own clean exit. The 670 check needs no hold.
# The job runs in <sweep_worktree>, a detached worktree whose tracked files are clean and whose HEAD is an ancestor of
# origin/main (the commit its records cite), never a corpus run worktree. Run this script from the main checkout.
# Usage: setsid -f bash scripts/ops/ic_sweep_launch.sh <mode> <sweep_worktree> <run_id|-> [job args...]
#        bash scripts/ops/ic_sweep_launch.sh --check <mode> <sweep_worktree> <run_id|-> (every refusal, read-only)
# <run_id> is the corpus run whose features the recorder reads; `-` for stepm-check.
# The MemAvailable floor is APR infra.run_guarded.mem_floor_gib.ic_sweep (migration 626).
# docs/operations/guarded-run-runbook.md; commands in docs/research/draft-ledger-2026-11-27a-first-ic-sweep.md.
set -u
CHECK=""; unset COLLECT_REFUSALS   # set here on --check only: an inherited value would make every fail() return
if [ "${1:-}" = "--check" ]; then CHECK=1; COLLECT_REFUSALS=1; shift; fi   # before sourcing: collect mode reads it there
. "$(dirname "${BASH_SOURCE[0]}")/guarded_run_common.sh"
FLOOR_KEY=infra.run_guarded.mem_floor_gib.ic_sweep
PSQL=(env PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc)   # the password reaches psql only

# sweep_preflight_judge <mode> <scope> <feature_complete> <ic_measure>
# Pure: prints the reason and returns 1 on the first refusal, returns 0 when the mode may run against the run's state.
sweep_preflight_judge() {
  local mode=$1 scope=$2 fc=$3 icm=$4
  case "$mode" in
    stepm-check) return 0;;
    dry-run|record) ;;
    *) echo "mode '$mode' is not dry-run, record or stepm-check"; return 1;;
  esac
  [ "$scope" = "1d" ] || { echo "run scope is '$scope', a level 1 sweep reads a scope-1d run"; return 1; }
  [ "$fc" = "completed" ] || { echo "feature_complete step is '$fc', not completed"; return 1; }
  [ "$icm" != "completed" ] || { echo "ic_measure already completed: the timers are released, so the recorder's window is closed (lead ruling 2026-11-28)"; return 1; }
}

# sweep_worktree_judge <worktree> <is_run_worktree> <dirty_tracked> <published>
# Pure: the job's checkout is a clean, published, non-run worktree.
sweep_worktree_judge() {
  local wt=$1 is_run=$2 dirty=$3 published=$4
  [ -n "$wt" ] && [ -d "$wt" ] || { echo "no sweep worktree '$wt'"; return 1; }
  [ "$is_run" = no ] || { echo "$wt is a corpus run worktree; use a detached sweep worktree"; return 1; }
  [ -z "$dirty" ] || { echo "$wt has uncommitted tracked changes: $dirty"; return 1; }
  [ "$published" = yes ] || { echo "$wt HEAD is not an ancestor of origin/main; run at a pushed commit"; return 1; }
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0     # sourced by a test: functions only

MODE=${1:?mode}; WT=${2:?sweep worktree}; RUN=${3:?run id or -}; shift 3
WT=$(cd "$WT" 2>/dev/null && pwd || echo "$WT")
case "$RUN" in
  -) [ "$MODE" = stepm-check ] || { echo "mode $MODE needs a run id"; exit 3; };;
  *) echo "$RUN" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || { echo "run id $RUN is not a uuid"; exit 3; }
     GUARDED_RUN_ID=$RUN;;   # a validated uuid labels the gauges
esac
[ -n "$CHECK" ] || { : >> "$STATUS"; exec 2>> "$STATUS"; run_resource_scope bash "$0" "$MODE" "$WT" "$RUN" "$@"; }

sweep_preflight() {   # a launch exits at the first refusal; --check reports them all
  local scope="" fc="" icm="" reason is_run=no dirty published=no floor_kb
  if [ "$RUN" != - ]; then
    scope=$("${PSQL[@]}" "select measured->>'data_gate_scope' from corpus_run where run_id='$RUN'") || fail "corpus_run query"
    fc=$("${PSQL[@]}" "select status from corpus_run_step where run_id='$RUN' and step='feature_complete'")
    icm=$("${PSQL[@]}" "select status from corpus_run_step where run_id='$RUN' and step='ic_measure'")
  fi
  reason=$(sweep_preflight_judge "$MODE" "$scope" "$fc" "$icm") || fail "preflight: $reason"
  case "$(basename "$WT")" in *-corpus-run-*) is_run=yes;; esac
  dirty=$(git -C "$WT" status --porcelain --untracked-files=no 2>&1 | tr '\n' ' ')
  git -C "$WT" merge-base --is-ancestor HEAD origin/main 2>/dev/null && published=yes
  reason=$(sweep_worktree_judge "$WT" "$is_run" "$dirty" "$published") || fail "worktree: $reason"
  if floor_kb=$(apr_floor_kb "$FLOOR_KEY"); then MEM_FLOOR_KB=$floor_kb
  elif [ $? -eq 2 ]; then MEM_FLOOR_KB=0; fail "cannot read $FLOOR_KEY from APR (database unreachable)"
  else MEM_FLOOR_KB=0; fail "$FLOOR_KEY is not an integer from 8 to 512 in APR"; fi   # 0: no second, misleading memory refusal
  [ "$MODE" = stepm-check ] || timers_quiesced_gate   # the stage's hold: required, never taken or released here
  host_gate
  [ -n "$CHECK" ] || log "ic_sweep $MODE preflight ok: run $RUN worktree $WT head $(git -C "$WT" rev-parse --short=12 HEAD) floor $((MEM_FLOOR_KB / 1048576)) GiB"
}

sweep_preflight
if [ -n "$CHECK" ]; then scope_gate; refusals_report; exit $?; fi

case "$MODE" in
  dry-run) JOB=("$PY" -m services.ic_sweep_recorder --tf 1d --dry-run "$@");;
  record) JOB=("$PY" -m services.ic_sweep_recorder --tf 1d "$@");;
  stepm-check) JOB=("$PY" scripts/research/stepm_sweep_scale_check.py "$@");;
esac
cd "$WT" || fail "cd $WT"
before=$(wc -l < "$TEMPLOG" 2>/dev/null || echo 0)
GUARDED_STAGE=ic_sweep_${MODE//-/_} run_guarded "$SCRATCH/ic_sweep_${MODE}_${GUARDED_RUN_ID}.out" "${JOB[@]}"
rc=$?
log "ic_sweep $MODE exit=$rc run=$RUN peak_rss_mb=$(peak_rss_mb_since "$TEMPLOG" "$before") output=$SCRATCH/ic_sweep_${MODE}_${GUARDED_RUN_ID}.out (timers untouched)"
exit "$rc"
