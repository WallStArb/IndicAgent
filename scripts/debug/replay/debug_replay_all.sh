#!/usr/bin/env bash
#
# debug_replay_all.sh — full pipeline replay for debugging
#
# Replays entire pipeline from raw bars to signals for specified time window.
# Use when debugging pipeline behavior or reproducing historical issues.
# Requires market_data_ohlcv backfill for target period.
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."
.venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --replay-only --days 21 --workers 4 "$@"
