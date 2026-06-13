---
created: 2026-06-13T04:35:52.622Z
title: I2 Tier Persistence — pipeline bias fix and schema hardening
area: database
files:
  - docs/plans/2026-06-12-i2-persistence-design.md
  - src/intelligence/schemas.py
  - src/intelligence/register_plugins.py
  - services/intelligence_pipeline.py
  - production/scripts/run_historical_pipeline.py
---

## Problem

Three compounding failures create a hidden training/production bias — the exact failure mode that destroys a fund:

1. **Two pipeline implementations produce structurally different i2 content.** Live pipeline (`executor.py`) calls `run_tiers()` which returns tier-isolated dicts and constructs `I2Events(**tiered.get("i2", {}))`. Historical pipeline calls `run_analysis_pipeline()` which merges all tier outputs into a flat dict then reconstructs via `_pick(I2Events, intelligence)` — a field-name filter across the entire merged dict. Same bar, different i2 content.

2. **I2Events schema has no contract.** Uses `extra="allow"` and the validator in `register_plugins.py:161` explicitly skips I2 validation. 4 composite plugins produce 19 fields not declared in `I2Events` — silently pass through, invisible to the type system.

3. **I2Events declares fields belonging to I3.** 8 MACD fields (`macd_cross_bullish` etc.) are declared in `I2Events` but the MACDEvents plugin runs in I3. Schema misattribution.

## Solution

Implement `docs/plans/2026-06-12-i2-persistence-design.md` as a dedicated phase:

1. Unify the two pipeline code paths so live and historical produce identical i2 content
2. Harden `I2Events` schema: explicit field declarations, remove `extra="allow"`, enable validator
3. Move misplaced MACD fields to `I3Events` (or confirm they belong in I2 and document why)
4. Add integration test asserting live and historical pipelines produce byte-identical i2 for a known bar

**Prerequisite:** Complete composite_events column rename first (todo: rename-intelligence-features-i2-column-to-composite-events) — reduces noise during schema audit.
