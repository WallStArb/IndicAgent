"""Market-residual kernels: the single-name stat-arb residual family (todo 584 item 8, D2).

The stored columns are the storable half of the Avellaneda-Lee (2010) ingredient set: the
name's residual against the fixed market series, its dispersion, trailing z, lag-1
autocorrelation, and the stability of the beta that defines it. The paper's s-score machinery
(OU half-life, equilibrium sigma) and sector-ETF residuals stay in the research layer by
decision (docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md, implementation spec).

Same shape as the factor-beta path in kernels/macro.py: one incremental builder over daily
bars (`build_market_residual_series`, called by the batch service), one daily-reference-grid
kernel that runs the same builder so its declared memory and causality are checked
(`market_residual_daily`), and one row-grid pass-through (`market_residual_pass_through`)
whose `ext_*` inputs the caller aligns as-of the row's bar end. The beta inside the residual
is THE equity beta: the same rolling OLS estimator and the same `feature.factor_beta.window`
seed as `kernels.macro.build_symbol_beta_series`, never a second beta definition. The market
series is SPY's daily log returns (pin-down 2: permanent, tradeable, point-in-time; never a
universe-derived average).

Definitions (daily grain, broadcast to every timeframe by date, the beta cadence contract):

- `market_residual_return[t]` = r_sym[t] - beta[t] * r_spy[t], beta[t] the trailing
  `feature.factor_beta.window` OLS slope over returns ending at t (NaN when var_spy <= 1e-12,
  and NaN at every date for SPY: a self-regression is degenerate, the equity_beta_z rule).
- `idiosyncratic_volatility[t]` = sample std (ddof=1) of the residual over the trailing
  `feature.idiosyncratic_volatility.window` (21, [conventional] monthly, Ang et al. 2006;
  unannualized).
- `market_residual_z[t]` = trailing time-series z of the name's own residual series over
  `feature.market_residual.z_window` (252, [conventional] one trading year). Cross-sectional
  standardization never happens in storage (pin-down 1).
- `market_residual_lag1_acf[t]` = lag-1 autocorrelation of the residual over
  `feature.market_residual.lag1_acf_window` (63, [initial_estimate] one quarter), as the
  Pearson correlation of the window against itself lagged one: `_corr_or_nan` semantics, so a
  no-spread window is NaN, never 0.0.
- `residual_beta_stability[t]` = sample std (ddof=1) of the rolling beta over
  `feature.residual_beta_stability.window` (60, [initial_estimate]): the dispersion estimator
  pinned by the review (pin-down 4), not beta-minus-lag-k.

A history-dependent statistic appends to its history only values computed over their own full
declared window (D1 rule 5): a date whose beta is undefined contributes no residual, and the
trailing windows hold the last N defined values (the `build_symbol_beta_series` convention).
Every output is NaN until its window fills; a zero-spread z is NaN; never a 0.0 fill.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import deque
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from src.intelligence.features.contract.registry import (
    Alignment,
    ExternalInput,
    Kernel,
    constant_value,
)
from src.intelligence.features.kernels._primitives import _corr_or_nan, _z_or_nan
from src.intelligence.features.kernels.macro import SPY, _grid_bars

if TYPE_CHECKING:
    from src.intelligence.feature_factory import FeatureFactoryConfig


class MarketResidualRecord(NamedTuple):
    """Five market-residual values for one calendar date; NaN is undefined, never a fill."""

    market_residual_return: float = math.nan
    idiosyncratic_volatility: float = math.nan
    market_residual_z: float = math.nan
    market_residual_lag1_acf: float = math.nan
    residual_beta_stability: float = math.nan


RESIDUAL_COLUMNS: tuple[str, ...] = MarketResidualRecord._fields


def _require_windows(config: FeatureFactoryConfig) -> tuple[int, ...]:
    """The four declared windows, each at least 2 (a spread needs two values), else ValueError."""
    windows = (
        config.market_residual_z_window,
        config.idiosyncratic_volatility_window,
        config.market_residual_lag1_acf_window,
        config.residual_beta_stability_window,
    )
    names = (
        "market_residual_z",
        "idiosyncratic_volatility",
        "market_residual_lag1_acf",
        "residual_beta_stability",
    )
    for name, value in zip(names, windows, strict=True):
        if value < 2:
            raise ValueError(f"{name} window must be >= 2, got {value}")
    return windows


def build_market_residual_series(
    symbol_1d_bars: list[dict],
    spy_1d_bars: list[dict],
    symbol: str,
    config: FeatureFactoryConfig,
) -> dict:
    """date -> MarketResidualRecord for one symbol, incrementally in O(D) over the daily bars.

    Mirrors `kernels.macro.build_symbol_beta_series` (bisect cursors, prev-close trackers,
    deques of declared windows). A date without a bar on both series, or with fewer than two closes on
    either, emits no record; a date whose beta is undefined carries NaN for `market_residual_return` and the
    last computed trailing statistics (they remain defined over their own histories). SPY
    emits all-NaN records: a self-regression is degenerate.
    """
    z_window, idio_window, acf_window, stability_window = _require_windows(config)
    beta_window = config.factor_beta_window
    is_spy = symbol == SPY

    bars_map = {"sym": symbol_1d_bars, "spy": spy_1d_bars}
    dates_map = {k: [b["ts"].date() for b in v] for k, v in bars_map.items()}
    # Only dates both series have a bar on: a missing bar would otherwise read as a stale close
    # and a fabricated 0.0 return. prev_close advances only on these dates, so a return spans the
    # same calendar interval for the name and for SPY.
    all_dates = sorted(set(dates_map["sym"]) & set(dates_map["spy"]))

    cursors: dict[str, int] = {k: 0 for k in bars_map}
    prev_close: dict[str, float] = dict.fromkeys(bars_map, 0.0)

    sym_ret_hist: deque = deque(maxlen=beta_window)
    spy_ret_hist: deque = deque(maxlen=beta_window)
    residual_hist: deque = deque(maxlen=max(z_window, idio_window, acf_window))
    beta_hist: deque = deque(maxlen=stability_window)

    market_residual_return = math.nan
    idiosyncratic_volatility = math.nan
    market_residual_z = math.nan
    market_residual_lag1_acf = math.nan
    residual_beta_stability = math.nan
    result: dict = {}

    for d in all_dates:
        for k in bars_map:
            cursors[k] = bisect_right(dates_map[k], d)
        sym_end, spy_end = cursors["sym"], cursors["spy"]
        if sym_end < 2 or spy_end < 2:
            for k, end in (("sym", sym_end), ("spy", spy_end)):
                if end >= 1:
                    prev_close[k] = float(bars_map[k][end - 1]["close"])
            continue

        sym_close = float(symbol_1d_bars[sym_end - 1]["close"])
        spy_close = float(spy_1d_bars[spy_end - 1]["close"])

        if prev_close["sym"] > 1e-10 and prev_close["spy"] > 1e-10 and not is_spy:
            sym_ret = math.log(sym_close / prev_close["sym"])
            spy_ret = math.log(spy_close / prev_close["spy"])
            sym_ret_hist.append(sym_ret)
            spy_ret_hist.append(spy_ret)

            if len(sym_ret_hist) >= beta_window:  # a beta over a full window only
                spy_arr = np.array(spy_ret_hist)
                # ddof=1 matches np.cov (see build_symbol_beta_series' WR-01 note).
                var_spy = float(np.var(spy_arr, ddof=1))
                if var_spy > 1e-12:
                    sym_arr = np.array(sym_ret_hist)
                    beta = float(np.cov(sym_arr, spy_arr)[0, 1]) / var_spy
                    market_residual_return = sym_ret - beta * spy_ret
                    residual_hist.append(market_residual_return)
                    beta_hist.append(beta)

                    residuals = np.asarray(residual_hist, dtype=float)
                    if len(residuals) >= idio_window:
                        idiosyncratic_volatility = float(np.std(residuals[-idio_window:], ddof=1))
                    market_residual_z = _z_or_nan(residual_hist, z_window)
                    if len(residuals) >= acf_window:
                        window = residuals[-acf_window:]
                        market_residual_lag1_acf = _corr_or_nan(
                            window[:-1], window[1:], acf_window - 1
                        )
                    if len(beta_hist) >= stability_window:
                        residual_beta_stability = float(np.std(np.asarray(beta_hist), ddof=1))
                else:  # no benchmark variance: the residual is undefined, not 0.0
                    market_residual_return = math.nan

        result[d] = MarketResidualRecord(
            market_residual_return,
            idiosyncratic_volatility,
            market_residual_z,
            market_residual_lag1_acf,
            residual_beta_stability,
        )
        prev_close["sym"] = sym_close
        prev_close["spy"] = spy_close

    return result


_RESIDUAL_GRID_OUTPUTS: tuple[str, ...] = tuple(f"_mr_{name}" for name in RESIDUAL_COLUMNS)


def _compute_market_residual_daily(x, config):
    ts_dt = x["ts_dt"]
    symbol = constant_value(x["symbol"], "symbol")
    records = build_market_residual_series(
        _grid_bars(ts_dt, x["ref_sym_close"]),
        _grid_bars(ts_dt, x["ref_spy_close"]),
        symbol,
        config,
    )
    out = {name: np.full(len(ts_dt), np.nan) for name in _RESIDUAL_GRID_OUTPUTS}
    for i, stamp in enumerate(ts_dt):
        record = records.get(stamp.date())
        if record is not None:
            for field, name in zip(RESIDUAL_COLUMNS, _RESIDUAL_GRID_OUTPUTS, strict=True):
                out[name][i] = getattr(record, field)
    return out


EXTERNAL_INPUTS = (
    *(
        ExternalInput(f"ext_{name}", np.dtype(np.float64), Alignment.DAILY_ASOF_CLOSE)
        for name in RESIDUAL_COLUMNS
    ),
)


def _compute_residual_pass_through(x, config):
    return {
        name: np.asarray(x[f"ext_{name}"], dtype=np.float64).copy() for name in RESIDUAL_COLUMNS
    }


KERNELS = (
    Kernel(
        name="market_residual_daily",
        outputs=_RESIDUAL_GRID_OUTPUTS,
        inputs=("ts_dt", "ref_sym_close", "ref_spy_close", "symbol"),
        # beta_window returns feed the oldest residual in the widest trailing window; +2 is the
        # factor_beta_daily slack convention.
        memory=lambda c: (
            c.factor_beta_window
            + max(
                c.market_residual_z_window,
                c.idiosyncratic_volatility_window,
                c.market_residual_lag1_acf_window,
                c.residual_beta_stability_window,
            )
            + 2
        ),
        compute=_compute_market_residual_daily,
    ),
    Kernel(
        name="market_residual_pass_through",
        outputs=RESIDUAL_COLUMNS,
        inputs=tuple(f"ext_{name}" for name in RESIDUAL_COLUMNS),
        # Pass-through, the macro_pass_through contract: the path dependence belongs to the
        # builder and its grid kernel; warmup is the builder's own NaN-until-full discipline.
        memory=lambda config: 0,
        compute=_compute_residual_pass_through,
    ),
)
