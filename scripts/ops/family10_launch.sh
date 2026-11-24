#!/usr/bin/env bash
# Family 10 (E24) counted runs, relaunch recipe (ledger 2026-11-24a). Born from the 2026-11-23 DIMM fault; docs/operations/guarded-run-runbook.md.
# Usage: setsid -f bash family10_launch.sh [spec ...]   (default: primary then core; WORKERS=4 default)
# Preconditions: memtester_clean file, DIMMs <= 60C, family10_block2_rerun.sh reported IDENTICAL, lead go.
set -u
. "$(dirname "$0")/guarded_run_common.sh"
: >> "$STATUS"; exec 2>> "$STATUS"
WT=$SCRATCH/wt-f10run
BOUND=c0832b091
SPECS=("$@"); [ ${#SPECS[@]} -gt 0 ] || SPECS=(family10_volume_shock_h5 family10_volume_shock_h5_core)
grep -q "block2 compare: IDENTICAL" "$STATUS" || fail "no IDENTICAL block 2 comparison in the status file"
host_gate
cd "$REPO" && git fetch -q origin || fail "fetch"
git diff --quiet "$BOUND" origin/main -- src/intelligence/research src/intelligence/statistics research config || fail "research code or specs differ from $BOUND (the run itself builds from $BOUND)"
[ -f research/battery_passes/family10_volume_shock_2026-11-24.json ] || fail "battery record missing"

rm -rf "$WT"; git worktree prune
git worktree add --detach "$WT" "$BOUND" >/dev/null || fail "worktree"
cd "$WT" || fail "cd worktree"
ln -s "$REPO/.venv" .venv; ln -sfn "$REPO/logs" logs
[ -z "$(git status --porcelain | grep -v -E '^\?\? (\.venv|logs)$')" ] || fail "worktree not clean"

run_guarded "$SCRATCH/repro_frozen.out" "$PY" -m scripts.research.determinism.repro_frozen "$SCRATCH/repro" --logs "$REPO/logs"
rc=$?; log "repro_frozen exit=$rc"
{ [ $rc -eq 0 ] && grep -q "bit-identical" "$SCRATCH/repro_frozen.out"; } || fail "repro_frozen not bit-identical"

for spec in "${SPECS[@]}"; do
  [ -f "$REPO/logs/${spec}_run.out" ] && mv "$REPO/logs/${spec}_run.out" "$REPO/logs/${spec}_run.prev.$(date -u +%s).out"
  log "start $spec workers=$WORKERS"
  run_guarded "$REPO/logs/${spec}_run.out" "$PY" scripts/research/run_spec.py --spec "research/specs/${spec}.yaml" --workers "$WORKERS"
  rc=$?; log "$spec exit=$rc"
  [ $rc -eq 0 ] || break
done
