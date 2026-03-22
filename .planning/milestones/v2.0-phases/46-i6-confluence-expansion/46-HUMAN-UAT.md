---
status: partial
phase: 46-i6-confluence-expansion
source: [46-VERIFICATION.md]
started: 2026-03-22T05:41:00Z
updated: 2026-03-22T05:41:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. VIX fields non-None in live data
expected: After 20+ minutes of VIX bar accumulation in the live pipeline, querying `intelligence_features.i6` for ES 1m bars should show non-None values for `ctf_vix_level` and `ctf_vix_z` fields
result: [pending]

### 2. EQ_INDEX vs non-EQ_INDEX field population
expected: With `cross_asset_enabled=True` and cross_asset topic data flowing, ES should have float values for `ctf_eq_spread_z` and `ctf_eq_pairs_confirming`, while non-EQ_INDEX symbols (e.g., GC) should have null for those fields
result: [pending]

### 3. ctf_score distribution unchanged post-deploy
expected: Compare pre/post deploy ctf_score statistics in `intelligence_features` — the 4 new fields should not shift the ctf_score distribution (weights W_TREND=0.4, W_STRUCTURE=0.3, W_REGIME=0.2, W_PATTERN=0.1, W_I2=0.1 are untouched)
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
