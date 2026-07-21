---
status: pending
priority: P1
filed: 2026-07-16
source: split from todo 035's full-tree audit (docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md)
reclassified: 2026-07-20 -- P3->P1, "style/DRY only" claim below is now WRONG for
  backfill_feature_factory.py; see "2026-07-20 correction" section
---

# 124 — `market_data_ohlcv_tradeable` view: Tier-2 file audit

## 2026-07-20 correction — `backfill_feature_factory.py`'s "style/DRY only" claim is stale

The "already filtering correctly, only a style/DRY benefit" assessment below was made
2026-07-16, **before `price_sanity_status` existed** (added by todo 149's migration,
2026-07-19/20). At that time `volume > 0` alone WAS equivalent to
`market_data_ohlcv_tradeable`'s filter. It no longer is: the view now also filters
`price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`, and confirmed-corrupt rows keep
`volume > 0` by design (price columns are never mutated, only the status flag is set).
`backfill_feature_factory.py`'s `volume > 0`-only filter lets these rows straight through.

**Confirmed with a live reproduction (todo 160, 2026-07-20):** KRE 5m 2007-09-18 18:15 was
correctly flagged `price_sanity_status='confirmed_corrupt'` and `forward_returns` recomputed
sane for it, but `feature_vectors.true_range_pct` for that exact bar is still the corrupt
value (7.855) — because `backfill_feature_factory.py` recomputed it from the same
unmutated raw `high=400` row. This is a live, proven correctness gap, not a hypothetical
one — it's why todo 147 (vol-normalized target `low_bull` divergence) still can't close
after two rounds of "correction." `regime_writer.py` and `forward_return_writer.py` carry
the same `volume > 0`-only exposure and haven't been checked for a live reproduction yet, but
inherit the identical risk (any future `confirmed_corrupt` row whose corruption happens to
land in a column their computation reads).

**Reclassified P3 -> P1** given proven, not hypothetical, correctness impact. At minimum,
`backfill_feature_factory.py`'s migration to `market_data_ohlcv_tradeable` should be
prioritized ahead of the other 13 files in this audit — see Fix order below.

## Problem

Todo 035 closed by fixing the 3 live call sites with zero placeholder-bar filtering
(`cross_sectional_regime_model.py`, `counterfactual_tracker.py`, `ops_oos_holdout_eval.py`) and
building `market_data_ohlcv_tradeable` as the single boundary. 14 more files reference the raw
table and were deliberately not touched in that pass (see the design doc's "not yet classified"
and "already correctly filtered" lists) — each needs a genuine per-file judgment call on whether
it should migrate to the view, and 3 of them (`regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py`) were assessed 2026-07-16 as already filtering correctly with an
inline `volume > 0`, believed at the time to be only a style/DRY benefit, not a correctness fix,
from switching — **see the 2026-07-20 correction above: this is no longer true for
`backfill_feature_factory.py`, and the other two need re-checking against the same risk.**

## Not yet done

**Do `services/backfill_feature_factory.py` first** — proven correctness impact (above),
unlike the other 13 files which are still a style/DRY-only judgment call as far as evidence
shows. After that: `regime_writer.py` and `forward_return_writer.py` next, given they share
the identical `volume > 0`-only exposure pattern and just haven't had a live reproduction
found yet — worth a quick check for any `confirmed_corrupt` row whose corruption lands in a
column each of them reads, not just assumed safe by absence of evidence. Then the remaining
files listed in `tests/unit/test_market_data_ohlcv_boundary.py`'s `_ALLOW_LIST` with a
"Tier-2" or "not yet classified" reason: read the call site, determine whether it needs
tradeable-only bars or genuinely wants the full calendar grid (e.g. backfill completeness
checks may intentionally count against the full grid), migrate to
`market_data_ohlcv_tradeable` where appropriate, and remove its entry from the allow-list.

After `backfill_feature_factory.py`'s migration lands, todo 160's DELETE + recompute step for
the currently-flagged `confirmed_corrupt` rows needs to be redone (the recompute prior to the
migration used the same raw-table read and reproduced the same corruption).

## References

- `docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` — full audit,
  per-file classification as of 2026-07-16
- `tests/unit/test_market_data_ohlcv_boundary.py` — the allow-list to shrink as files are
  reviewed
- `.planning/todos/completed/035-market-ohlcv-active-bars-view.md` — closed todo this splits from
- `.planning/todos/pending/160-vwo-dia-kre-corrupt-prints-uncorrected.md` — the live
  reproduction that reclassified this todo's priority 2026-07-20
