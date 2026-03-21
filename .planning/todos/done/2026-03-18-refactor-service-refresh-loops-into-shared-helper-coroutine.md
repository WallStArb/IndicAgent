---
created: 2026-03-18T00:00:00Z
title: Refactor service refresh loops into shared helper coroutine
area: services
files:
  - services/signal_generator_service.py:_calibration_curves_refresh_loop,_tod_multipliers_refresh_loop,_cis_weights_refresh_loop,_perf_weights_refresh_loop,_drift_penalties_refresh_loop
---

## Problem

`signal_generator_service.py` has 5 refresh loops that share identical shutdown-wait boilerplate:

```python
while self.running and not self.shutdown_requested:
    try:
        try:
            await asyncio.wait_for(self.shutdown_event.wait(), timeout=_REFRESH_INTERVAL)
            break
        except TimeoutError:
            pass
        if self.shutdown_requested:
            break
        await self._load_<thing>()
    except asyncio.CancelledError:
        break
    except Exception as e:
        self.logger.error/warning(...)
```

Copy-paste has already produced behavioral divergence: `_cis_weights_refresh_loop` uses `logger.error` while others use `logger.warning`; `_perf_weights` and `_drift_penalties` loops have `await asyncio.sleep(30)` backoff on error while the Phase 35 loops do not.

## Solution

Extract a `_make_refresh_loop(load_fn, interval_s, label)` coroutine factory (or a private `_run_refresh_loop` helper) that handles the shutdown-wait pattern, error logging, and optional backoff consistently. All 5 loops become one-liners:

```python
asyncio.create_task(self._run_refresh_loop(self._load_calibration_curves_from_db, 1800, "calibration_curves"))
```

Standardize on `logger.warning` for DB errors (not `error`) and include 30s sleep backoff on all loops.
