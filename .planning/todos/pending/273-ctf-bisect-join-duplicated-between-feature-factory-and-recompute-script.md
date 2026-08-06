---
status: pending
priority: P3
filed: 2026-08-06
source: /simplify altitude-angle review of scripts/ops/corpus/ops_ctf_columns_recompute_15m.py
  (todo 243's batching fix), commit 9fb5a27d
---

# 273: CTF HTF-bar bisect-join lookup duplicated between `feature_factory.py` and the recompute script

## What

`FeatureFactory.compute_batch` (`src/intelligence/feature_factory.py:~7621`) and
`scripts/ops/corpus/ops_ctf_columns_recompute_15m.py`'s `_recompute_symbol`
(`ops_ctf_columns_recompute_15m.py:127-148`) both inline the identical CTF join logic:

```python
idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
if idx >= 0:
    ctf = ctf_by_ts[ctf_ts_list[idx]]
    ...
else:
    new_mom = new_vwap = new_regime = 0.0
```

The recompute script's own comment admits this is "a deliberate narrow duplication, not an
oversight... If that join logic ever changes, this copy must be updated to match." This is a
pure function of `(ctf_by_ts, ctf_ts_list, bar_ts)` with no dependency on `compute_batch`'s
surrounding per-bar loop state -- a clean extraction candidate.

## Why deferred, not fixed inline

Found during `/simplify`'s altitude review of todo 243's batching fix (commit 9fb5a27d). The
fix would require modifying `FeatureFactory.compute_batch` -- a large, actively-used, hot-path
production function -- which is entirely outside that diff's scope (the diff only touched the
new ops script and `cross_sectional_spread_tracker.py`). Not something to fold into a
simplify pass on an unrelated script.

## Suggested fix

Extract into a shared helper, e.g. `feature_factory.py::_lookup_ctf(ctf_by_ts, ctf_ts_list,
bar_ts) -> CtfValues | None` (or similar), used by both `compute_batch` and any future
scoped-recompute script that needs the same join. Low risk given it's a pure lookup with no
side effects, but touches a hot production path so should get its own test coverage and a
careful diff, not a drive-by change.
