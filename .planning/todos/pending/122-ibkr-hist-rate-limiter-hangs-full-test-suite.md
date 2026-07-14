---
status: pending
priority: P0
filed: 2026-07-14
source: found while verifying `tests/unit/` is green before committing todo 011 —
  `.venv/bin/pytest tests/unit/` hung twice in a row (reproducibly, at the same point in
  collection order), each time killed manually
---

# `src/providers/ibkr.py`'s module-global historical-data rate limiter causes real
# multi-minute stalls inside the unit test suite

## Problem

`_hist_rate_limiter` (`src/providers/ibkr.py:179`, `_SlidingWindowRateLimiter(max_requests=55,
window_s=600.0)`) is a **process-wide module-level singleton** tracking real
`time.monotonic()` timestamps in a `deque`, never reset between tests. Any unit test that
exercises `IBKRProvider.fetch_historical_bars()` — even fully mocked at the `_ib` (ib_insync)
layer — still calls the real `await _hist_rate_limiter.acquire()` (`ibkr.py:729`). Once the
cumulative count of such calls across the pytest session reaches 55 within a trailing 10-minute
window, `acquire()` genuinely `await asyncio.sleep(wait)`s for up to ~601 seconds before the
next call proceeds — a real, unmocked, wall-clock sleep with zero CPU activity and the asyncio
event loop idle in `select()`.

**Confirmed reproducible:** `.venv/bin/pytest tests/unit/` (and `.venv/bin/pytest
tests/unit/providers/test_ibkr_equity.py` in isolation) stalls at
`TestIBKRUseRTH::test_fetch_equity_bars_uses_rth` — confirmed via `py-spy dump` (main thread
idle in `asyncio/base_events.py` `select()`, zero CPU progress over a 15-minute observation
window) and via `timeout 20 pytest ...` exiting 124. Not corpus-rebuild CPU contention — the
process is genuinely blocked, not starved.

**Known call sites accumulating against the shared limiter** (found via `grep -rl
"fetch_historical_bars\|_hist_rate_limiter" tests/unit/`):
`tests/unit/services/test_backfill_feature_factory.py`,
`tests/unit/providers/test_ibkr_provider.py`, `tests/unit/providers/test_base.py`,
`tests/unit/providers/test_ibkr_adapter.py`, `tests/unit/providers/test_ibkr_equity.py`.

**Impact:** any full `tests/unit/` run (the exact gate CLAUDE.md's Done-Coding SOP and every
GSD `execute-phase` require before commit) can silently stall for up to ~10 minutes depending
on test collection order and how many rate-limited calls preceded it in the same session — and
worse, if test execution order or count ever shifts (new tests added, parallelization, `-k`
filtering changes ordering), the exact point of the stall moves. A CI runner with a shorter
timeout than ~10 minutes would report this as a hang/timeout failure with no useful diagnostic,
not as a clean pass/fail.

## What to do

Give tests control over `_hist_rate_limiter` instead of sharing real process-wide state:
- Inject the rate limiter (constructor param or `IBKRProvider` attribute) instead of a bare
  module global, so tests can substitute a no-op/instant limiter — OR
- Add an autouse `pytest` fixture in `tests/unit/providers/conftest.py` (or wherever shared
  fixtures live) that monkeypatches `ibkr._hist_rate_limiter` to a fresh, no-op-`acquire()`
  double for every test in the session, so no test ever pays real rate-limit wait time.

Either fix must preserve the real limiter's behavior in production (`IBKRProvider` is a
live-trading-critical Ring-2 provider file — do not weaken the actual 55-req/10-min IBKR
compliance, only its exposure inside tests).

## Not in scope for todo 011

Found while finishing todo 011 (`alpha_events.is_shadow`) during a corpus-rebuild idle window;
completely unrelated code path (`src/providers/ibkr.py`, a live-trading-critical Ring-2 file —
not touched by todo 011's `alpha_publisher.py`/`ensemble_trainer.py`/`_batch_utils.py` changes).
Verified pre-existing on `main` (`git log` shows the rate limiter last touched by unrelated
commit `9c0f2996`, no uncommitted changes). Todo 011's own unit-test gate was run *excluding*
`tests/unit/providers/` and `tests/unit/services/test_backfill_feature_factory.py` to route
around this hang rather than block on it — see that todo's resolution note.
