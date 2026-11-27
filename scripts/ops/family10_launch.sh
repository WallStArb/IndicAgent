#!/usr/bin/env bash
# Family 10 (E24) counted runs, relaunch recipe (ledger 2026-11-24a). Born from the 2026-11-23 DIMM fault; docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash family10_launch.sh [spec ...]   (default: primary then core; WORKERS=4 default)
# Preconditions: memtester_clean file, DIMMs <= 60C, family10_block2_rerun.sh reported IDENTICAL, lead go.
# LAUNCH_COMMIT (default BOUND) is the commit the runs build from: it must be on origin/main, its battery key must equal the
# bound record (the runner's own static_gate), its spec hashes must equal the recorded rows' and StepM must be the attested one.
# PREFLIGHT_ONLY=1 stops after those checks. It writes only: a `git fetch` (remote-tracking refs), a throwaway worktree
# $SCRATCH/wt-f10pre-<pid> removed on exit, and its messages on the terminal (not the status file). It never touches the live
# run's worktree path, prunes nothing, skips the host gate and repro_frozen, and refuses while a run_spec process is live.
set -u
unset COLLECT_REFUSALS   # collect mode is corpus_pilot.sh --check only: an inherited value would make every fail() return
. "$(dirname "$0")/guarded_run_common.sh"
[ -z "${PREFLIGHT_ONLY:-}" ] || STATUS=/dev/stdout   # preflight talks to the terminal, never the run's status file
: >> "$STATUS"; exec 2>> "$STATUS"
[ -n "${PREFLIGHT_ONLY:-}" ] || run_resource_scope bash "$0" "$@"   # the whole launcher in one user scope (todo 681)
WT=$SCRATCH/wt-f10run
if [ -n "${PREFLIGHT_ONLY:-}" ]; then
  pgrep -f 'python.*run_spec' >/dev/null && fail "a run_spec process is live: preflight refuses while a counted run may use the shared checkout"
  WT=$SCRATCH/wt-f10pre-$$
  trap 'git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1' EXIT
fi
BOUND=c0832b091
SPECS=("$@"); [ ${#SPECS[@]} -gt 0 ] || SPECS=(family10_volume_shock_h5 family10_volume_shock_h5_core)
LAUNCH=${LAUNCH_COMMIT:-$BOUND}
if [ -z "${PREFLIGHT_ONLY:-}" ]; then
  grep -q -E "block2 compare: (IDENTICAL|ACCEPTED)" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
  host_gate
fi
cd "$REPO" && git fetch -q origin || fail "fetch"
git cat-file -e "$LAUNCH^{commit}" && git merge-base --is-ancestor "$LAUNCH" origin/main || fail "$LAUNCH is not a commit on origin/main (code_commit and spec_blob must resolve for the StepM read)"
git diff --quiet "$LAUNCH" origin/main -- src/intelligence/research src/intelligence/statistics research config || fail "research code or specs differ from $LAUNCH (the run itself builds from $LAUNCH)"
[ -f research/battery_passes/family10_volume_shock_2026-11-24.json ] || fail "battery record missing"

[ -n "${PREFLIGHT_ONLY:-}" ] || { rm -rf "$WT"; git worktree prune; }
git worktree add --detach "$WT" "$LAUNCH" >/dev/null || fail "worktree"
cd "$WT" || fail "cd worktree"
ln -s "$REPO/.venv" .venv; ln -sfn "$REPO/logs" logs
[ -z "$(git status --porcelain | grep -v -E '^\?\? (\.venv|logs)$')" ] || fail "worktree not clean"

# Preflight (light, read-only): what recording the StepM read needs (todo 636).
STEPM_ATTESTED=$("$PY" -c "import json;print(json.load(open('research/certificates/records/stepm_null_battery_s4000_2026-11-23.json'))['stepm_sha256'])")
[ "$(sha256sum src/intelligence/statistics/stepm.py | cut -d' ' -f1)" = "$STEPM_ATTESTED" ] || fail "stepm.py is not the attested StepM (research/certificates/records): the read would refuse"
declare -A HASH
for spec in "${SPECS[@]}"; do
  HASH[$spec]=$("$PY" - "research/specs/${spec}.yaml" <<'PY'
import sys
from pathlib import Path
from src.intelligence.research import runner
from src.intelligence.research.spec import load_spec_from_file
loaded = load_spec_from_file(Path(sys.argv[1]))
runner.static_gate(loaded.model, require_pass=True)  # the battery key must equal the bound record, as at run time
print(loaded.spec_hash)
PY
  ) || fail "$spec: battery pass is not current at $LAUNCH (runner.static_gate refused)"
  recorded=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tA -c "SELECT DISTINCT spec_hash FROM research_run WHERE spec_path = 'research/specs/${spec}.yaml'") || fail "$spec: ledger query failed"
  [ -z "$recorded" ] || [ "$recorded" = "${HASH[$spec]}" ] || fail "$spec: spec hash ${HASH[$spec]} differs from the recorded rows ($recorded): the earlier killed rows would become gaps in the StepM read"
  log "preflight $spec hash=${HASH[$spec]:0:10} battery ok"
done
[ -z "${PREFLIGHT_ONLY:-}" ] || { log "preflight OK at $LAUNCH"; exit 0; }

GUARDED_STAGE=repro_frozen run_guarded "$SCRATCH/repro_frozen.out" "$PY" -m scripts.research.determinism.repro_frozen "$SCRATCH/repro" --logs "$REPO/logs"
rc=$?; log "repro_frozen exit=$rc"
{ [ $rc -eq 0 ] && grep -q "bit-identical" "$SCRATCH/repro_frozen.out"; } || fail "repro_frozen not bit-identical"
hold_timers   # the counted runs read bars: no timer restates them while a run is live; any exit releases

for spec in "${SPECS[@]}"; do
  [ -f "$REPO/logs/${spec}_run.out" ] && mv "$REPO/logs/${spec}_run.out" "$REPO/logs/${spec}_run.prev.$(date -u +%s).out"
  log "start $spec workers=$WORKERS"
  GUARDED_STAGE=$spec run_guarded "$REPO/logs/${spec}_run.out" "$PY" scripts/research/run_spec.py --spec "research/specs/${spec}.yaml" --workers "$WORKERS"
  rc=$?; log "$spec exit=$rc"
  [ $rc -eq 0 ] || break
  # exit 0 means every row reached a terminal status (refused and guard_failed included); the StepM read needs a series on every member
  want=$(grep -c '^  - name:' "research/specs/${spec}.yaml")
  have=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tA -c "SELECT count(*) FROM research_run r JOIN research_run_series s USING (run_id) WHERE r.spec_path = 'research/specs/${spec}.yaml' AND r.spec_hash = '${HASH[$spec]}' AND r.mode = 'real' AND r.status = 'completed'")
  log "$spec series check: $have of $want members completed with a series"
  [ "$have" = "$want" ] || { log "ABORT $spec recorded $have of $want series; do not run the StepM read"; break; }
done
