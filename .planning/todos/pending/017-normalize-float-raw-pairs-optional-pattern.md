---
created: 2026-03-22T00:00:00Z
title: Normalize float(raw_pairs) if ... else None pattern across cross-asset plugins
area: intelligence
files:
  - src/intelligence/trading/cross_asset_divergence.py
---

## Problem

Phase 46 review found the `float(raw_pairs) if raw_pairs else None` guard pattern repeated across 5+ files in the cross-asset and I7 layers. It's a pre-existing pattern, not introduced by Phase 46, so it was skipped in the simplify pass. The repetition is low-risk today but will grow as more cross-asset plugins are added.

## Solution

Extract to a small utility function (e.g. `safe_float(val) -> float | None`) in `src/intelligence/cross_asset_pairs.py` or `composites/common.py` (already has similar helpers like `is_num`). Migrate callers in a single focused refactor pass — verify no behavior change since `float(None)` raises but `if raw_pairs` guards against it.
