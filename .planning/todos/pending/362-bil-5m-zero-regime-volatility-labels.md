---
status: pending
priority: P3
filed: 2026-08-31
source: todo 285's closure verification (per-cell coverage check, step 4) -- found
  while diffing the post-Phase-173 corpus recompute against 172-05's relabel-coverage
  evidence file
---

# `BIL`/`5m` has zero `regime_volatility` (calm/elevated/turbulent) labels despite 165,500 rows

## What

`172-05-relabel-coverage.json` (Phase 172's original relabel run) recorded `BIL/5m` as
`verdict: 'labeled'`. In the post-Phase-173 full corpus recompute (completed 2026-08-31),
`feature_ic_scores` has zero rows for `BIL/5m` under any of `calm`/`elevated`/`turbulent`.
Checked `feature_vectors` directly: `BIL/5m` has 165,500 total rows and 0 with
`regime_volatility IS NOT NULL` -- so the gap is upstream of `ic_engine` entirely, in
`regime_writer`'s volatility-HMM labeling itself, not a downstream measurement issue.

This is NOT the same explanation as the other 44 cells in the same diff (43x `1d`
timeframe + `IBIT/5m`) -- those are all short-history/low-bar-count cases consistent
with the documented ~60K-bar reliability floor. `BIL/5m` has plenty of rows (165,500);
something about its price series specifically produces zero volatility-regime labels.

## Hypothesis (not yet confirmed)

`BIL` (SPDR Bloomberg 1-3 Month T-Bill ETF) is a near-zero-volatility instrument by
construction -- its price series may be too flat for the volatility HMM to identify
distinct regime states at all (e.g. if the fitting step requires some minimum variance
to converge, or degenerates to a single-state fit that never gets a `calm`/`elevated`/
`turbulent` label written). Not verified -- needs a look at `regime_writer.py`'s
volatility walk-forward path against `BIL/5m` specifically (log output, HMM fit
diagnostics) before concluding this is expected-and-fine vs. a real gap.

## What to do

1. Check `regime_writer.log` (or re-run scoped to `--symbols BIL --tf 5m`) for what
   happened during `BIL/5m`'s labeling pass -- did it fail silently, get skipped, or
   fit successfully but degenerate to a single always-same label that never got written?
2. If BIL's near-flat price series is structurally unsuited to volatility-regime HMM
   fitting, this may be a legitimate "not applicable" case -- decide whether to
   document it as such (similar to the 1d bar-floor exemption) or whether the HMM
   fitting logic needs a minimum-variance guard that fails loud instead of silent.
3. Low priority, single-symbol/single-tf scope -- not blocking anything downstream.

## References

- `.planning/todos/completed/285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md` -- closure section, where this was found
- `.planning/phases/172-hmm-regime-volatility-only-redesign/evidence/172-05-relabel-coverage.json`
- `services/regime_writer.py` -- `_compute_symbol_tf_volatility_walk_forward`
