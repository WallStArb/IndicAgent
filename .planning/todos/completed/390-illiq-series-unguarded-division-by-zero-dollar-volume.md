---
status: closed
priority: P1
filed: 2026-09-23
closed: 2026-10-27
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

## Triage 2026-09-26 (backlog review with the owner)

On the feature critical path: todo 435 wires `feature_vectors` into the research layer, so fresh, complete, correct features are a book input. Must land before `illiq` enters any family.

## Resolution

Closed 2026-10-27 in the todo 553 change. The function now lives in
`src/intelligence/features/kernels/volume.py`. Bar t's illiq is undefined, and NaN, when either
close it reads is not positive (the return has no log and the dollar-volume divisor is zero);
every z-score whose window holds it is NaN (no_fill), never inf and never 0.0. The undefined value
enters the z-score's cumulative sums as 0.0 and its windows are masked afterwards, because the
old body's inf poisoned the sums and turned every later z-score into 0.0, not only the windows
holding the bar. A series with no such bar computes bit-identically to before. Chose NaN over
the todo's suggested floor: a floored divisor would fabricate a huge finite illiq value.
Tests in `tests/unit/intelligence/test_liquidity_kernels.py`. Follow-up: todo 555.
