#!/usr/bin/env bash
# First IC measure at the scope-1d pin (todo 471), guarded: quiesce -> ic_measure step of the corpus run under the
# DIMM watchdog and RSS log -> release timers. docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash ic_measure_launch.sh <run_id> <expected_rebuild_code_key_prefix>
# Env:   PREFLIGHT_ONLY=1   read-only checks, print the verdict on the terminal, exit; no host gate, no timers touched.
#        RSS_CHECK=1        first run `ic_measure --tf 1d --dry-run` on the 25 names in $RSS_SYMBOLS_FILE (one per line)
#                           under the watchdog, record the peak rss_mb in the status file, then stop (the lead reads it).
# The block width is never a flag: `alpha.ic.feature_block_columns` is read from APR and must be 16 (todo 471 ruling
# 2026-11-24); the run pins it in its apr_hash. Only the 1d timeframe is measured: the run's recorded scope must be 1d.
# Preconditions: pilot and feature_complete completed for the run at this pin, memtester_clean present, no heavy job live.
set -u
. "$(dirname "$0")/guarded_run_common.sh"
WIDTH_KEY=alpha.ic.feature_block_columns
WIDTH_RULED=16

# ic_preflight_judge <scope> <width> <pilot> <feature_complete> <ic_measure> <worktree_head> <recorded_commit> <key> <expect>
# Pure: prints the reason and returns 1 on the first refusal, returns 0 when the run may be measured.
ic_preflight_judge() {
  local scope=$1 width=$2 pilot=$3 fc=$4 icm=$5 head=$6 recorded=$7 key=$8 expect=$9
  [ "$scope" = "1d" ] || { echo "run scope is '$scope', only a scope-1d run is measured (ic_tfs 1d, todo 471)"; return 1; }
  [ "$width" = "$WIDTH_RULED" ] || { echo "$WIDTH_KEY is '$width', ruled $WIDTH_RULED for the scope-1d pin (set before --new-run; the run pins it)"; return 1; }
  [ "$pilot" = "completed" ] || { echo "pilot step is '$pilot', not completed"; return 1; }
  [ "$fc" = "completed" ] || { echo "feature_complete step is '$fc', not completed"; return 1; }
  [ "$icm" != "completed" ] || { echo "ic_measure already completed for this run"; return 1; }
  [ -n "$recorded" ] && [ "$head" = "$recorded" ] || { echo "worktree HEAD '$head' is not the run's code_commit '$recorded'"; return 1; }
  case "$key" in "$expect"?*) ;; *) echo "rebuild_code_key '$key' does not start with '$expect'"; return 1;; esac
}

# peak_rss_mb_since <file> <line_count_before>: the largest rss_mb the watchdog logged after that line.
peak_rss_mb_since() {
  local peak
  peak=$(tail -n +"$(($2 + 1))" "$1" 2>/dev/null | sed -n 's/.* rss_mb=\([0-9]*\) .*/\1/p' | sort -n | tail -1)
  echo "${peak:-unknown}"
}

[ "${BASH_SOURCE[0]}" = "$0" ] || return 0     # sourced by the test: functions only

RUN=${1:?run id}; EXPECT=${2:?expected rebuild_code_key prefix}
echo "$RUN" | grep -qE '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || { echo "run id $RUN is not a uuid"; exit 3; }
[ -z "${PREFLIGHT_ONLY:-}" ] || STATUS=/dev/stdout   # preflight talks to the terminal, never the run's status file
: >> "$STATUS"; exec 2>> "$STATUS"
CR="$PY -m services.corpus_rerun"
PSQL=(psql -U postgres -h localhost -d indicagent -tAc)
export PGPASSWORD=postgres
cd "$REPO" || fail "cd repo"
WT="$(dirname "$REPO")/$(basename "$REPO")-corpus-run-$RUN"
[ -d "$WT" ] || fail "no worktree $WT for run $RUN"

# One live heavy job at a time, also under PREFLIGHT_ONLY, which skips host_gate (whose list now holds these too).
pgrep -f 'python.*(services\.corpus_rerun|services\.ic_measure|ic_sweep_recorder|backfill_feature_factory)' >/dev/null && fail "a corpus run, ic_measure or rebuild process is live"
window_gate 5

scope=$("${PSQL[@]}" "select measured->>'data_gate_scope' from corpus_run where run_id='$RUN'") || fail "corpus_run query"
recorded=$("${PSQL[@]}" "select code_commit from corpus_run where run_id='$RUN'")
width=$("${PSQL[@]}" "select config_value from config_state where config_key='$WIDTH_KEY'")
step() { "${PSQL[@]}" "select status from corpus_run_step where run_id='$RUN' and step='$1'"; }
head_now=$(git -C "$WT" rev-parse HEAD)
key=$(cd "$WT" && "$PY" -c "import sys; sys.path.insert(0,'.'); from services.backfill_feature_factory import rebuild_code_key; print(rebuild_code_key())") \
  || fail "cannot compute rebuild_code_key in $WT"
reason=$(ic_preflight_judge "$scope" "$width" "$(step pilot)" "$(step feature_complete)" "$(step ic_measure)" "$head_now" "$recorded" "$key" "$EXPECT") \
  || fail "preflight: $reason"
log "ic_measure preflight ok: run $RUN scope $scope width $width code key ${key:0:12}"
[ -z "${PREFLIGHT_ONLY:-}" ] || exit 0

grep -q -E "block2 compare: (IDENTICAL|ACCEPTED)" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
host_gate 5
verdict_preflight

if [ -n "${RSS_CHECK:-}" ]; then
  [ -s "${RSS_SYMBOLS_FILE:-}" ] || fail "RSS_CHECK needs RSS_SYMBOLS_FILE (25 names, one per line)"
  [ "$(wc -l < "$RSS_SYMBOLS_FILE")" -eq 25 ] || fail "RSS_SYMBOLS_FILE must hold exactly 25 names"
  mapfile -t names < "$RSS_SYMBOLS_FILE"
  before=$(wc -l < "$TEMPLOG" 2>/dev/null || echo 0)
  cd "$WT" || fail "cd worktree"
  run_guarded "$SCRATCH/ic_measure_rss_$RUN.out" "$PY" -m services.ic_measure --tf 1d --dry-run --symbols "${names[@]}"
  rc=$?; log "ic_measure rss check exit=$rc width=$width peak_rss_mb=$(peak_rss_mb_since "$TEMPLOG" "$before") symbols=25 (record in todo 471)"
  exit "$rc"
fi

log "quiesce"; $CR --quiesce >> "$STATUS" 2>&1 || { $CR --release >> "$STATUS" 2>&1; fail "quiesce failed"; }
cd "$WT" || { $CR --release >> "$STATUS" 2>&1; fail "cd worktree"; }
before=$(wc -l < "$TEMPLOG" 2>/dev/null || echo 0)
run_guarded "$SCRATCH/ic_measure_$RUN.out" "$PY" -m services.corpus_rerun --run-id "$RUN" --through ic_measure
rc=$?; log "ic_measure exit=$rc run=$RUN width=$width peak_rss_mb=$(peak_rss_mb_since "$TEMPLOG" "$before")"
cd "$REPO" || exit 3
if [ "$rc" -eq 0 ]; then
  $CR --release >> "$STATUS" 2>&1; log "timers released"
else
  log "timers held: run $RUN (ic_measure exit=$rc); resume with: bash scripts/ops/ic_measure_launch.sh $RUN $EXPECT; release with --release after the run is abandoned"
fi
exit "$rc"
