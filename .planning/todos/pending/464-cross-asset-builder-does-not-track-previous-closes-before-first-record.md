---
status: pending
priority: P2
filed: 2026-09-29
source: 186 debt pass B5a
---

# build_cross_asset_series ignores TIP, HYG and LQD history before its first record date

## What

`build_cross_asset_series` skips every date until SPY, TLT and SHY each have two bars. In that
skip branch it advances `prev_close` for SPY, TLT and SHY only. TIP, HYG and LQD start the first
real date with `prev_close == 0.0` even when they have years of history, so on that date the
coverage guard (`prev_close["tip"] > 1e-10`) fails and `tip_tlt_ret_z` and `hyg_lqd_ret_z` are
missing (NaN since pass B5a, 0.0 before). The z-score histories for both spreads then start one
observation late, which shifts every later value of those two columns.

On the live database SPY, TLT, SHY, TIP, HYG and LQD all cover 2017-08 onward, so the defect
touches the first record date of each build and, through the shifted history, the later values of
`tip_tlt_ret_z` and `hyg_lqd_ret_z`.

## Why it was not fixed in pass B5

Advancing the three trackers in the skip branch (`for k, end in cursors.items()`) is a one-line
change, and it moves the golden fixture: `tests/unit/intelligence/test_kernel_registry_parity.py`
failed on `real|SPY|1d column tip_tlt_ret_z: digest mismatch, sample row 0 got -0.582712 golden
0.0` and on the QQQ, TLT and XLE 1d cases. The fixture must not be edited outside a regeneration
commit, so the change was reverted.

## Steps

1. Apply the tracker fix with a failing test first (a TIP history that predates SPY, TLT and SHY:
   the first record date has a finite `tip_tlt_ret_z`).
2. Regenerate the golden fixture in its own commit with the per-case changed-column list
   (expected: `tip_tlt_ret_z`, `hyg_lqd_ret_z` and their downstream products on every case).
3. Land it before the phase 186 rebuild (186-26) so stored rows carry the corrected series once.
