---
status: pending
priority: P3
filed: 2026-07-19
source: /simplify altitude review after todo 138/137's fix batch
---

# `except HTTPException: raise` guard is hand-copied across 5 route files, not centralized

## Finding

`src/api/routes/market_data.py`'s fix for todo 137's collateral finding (a route's own
`HTTPException(404)` getting re-caught and re-wrapped as a 500 by its surrounding
`except Exception`) added a 5th copy of the same 2-line guard already present in
`narrative.py`, `ai_stats.py`, `validation.py`, and `signals.py`. No shared mechanism in
`src/api/` prevents a 6th route from reintroducing the same bug — `src/api/main.py`
registers no `@app.exception_handler`, and `src/api/utils.py` (which already centralizes
other cross-route concerns) has no error-translation helper.

## Fix

Either (a) a shared decorator (e.g. `@translate_db_errors` in `src/api/utils.py`) applied
to route handlers, or (b) restructure routes so `HTTPException` (not-found, validation) is
raised outside the broad `try/except Exception` block instead of inside it. Either
eliminates the possibility of a 6th route reintroducing this bug rather than relying on
every future route author remembering the guard.

## Gate

None, independent. Touches all 5 existing route files plus `src/api/utils.py` — bigger than
a single-route fix, hence not done inline during todo 137/138's session.
