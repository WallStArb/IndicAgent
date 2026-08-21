---
status: pending
priority: P2
filed: 2026-08-21
source: found live, first production run of regime_coverage_auditor.py immediately after
  enabling its systemd timer (todo 169)
---

# BIL, ETHA, IBIT have 100% NULL `feature_vectors.regime` -- same failure shape as todo 168's 7 symbols

## What

`regime_coverage_auditor.py`'s first live run (2026-08-21, right after its systemd timer was
enabled per todo 169) found 3 symbols with zero non-null per-symbol HMM regime labels, despite
having substantial `feature_vectors` row counts:

```
symbol | total_rows | non_null_regime
BIL    | 179,500    | 0
ETHA   | 56,399      | 0
IBIT   | 70,758      | 0
```

Same failure shape as todo 168 (7 symbols: LQD/PFF/RSP/USMV/UUP/VWO/XRT, closed 2026-07-22) --
`regime_writer.py` has never produced a usable HMM label for these 3, despite real bar/feature
history existing. Not the same symbols as 168's list -- a distinct occurrence, not a regression
of an already-fixed case.

`ETHA`/`IBIT` are crypto-trust ETFs (Ethereum/Bitcoin), plausibly added in the 2026-08-05/06
universe expansion -- worth checking whether their price/return dynamics (e.g. near-zero-volume
early history, or extreme volatility) cause a degenerate HMM fit (todo 168's "near-miss vs true
degenerate-collapse split" precedent). `BIL` (T-Bill ETF, near-zero-volatility by construction)
is a pre-existing symbol already flagged THIS SESSION (todo 340's sibling finding) with
`"value out of range: underflow"` `backfill_status` compute errors across all 4 real
timeframes despite having real `feature_vectors` rows -- BIL's near-zero-return-variance
character is a plausible common root cause behind both this regime-label gap and that separate
compute-underflow finding, worth checking together rather than assuming unrelated.

## Fix shape (not investigated yet)

1. Re-run `regime_writer.py --symbols BIL,ETHA,IBIT` with verbose/debug logging to see whether
   the HMM fit itself fails (exception, degenerate covariance) or silently produces an
   all-NULL/all-same-state result that gets written as NULL.
2. If it's a degenerate-HMM issue (e.g. BIL's near-zero volatility collapsing all states into
   one), decide the same way todo 168's precedent did: real near-miss vs. true degenerate
   collapse, and whether a relaxed covariance floor or a different `n_components` fixes it
   without compromising other symbols' fits.
3. Check whether `ETHA`/`IBIT`'s short history (crypto-trust ETFs, recent listings) is simply
   below the walk-forward warmup requirement (`initial_warmup_bars`) -- if so, this may resolve
   on its own as more history accumulates, not a code bug.

## Where

- `services/regime_writer.py` -- HMM fit / walk-forward path
- `services/regime_coverage_auditor.py` -- the auditor that surfaced this (working as intended,
  no fix needed there)
- Precedent: `completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md`
- Possibly related: `pending/340-ihf-5m-feature-compute-zero-row-positive-input-error.md` (BIL's
  separate compute-underflow finding, same session)
