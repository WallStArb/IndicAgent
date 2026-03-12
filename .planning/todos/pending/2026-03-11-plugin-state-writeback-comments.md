# Add Plugin State Write-Back Warning Comments

**Created:** 2026-03-11
**Priority:** Low (documentation, regression prevention)
**Effort:** Tiny (15 min)
**Source:** CONCERNS.md audit

## Problem

`market_analysis_service` and `indicator_service` both do a critical state write-back pattern after every `compute_full()` call:

```python
p._state = self._plugin_states[key]       # swap state onto plugin
result = p.compute_full(bar)
self._plugin_states[key] = p._state       # write back — LOAD-BEARING
```

The write-back is **load-bearing for GARCH and HMM plugins** — they fully reassign `p._state` inside `compute_full()`. If the write-back line is removed or placed before `compute_full()`, GARCH/HMM silently lose state between bars and produce wrong results.

This is not obvious from reading the code.

## Fix

Add a warning comment in both services at the write-back line:

```python
# CRITICAL: Write state back AFTER compute_full(). GARCH and HMM fully reassign
# p._state inside compute_full() — skipping this line loses their state between bars.
self._plugin_states[key] = p._state
```

## Files

- `services/market_analysis_service.py` — find the plugin computation loop
- `services/indicator_service.py` — find the I1 plugin computation loop
