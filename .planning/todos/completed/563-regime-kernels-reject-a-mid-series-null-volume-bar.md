---
status: pending
priority: P1
filed: 2026-10-29
source: Opus review of the todo 560 volume guard
---

# Regime walk-forward kernels fail a whole 1d series on a mid-series NULL-volume bar

`hmm_trend_walk_forward` is `nan_volume_safe` and reads `volume` (`needs_volume`). Its
`_finite_prefix_rows` (`kernels/regime.py`) raises `ValueError` when a non-finite value is followed
by finite rows, deliberately (a NaN volume is never silent). `compute_kernels` runs the regime
kernels in the same call as every other kernel, so one mid-series NULL-volume bar fails the whole
series in `backfill_feature_factory` (logged as a failed series, no rows written).

145 names have mid-series NULL volume on 1d (IBKR `ibkr/fallback` and `venue` rows, all followed by
non-NULL bars). The raise predates todo 560 and is correct for a silent-wrong-answer standard, but
those 145 names then get no regime and no features from the 186-26 rebuild.

## Options

- Plan 191-20's Alpaca 1d re-derive (todo 545, D-191-Q) may remove the NULLs; recount after it lands
  before building anything.
- Else treat a NaN-volume row as a missing observation in the trend family: the walk-forward state
  carries over and that row's outputs are unlabeled, which needs the HMM's own review (todo 248).

Decide before 186-26 launches, since the regime kernels are in its fingerprinted closure.

## Recount after the 1d re-derive and decision (2026-10-29, data lane)

The Alpaca SIP re-derive does not remove the NULLs. Canonical 1d still holds 125,198 `ibkr/fallback`
bars on 145 names (the tradeable view NULLs volume for the basis-`none` kinds `fallback` and
`venue`; `venue` is no longer canonical). In the view: 125,174 NULL-volume rows on the same 145
names, each followed by finite-volume bars. Per name: median 1 NULL run (143 of 145 have one
contiguous gap, max 4), median 18.4% of the series NULL, 13 names more than half NULL.

Decision for 186-26 (the regime kernels are in its fingerprinted closure, so this lands before launch
or the rebuild's completed cells are discarded): do not build NaN-tolerant observation windows and
HMM marginalization first. Contain it. A series with a mid-series non-finite volume gets the
`needs_volume` regime family's outputs NaN with a distinct status code (a new `STATUS_INPUT_GAP`
beside `STATUS_NO_MODEL`, never a silent NaN), and every other kernel of that series computes and
writes as usual. The 145 names keep all non-regime features; their trend regime is explicitly
unlabeled. The marginalizing walk-forward (predict through the gap, skip the emission update, NaN-safe
windows) is a separate follow-up needing the todo 248 HMM review, filed below as P2; it can rebuild
only the regime columns of these names later.

Follow-up todo to file after the fix lands: marginalize a mid-series volume gap in the trend HMM
(145 names, 125,174 rows).

## Landed 2026-10-29

Containment (the decision above): `_compute_family` returns the all-NaN result with `STATUS_INPUT_GAP` (5.0, `_hmm.py`)
when a `needs_volume` family sees a non-finite volume followed by finite rows; a close gap still raises, a non-finite
tail and a clean series are unchanged. The marginalizing walk-forward stays a P2 follow-up (todo 248 review).
