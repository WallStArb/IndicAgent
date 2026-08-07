# src/intelligence/regime_signals/commodity_momentum_ts.py
"""commodity_momentum_ts — Commodity cross-sectional regime signal.

Computes two aligned series from a peer group of commodity ETFs:
  1. momentum_z_median  — cross-sectional median of per-symbol rolling log-return z-scores
  2. ts_proxy_median    — cross-sectional median of momentum slope acceleration (d^2 price/dt^2
                          z-score), an ETF-based proxy for contango/backwardation direction

Labels: up_primary / up_secondary / down_secondary / down_primary (4 states, composed
from Section 7's direction x primary/secondary rank scale — not an invented term).
4 labels (not 9) because commodity peer groups have 4-8 instruments — 9 would produce
sparse buckets with unreliable IC stratification.

Backs the single unified `commodity` regime_group (migration 306 merged the former
commodity_energy/commodity_metals/commodity_agri groups — each was too thin on its own to
clear the 4-8 instrument peer-group floor below). APR key momentum_window and
primary_threshold are read from the alpha.commodity_regime.* namespace.

Label-vocabulary non-overlap invariant (Pitfall 4, feature_ic_scores has no regime_group
column — group identity is implicit in regime_label string uniqueness): this module's tier
strings (up_primary/up_secondary/down_secondary/down_primary x contango/neutral/backwardation)
MUST NOT collide with equity's (low/mid/high x bear/neutral/bull) or rates' (steep/flat/inverted
x wide/tight) label sets. Do not rename these tiers to match another group's vocabulary.

Peer group for THIS module's own compute() (~11 members, all used as full peers here):
OIH/XLE/XOP/AMLP (energy), GLD/SLV/PPLT/GDX (metals), DBB (industrial metals), DBA (agri),
DBC (broad). Downstream, ic_engine.py's per-symbol regime-stratified IC routing treats 5 of
these (AMLP/GDX/OIH/XLE/XOP) differently: they carry genuine dual-categorical eq_*/
commodity_* tags (sector ETFs whose earnings driver is a single commodity), so the
`commodity` group's exclude_symbols (todo 224/225) keeps them routed to `equity` there —
this module's own peer set is unaffected, that carve-out is Job-2-only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("momentum_z", "ts_proxy")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Return (momentum_z_median, ts_proxy_median) series indexed by timestamp.

    Both series have NaN for the first momentum_window bars (warmup).
    Returns None if ref_bars is empty.
    """
    if not ref_bars:
        return None

    window: int = int(params["momentum_window"])

    momentum_cols: list[pd.Series] = []
    ts_proxy_cols: list[pd.Series] = []

    for symbol, df in ref_bars.items():
        closes = df["close"].values.astype(float)
        log_ret = np.log(closes[1:] / closes[:-1])
        log_ret = np.concatenate([[np.nan], log_ret])

        # rolling z-score of log returns
        s = pd.Series(log_ret, index=df["timestamp"])
        roll_mean = s.rolling(window, min_periods=window).mean()
        roll_std = s.rolling(window, min_periods=window).std()
        z = (s - roll_mean) / roll_std.replace(0, np.nan)
        momentum_cols.append(z)

        # term structure proxy: slope acceleration (2nd derivative of price)
        price_s = pd.Series(closes, index=df["timestamp"])
        slope = price_s.diff()
        accel = slope.diff()
        accel_roll_std = accel.rolling(window, min_periods=window).std()
        accel_z = accel / accel_roll_std.replace(0, np.nan)
        ts_proxy_cols.append(accel_z)

    # pd.concat(axis=1) aligns each peer's Series on its own timestamp index and
    # unions them -- do NOT overwrite the result with any single peer's raw index
    # (previously .set_axis()'d onto an arbitrary first-seen symbol): peers can have
    # meaningfully different backfill depth (a newly-added single-name equity vs. a
    # long-tenured ETF), so their raw lengths routinely differ and a positional
    # relabel is both wrong when it doesn't crash and guaranteed to crash when
    # lengths merely happen to differ. Mirrors breadth_vol.py's _compute_breadth,
    # which returns its natural concat-unioned index rather than forcing one on.
    momentum_df = pd.concat(momentum_cols, axis=1)
    ts_proxy_df = pd.concat(ts_proxy_cols, axis=1)

    return (
        momentum_df.median(axis=1),
        ts_proxy_df.median(axis=1),
    )


def build_tiers(
    params: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold lists for _assign_labels.

    Tier 1 (momentum): up_primary | up_secondary | down_secondary | down_primary
    Tier 2 (ts_proxy): contango | neutral | backwardation

    See module docstring — this vocabulary is deliberately non-overlapping with the
    equity (low/mid/high x bear/neutral/bull) and rates (steep/flat/inverted x wide/tight)
    tier vocabularies.
    """
    primary = float(params["primary_threshold"])
    tiers1 = [("up_primary", primary), ("up_secondary", 0.0), ("down_secondary", -primary)]
    tiers2 = [("contango", 0.25), ("neutral", -0.25)]
    return tiers1, tiers2
