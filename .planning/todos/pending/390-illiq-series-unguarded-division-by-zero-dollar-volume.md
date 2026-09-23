---
status: pending
priority: P2
filed: 2026-09-23
source: found during todo 340's IHF investigation (2026-09-22), RuntimeWarning surfaced live,
  triaged and deferred at the time; confirmed root cause while closing out todo 340
---

# `_amihud_illiq_z_series_full`'s `dollar_vols` divisor is unguarded against a zero-price bar

## What

`src/intelligence/feature_factory.py:2284`:

```python
log_rets_abs = np.abs(np.diff(np.log(np.maximum(closes.astype(float), 1e-10))))
dollar_vols = closes[1:].astype(float) * np.maximum(volumes[1:].astype(float), 1.0)
illiq = log_rets_abs / dollar_vols
```

`log_rets_abs`'s input is floored at `1e-10` before the `log()` call, but `dollar_vols`'s
`closes[1:]` term is NOT floored -- only the volume term is (`np.maximum(volumes[1:], 1.0)`). A
bar with `close == 0.0` makes `dollar_vols[i] == 0.0` regardless of volume, and
`illiq = log_rets_abs / dollar_vols` divides by zero, producing `inf`/`nan` silently (confirmed
live 2026-09-22: `RuntimeWarning: divide by zero encountered in divide` during an IHF
`--compute-only` run, the same run that surfaced todo 340's `_canary_acausal_placebo` bug).

This is the same root data condition as todo 340's IHF fix (a genuine historical `close=0` bar,
e.g. the 2010-05-06 Flash Crash bar) but a different function and a different failure mode:
`_canary_acausal_placebo` raised a hard `ValueError` (Postgres/Python-level crash, todo 340,
fixed); this one degrades silently to `inf`/`nan` in a real feature (`illiq`, an actual
liquidity/impact measure feature_vectors persists), not a canary. A warning, not a crash -- which
is exactly why it was deferred at the time rather than blocking todo 340's more urgent
investigation.

## Fix

Floor `dollar_vols` the same way `dollar_vols`'s denominator role deserves, e.g.:
`dollar_vols = np.maximum(closes[1:].astype(float), 1e-10) * np.maximum(volumes[1:].astype(float), 1.0)`
matching the existing `log_rets_abs` floor pattern in the same function. Confirm what value
`illiq` should take for a genuinely zero-price bar (0.0, matching the codebase's usual
degenerate-input fallback convention, vs. some other sentinel) before landing the fix -- check
how downstream consumers (IC engine, ensemble) already handle `illiq`'s existing NaN/None
convention.

## Where

- `src/intelligence/feature_factory.py` -- `_amihud_illiq_z_series_full` (line 2273 as of
  2026-09-22; the divide is at line 2284)
- Related: [340](completed/340-ihf-5m-feature-compute-zero-row-positive-input-error.md) (same
  root data condition, different function, already fixed)
