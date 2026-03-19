---
created: 2026-03-19T15:51:25.948Z
title: Fix ShannonEntropy plugin NaN range handling
area: intelligence
files:
  - src/intelligence/i4/context_shannon_entropy.py
---

## Problem

ShannonEntropy plugin fails with: `autodetected range of [nan, nan] is not finite` and `autodetected range of [X, inf] is not finite`

The plugin doesn't validate input data before computing range normalization, causing failures when encountering NaN or Inf values. This occurs on symbols with incomplete or degenerate data sequences.

## Evidence

From `logs/market_analysis_service.log`:
```
{"plugin": "ctx_ShannonEntropy", "error": "autodetected range of [nan, nan] is not finite", "event": "I4 plugin failed", "level": "warning"}
{"plugin": "ctx_ShannonEntropy", "error": "autodetected range of [-0.0024907682721657665, inf] is not finite", "event": "I4 plugin failed", "level": "warning"}
```

## Solution

Add validation before range detection:
```python
# Filter invalid data before processing
valid_data = data[~np.isnan(data) & ~np.isinf(data)]
if len(valid_data) < 2:
    return {}  # Skip this bar - insufficient valid data

# Then compute range on valid_data only
```

## Impact

Context entropy is an I4 layer regime indicator that measures market uncertainty. When it fails on symbols with incomplete data, the entire I4 layer loses signal quality for those instruments, reducing regime detection accuracy across the portfolio.
