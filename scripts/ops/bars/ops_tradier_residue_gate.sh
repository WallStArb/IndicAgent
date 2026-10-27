#!/usr/bin/env bash
# Plan 191-19 readiness gate (todo 533 step 10): hourly readiness check; when it exits 0,
# runs the read-only measure/prove/report sequence that writes 191-TRADIER-RESIDUE.md.
# Commits and plan 20 remain human/session work. Never launches anything else.
set -u
cd /home/bg/dev/indicagent || exit 1
PY=/home/bg/dev/indicagent/.venv/bin/python
LOG=logs/191_19_gate.log
STATE=logs/191_19_gate.state
REPORT=.planning/phases/191-unified-raw-bar-table/191-TRADIER-RESIDUE.md
FROZEN=MOD,PSKY  # holds a listing end does not describe; QRVO, WBD, CCO come from listing_end (518)
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }

[ -f "$STATE" ] && grep -q done "$STATE" && exit 0

"$PY" -m scripts.ops.bars.ops_tradier_residue --readiness --frozen-names "$FROZEN" >/tmp/r191.json 2>/tmp/r191.err
rc=$?
if [ "$rc" -eq 2 ]; then
  log "not ready: $("$PY" -c 'import json,sys;d=json.load(open(sys.argv[1]));print("settled",d["n_settled"],"unsettled",d["n_unsettled"])' /tmp/r191.json 2>/dev/null)"
  exit 0
fi
if [ "$rc" -ne 0 ]; then
  log "readiness FAILED rc=$rc: $(tail -c 200 /tmp/r191.err)"
  exit 0
fi
log "readiness green, running measure/prove/report"
"$PY" -m scripts.ops.bars.ops_tradier_residue --measure --frozen-names "$FROZEN" --out logs/191-19/measure.json >>"$LOG" 2>&1 || { log "measure FAILED"; exit 0; }
"$PY" -m scripts.ops.bars.ops_tradier_residue --prove --frozen-names "$FROZEN" --out logs/191-19/prove.json >>"$LOG" 2>&1 || log "prove exited nonzero (unproven names recorded in the payload)"
"$PY" -m scripts.ops.bars.ops_tradier_residue --report >>"$LOG" 2>&1 || { log "report FAILED"; exit 0; }
echo done >"$STATE"
log "residue report written to $REPORT; ready for session review and plan 20 (owner checkpoint)"
