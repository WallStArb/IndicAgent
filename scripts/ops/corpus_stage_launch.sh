#!/usr/bin/env bash
# Corpus stage launcher (scope 1d): the run's stage_1d and feature_complete steps, guarded: refuse unless the pilot
# completed at the run's pin and the blocking timers are quiesced -> stage under the DIMM watchdog and RSS log in one
# user scope (run_resource gauges) -> hold the timers on every exit.
# docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash corpus_stage_launch.sh <run_id> <expected_rebuild_code_key_prefix>
#        bash corpus_stage_launch.sh --check <run_id> <expected_rebuild_code_key_prefix>
#                                  (every refusal a launch would meet, read-only, at once)
# The run walks `--through feature_complete` and no further until todos 670 and 671 exist (ledger 2026-11-24f).
# Preconditions: pilot completed for the run at its recorded code_commit; the blocking timers quiesced
# (`python -m services.corpus_rerun --quiesce`, so the bars stay unchanged under the run); block 2 compare IDENTICAL in
# the status file; memtester_clean present; no heavy job live. The timers stay held on every exit: a stage that stops
# resumes with the same command, and a complete one is followed by ic_measure_launch.sh, which reads the same rows and
# releases on its own clean exit (restated bars between feature_complete and ic_measure would split the IC inputs from
# the features, lead ruling 2026-11-27). Release by hand with `python -m services.corpus_rerun --release` if the run is abandoned.
# The MemAvailable floor is APR infra.run_guarded.mem_floor_gib.stage_1d (seed 40, sized for 16-worker batteries):
# the pilot at 4 workers peaked at 1.90 GiB in its cgroup.
set -u
CHECK=""; unset COLLECT_REFUSALS   # set here on --check only: an inherited value would make every fail() return
if [ "${1:-}" = "--check" ]; then CHECK=1; COLLECT_REFUSALS=1; shift; fi   # before sourcing: collect mode reads it there
. "$(dirname "$0")/guarded_run_common.sh"
THROUGH=feature_complete
FLOOR_KEY=infra.run_guarded.mem_floor_gib.stage_1d
PSQL=(psql -U postgres -h localhost -d indicagent -tAc)
export PGPASSWORD=postgres

# stage_preflight_judge <scope> <pilot> <feature_complete> <worktree_head> <recorded_commit> <key> <expect>
# Pure: prints the reason and returns 1 on the first refusal, returns 0 when the run may be staged.
stage_preflight_judge() {
  local scope=$1 pilot=$2 fc=$3 head=$4 recorded=$5 key=$6 expect=$7
  [ "$scope" = "1d" ] || { echo "run scope is '$scope', only a scope-1d run is staged"; return 1; }
  [ "$pilot" = "completed" ] || { echo "pilot step is '$pilot', not completed"; return 1; }
  [ "$fc" != "completed" ] || { echo "feature_complete already completed for this run"; return 1; }
  [ -n "$recorded" ] && [ "$head" = "$recorded" ] || { echo "worktree HEAD '$head' is not the run's code_commit '$recorded'"; return 1; }
  case "$key" in "$expect"?*) ;; *) echo "rebuild_code_key '$key' does not start with '$expect'"; return 1;; esac
}

# stage_floor_kb: the MemAvailable floor in kB from APR; prints nothing and returns 1 unless it is an integer inside the
# schema bounds (migration 622: 8 to 512 GiB), so a value written around ConfigService cannot switch the gate off.
stage_floor_kb() {
  local gib; gib=$("${PSQL[@]}" "select config_value from config_state where config_key='$FLOOR_KEY'") || return 1
  case "$gib" in ""|*[!0-9]*) return 1;; esac
  gib=$((10#$gib))
  { [ "$gib" -ge 8 ] && [ "$gib" -le 512 ]; } || return 1
  echo $((gib * 1024 * 1024))
}

# timers_quiesced_gate: every blocking timer is disabled or masked and inactive, the runner's own rule (QUIET_ENABLED_STATES in
# services/corpus_rerun_quiesce.py): any other enablement state, an unreadable one included, can fire during the stage.
timers_quiesced_gate() {
  local units u
  units=$(blocking_timer_units) || { fail "cannot read the blocking timers from APR"; return 1; }
  while read -r u; do
    [ -n "$u" ] || continue
    case "$(systemctl is-enabled "$u" 2>/dev/null)" in
      disabled|masked) ;;
      *) fail "$u is not disabled or masked: quiesce first (python -m services.corpus_rerun --quiesce)";;
    esac
    [ "$(systemctl is-active "$u" 2>/dev/null)" != active ] || fail "$u is active: quiesce first (python -m services.corpus_rerun --quiesce)"
  done <<< "$units"
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0     # sourced by a test: functions only

