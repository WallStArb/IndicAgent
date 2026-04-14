---
phase: 067-observability-alerting-automation
plan: 10
status: complete
started: 2026-04-14
completed: 2026-04-14
---

# Plan 067-10: Remove CrossAssetService Backward-Compat Shim — SUMMARY

## Objective
Remove the backward compatibility shim `CrossAssetService = CrossAssetComputeAgent` and update all test imports to use the new name directly.

## What Was Done

1. **Removed the alias** from `services/cross_asset_service.py` (lines 461-466) — the `CrossAssetService = CrossAssetComputeAgent` shim and its surrounding comment block.

2. **Updated test imports** in `tests/unit/service_tests/test_cross_asset_service.py`:
   - Replaced `CrossAssetService` with `CrossAssetComputeAgent` in docstring and all import/usage
   - Fixed `_make_service()` to use `_stop_event = asyncio.Event()` instead of setting the read-only `running` property
   - Added `import asyncio` for the Event

3. **Removed 3 unused imports** from `cross_asset_service.py`: `signal`, `typing.Any`, `structlog`

## Verification

- `grep -rn "CrossAssetService" --include="*.py" services/ tests/ src/` → 0 matches
- `.venv/bin/pytest tests/unit/service_tests/test_cross_asset_service.py -v` → 15 passed

## Files Modified

- `services/cross_asset_service.py` — alias removed, unused imports cleaned
- `tests/unit/service_tests/test_cross_asset_service.py` — imports updated, asyncio.Event for _stop_event

## Self-Check: PASSED
