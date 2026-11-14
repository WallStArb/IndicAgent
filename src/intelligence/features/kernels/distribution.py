"""Return-distribution and scale kernels: the single-name distribution columns (todo 584 item 8).

Four stored columns. Three are computed on the daily reference grid and broadcast to every
timeframe by date (the beta cadence contract, `kernels.macro`); `size_proxy` is a row-grid
column stored at the row timeframe like every own-bars column. The definitions are the pinned
spec's, verbatim (docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md, item 8):

- `max_daily_return[t]` = max daily log return over `feature.max_daily_return.window` (default
  21, [conventional] monthly, Bali et al. MAX).
- `max_drawdown[t]` = 1 - min over the trailing `feature.max_drawdown.window` (default 252,
  [conventional]) grid dates of close[j] / max(close within the window up to j). Close-based,
  price-only (pin-down 5): the total-return adjustment is a research-layer concern via
  `panel.total_return`. Stored in [0, 1]; 0.0 is a measured state (new high held through the
  window).
- `downside_deviation[t]` = sqrt(mean(min(r, 0)^2)) over `feature.downside_deviation.window`
  (default 252, [conventional]); target 0; 0.0 is measured (no negative return in the window).
- `size_proxy[t]` = mean over `feature.size_proxy.window` own-grid bars (default 63,
  [initial_estimate]) of ln(close * volume); dollar volume <= 0 is NaN, and the column runs
  per volume-basis segment (it reads the volume level). Stored at the row timeframe like every
  own-bars column; the level is a scale, not comparable across timeframes.

Sign ruling (lead, 2026-11-03): the spec's original `Stored <= 0` contradicted the pinned
formula - every ratio close[j]/running max is <= 1, so 1 - min is in [0, 1]. The formula
stands and the sign comment was the error; the positive magnitude matches
research/evaluate.py's max_drawdown. Spec text corrected in the additions doc.

Every window is full-window only: an output is NaN until its declared window has filled, and
a measured 0.0 is stored, never filled (`zero_is_state` on `max_drawdown` and
`downside_deviation`). The daily windows run over the symbol's own bars (the finite rows of
the daily reference grid), the `build_symbol_beta_series` convention: a date whose return is
undefined (a non-positive close on either side, todo 390's no-observation rule) appends no
return and the return windows hold the last N defined values, while the drawdown window holds
the closes themselves, so a non-positive close inside it makes that window NaN. A
history-dependent statistic appends only values computed over its own full declared window
(D1 rule 5); never a 0.0 fill.

`size_proxy` mirrors `dollar_vol_z`: it declares `volume` and is not basis-safe, so the
registry's volume guard (`registry._guard_volume`, todos 555/560) runs it per volume-basis
segment and NaNs the rows whose window spans a segment start: a loud gap, never a silent
level shift.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._primitives import _rolling_mean_series
from src.intelligence.features.kernels.macro import _grid_bars

if TYPE_CHECKING:
    from src.intelligence.features.feature_factory_config import FeatureFactoryConfig


class DistributionRecord(NamedTuple):
    """Three daily return-distribution values for one calendar date; NaN is undefined, never
    a fill. `size_proxy` is not here: it is a row-grid column, not a daily one."""

    max_daily_return: float = math.nan
    max_drawdown: float = math.nan
    downside_deviation: float = math.nan


DISTRIBUTION_COLUMNS: tuple[str, ...] = DistributionRecord._fields

_WINDOW_NAMES: tuple[str, ...] = (
    "max_daily_return",
    "max_drawdown",
    "downside_deviation",
    "size_proxy",
)


def _require_windows(config: FeatureFactoryConfig) -> tuple[int, ...]:
    """The four declared windows, each at least 2 (a statistic over one value is a level, not
    a window statistic), else ValueError."""
    windows = (
        config.max_daily_return_window,
        config.max_drawdown_window,
        config.downside_deviation_window,
        config.size_proxy_window,
    )
    for name, value in zip(_WINDOW_NAMES, windows, strict=True):
        if value < 2:
            raise ValueError(f"{name} window must be >= 2, got {value}")
    return windows


def build_distribution_series(
    symbol_1d_bars: list[dict],
    config: FeatureFactoryConfig,
) -> dict:
    """date -> DistributionRecord for one symbol, incrementally over its daily bars.

    Mirrors the `kernels.macro` builders (prev-close tracking, deques of declared windows):
    O(D) dates with an O(window) vectorized reduction per date, the `build_symbol_beta_series`
    convention. Returns are daily log returns of consecutive bars; the module docstring holds
    the undefined-return and non-positive-close rules.
    """
    max_ret_window, drawdown_window, downside_window, _size_window = _require_windows(config)

    closes: deque = deque(maxlen=drawdown_window)
    max_rets: deque = deque(maxlen=max_ret_window)
    downside_rets: deque = deque(maxlen=downside_window)

    max_daily_return = math.nan
    max_drawdown = math.nan
    downside_deviation = math.nan
    prev_close = 0.0
    result: dict = {}

    for bar in symbol_1d_bars:
        close = float(bar["close"])
        if prev_close > 1e-10 and close > 1e-10:  # todo 390: a non-positive close is no observation
            ret = math.log(close / prev_close)
            max_rets.append(ret)
            downside_rets.append(ret)
            if len(max_rets) == max_ret_window:
                max_daily_return = float(np.max(np.asarray(max_rets)))
            if len(downside_rets) == downside_window:
                downside = np.asarray(downside_rets)
                downside_deviation = float(np.sqrt(np.mean(np.minimum(downside, 0.0) ** 2)))

        closes.append(close)
        if len(closes) == drawdown_window:
            window = np.asarray(closes)
            if bool(np.all(window > 0.0)):
                max_drawdown = 1.0 - float(np.min(window / np.maximum.accumulate(window)))
            else:  # an invalid close inside the price window: no observation, never a ratio
                max_drawdown = math.nan

        result[bar["ts"].date()] = DistributionRecord(
            max_daily_return, max_drawdown, downside_deviation
        )
        prev_close = close

    return result


_DISTRIBUTION_GRID_OUTPUTS: tuple[str, ...] = tuple(
    f"_dist_{name}" for name in DISTRIBUTION_COLUMNS
)


def _compute_distribution_daily(x, config):
    ts_dt = x["ts_dt"]
    records = build_distribution_series(_grid_bars(ts_dt, x["ref_sym_close"]), config)
    out = {name: np.full(len(ts_dt), np.nan) for name in _DISTRIBUTION_GRID_OUTPUTS}
    for i, stamp in enumerate(ts_dt):
        record = records.get(stamp.date())
        if record is not None:
            for field, name in zip(DISTRIBUTION_COLUMNS, _DISTRIBUTION_GRID_OUTPUTS, strict=True):
                out[name][i] = getattr(record, field)
    return out


EXTERNAL_INPUTS = (
    *(
        ExternalInput(f"ext_{name}", np.dtype(np.float64), Alignment.DAILY_ASOF_CLOSE)
        for name in DISTRIBUTION_COLUMNS
    ),
)


def _compute_distribution_pass_through(x, config):
    return {
        name: np.asarray(x[f"ext_{name}"], dtype=np.float64).copy() for name in DISTRIBUTION_COLUMNS
    }


def _size_proxy_series(closes: np.ndarray, volumes: np.ndarray, window: int) -> np.ndarray:
    """Trailing mean of ln(close * volume): NaN until `window` own-grid bars, NaN on a bar
    whose dollar volume is <= 0 and on every window holding one (windows past the bad bar
    recover, the `_cumsum_window_moments` convention). The `dollar_vol_z` sibling's rule,
    without the z-score: the level is the feature."""
    dollar = np.asarray(closes, dtype=float) * np.asarray(volumes, dtype=float)
    positive = dollar > 0.0
    ln_dollar = np.where(positive, np.log(np.where(positive, dollar, 1.0)), np.nan)
    mean = _rolling_mean_series(ln_dollar, window)
    if len(mean):
        mean[: window - 1] = np.nan  # NaN until the window fills (D1 rule 5)
    return mean


def _compute_size_proxy(x, config):
    return {"size_proxy": _size_proxy_series(x["close"], x["volume"], config.size_proxy_window)}


KERNELS = (
    Kernel(
        name="distribution_daily",
        outputs=_DISTRIBUTION_GRID_OUTPUTS,
        inputs=("ts_dt", "ref_sym_close"),
        # The deepest trailing window of the three columns (the spec: max_daily_return = its
        # window; max_drawdown/downside_deviation = their windows).
        memory=lambda c: max(
            c.max_daily_return_window,
            c.max_drawdown_window,
            c.downside_deviation_window,
        ),
        compute=_compute_distribution_daily,
    ),
    Kernel(
        name="distribution_pass_through",
        outputs=DISTRIBUTION_COLUMNS,
        inputs=tuple(f"ext_{name}" for name in DISTRIBUTION_COLUMNS),
        # Pass-through, the macro_pass_through contract: the path dependence belongs to the
        # builder and its grid kernel; warmup is the builder's own NaN-until-full discipline.
        memory=lambda config: 0,
        compute=_compute_distribution_pass_through,
        zero_is_state=frozenset({"max_drawdown", "downside_deviation"}),
    ),
    Kernel(
        name="size_proxy",
        outputs=("size_proxy",),
        inputs=("close", "volume"),
        # The registry's volume guard runs this kernel per volume-basis segment (it reads the
        # volume level) and NaNs the rows whose window spans a segment start; the declared
        # memory is that masking reach.
        memory=lambda c: c.size_proxy_window,
        compute=_compute_size_proxy,
    ),
)
