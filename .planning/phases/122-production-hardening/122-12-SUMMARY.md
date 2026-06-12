---
plan: 122-12
status: complete
completed_at: 2026-06-12
---

## Summary

Fixed three additional files with missed i1/i3/i4 JSONB column accessor SQL that plan 11 didn't cover.

**One-liner:** `hmm_trainer.py`, `validation_engine.py`, and `cross_asset_analyzer.py` SQL updated from tier-code to functional column names (i1→technical_indicators, i4→confluence_scores).

## What Was Done

1. `src/intelligence/services/hmm_trainer.py` — 4 JSONB accessor lines (`i1->>'rsi_14'`, `i1->>'adx_14'`, `i1->>'atr_14'`, `i1->>'macd_histogram_12_26_9'`) → `technical_indicators->>'...'`; comment updated
2. `src/validation/validation_engine.py` — 3 i1 and 2 i4 JSONB accessors updated to functional names
3. `services/cross_asset_analyzer.py` — 2 i1 JSONB accessors updated to `technical_indicators`

## Verification

- `grep -rn "i1->>\|i3->>\|i4->>\|i5->>" src/ services/ production/scripts/` returns empty — no remaining tier-code JSONB column accessors
- Unit tests: 42 failed (all pre-existing), 4622 passed
