#!/usr/bin/env bash
# Stage 2 of the 186-26 feature_vectors_v2 rebuild: intraday tfs (5m, 15m, 1h) for the 1,252 names that pass every
# intraday verdict in the 2026-10-31 audit (slot_coverage, digest_fresh, grid_parity, coverage_cache) and
# already hold 1d rows. The main process idles on its write connection while workers compute for hours, so the
# database idle_session_timeout (60 min) would kill it (2026-10-31 13:27 UTC); PGOPTIONS turns it off for this run only. Launch and resume are this same command; stop the unit first if it is failed or active.
set -euo pipefail
RUN_TREE=/home/bg/dev/indicagent-186-26
SYMBOLS_FILE=/home/bg/dev/indicagent/.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-26-stage2-intraday-symbols.txt
systemd-run --user --unit=feature-rebuild-intraday \
  --description="186-26 stage 2 feature_vectors_v2 rebuild, 5m 15m 1h, 1252 names" \
  --working-directory="$RUN_TREE" \
  -p MemoryMax=14G -p Nice=10 -p Restart=no \
  -p StandardOutput=append:/home/bg/dev/indicagent/logs/feature_rebuild_intraday.log \
  -p StandardError=append:/home/bg/dev/indicagent/logs/feature_rebuild_intraday.log \
  -E PYTHONPATH="$RUN_TREE" -E PGOPTIONS="-c idle_session_timeout=0" \
  /home/bg/dev/indicagent/.venv/bin/python services/backfill_feature_factory.py \
  --compute-only --tf 5m,15m,1h --data-horizon 2026-10-01 --workers 8 \
  --symbols "$(cat "$SYMBOLS_FILE")"
