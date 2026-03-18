---
created: 2026-03-18T00:00:00Z
title: Pre-convert calibration curves to numpy arrays at cache load
area: intelligence
files:
  - services/signal_generator_service.py:_load_calibration_curves_from_db
  - src/intelligence/trading/aggregator.py:_build_all_ranked
---

## Problem

`_load_calibration_curves_from_db()` stores calibration curve breakpoints/values as Python `list`. In `_build_all_ranked()`, `np.interp()` is called once per signal per bar — it converts the Python lists to numpy arrays internally on every call. Since curves are refreshed only every 30 minutes but evaluated hundreds of times per second during market hours, this is wasted allocation.

## Solution

In `_load_calibration_curves_from_db()`, store arrays as `np.ndarray` at cache-load time:

```python
import numpy as np
new_cache[key] = (np.array(row["breakpoints"]), np.array(row["values"]))
```

`np.interp()` in `_build_all_ranked` works natively with arrays — no call-site change needed. Requires adding `numpy` import to `signal_generator_service.py` (already imported in `aggregator.py`).
