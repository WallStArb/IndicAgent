"""Dividend kernels: the trailing dividend yield (todo 584 item 8).

One stored column, `dividend_yield`, computed on the daily reference grid and broadcast to
every timeframe by date (the beta cadence contract). The definition is the pinned spec's,
verbatim (docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md, item 8):

- `dividend_yield[t]` = sum of dividend_events amount over the trailing
  `feature.dividend_yield.window` (default 252, [conventional] trailing twelve months) grid
  dates divided by close[t]; one event per ex-date, Yahoo amount first with IBKR fallback (the
  view's documented naive default; 606 of 42,926 two-source events disagree beyond rounding,
  bounded except part-stock specials). Outside `dividend_event_coverage` the window is
  unknown, never zero: the builder supplies NaN for out-of-coverage dates and a window
  holding one is NaN (no_fill). 0.0 over a fully covered window is measured (zero_is_state).

`days_to_ex_dividend` is NOT in this pass: `dividend_events` and `dividend_events_reconciled`
carry ex-date, amount and prev-close only, with no declaration/announcement timestamp, so
"days to the next ex-date" cannot be computed at t without reading the future (pin-down 3).
It stays research-layer-only until the dividend layer records availability times.

The builder takes the per-date amount series as supplied input; `reconciled_amounts` applies the
coverage rule to it, and the Yahoo-first query is service-side wiring (`build_daily_records`). The supplied mapping carries the
reconciled per-date amount: the amount on an ex-date, 0.0 on a covered date with no event,
and NaN (or no entry) on a date outside `dividend_event_coverage`; a missing key is unknown,
never 0.0. The trailing window runs over the symbol's own daily bars (the finite rows of the
daily reference grid), the `build_symbol_beta_series` convention. A window is full-window
only: NaN until it fills, NaN while it holds an unknown date, and a measured 0.0 is stored
(zero_is_state). A history-dependent statistic appends only values computed over its own full
declared window (D1 rule 5); never a 0.0 fill.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels.macro import _grid_bars

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.intelligence.feature_factory import FeatureFactoryConfig


def _require_window(config: FeatureFactoryConfig) -> int:
    """The declared trailing window, at least 2 (a one-date sum is an event lookup, not a
    trailing window), else ValueError."""
    window = config.dividend_yield_window
    if window < 2:
        raise ValueError(f"dividend_yield window must be >= 2, got {window}")
    return window


def build_dividend_yield_series(
    symbol_1d_bars: list[dict],
    dividend_amounts: Mapping[date, float],
    config: FeatureFactoryConfig,
) -> dict:
    """date -> dividend_yield for one symbol over its daily bars; NaN is unknown, never 0.0.

    The trailing window sums the supplied per-date amounts over the symbol's own bar dates
    (one value per date, already reconciled to one event per ex-date by the wiring) and
    divides by that date's close. A window holding one NaN (an out-of-coverage or missing
    date) is NaN until the unknown date leaves it; a non-positive close divides nothing.
    """
    window = _require_window(config)

    amounts: deque = deque(maxlen=window)
    result: dict = {}

    for bar in symbol_1d_bars:
        d = bar["ts"].date()
        amounts.append(float(dividend_amounts.get(d, math.nan)))
        value = math.nan
        if len(amounts) == window:
            window_arr = np.asarray(amounts)
            close = float(bar["close"])
            if not bool(np.isnan(window_arr).any()) and close > 1e-10:
                value = float(np.sum(window_arr)) / close
        result[d] = value

    return result


def reconciled_amounts(
    bar_dates: Iterable[date],
    coverage: tuple[date, date] | None,
    event_amounts: Mapping[date, float],
) -> dict[date, float]:
    """The per-date amount series `build_dividend_yield_series` takes, for one symbol.

    `coverage` is the symbol's Yahoo `dividend_event_coverage` span (the source that decides
    known versus unknown, as in the research snapshot) and `event_amounts` its one amount per
    ex-date (Yahoo first, IBKR fallback, resolved in the query). A bar date inside the span is
    the event amount, or 0.0 on a covered date with no event (an ex-date with no bar goes to the
    next bar); a date outside it, or any date of
    a symbol with no coverage row, is NaN (unknown, never 0.0).
    """
    dates = sorted(bar_dates)
    if coverage is None:
        return {d: math.nan for d in dates}
    lo, hi = coverage
    amounts = {d: (0.0 if lo <= d <= hi else math.nan) for d in dates}
    for ex_date, amount in sorted(event_amounts.items()):
        if not lo <= ex_date <= hi:
            continue
        # an ex-date without a daily bar belongs to the next bar, so the dividend is counted
        position = bisect_left(dates, ex_date)
        if position < len(dates) and not math.isnan(amounts[dates[position]]):
            amounts[dates[position]] += float(amount)
    return amounts


_DIVIDEND_GRID_OUTPUTS: tuple[str, ...] = ("_dy_dividend_yield",)


def _compute_dividend_yield_daily(x, config):
    ts_dt = x["ts_dt"]
    closes = np.asarray(x["ref_sym_close"], dtype=float)
    # The amount column keeps its NaN (out-of-coverage) on the symbol's own dates; holes in
    # the symbol's close column never enter the window (the builder runs on its own bars).
    amounts_by_date = {
        ts_dt[i].date(): float(x["ref_dividend_amount"][i])
        for i in np.flatnonzero(np.isfinite(closes))
    }
    records = build_dividend_yield_series(_grid_bars(ts_dt, closes), amounts_by_date, config)
    out = {name: np.full(len(ts_dt), np.nan) for name in _DIVIDEND_GRID_OUTPUTS}
    for i, stamp in enumerate(ts_dt):
        value = records.get(stamp.date())
        if value is not None:
            for name in _DIVIDEND_GRID_OUTPUTS:
                out[name][i] = value
    return out


EXTERNAL_INPUTS = (
    ExternalInput("ext_dividend_yield", np.dtype(np.float64), Alignment.DAILY_ASOF_CLOSE),
    # The reconciled per-date dividend amount on the daily reference grid: the amount on an
    # ex-date, 0.0 on a covered date with no event, NaN outside dividend_event_coverage. The
    # wiring builds it; only this module's daily-grid kernel reads it.
    ExternalInput("ref_dividend_amount", np.dtype(np.float64), Alignment.DAILY_REFERENCE_GRID),
)


def _compute_dividend_yield_pass_through(x, config):
    return {"dividend_yield": np.asarray(x["ext_dividend_yield"], dtype=np.float64).copy()}


KERNELS = (
    Kernel(
        name="dividend_yield_daily",
        outputs=_DIVIDEND_GRID_OUTPUTS,
        inputs=("ts_dt", "ref_sym_close", "ref_dividend_amount"),
        # The spec's pinned memory: window + 1 (the amounts' trailing window plus the close).
        memory=lambda c: c.dividend_yield_window + 1,
        compute=_compute_dividend_yield_daily,
    ),
    Kernel(
        name="dividend_yield_pass_through",
        outputs=("dividend_yield",),
        inputs=("ext_dividend_yield",),
        # Pass-through, the macro_pass_through contract: warmup and the coverage NaN are the
        # builder's own discipline.
        memory=lambda config: 0,
        compute=_compute_dividend_yield_pass_through,
        zero_is_state=frozenset({"dividend_yield"}),
    ),
)
