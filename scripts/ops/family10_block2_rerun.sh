#!/usr/bin/env bash
# Rerun family 10 battery block 2 (seed base 12,000,000, commit 48a65742d) and compare it with the
# recorded block2.json, which finished 50 s after the first memory-corruption event (DIMMs at 117C).
# Seeds are by position, so the worker count does not change a result. NOT RUN.
# Usage: setsid -f bash family10_block2_rerun.sh
set -u
. "$(dirname "$0")/guarded_run_common.sh"
: >> "$STATUS"; exec 2>> "$STATUS"
COMMIT=48a65742d44e5357b181a042d495c4d38a6d946f
WT=$SCRATCH/wt-f10block2
OUT=$SCRATCH/block2_rerun.json
RECORDED=$REPO/logs/e17_family10_s12m/block2.json
host_gate
hold_timers
cd "$REPO" && git worktree prune && rm -rf "$WT"
git worktree add --detach "$WT" "$COMMIT" >/dev/null || fail "worktree"
cd "$WT" || fail "cd"; ln -s "$REPO/.venv" .venv
log "block2 rerun start workers=$WORKERS"
run_guarded "$SCRATCH/block2_rerun.out" "$PY" scripts/research/e17_null_battery.py "$OUT" --sims 1000 \
  --workers "$WORKERS" --battery src.intelligence.research.null_battery_volume_shock --seed-base 12000000
rc=$?; log "block2 rerun exit=$rc"; [ $rc -eq 0 ] || exit $rc
"$PY" - "$RECORDED" "$OUT" >> "$STATUS" <<'PY'
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
drop = ("seconds",)
for d in (a, b):
    for k in drop: d.pop(k, None)
print("block2 compare:", "IDENTICAL" if a == b else "DIFFERENT",
      [k for k in a if a.get(k) != b.get(k)])
PY
