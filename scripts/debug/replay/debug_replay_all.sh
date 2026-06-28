#!/bin/bash
# Replay all active instruments in parallel — safe to re-run (ON CONFLICT DO NOTHING)
# Usage: ./replay_all.sh [--days N] [--symbols SYM,...] [--workers N] [--clean]
# Defaults: 21 days, all active contracts from settings, 4 workers
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --days 21 --workers 4 "$@"
