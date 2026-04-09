---
created: 2026-03-21T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: Implement plugin validation layer (PluginValidator)
area: intelligence
priority: 8
tier: near-term
files:
  - src/intelligence/plugins/validator.py
---

## Problem

Plugin misconfiguration (missing `regime_type`, wrong tier registration, TREND_SETUPS drift) causes silent production failures. No startup enforcement catches these until a signal misfires.

## Solution

`PluginValidator` class that runs at service startup and hard-crashes on config errors:
- Tier list integrity (all names resolve to registered classes)
- Required attributes present (`regime_type`, `outputs`, `inputs`)
- Schema coverage (all expected output keys present in plugin output)
- `TREND_SETUPS` auto-sync validation
- Prometheus metrics: `registered_plugins_total`, `plugin_validation_status`

## Notes

- Create `src/intelligence/plugins/validator.py` (does not yet exist)
- Approved implementation plan at: `/home/bg/.claude/plans/parsed-wobbling-hanrahan.md`
- Can be executed standalone — no phase dependency
