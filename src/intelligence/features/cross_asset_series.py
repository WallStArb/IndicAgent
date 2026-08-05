"""CrossAssetRecord -- the single shared cross-asset contract (Phase 151 Plan 04).

Declares the 8 symbol-independent cross-asset/macro values (vix_z, flight_quality,
yield_slope_z, tip_tlt_ret_z, hyg_lqd_ret_z, sb_corr_fast, sb_corr_slow, sb_corr_z)
as a NamedTuple instead of a bare tuple, so a positional-unpack mistake becomes
impossible as this payload grows across phases (Codex review, MEDIUM: "several
waves depend on tuple-shaped payloads and a growing number of positional outputs").

Every construction site MUST use keyword arguments -- never positional -- so field
order can never silently matter. Imported by every producer and consumer:
`services/backfill_feature_factory.py` (batch path, Task 2), `src/intelligence/
feature_factory.py` (batch/live branch), and the live pipeline (plan 151-09).

Ring 1 (`src/intelligence/`): this module carries domain vocabulary (VIX proxy,
yield slope, flight-to-quality, stock-bond correlation), so it belongs in Ring 1,
never Ring 0 `src/core/`. Deliberately NOT placed in the existing
`src/intelligence/cross_asset_features.py` -- that module is archived v2.x ES/NQ
futures-spread code with its own module-level hardcoded constants; touching it
would pull unrelated tech debt into this phase (see 151-04's Interfaces section).
"""

from __future__ import annotations

from typing import NamedTuple


class CrossAssetRecord(NamedTuple):
    """8 symbol-independent cross-asset/macro values, one per calendar date.

    vix_z/flight_quality/yield_slope_z are the 3 pre-existing macro features
    (todo 222). tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_fast/sb_corr_slow/sb_corr_z
    are Phase 151 Plan 04's 5 new symbol-independent additions (the 2 remaining
    new fields, equity_beta_z/rate_beta_z, are per-SYMBOL and therefore carried
    separately -- see `build_symbol_beta_series` in services/backfill_feature_factory.py,
    not this tuple).

    All fields default to 0.0 so `cross_asset_by_date.get(date, CrossAssetRecord())`
    degrades to today's cold-start behaviour with no special-casing at the call site.
    """

    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0
    tip_tlt_ret_z: float = 0.0
    hyg_lqd_ret_z: float = 0.0
    sb_corr_fast: float = 0.0
    sb_corr_slow: float = 0.0
    sb_corr_z: float = 0.0
