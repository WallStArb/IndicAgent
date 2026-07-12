"""REGISTRY -- signal_type string -> regime signal module.

`services/cross_sectional_regime_model.py` dispatches to a module here by the
`signal_type` field of each `alpha.regime.groups` entry. Registry completeness is
independent of group enablement (RESEARCH.md / PATTERNS.md) -- commodity_momentum_ts and
fx_dollar_carry are registered here even though their groups ship `enabled: false`
(todo 041 gates enablement only, not module existence).

Every module implements the same pure, DB-free contract:
  - compute(ref_bars: dict[str, pd.DataFrame], params: dict[str, Any]) -> tuple[pd.Series, pd.Series] | None
  - build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]
  - PROB_KEYS: tuple[str, str]
"""

from __future__ import annotations

from src.intelligence.regime_signals import (
    breadth_vol,
    commodity_momentum_ts,
    curve_credit,
    fx_dollar_carry,
)

REGISTRY: dict[str, object] = {
    "breadth_vol": breadth_vol,
    "curve_credit": curve_credit,
    "commodity_momentum_ts": commodity_momentum_ts,
    "fx_dollar_carry": fx_dollar_carry,
}
