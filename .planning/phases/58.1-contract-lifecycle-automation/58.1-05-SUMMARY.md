---
phase: 58.1-contract-lifecycle-automation
plan: 05
subsystem: config
tags: [settings, contracts, futures, roll-automation, cleanup]
dependency_graph:
  requires: [58.1-04]
  provides: [base-symbol-templates-in-settings]
  affects: [get_active_contracts, build_contracts]
tech_stack:
  added: []
  patterns: [base-symbol-template, DB-first contract resolution]
key_files:
  created:
    - tests/unit/test_settings.py
  modified:
    - src/config/settings.py
decisions:
  - "Futures templates use symbol=base (e.g. symbol='ES') with no expiry; session_id='futures_24_5' explicit on each"
  - "VIX futures base preserved as 'VIX' (not 'VX') matching existing provider_meta trading_class"
  - "get_active_contracts() function body completely unchanged — DB-first resolution unaffected"
  - "Added 8 tests (3 beyond plan's 5) including session_id and front-month suffix checks"
metrics:
  duration: "8 minutes"
  completed: "2026-04-02"
  tasks: 2
  files: 2
---

# Phase 58.1 Plan 05: Settings Base-Symbol Template Cleanup Summary

Replaced 17 front-month contract codes in `build_contracts()` defaults with base-symbol templates, eliminating the need to manually update `settings.py` on each quarterly roll.

## What Was Built

**One-liner:** Replaced all front-month contract codes (ESM6, NQM6, etc.) in `build_contracts()` defaults with base-symbol templates (symbol=base, no expiry) so contract resolution flows entirely through `contract_metadata` DB table.

### Task 1: Replace front-month defaults with base-symbol templates
**Commit:** `f374fdb`

Modified `src/config/settings.py` `build_contracts()` validator defaults:

- 17 futures instruments converted from contract-code form (e.g. `symbol="ESM6", expiry="202606"`) to base-symbol templates (e.g. `symbol="ES", base="ES"`)
- Futures groups converted: equity_index (ES, NQ, RTY, YM), energy (CL, NG), metals (GC, SI, HG), volatility (VIX), interest_rates (ZN, ZF, ZB, ZT), agriculture (ZS, ZC, ZW)
- `session_id="futures_24_5"` explicitly set on each futures template for clarity
- 44 non-futures instruments (FX, crypto, equity ETFs) completely unchanged
- `get_active_contracts()` function body not touched — it already queries contract_metadata for DB-first resolution

### Task 2: Tests verifying base-symbol templates and backward compatibility
**Commit:** `cd29e32`

Created `tests/unit/test_settings.py` with `TestBuildContractsBaseSymbolTemplates` (8 tests):

| Test | Assertion |
|------|-----------|
| `test_futures_use_base_symbol` | All futures: symbol == base |
| `test_futures_no_expiry` | All futures: empty expiry |
| `test_futures_have_required_fields` | exchange, point_value, tick_size, session_id, sector all set |
| `test_non_futures_unchanged` | Non-futures retain their symbols |
| `test_settings_instantiation` | Settings() loads without error |
| `test_known_futures_bases_present` | ES, NQ, RTY, YM all present |
| `test_futures_session_id_is_futures_24_5` | All futures use futures_24_5 session |
| `test_no_front_month_codes_in_futures_symbols` | No M6/H6/etc suffix on futures symbols |

All 8 tests pass.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written. One minor enhancement: added 3 extra tests beyond the plan's specified 5 (`test_futures_session_id_is_futures_24_5`, `test_no_front_month_codes_in_futures_symbols`, plus a slightly expanded field check), as they exercise distinct correctness properties at zero cost.

## Verification Results

```
17 futures use base-symbol templates
44 non-futures unchanged
PASS

8 passed in 0.05s

RUFF CLEAN on src/config/settings.py and tests/unit/test_settings.py

61 instruments total in Settings()
```

Front-month codes (M6/H6) in file: 3 occurrences — all in docstrings of `get_active_contracts`, `get_active_symbols`, and `get_contract_info` (illustrative examples only, not in defaults).

## Known Stubs

None. All futures instruments have complete templates with real exchange, point_value, tick_size, session_id, and sector values.

## Self-Check: PASSED

- `src/config/settings.py` exists and has `symbol="ES"` in defaults
- `tests/unit/test_settings.py` exists with 8 tests
- `f374fdb` commit exists (feat: replace front-month contract codes)
- `cd29e32` commit exists (test: add TestBuildContractsBaseSymbolTemplates)
