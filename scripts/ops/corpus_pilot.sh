#!/usr/bin/env bash
# Corpus pilot launcher (scope 1d): quiesce -> new run -> pilot under the DIMM watchdog and RSS log
# -> release timers. See docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash corpus_pilot.sh <expected_rebuild_code_key_prefix> [commit_sha]
#        setsid -f bash corpus_pilot.sh --resume <run_id>   (same run, same pin; timers already held)
# Preconditions: block 2 compare IDENTICAL in the status file; memtester_clean present; the lead has
# set infra.feature_factory.workers to 4 (config_history reason recorded); no heavy job live.
set -u
. "$(dirname "$0")/guarded_run_common.sh"
: >> "$STATUS"; exec 2>> "$STATUS"
CR="$PY -m services.corpus_rerun"
cd "$REPO" || fail "cd repo"
RESUME=""
if [ "${1:-}" = "--resume" ]; then RESUME=${2:?run id}; else EXPECT=${1:?expected rebuild_code_key prefix}; COMMIT=${2:-}; fi

grep -q -E "block2 compare: (IDENTICAL|ACCEPTED)" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
workers_now=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "select config_value from config_state where config_key='infra.feature_factory.workers'")
[ "$workers_now" = "4" ] || fail "infra.feature_factory.workers is $workers_now, expected 4"
host_gate
# the pilot must end before the Alpaca nightly (04:40Z); refuse to start inside the last 3 hours
now_h=$(date -u +%H); [ "$now_h" -lt 1 ] || [ "$now_h" -ge 5 ] || fail "inside the 04:40Z nightly window"
verdict_preflight
if [ -n "$RESUME" ]; then
  RUN=$RESUME
  WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"
  [ -d "$WT" ] || fail "no worktree $WT for run $RUN"
  echo "$RUN" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || fail "run id $RUN is not a uuid"
  recorded=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "select code_commit from corpus_run where run_id='$RUN'")
  [ -n "$recorded" ] || fail "no corpus_run row for $RUN"
  head_now=$(git -C "$WT" rev-parse HEAD)
  [ "$head_now" = "$recorded" ] || fail "worktree HEAD $head_now is not the run's recorded code_commit $recorded"
  log "pilot resume preflight ok: run $RUN"
  cd "$WT" || fail "cd worktree"
  run_guarded "$REPO/logs/corpus_pilot_${RUN}_resume.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through pilot
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
WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"
log "run $RUN worktree $WT"

cd "$WT" || { $CR --release >> "$STATUS" 2>&1; fail "cd worktree"; }
run_guarded "$REPO/logs/corpus_pilot_$RUN.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through pilot
rc=$?; log "pilot exit=$rc run=$RUN (rss_mb per 20 s is in $TEMPLOG)"
cd "$REPO" || exit 3
if [ "$rc" -eq 0 ]; then
  $CR --release >> "$STATUS" 2>&1; log "timers released"
else
  log "timers held: run $RUN (pilot exit=$rc); resume with: bash scripts/ops/corpus_pilot.sh --resume $RUN; release with --release after the run is abandoned"
fi
