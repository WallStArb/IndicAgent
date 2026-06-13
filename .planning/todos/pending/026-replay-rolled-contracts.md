# 026 - Replay Rolled Contracts + Structural Fix

## Problem
`run_historical_pipeline.py --replay-only` uses `get_active_contracts()` which filters
`contract_metadata WHERE is_front_month = true`. Expired/rolled contracts are never replayed,
leaving 114k+ 1m bars of legitimate signal history orphaned from signal_ledger.

## Rolled contracts with 1m bar data (as of 2026-06-13)
GCM6, HGM6, SIM6, NGM6, VXK6, HGK6, SIK6, GCK6, CLM6, ZSK6, ZCK6, ZWK6

## Immediate remediation (after current rebuild completes)
Run supplementary replay + lifecycle for rolled contracts:
```bash
.venv/bin/python production/scripts/run_historical_pipeline.py \
  --replay-only --workers 8 \
  --symbols GCM6,HGM6,SIM6,NGM6,VXK6,HGK6,SIK6,GCK6,CLM6,ZSK6,ZCK6,ZWK6

.venv/bin/python lifecycle_replay.py \
  --symbols GCM6,HGM6,SIM6,NGM6,VXK6,HGK6,SIK6,GCK6,CLM6,ZSK6,ZCK6,ZWK6
```

## Structural fix
Add `--include-rolled` flag to `run_historical_pipeline.py` that queries:
  `contract_metadata WHERE asset_class = 'futures'` (no `is_front_month` filter)
so future replays capture all contracts that have bar data.

Also update `rebuild_signal_ledger.py` STAGE_REPLAY to pass `--include-rolled` by default.

## Why this matters
Each rolled contract represents real front-month price action during its active period.
These are training data - the plugins should have fired on those bars. Never drop signal history.