RUN=${1:?run id}; EXPECT=${2:?expected rebuild_code_key prefix}
[ -n "$CHECK" ] || { : >> "$STATUS"; exec 2>> "$STATUS"; run_resource_scope bash "$0" "$@"; }   # a check writes nothing; the launcher then runs in one user scope
CR="$PY -m services.corpus_rerun"
WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"

stage_preflight() {   # a launch exits at the first refusal; --check goes on and reports all (it returns early only when no gate can be read)
  echo "$RUN" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || { fail "run id $RUN is not a uuid"; return 1; }
  [ -d "$WT" ] || { fail "no worktree $WT for run $RUN"; return 1; }
  local scope recorded head_now key reason floor_kb
  scope=$("${PSQL[@]}" "select measured->>'data_gate_scope' from corpus_run where run_id='$RUN'")
  recorded=$("${PSQL[@]}" "select code_commit from corpus_run where run_id='$RUN'")
  head_now=$(git -C "$WT" rev-parse HEAD 2>/dev/null)
  key=$(cd "$WT" && "$PY" -c "import sys; sys.path.insert(0,'.'); from services.backfill_feature_factory import rebuild_code_key; print(rebuild_code_key())") \
    || { fail "cannot compute rebuild_code_key in $WT"; return 1; }
  reason=$(stage_preflight_judge "$scope" "$(step_status pilot)" "$(step_status feature_complete)" "$head_now" "$recorded" "$key" "$EXPECT") \
    || fail "preflight: $reason"   # a check goes on: the gates below are independent of the run's state
  grep -q -E "block2 compare: (IDENTICAL|ACCEPTED)" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
  apr_value_gate infra.feature_factory.workers 4
  apr_value_gate alpha.ic.feature_block_columns 16 "the run pins it; ic_measure_launch.sh refuses any other width"
  if floor_kb=$(stage_floor_kb); then MEM_FLOOR_KB=$floor_kb; else fail "$FLOOR_KEY is not a positive integer in APR"; fi
  timers_quiesced_gate
  host_gate
  verdict_preflight
  [ -n "$CHECK" ] || log "stage preflight ok: run $RUN code key ${key:0:12} mem floor $((MEM_FLOOR_KB / 1048576)) GiB"
}
step_status() { "${PSQL[@]}" "select status from corpus_run_step where run_id='$RUN' and step='$1'"; }

stage_preflight
if [ -n "$CHECK" ]; then
  if [ -d "$WT" ]; then (cd "$WT" && $CR --run-id "$RUN" --check --step stage_1d) || fail "services.corpus_rerun --check refused (above)"; fi
  refusals_report
  exit $?
fi

GUARDED_RUN_ID=$RUN   # the validated run id labels the run_resource gauges
cd "$WT" || fail "cd worktree"
GUARDED_STAGE=stage_1d run_guarded "$REPO/logs/corpus_stage_$RUN.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through "$THROUGH"
rc=$?; log "stage exit=$rc run=$RUN (rss_mb per 20 s is in $TEMPLOG)"
cd "$REPO" || exit 3
if [ "$rc" -eq 0 ]; then
  log "stage_1d complete, timers held for ic_measure, release after it (ic_measure_launch.sh releases on its own clean exit)"
else
  log "timers held: run $RUN (stage exit=$rc); resume with: bash scripts/ops/corpus_stage_launch.sh $RUN $EXPECT; release with --release after the run is abandoned"
fi
exit "$rc"
