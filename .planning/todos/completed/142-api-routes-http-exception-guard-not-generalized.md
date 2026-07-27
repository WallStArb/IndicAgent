---
status: closed
priority: P3
filed: 2026-07-19
closed: 2026-07-27
source: /simplify altitude review after todo 138/137's fix batch
---

## RESULT (2026-07-27): fixed, generalized to all 9 route handlers across the 5 files.

Built `translate_db_errors` decorator in `src/api/utils.py` (option (a)): lets a route's own
`HTTPException` pass through untouched, catches any other exception, logs server-side under
the route module's own `structlog` logger name, and raises a generic `HTTPException(500,
detail="Database error")` -- standardizing on `narrative.py`'s pre-existing non-leaking
convention rather than the `str(e)`-in-detail pattern several routes had (a minor info-
disclosure smell, fixed as a side effect of centralizing). Confirmed FastAPI's dependency
injection still resolves the real signature through `functools.wraps`' `__wrapped__` chain
(`inspect.signature`'s default `follow_wrapped=True`) -- verified via the full existing test
suite, not just theory.

Applied to all 9 route handlers across the 5 named files (`market_data.py`,
`narrative.py`, `ai_stats.py` x2, `validation.py`, `signals.py` x6) -- not just the ones that
already hand-copied the guard. Checked each of the other handlers for the actual latent risk
first (`raise HTTPException` inside the try body before the except): none had it, so applying
the decorator there is pure future-proofing, not a live bug fix. Full unit suite green
(zero regressions) after every file.

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
