---
status: pending
priority: P3
filed: 2026-07-16
source: split from todo 035's full-tree audit (docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md)
---

# 124 — `market_data_ohlcv_tradeable` view: Tier-2 file audit

## Problem

Todo 035 closed by fixing the 2 live call sites with zero placeholder-bar filtering
(`cross_sectional_regime_model.py`, `counterfactual_tracker.py`) and building
`market_data_ohlcv_tradeable` as the single boundary. 13 more files reference the raw table and
were deliberately not touched in that pass (see the design doc's "not yet classified" and
"already correctly filtered" lists) — each needs a genuine per-file judgment call on whether it
should migrate to the view, and 3 of them (`regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py`) are already filtering correctly with an inline `volume > 0` and
would only gain a style/DRY benefit, not a correctness fix, from switching.

## Not yet done

For each of the 13 files listed in `tests/unit/test_market_data_ohlcv_boundary.py`'s
`_ALLOW_LIST` with a "Tier-2" or "not yet classified" reason: read the call site, determine
whether it needs tradeable-only bars or genuinely wants the full calendar grid (e.g. backfill
completeness checks may intentionally count against the full grid), migrate to
`market_data_ohlcv_tradeable` where appropriate, and remove its entry from the allow-list.

## References

- `docs/plans/2026-07-16-market-data-ohlcv-active-bars-boundary-design.md` — full audit,
  per-file classification as of 2026-07-16
- `tests/unit/test_market_data_ohlcv_boundary.py` — the allow-list to shrink as files are
  reviewed
- `.planning/todos/completed/035-market-ohlcv-active-bars-view.md` — closed todo this splits from
