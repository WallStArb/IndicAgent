#!/usr/bin/env bash
# Rerun family 10 battery block 2 (seed base 12,000,000, commit 48a65742d) and compare it with the
# recorded block2.json, which finished 50 s after the first memory-corruption event (DIMMs at 117C).
# Seeds are by position, so the worker count does not change a result. NOT RUN.
# Usage: setsid -f bash family10_block2_rerun.sh
set -u
unset COLLECT_REFUSALS   # collect mode is corpus_pilot.sh --check only: an inherited value would make every fail() return
. "$(dirname "$0")/guarded_run_common.sh"
: >> "$STATUS"; exec 2>> "$STATUS"
run_resource_scope bash "$0" "$@"   # the whole launcher in one user scope (todo 681)
COMMIT=$BLOCK2_COMMIT   # the pin of the comparison line, defined once in guarded_run_common.sh
WT=$SCRATCH/wt-f10block2
OUT=$SCRATCH/block2_rerun.json
RECORDED=$REPO/logs/e17_family10_s12m/block2.json
host_gate
hold_timers
cd "$REPO" && git worktree prune && rm -rf "$WT"
git worktree add --detach "$WT" "$COMMIT" >/dev/null || fail "worktree"
cd "$WT" || fail "cd"; ln -s "$REPO/.venv" .venv
log "block2 rerun start workers=$WORKERS"
GUARDED_STAGE=block2 run_guarded "$SCRATCH/block2_rerun.out" "$PY" scripts/research/e17_null_battery.py "$OUT" --sims 1000 \
  --workers "$WORKERS" --battery src.intelligence.research.null_battery_volume_shock --seed-base 12000000
rc=$?; log "block2 rerun exit=$rc"; [ $rc -eq 0 ] || exit $rc
"$PY" "$REPO/scripts/ops/block2_compare.py" "$RECORDED" "$OUT" "$COMMIT" >> "$STATUS"   # from $REPO: the worktree is the old battery commit
