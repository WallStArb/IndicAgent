---
created: 2026-03-22T00:00:00Z
title: Extract cross-asset pair identifiers to shared constant or enum
area: intelligence
files:
  - src/intelligence/trading/cross_asset_divergence.py
---

## Problem

Phase 46 review found `"ES_NQ"` and `"ES_RTY"` hardcoded as string literals in `cross_asset_divergence.py`, with the same strings mirrored inside I7 plugins. No single source of truth for valid cross-asset pair identifiers — if a pair is renamed or added, it must be updated in multiple places.

Skipped during Phase 46 simplify pass because the fix touches both the I7 plugin tier and the cross-asset service layer, making it non-trivial scope for a cleanup step.

## Solution

Define a `CrossAssetPair` enum (or module-level constants) in a shared location (e.g. `src/intelligence/schemas.py` or a new `src/intelligence/cross_asset_pairs.py`), then import and reference it from `cross_asset_divergence.py` and all I7 plugins that gate on pair identity. Ensures rename/addition of pairs is a single-file change.
