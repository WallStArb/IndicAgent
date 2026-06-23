---
discovered: "2026-06-23"
during: "138-perf ATR/gap_z vectorization"
priority: high
---

# Replace scipy.stats.skew with numpy rolling skewness in _rolling_stat_z

## Context

Profiled during 138-perf fix. `_rolling_stat_z` in `feature_factory.py` calls
`scipy.stats.skew` 2000 times per `compute()` call (once per bar in the rolling
window). Scipy's `axis_nan_policy_wrapper` + `inspect.getfullargspec` overhead
dominates: 2.5s of 3.0s total per call at 2000-bar window.

## Fix

Replace `scipy.stats.skew(window_data)` in `_skewness()` (called by `_rolling_stat_z`)
with a pure-numpy 3rd central moment:

```python
def _skewness(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 3:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    return float(np.mean(((arr - mean) / std) ** 3))
```

Expected speedup: 260ms -> ~40ms per `compute()` call (6-7x) at 2000-bar window.
Also applies to `ret_acf1_z` if it has similar scipy usage.

## Impact

- No behavior change for finite data (numpy skewness = scipy skewness)
- Drop scipy import if no other users remain in feature_factory.py
- Run `test_feature_factory.py` + `test_batch_feature_parity.py` after
