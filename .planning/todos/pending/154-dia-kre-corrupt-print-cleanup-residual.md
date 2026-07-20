---
status: pending
priority: P2
filed: 2026-07-20
source: todo 147's 2026-07-20 low_bull CV investigation independently found 2 corrupt
  OHLCV prints not covered by todo 151's 18-row cleanup batch (151 closed 2026-07-20
  before these were folded in).
---

# `DIA` 2009-06-02 and `KRE` 2007-09-18 corrupt prints -- residual from 151's cleanup

## Problem

Todo 151 (known corrupt OHLCV print cleanup) ran `--apply` and corrected 18 confirmed
corrupt rows (`RSP`/`UUP`/`VWO`/`XRT`) on 2026-07-20, then closed. Todo 147's
independent investigation (same day, into `low_bull`'s vol-normalization CV outliers)
found 2 more textbook fabricated prints that were never in 151's candidate list
because `ops_known_corrupt_print_cleanup.py`'s candidate discovery is seeded from
`forward_returns.return_{scale}_suspect` flags on the 4 symbols 151 scanned, not a
full-corpus scan:

- `DIA` 1d 2009-06-02: `high=100000` on an `open=87.14` bar (sentinel-overflow tick,
  not previously named in any prior investigation)
- `KRE` 5m 2007-09-18 18:15: `high=400` on an `open=44.43` bar -- a full year before
  the already-known and already-classified 2008-09-18 KRE Lehman-aftermath event; a
  distinct occurrence, same symbol, do not conflate the two

Both are `99999.99`/`100000`/`400`-vs-`44` magnitude fabrications with no economic
basis, per todo 147's own characterization ("textbook fabricated/sentinel-overflow
ticks, not real prices; nothing here is an ambiguous crisis-event case").

## Fix

Run `ops_known_corrupt_print_cleanup.py --symbols DIA KRE` (scoped, not a full
corpus re-scan) to get these two into the tool's normal classify/dry-run/`--apply`
flow, then follow 151's own completed disposition note for the full-recompute
requirement: `backfill_status` reset to `pending` for the affected (symbol, tf)
pairs before `backfill_feature_factory.py --compute-only`, since
`forward_return_writer.py` has no historical-gap-fill mode (see
`.planning/todos/completed/151-known-corrupt-ohlcv-print-cleanup.md`'s disposition
for the exact sequence and empirical timing, ~17 min for 4 symbols -- 2 symbols
should be proportionally faster).

## Sizing

Small -- 2 known rows, same tooling and procedure 151 already used and documented.
Not urgent (doesn't block anything on its own; todo 147 already found its CV
divergence traces to this same corrupt-print class and is separately tracking
whether the fix resolves its own finding once this lands).

## References

- `.planning/todos/completed/151-known-corrupt-ohlcv-print-cleanup.md` -- disposition
  note has the exact recompute procedure + timing to reuse
- `.planning/todos/pending/147-vol-normalized-target-low-bull-divergence.md` -- the
  investigation that found these 2 rows, and the follow-up check (`true_range_pct` CV,
  `ops_vol_normalized_target_ab.py --all-regimes`) to re-run once this lands
- `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`
