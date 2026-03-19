# Deferred Items — 39.1-02

## Pre-existing test failure (out of scope)

**Test:** `tests/unit/api/test_signals_route.py::TestGetSignals::test_get_signals_base_symbol_resolved`
**Failure:** Asserts `ESH6` (March contract) but config now returns `ESM6` (June contract) — contract rolled post-expiry
**Root cause:** Test fixture hardcodes `ESH6` in `_make_client()` mock but the live `derive_roll_chain()` now returns June contract
**Impact:** None on my changes — pre-existing before this plan
**Action needed:** Update test mock to use `ESM6` or mock `resolve_contract` to return the expected symbol
