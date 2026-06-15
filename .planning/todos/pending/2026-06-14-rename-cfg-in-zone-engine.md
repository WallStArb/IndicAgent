# TODO: Rename _cfg() to _read_config() in zone_engine.py
Created: 2026-06-14
Phase: Capture from Phase 125 D-05
Status: pending

## What
`_cfg()` in zone_engine.py uses the banned abbreviation "cfg" (naming system §6 Tier 3 banned).
Correct name: `_read_config()`

## Why deferred
Phase 125 does not touch zone_engine.py code. Rename belongs in a dedicated cleanup commit.

## How to do it
1. Rename _cfg() to _read_config() in zone_engine.py
2. Update all call sites within zone_engine.py (internal function only)
