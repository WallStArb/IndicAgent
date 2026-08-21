#!/usr/bin/env bash
# Relaunched 2026-08-21 -- the original todo-335 watcher (PID 2737924, launched 2026-08-20
# via nohup+disown) is confirmed dead (not in `ps`, its log stayed 0 bytes) with no trace of
# ever running. `disown` alone doesn't survive a terminal/session teardown; `setsid` here fully
# detaches from any controlling terminal so this one does.
#
# Purpose: once the in-flight corpus pipeline run (wrapper PID 1887017,
# `ops_corpus_pipeline_run.sh --from-step 5`) exits, launch the todo-335 recompute
# (`--from-step 4`) so the corrected commodity/fx regime_signals tier fix (commit db98ac0a3)
# actually reaches `market_regimes` and downstream `ic_engine`/`ic_shrinkage`/`ensemble_trainer`/
# `alpha_publisher` -- the run in flight was launched with `--from-step 5`, which skips step 4
# and is consuming pre-fix, still-mislabeled commodity/fx rows.
set -euo pipefail

WRAPPER_PID=1887017
REPO_DIR="/home/bg/dev/indicagent"
WATCHER_LOG="${REPO_DIR}/logs/todo335_recompute_watcher.log"
POLL_SECONDS=300

cd "$REPO_DIR"

echo "$(date -u +%FT%TZ) watcher (re)started, watching PID ${WRAPPER_PID}" >> "$WATCHER_LOG"

while kill -0 "$WRAPPER_PID" 2>/dev/null; do
    sleep "$POLL_SECONDS"
done

echo "$(date -u +%FT%TZ) PID ${WRAPPER_PID} no longer running" >> "$WATCHER_LOG"

# Confirm success via ic_engine's own DB-visible completion signal instead of a log-file banner
# (the original design's log-tail check is unreliable -- the target log file was found
# truncated to 0 bytes with a recent mtime, consistent with the same unexpected-log-rotation
# class of bug todo 315 already found for regime_writer.log).
ALPHA_EVENTS_FRESH=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc \
    "SELECT count(*) FROM alpha_ensemble_ic WHERE created_at > now() - interval '2 hours';" 2>>"$WATCHER_LOG" || echo "0")

if [ "${ALPHA_EVENTS_FRESH:-0}" -gt 0 ]; then
    echo "$(date -u +%FT%TZ) run appears to have completed successfully (alpha_ensemble_ic has ${ALPHA_EVENTS_FRESH} fresh rows) -- launching --from-step 4 recompute" >> "$WATCHER_LOG"
    setsid nohup bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 4 \
        > "logs/corpus_pipeline_todo335_recompute_$(date -u +%Y%m%d_%H%M%S).log" 2>&1 < /dev/null &
    disown
    echo "$(date -u +%FT%TZ) launched --from-step 4 recompute, PID $!" >> "$WATCHER_LOG"
else
    echo "$(date -u +%FT%TZ) WARNING: no fresh alpha_ensemble_ic rows found -- run may have failed. NOT auto-launching recompute. Check logs/ic_engine.log and step_timings.jsonl manually." >> "$WATCHER_LOG"
fi
