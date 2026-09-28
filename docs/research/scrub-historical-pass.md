# Historical D2a scrub pass: 1d and 5m results

Author: Claude (phase 185 plan 10 execution, 2026-09-28)
Informed by: `.planning/phases/185-daily-data-foundation/185-10-PLAN.md`; todo 151 dry-run report (`tests/fixtures/bars/corrupt_1d_dry_run_2026_09_26.txt`); migration 381; plan 05's rule library.

Status: complete. Both passes applied; quarantine state verified by
`tests/integration/test_scrub_pass_live.py`.

## Runs

| tf | wall | symbols | flags | quarantine flags |
|---|---|---|---|---|
| 1d | 45.2 s | 931 | 3,343 | 86 (price_sanity 83, non_positive_price 3) |
| 5m | 96.7 s | 931 | 418,962 | 0 |

Per-rule counts (1d): vol_scaled_jump 2,629 · stale_print 220 · return_magnitude 269 ·
volume_outlier 139 · price_sanity 83 · non_positive_price 3 · ohlc_invariant 0 ·
gap_before_next 0.
Per-rule counts (5m, D-14 ports only): gap_before_next 418,814 (~0.54% of bars) ·
return_magnitude 148. Both informational by design; nothing quarantines at 5m yet.

Provenance: one completed `bar_derivation_batch` row per tf (stage scrub,
code_commit 6d3e9868e for 1d), integrity facts per rule plus
`historical_pass_complete` per tf.

## Known answers

All 72 todo-151 dry-run keys (45 CONFIRMED_CORRUPT + 27 MARKET_EVENT) carry a
quarantine flag and are absent from `market_data_ohlcv_tradeable`; 0 of the
1,864 AMBIGUOUS keys is quarantined; the 15 legacy 1d confirmed_corrupt keys
stay quarantined through migration 381's `legacy_price_sanity_status` copy.
Global check: the tradeable view admits no bar with a quarantine flag.

## The 441 1d moves beyond ln(1.5)

Of the 441 1d close-to-close log moves with |ln| > ln(1.5) across the traded
series: 184 carry a `vol_scaled_jump` flag, 257 do not (short series never
reach the 61-bar window, by design). Exactly 1 of the 441 has any quarantine
rule co-fire: UHAL 2022-11-09 (52.89 -> 5.13 -> 52.02, one-bar crash that
fully reverses; price_sanity correctly quarantined it and the plan 05 tests
already pin it). The informational tier is behaving as intended: large real
moves are recorded, not hidden.

Top 20 by |move|, hand-checked against the surrounding price series:

| symbol | date | ln move | verdict |
|---|---|---|---|
| FRHC | 2012-10-31 | -2.849 | split-like: 7.77 -> 0.45 (~17:1), level persists |
| RCAT | 2009-01-05 | +2.590 | ultra-thin series (volume <= 11), print noise, see todo 454 |
| RCAT | 2011-07-14 | -2.492 | same |
| GYRE | 2017-02-13 | +2.361 | event-like: jump across an untraded gap, orderly decay after |
| UHAL | 2022-11-09 | -2.333 | bad print, fully reverses next bar; quarantined by price_sanity |
| UHAL | 2022-11-10 | +2.317 | the mirror rebound of the same bad print; real level returns |
| RCAT | 2008-12-09 | +2.303 | ultra-thin series |
| FRHC | 2011-10-25 | -2.003 | split-like or sustained collapse: 28.25 -> 3.81 (~7.4:1), persists; seam audit (plan 15) decides |
| ACRS | 2023-11-13 | -1.998 | event-like: 4.76 -> 0.64 on 100x volume (70M), persists; biotech failure shape |
| VNDA | 2009-05-07 | +1.982 | event-like: 1.08 -> 7.84 on 9M volume, keeps rising (Phase III pop) |
| WSHP | 2025-11-19 | +1.802 | event-like: 33 -> 200 round-number spike, decays but holds above pre-move |
| KDP | 2018-07-10 | -1.718 | split-like: Keurig merger exchange re-based 123.66 -> 22.19, persists |
| SEZL | 2023-09-14 | +1.633 | event-like: uplisting spike across an untraded gap |
| RCAT | 2011-07-25 | +1.609 | ultra-thin series |
| RCAT | 2013-01-04 | +1.599 | ultra-thin series |
| SRRK | 2024-10-07 | +1.530 | event-like: 7.42 -> 34.28 on 30M volume, holds a new level |
| RCAT | 2015-02-19 | +1.514 | ultra-thin series (volume 5) |
| SSP | 2018-06-05 | +1.430 | split-like: Scripps/Discovery transaction re-base across an untraded gap |
| RCAT | 2011-03-02 | +1.406 | ultra-thin series |
| SVRA | 2019-06-13 | -1.395 | event-like: 10.57 -> 2.62 on 8.7M volume, persists (failed trial) |

Summary: 9 event-like, 6 ultra-thin (all RCAT), 5 split-like or corporate-action
re-bases. None of the 19 un-quarantined rows looks like a corrupt print;
quarantining them would delete real signal. The 5 split-like rows are inputs
for plan 15's seam audit, not scrub defects.

## New defect class (todo 052)

One candidate appeared: ultra-thin traded series (todo 454). RCAT's entire 1d
"traded" history clears the volume > 0 bar while trading volume <= 30 shares
for years, with prices that jump orders of magnitude between consecutive
prints. No scrub rule fires (vol_scaled_jump needs a 61-bar window; the series
is too sparse), which is correct per rule, but the series carries no price
information. Filed as todo 454 with a PRIORITIES row; the decision (universe
eligibility dimension vs informational rule) belongs there, not here.
