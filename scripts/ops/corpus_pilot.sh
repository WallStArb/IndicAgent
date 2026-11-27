#!/usr/bin/env bash
# Corpus pilot launcher (scope 1d): quiesce -> new run -> pilot under the DIMM watchdog and RSS log
# -> release timers. See docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash corpus_pilot.sh <expected_rebuild_code_key_prefix> [commit_sha]
#        setsid -f bash corpus_pilot.sh --resume <run_id>   (same run, same pin; timers already held)
#        bash corpus_pilot.sh --check [--resume <run_id>]   (every refusal a launch would meet, read-only, at once)
# Preconditions: block 2 compare IDENTICAL in the status file; memtester_clean present; the lead has
# set infra.feature_factory.workers to 4 (config_history reason recorded); no heavy job live.
set -u
CHECK=""; unset COLLECT_REFUSALS   # set here on --check only: an inherited value would make every fail() return
if [ "${1:-}" = "--check" ]; then CHECK=1; COLLECT_REFUSALS=1; shift; fi   # before sourcing: collect mode reads it there
. "$(dirname "$0")/guarded_run_common.sh"
[ -n "$CHECK" ] || { : >> "$STATUS"; exec 2>> "$STATUS"; run_resource_scope bash "$0" "$@"; }   # a check writes nothing, not even the status file; the launcher then runs in one user scope (todo 681)
CR="$PY -m services.corpus_rerun"
cd "$REPO" || fail "cd repo"
RESUME=""
if [ "${1:-}" = "--resume" ]; then RESUME=${2:?run id}; elif [ -z "$CHECK" ]; then EXPECT=${1:?expected rebuild_code_key prefix}; COMMIT=${2:-}; fi

grep -q -E "block2 compare: (IDENTICAL|ACCEPTED)" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
apr_value_gate infra.feature_factory.workers 4
# The run pins the IC block width in its apr_hash at --new-run and ic_measure_launch.sh refuses any other width (todo 471);
# a wrong value found there costs a repeat of stage_1d, so the pilot refuses at minute zero. Keep in step with WIDTH_RULED there.
apr_value_gate alpha.ic.feature_block_columns 16 "the run pins it; ic_measure_launch.sh refuses any other width"
host_gate
# host_gate also refuses inside the 01:00 to 05:00Z nightly window and while a blocking timer's service runs
verdict_preflight
if [ -n "$CHECK" ]; then   # the run-side checks: the same gates the launch meets (services/corpus_rerun_check.py)
  scope_gate
  if [ -n "$RESUME" ]; then
    WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RESUME"
    if [ -d "$WT" ]; then (cd "$WT" && $PY -m services.corpus_rerun --run-id "$RESUME" --check) || fail "services.corpus_rerun --check refused (above)"
    else fail "no worktree $WT for run $RESUME"; fi
  else
    # the check plans batch keys from the checked-out code while the launch pulls first: a stale checkout
    # would plan the old pin's keys, see the old run's units as adopted and pass (read-only: no fetch). It
# checks the default commit (origin/main); a launch given a commit_sha pins that commit instead.
    head=$(git rev-parse HEAD 2>/dev/null); remote=$(git ls-remote origin refs/heads/main 2>/dev/null | cut -f1)
    { [ -n "$remote" ] && [ "$head" = "$remote" ]; } || fail "main checkout HEAD ${head:-unknown} is not origin/main ${remote:-unreadable}: pull, then check"
    [ -z "$(git status --porcelain --untracked-files=no 2>/dev/null)" ] || fail "main checkout has uncommitted tracked edits: the check would plan keys from code the launch does not pin"
    $CR --new-run --check --data-gate-scope 1d || fail "services.corpus_rerun --new-run --check refused (above)"
  fi
  refusals_report
  exit $?
fi
if [ -n "$RESUME" ]; then
  RUN=$RESUME; GUARDED_RUN_ID=$RUN   # the run id is validated as a uuid just below
  WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"
  [ -d "$WT" ] || fail "no worktree $WT for run $RUN"
  echo "$RUN" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || fail "run id $RUN is not a uuid"
  recorded=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "select code_commit from corpus_run where run_id='$RUN'")
  [ -n "$recorded" ] || fail "no corpus_run row for $RUN"
  head_now=$(git -C "$WT" rev-parse HEAD)
  [ "$head_now" = "$recorded" ] || fail "worktree HEAD $head_now is not the run's recorded code_commit $recorded"
  log "pilot resume preflight ok: run $RUN"
  cd "$WT" || fail "cd worktree"
  GUARDED_STAGE=pilot run_guarded "$REPO/logs/corpus_pilot_${RUN}_resume.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through pilot
  rc=$?; log "pilot resume exit=$rc run=$RUN (rss_mb per 20 s is in $TEMPLOG)"
  cd "$REPO" || exit 3
  if [ "$rc" -eq 0 ]; then
    $CR --release >> "$STATUS" 2>&1; log "timers released"
  else
    log "timers held: run $RUN (pilot resume exit=$rc); resume with --resume $RUN, release with --release after the run is abandoned"
  fi
  exit "$rc"
fi
git fetch -q origin && git pull -q --ff-only || fail "main checkout not fast-forwardable"
SHA=${COMMIT:-$(git rev-parse HEAD)}
key=$($PY -c "import sys; sys.path.insert(0,'.'); from services.backfill_feature_factory import rebuild_code_key; print(rebuild_code_key())")
case "$key" in "$EXPECT"*) ;; *) fail "rebuild_code_key $key does not start with $EXPECT; the pin would not match the plan";; esac
log "pilot preflight ok: commit $SHA code key ${key:0:12}"

log "quiesce"; $CR --quiesce >> "$STATUS" 2>&1 || { log "quiesce failed"; $CR --release >> "$STATUS" 2>&1; fail "quiesce failed"; }
out=$($CR --new-run --data-gate-scope 1d --commit "$SHA" 2>&1) || { echo "$out" >> "$STATUS"; $CR --release >> "$STATUS" 2>&1; fail "new-run failed"; }
echo "$out" >> "$STATUS"
RUN=$(echo "$out" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)
[ -n "$RUN" ] || { $CR --release >> "$STATUS" 2>&1; fail "no run id in the new-run output"; }
GUARDED_RUN_ID=$RUN   # matched the uuid pattern above
WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"
log "run $RUN worktree $WT"

cd "$WT" || { $CR --release >> "$STATUS" 2>&1; fail "cd worktree"; }
GUARDED_STAGE=pilot run_guarded "$REPO/logs/corpus_pilot_$RUN.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through pilot
rc=$?; log "pilot exit=$rc run=$RUN (rss_mb per 20 s is in $TEMPLOG)"
cd "$REPO" || exit 3
if [ "$rc" -eq 0 ]; then
  $CR --release >> "$STATUS" 2>&1; log "timers released"
else
  log "timers held: run $RUN (pilot exit=$rc); resume with: bash scripts/ops/corpus_pilot.sh --resume $RUN; release with --release after the run is abandoned"
fi
exit "$rc"
