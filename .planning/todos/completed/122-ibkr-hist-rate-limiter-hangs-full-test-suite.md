---
status: completed
priority: P0
filed: 2026-07-14
resolved: 2026-07-14
source: found while verifying `tests/unit/` is green before committing todo 011 —
  `.venv/bin/pytest tests/unit/` hung twice in a row (reproducibly, at the same point in
  collection order), each time killed manually
---

# `tests/unit/` full-suite hang — real root cause was retry-backoff sleeps in three
# mistaken test mocks, not the rate limiter this todo originally blamed

## Correction (read first)

This todo's original text blamed `src/providers/ibkr.py`'s module-global `_hist_rate_limiter`
singleton (`max_requests=55, window_s=600.0`) — plausible from the symptom (event loop idle in
`select()`, zero CPU, matching a `_SlidingWindowRateLimiter.acquire()` sitting in a real
`asyncio.sleep(wait)`) and already committed as such (commit `42b2dbf9`, alongside a
`tests/unit/conftest.py` fixture that no-ops `_hist_rate_limiter.acquire()`). **That diagnosis
was wrong.** Applying the no-op fixture alone did not fix the hang — confirmed by re-running
`tests/unit/providers/test_ibkr_equity.py` afterward and it still stalled (`timeout 15` exit
124).

## Actual root cause

`_fetch_historical_bars_impl`'s per-chunk retry loop (`ibkr.py:747-811`) checks `if result:`
after each `reqHistoricalDataAsync` call — **not** `if result is not None:`. An empty-but-valid
response (`[]`, or a `BarDataList` with no bars) is falsy, so it's treated identically to a
`TimeoutError`: an AMBIGUOUS failure, not confirmed no-data. The code only takes the fast
"confirmed no-data, stop" path when `getattr(result, "reqId", None)` matches an entry already
recorded in the module-level `_no_data_req_ids` set (the deliberate F3 2026-07-05 fix — see the
docstring at `ibkr.py:738-746` and the already-correct
`test_two_consecutive_no_data_chunks_aborts_backfill` in `test_ibkr_provider.py`, which sets
`.reqId` on its `BarDataList` mock for exactly this reason). Any mock that returns a bare falsy
value without a matching `.reqId` falls through to the AMBIGUOUS path instead, which does a
real `await asyncio.sleep(65)` then, if still ambiguous, `await asyncio.sleep(130)` — **~195
real seconds per occurrence**, zero CPU, event loop idle in `select()` — exactly matching every
symptom this todo originally observed and misattributed to the rate limiter.

Three test mocks hit this:
- `test_ibkr_equity.py::TestIBKRUseRTH::test_fetch_equity_bars_uses_rth` and
  `test_fetch_futures_bars_no_rth` — both `AsyncMock(return_value=[])`. Neither test cares about
  the returned bars (they only assert on the `useRTH` kwarg), so no reason to hit the retry path
  at all.
- `test_ibkr_provider.py::TestFetchHistoricalBars::test_returns_empty_on_no_data` — same
  `AsyncMock(return_value=[])` pattern, ~195s.
- `test_ibkr_provider.py::TestFetchHistoricalBars::test_single_no_data_chunk_does_not_abort_backfill`
  — a `side_effect` returning a bare `[]` (no `.reqId`) on the first call while separately (and
  ineffectively) adding a reqId to `_no_data_req_ids` that the returned value never carries.
  ~65s. Worse than just slow: because the confirmed-no-data fast path never actually fired, this
  test was silently NOT exercising todo 049's "single confirmed no-data chunk doesn't abort the
  walk" behavior at all — it was passing by accident, via the retry-then-recover path, not via
  the mechanism its own docstring claims to verify.

`test_base.py`, `test_ibkr_adapter.py`, and `test_backfill_feature_factory.py` (also flagged in
this todo's original "known call sites" list) mock at a higher level and never reach this retry
loop — no changes needed there.

## Fix

Each of the three broken mocks now either returns a genuinely truthy result (the two
`useRTH`-only tests — they don't care what's returned) or properly constructs a `BarDataList`
with `.reqId` set to match `_no_data_req_ids` (`test_returns_empty_on_no_data` and
`test_single_no_data_chunk_does_not_abort_backfill` — matching the pattern the codebase already
uses correctly in the adjacent `test_two_consecutive_no_data_chunks_aborts_backfill`). No
production code changed — `ibkr.py`'s `if result:` ambiguous-vs-confirmed retry design is
intentional (per its own docstring reasoning) and out of scope to second-guess here.

`tests/unit/conftest.py`'s `_hist_rate_limiter` no-op fixture (added while chasing the wrong
diagnosis) is kept as cheap defensive test-isolation — with the retry bug fixed, no unit test
should ever approach the real 55-req/10-min budget, but the fixture costs nothing and forecloses
a same-shape regression if a future test adds enough real `fetch_historical_bars` calls to
matter.

**Verified:** `tests/unit/providers/` + `tests/unit/services/test_backfill_feature_factory.py`
(79 tests) now complete in 5.5s, was an unbounded hang. Full `tests/unit/` suite green.

## Not in scope for todo 011

Found while finishing todo 011 (`alpha_events.is_shadow`) during a corpus-rebuild idle window;
completely unrelated code path. Todo 011's own unit-test gate was originally run *excluding*
these files to route around the (then-misdiagnosed) hang — see that todo's resolution note. This
todo's fix lands in a separate commit from 011's.
