---
status: pending
priority: P0
filed: 2026-07-20
source: todo 147's true_range_pct CV re-check, re-run after 151/154 to verify their
  correction pass actually resolved the low_bull CV outlier -- it didn't. Root cause
  investigation below revised once from the initial framing after checking
  price_sanity_status directly (see "Correction" note).
---

# `price_sanity_status='confirmed_corrupt'` doesn't reach feature computation; VWO/DIA also never flagged at all

## Correction to initial framing

This todo originally claimed "VWO/DIA/KRE were all never corrected." That's only true for
VWO and DIA. **KRE was correctly identified and flagged** — verified live:
`market_data_ohlcv.price_sanity_status='confirmed_corrupt'` for the KRE row, and
`forward_returns.return_fast/return_mid` for that bar are sane and not suspect (151/154 did
their job for the columns they touch). The actual bug is one level deeper and affects KRE
too, despite it being "correctly" flagged.

## What's wrong

Two distinct gaps, found investigating why todo 147's `true_range_pct` CV check still fails
post-151/154:

**1. VWO (2007-05-02 15:00, 1h, `high=99999.99`) and DIA (2009-06-02 14:00, 5m,
`high=100000`) were never flagged at all** — `price_sanity_status` is NULL for both, verified
live via psql. Same candidate-discovery gap 154 already documented for KRE: discovery is
seeded from `forward_returns.return_*_suspect` flags, and these two prints apparently never
tripped that flag either (both were found via todo 147's independent CV investigation, not
this tool's own discovery path).

**2. Even a correctly-flagged row (KRE) still corrupts `feature_vectors.true_range_pct`,
because the flag never reaches feature computation.** `market_data_ohlcv_tradeable` (the
view CLAUDE.md mandates for all compute/measurement reads) DOES filter
`price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'` correctly. But
`services/backfill_feature_factory.py` — the service that actually computes
`feature_vectors.true_range_pct` — reads the RAW `market_data_ohlcv` table directly (its own
docstring: "Source invariant (T1/D-05): Only market_data_ohlcv is read for compute"), not the
tradeable view. Confirmed via `tests/unit/test_market_data_ohlcv_boundary.py`'s allow-list:
`backfill_feature_factory.py` is listed as "Already correctly filters with `volume > 0`
(confirmed correct via empirical audit **2026-07-16**... Tier-2 follow-up, todo 124's sibling
audit list)."

**That audit predates `price_sanity_status`, which didn't exist until todo 149's migration
(2026-07-19/20).** `volume > 0` and the tradeable view's filter WERE equivalent when audited
— they no longer are. `price_sanity_status='confirmed_corrupt'` rows still have `volume > 0`
(price columns are deliberately never mutated, per Renaissance data-retention principle), so
`backfill_feature_factory.py`'s `volume > 0`-only filter lets them straight through. This is
why 154's KRE fix (`DELETE FROM feature_vectors` + `backfill_feature_factory.py
--compute-only --symbols KRE` recompute) reproduced the exact same corrupt `true_range_pct`
value on recompute — the recompute read the same raw, unmutated, still-`high=400` row again.
`ops_known_corrupt_print_cleanup.py`'s own docstring claims setting the flag "closes th[e]
residual exposure" for features computed directly from raw OHLCV (momentum_z_*, volatility_
rank, etc.) — that claim is **not true for the batch/backfill computation path**, only for
any consumer that actually reads `market_data_ohlcv_tradeable`.

## Blast radius

Small and bounded today: `SELECT price_sanity_status, count(*) FROM market_data_ohlcv GROUP
BY price_sanity_status` → 20 rows `confirmed_corrupt`, 16 `ambiguous`, 484 `plausible`, rest
NULL (out of 215.6M total rows). But every one of those 20 `confirmed_corrupt` rows still
feeds `true_range_pct` and every other feature computed directly from raw high/low/close
(`body_ratio`, `upper_wick_ratio`, `lower_wick_ratio`, `range_vs_atr`, `bar_close_pos`,
`dist_from_high`/`dist_from_low`, `stoch_k`, `range_pct`, etc. — same exposure class
`ops_known_corrupt_print_cleanup.py`'s own docstring names) via `backfill_feature_factory.py`.
Not urgent by row count, but architecturally the "flag it and downstream consumers respect
it" contract is silently false for the one consumer (feature computation) the correction
mechanism was built to protect.

## Fix

1. **VWO/DIA**: run `ops_known_corrupt_print_cleanup.py --symbols VWO DIA --apply` (human
   dry-run review first, per its own safety design) to flag them — same as KRE's fix, just
   two more rows.
2. **The real fix**: migrate `services/backfill_feature_factory.py` to read from
   `market_data_ohlcv_tradeable` instead of raw `market_data_ohlcv` — this is exactly what
   [todo 124](124-market-ohlcv-tradeable-view-tier2-audit.md) already tracks, but its current
   text ("would only gain a style/DRY benefit, not a correctness fix") is now **stale** —
   written 2026-07-16, before `price_sanity_status` existed. Updated 124 directly with this
   finding; that todo now owns the actual fix, this one is the evidence trail.
3. After 124's fix lands, redo the DELETE + recompute sequence for all `confirmed_corrupt`
   rows (KRE plus the newly-flagged VWO/DIA) so `feature_vectors`/`forward_returns` actually
   exclude them, then re-run todo 147's CV check a third time.

## References

- `.planning/todos/pending/147-vol-normalized-target-low-bull-divergence.md` — the CV
  re-check this gap was found investigating
- `.planning/todos/pending/124-market-ohlcv-tradeable-view-tier2-audit.md` — now the owner
  of the actual fix (raw-table → tradeable-view migration for
  `backfill_feature_factory.py`); updated with this finding
- `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py:1-12` — docstring claims this
  "closes th[e] residual exposure" for raw-OHLCV-derived features; not true for the batch
  compute path given (2) above
- `services/backfill_feature_factory.py:16` — "Source invariant (T1/D-05): Only
  market_data_ohlcv is read for compute"
- `tests/unit/test_market_data_ohlcv_boundary.py` `_ALLOW_LIST["services/backfill_feature_factory.py"]`
  — the stale 2026-07-16 "confirmed correct" note
- Live verification (2026-07-20): `market_data_ohlcv.price_sanity_status` NULL for VWO
  2007-05-02/DIA 2009-06-02, `'confirmed_corrupt'` for KRE 2007-09-18;
  `feature_vectors.true_range_pct` still 7.855 for the KRE row despite the flag and a
  completed recompute; `forward_returns` for the same KRE row is sane (return computation
  uses `open`, unaffected by this particular corrupt `high` value — coincidental, not
  systematic protection)
- Distinct from the 2010-05-06 IGV/CWB/VUG cluster also surfaced in this CV re-check — that's
  the real Flash Crash, legitimate per todo 152's crisis-event precedent, not corrupt
