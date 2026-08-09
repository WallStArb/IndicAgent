# 286 - `_build_obs_matrix`'s `vol_of_vol` column carries a nested-rolling warmup artifact

**Filed:** 2026-08-09
**Source:** Phase 172 cross-AI plan review (Antigravity, LOW) — the one finding neither reviewer
duplicated
**Status:** pending, not blocking

## The bug

`services/regime_writer.py::_build_obs_matrix` builds the 5-column composite observation matrix and
sets:

```
valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
```

That is correct for `log_return`, `realized_vol`, `momentum`, and `rel_volume`, each of which is a
single rolling pass over `log_returns` (or `log_volumes`). It is not correct for `vol_of_vol`,
which is a rolling std of `realized_vol`:

```
realized_vol = _rolling(log_returns, vol_window, np.std)
vol_of_vol   = _rolling(realized_vol, vol_of_vol_window, np.std)
```

`_rolling` zero-pads its own warmup prefix by `window - 1`. So `realized_vol[0 : vol_window - 1]`
is zeros, and any `vol_of_vol[i]` whose lookback window reaches back into that range is computed
partly over fabricated zeros. Under `max(windows) - 1`, the first `vol_window - 1` emitted
`vol_of_vol` values are exactly those rows. At production's `vol_window = 20`, that is 19 rows per
(symbol, tf) cell presented as valid observations when they are warmup artifacts.

The mathematically clean start index for a nested rolling operation is
`vol_window + vol_of_vol_window - 2`.

## Why it was not fixed in Phase 172

Phase 172's new `_build_obs_matrix_volatility` uses the corrected index
(`vol_window + vol_of_vol_window - 2`); that was decided during the Phase 172 review incorporation
and is specified in `172-03-PLAN.md` Task 2. The legacy `_build_obs_matrix` was deliberately left
alone: it feeds `feature_vectors.regime`, whose ~26.8M existing rows were all produced under the
current behavior. Changing the builder would silently change the meaning of a column Phase 172 is
explicitly leaving untouched during the phased cutover, and would invalidate the corpus without a
recompute.

## Impact assessment (do this before deciding to fix)

The artifact affects 19 bars at the start of each (symbol, tf) series out of at least 20000, and
those bars are additionally inside the HMM's own `initial_warmup_bars` window in the walk-forward
path (252 bars at `1d`, 19800 at `5m`), so in the walk-forward path they are very likely never used
to label anything. Measure that before spending effort:

1. Confirm whether any labeled bar in `feature_vectors` maps back to an observation row inside the
   contaminated prefix. If none does, the artifact is latent and the fix is documentation only.
2. If some do, the fix is a one-line change to `valid_start` plus its early-return threshold
   (`len(log_returns) < vol_window + vol_of_vol_window - 1`), and it invalidates
   `feature_vectors.regime` corpus-wide, so it should be bundled with a recompute rather than
   shipped alone.

Either way, add a code comment to `_build_obs_matrix` naming the artifact, so the next reader does
not rediscover it or "restore parity" from the volatility builder in the wrong direction.

## References

- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-REVIEWS.md` (Antigravity, concern 1)
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-03-PLAN.md` Task 2
- `services/regime_writer.py::_rolling`, `::_build_obs_matrix`
