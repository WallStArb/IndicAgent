#!/usr/bin/env bash
# D-191-P follow-on (2026-10-26): after the 5m reselect exits, re-derive the 15m/1h grid of the
# reselected names in full (their 5m changed without a new vendor answer, so --changed-only would
# skip them), then run the selection gate over every 5m series. One-shot; logs to
# logs/d191p_followon_20261027.log. Delete after D-191-P closes.
set -u
cd /home/bg/dev/indicagent || exit 1
LOG=logs/d191p_followon_20261027.log
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }
PID="$1"
log "waiting for reselect pid $PID"
while kill -0 "$PID" 2>/dev/null; do sleep 60; done
log "reselect exited; tail: $(tail -1 logs/d191p_reselect_20261027.log)"
SYMS=$( { echo A; cat data/policy_plans/2026-10-26-d191p-reselect-symbols.txt; } | tr '\n' ' ')
log "grid derivation (full) over the reselected names"
.venv/bin/python -m services.bar_derivation --stage grid --symbols $SYMS --apply >>"$LOG" 2>&1
log "grid exit $?"
log "selection gate --compare over all 5m"
.venv/bin/python -m scripts.ops.bars.ops_selection_gate --compare --timeframes 5m >>"$LOG" 2>&1
log "gate exit $?"
