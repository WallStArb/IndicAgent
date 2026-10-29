#!/usr/bin/env bash
# Stage 1 of the 186-26 feature_vectors_v2 rebuild: 1d only, the 1,273 compute_1d names that are not
# D7 holds. Launch and resume are this same command. Run from anywhere; the unit pins its own cwd.
# If the unit is "failed" or "active", stop it first (see the resume procedure in the evidence JSON).
set -euo pipefail
RUN_TREE=/home/bg/dev/indicagent-186-26
SYMBOLS_FILE="$RUN_TREE/.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/evidence/186-26-stage1-1d-symbols.txt"
systemd-run --user --unit=feature-rebuild-1d \
  --description="186-26 stage 1 feature_vectors_v2 rebuild, 1d, 1273 non-hold names" \
  --working-directory="$RUN_TREE" \
  -p MemoryMax=14G -p Nice=10 -p Restart=no \
  -p StandardOutput=append:/home/bg/dev/indicagent/logs/feature_rebuild_1d.log \
  -p StandardError=append:/home/bg/dev/indicagent/logs/feature_rebuild_1d.log \
  -E PYTHONPATH="$RUN_TREE" \
  /home/bg/dev/indicagent/.venv/bin/python services/backfill_feature_factory.py \
  --compute-only --tf 1d --data-horizon 2026-10-01 --workers 12 \
  --symbols "$(cat "$SYMBOLS_FILE")"
