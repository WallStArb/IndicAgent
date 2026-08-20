# src/intelligence/regime_signals/fx_dollar_carry.py
"""fx_dollar_carry — FX cross-sectional regime signal.

Two signal dimensions:
  1. dollar_z  — UUP rolling log-return z-score (dollar trend strength)
  2. carry_z   — HYG rolling log-return z-score (risk-on/off proxy for carry)

UUP and HYG are REFERENCE_SYMBOLS: fetched by the service even if not peer members
of the fx group. The peer group (FXE, FXY, etc.) is used only to validate the group
has enough members; the signal itself anchors on UUP and HYG.

Labels: strong_dollar_risk_on / strong_dollar_risk_off /
        weak_dollar_risk_on / weak_dollar_risk_off

Note: IBIT (crypto) routes into the fx group via tag_filter ["fx_*", "crypto"] per the
ROADMAP Phase 144 crypto-into-fx decision — a routing config concern (migration/dispatcher),
not a change to this module's math.

Label-vocabulary non-overlap invariant (Pitfall 4, feature_ic_scores has no regime_group
column — group identity is implicit in regime_label string uniqueness): this module's tier
strings (strong_dollar/weak_dollar x risk_on) MUST NOT collide with equity's (low/mid/high x
bear/neutral/bull), rates' (steep/flat/inverted x wide/tight), or commodity's (up_primary/
up_secondary/down_secondary/down_primary x contango/neutral/backwardation) label sets. Do
not rename these tiers to match another group's vocabulary.

This module ships with its regime_group enabled: false (todo 041 gates enablement) —
built now for registry completeness per CONTEXT.md Claude's Discretion.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("dollar_z", "carry_z")
REFERENCE_SYMBOLS: tuple[str, ...] = ("UUP", "HYG")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Return (dollar_z, carry_z) indexed by timestamp. None if UUP missing."""
    if "UUP" not in ref_bars:
        return None

    window = int(params["momentum_window"])

    def _rolling_z(df: pd.DataFrame) -> pd.Series:
        closes = df["close"].values.astype(float)
        log_ret = np.log(closes[1:] / closes[:-1])
        log_ret = np.concatenate([[np.nan], log_ret])
        s = pd.Series(log_ret, index=df["timestamp"])
        roll_mean = s.rolling(window, min_periods=window).mean()
        roll_std = s.rolling(window, min_periods=window).std()
        return (s - roll_mean) / roll_std.replace(0, np.nan)

    dollar_z = _rolling_z(ref_bars["UUP"])
    carry_z = (
        _rolling_z(ref_bars["HYG"])
        if "HYG" in ref_bars
        else pd.Series(np.nan, index=dollar_z.index)
    )
    return dollar_z, carry_z


def build_tiers(
    params: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Tier 1: dollar strength. Tier 2: carry environment.

    Both lists MUST be ascending by upper_bound (_bucket()'s contract, enforced by
    cross_sectional_regime_model._assert_ascending_tiers -- see that function's
    docstring for what breaks if this list isn't ascending, todo 335).

    See module docstring — this vocabulary is deliberately non-overlapping with the
    equity, rates, and commodity tier vocabularies.
    """
    dollar_thresh = float(params["dollar_strong_threshold"])
    carry_thresh = float(params["carry_risk_on_threshold"])
    tiers1 = [("weak_dollar", dollar_thresh), ("strong_dollar", float("inf"))]
    tiers2 = [("risk_off", carry_thresh), ("risk_on", float("inf"))]
    return tiers1, tiers2
