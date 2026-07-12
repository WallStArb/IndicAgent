"""curve_credit -- Rates cross-sectional regime signal.

Signal 1 (curve_z): TLT log-return minus SHY log-return, rolling z-score.
  Positive -> long-end outperforms (curve steepening / rates falling) -> "steep".
  Negative -> short-end outperforms (curve inverted / rates rising) -> "inverted".
  Neither -> "flat".

Signal 2 (credit_z): HYG log-return minus LQD log-return, rolling z-score.
  Positive -> HY outperforms IG (spreads tightening, risk-on) -> "tight".
  Negative -> IG outperforms HY (spreads widening, risk-off) -> "wide".

Tier vocabulary follows docs/foundation/naming-system.md Section 7 (Gradient Scale
Vocabulary, Domain-Specific Scales) -- "steep/flat/inverted" is the Curve shape scale,
"tight/wide" is the Credit spread state scale. Both are sanctioned domain-specific terms
(standard fixed-income/credit vocabulary a practitioner recognizes unprompted), not
generic low/mid/high.

LABEL-VOCABULARY NON-OVERLAP INVARIANT (RESEARCH.md Pitfall 4): feature_ic_scores has no
regime_group column -- group identity is implicit in regime_label string uniqueness
across enabled groups. curve_credit's tier vocabulary (steep/flat/inverted x wide/tight)
MUST NOT reuse any tier name from breadth_vol's vocabulary (low/mid/high x
bear/neutral/bull) or any other enabled group's vocabulary. If a future group's
build_tiers() ever collides with an existing tier name, two semantically different
regimes would silently coalesce under the same `regime` string in feature_ic_scores.
This is a documented constraint, not schema-enforced -- verify manually when adding a
new group.

Label format: {curve_tier}_{credit_tier}  e.g. "steep_tight", "inverted_wide".
6 possible labels (3 x 2).

No DB calls in this module -- pure functions over pre-fetched ref_bars (DB-free,
compute != persistence SoC rule).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("curve_z", "credit_z")

_REQUIRED_SYMBOLS = ("TLT", "SHY", "HYG", "LQD")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Compute (curve_z, credit_z) series from pre-fetched peer bars.

    TLT, SHY, HYG, LQD must all be present in ref_bars.
    Returns None if any required symbol is missing.
    Both returned series indexed by timestamp. NaN for warmup bars.

    curve_window/credit_window are treated as already-bar-scaled ints by this module
    (dispatcher pre-scales day-denominated APR window values via tf_window() before
    calling compute() -- same convention as breadth_vol.py, RESEARCH.md Assumption A1).
    """
    for sym in _REQUIRED_SYMBOLS:
        if sym not in ref_bars:
            return None

    curve_window = int(params.get("curve_window", 60))
    credit_window = int(params.get("credit_window", 60))

    curve_spread = _log_return_spread(ref_bars["TLT"], ref_bars["SHY"])
    credit_spread = _log_return_spread(ref_bars["HYG"], ref_bars["LQD"])

    curve_z = _rolling_z(curve_spread, curve_window)
    credit_z = _rolling_z(credit_spread, credit_window)

    combined_index = curve_z.index.intersection(credit_z.index)
    return curve_z.reindex(combined_index), credit_z.reindex(combined_index)


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker.

    tiers1: curve z-score buckets (3 tiers: inverted, flat, steep).
    tiers2: credit z-score buckets (2 tiers: wide, tight).
    """
    inverted = float(params.get("inverted_threshold", -0.5))
    steep = float(params.get("steep_threshold", 0.5))
    tight = float(params.get("credit_tight_threshold", 0.0))
    return (
        [("inverted", inverted), ("flat", steep), ("steep", float("inf"))],
        [("wide", tight), ("tight", float("inf"))],
    )


def _log_return_spread(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.Series:
    s_a = df_a.set_index("timestamp")["close"].astype(float).sort_index()
    s_b = df_b.set_index("timestamp")["close"].astype(float).sort_index()
    lr_a = np.log(s_a / s_a.shift(1))
    lr_b = np.log(s_b / s_b.shift(1))
    aligned = pd.concat([lr_a.rename("a"), lr_b.rename("b")], axis=1).dropna()
    return (aligned["a"] - aligned["b"]).rename("spread")


def _rolling_z(spread: pd.Series, window: int) -> pd.Series:
    mean = spread.rolling(window=window, min_periods=window).mean()
    std = spread.rolling(window=window, min_periods=window).std()
    return (spread - mean) / std.where(std > 1e-10)
