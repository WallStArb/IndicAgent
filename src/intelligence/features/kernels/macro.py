"""Macro kernels: cross-asset and factor-beta pass-through plus the two macro products (D-25).

The daily cross-asset record (`build_cross_asset_series`) and the per-symbol beta record
(`build_symbol_beta_series`) are built by the caller from daily bars; a kernel receives them as
external inputs on the row grid. The contract that keeps them causal is in each external's
`alignment` string: the caller aligns them with `align_daily_asof`, so a row reads only records
that were available at the row's bar end.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from src.core.bar_accumulator import _RTH_CLOSE_ET
from src.core.service_utils import TF_DURATIONS
from src.intelligence.features.registry import ExternalInput, Kernel

_NEW_YORK = ZoneInfo("America/New_York")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NS_PER_S = 1_000_000_000

_ALIGNMENT = (
    "daily cross-asset record aligned by the caller with align_daily_asof: available at the "
    "16:00 ET close of its date"
)

MACRO_COLUMNS: tuple[str, ...] = (
    "vix_z",
    "flight_quality",
    "yield_slope_z",
    "tip_tlt_ret_z",
    "hyg_lqd_ret_z",
    "sb_corr_fast",
    "sb_corr_slow",
    "sb_corr_z",
    "equity_beta_z",
    "rate_beta_z",
)

# The eight columns a daily cross-asset record carries; the two betas arrive as a separate pair.
RECORD_COLUMNS: tuple[str, ...] = MACRO_COLUMNS[:8]

EXTERNAL_INPUTS = tuple(
    ExternalInput(f"ext_{name}", np.dtype(np.float64), _ALIGNMENT) for name in MACRO_COLUMNS
)


def _bar_end_offset_seconds(tf: str) -> int:
    """Seconds from a bar's `ts` to the moment its close is known.

    For 5m and up `ts` is the period start (`TF_DURATIONS`). For 1m, `ts` is documented as the
    close time in `service_utils`, so the offset is 0, which is also the conservative reading if
    it were a start. An unknown timeframe raises rather than defaulting to a duration.
    """
    if tf == "1m":
        return 0
    try:
        return TF_DURATIONS[tf]
    except KeyError:
        raise ValueError(f"unknown timeframe {tf!r}; known: 1m, {sorted(TF_DURATIONS)}") from None


def bar_ts_ns(bar_ts: datetime) -> int:
    """UTC nanoseconds of a bar start by integer arithmetic; a naive datetime is taken as UTC."""
    if bar_ts.tzinfo is None:
        bar_ts = bar_ts.replace(tzinfo=UTC)
    return (bar_ts - _EPOCH) // timedelta(microseconds=1) * 1000


def _daily_close_ns(day: date) -> int:
    """UTC nanoseconds of the 16:00 ET regular-session close on `day`."""
    close = datetime.combine(day, _RTH_CLOSE_ET, tzinfo=_NEW_YORK)
    return (close.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1) * 1000


def align_daily_asof(
    row_ts_ns: np.ndarray,
    tf: str,
    daily_dates: Sequence[date],
    values: Sequence[Any],
    default: Any,
) -> list[Any]:
    """For each row, the latest daily record available at the row's bar end, else `default`.

    A daily record dated d is available at the 16:00 ET close of d; a row (bar start
    `row_ts_ns`, timeframe `tf`) can use it when that close is at or before the row's bar end,
    `row_ts_ns` plus the bar duration. Keying a record by the row's UTC date instead reads the
    same day's close from inside the session, which is lookahead on intraday rows.

    Half-day sessions close before 16:00 ET, so this rule is conservative on those days: it only
    withholds a record that was already available, never admits one that was not.

    `daily_dates` must be sorted ascending and parallel to `values`. Pure: no I/O.
    """
    if len(daily_dates) != len(values):
        raise ValueError("daily_dates and values must have the same length")
    offset_ns = _bar_end_offset_seconds(tf) * _NS_PER_S
    available = [_daily_close_ns(d) for d in daily_dates]
    if any(later < earlier for earlier, later in zip(available, available[1:], strict=False)):
        raise ValueError("daily_dates must be sorted ascending")
    out: list[Any] = []
    for ts in row_ts_ns.tolist():
        j = bisect_right(available, ts + offset_ns) - 1
        out.append(values[j] if j >= 0 else default)
    return out


def _compute_pass_through(x, config):
    return {name: np.asarray(x[f"ext_{name}"], dtype=np.float64).copy() for name in MACRO_COLUMNS}


def _compute_products(x, config):
    return {
        "yield_slope_momentum_product": x["yield_slope_z"] * x["momentum_z_fast"],
        "vix_reversion_product": x["vix_z"] * x["momentum_reversal_z"],
    }


KERNELS = (
    Kernel(
        name="macro_pass_through",
        outputs=MACRO_COLUMNS,
        inputs=tuple(f"ext_{name}" for name in MACRO_COLUMNS),
        # Pass-through: the path dependence of the builders (flight_quality anchors to the
        # first close, the z-scores accumulate) belongs to the builder kernels 186-15 creates.
        memory=lambda config: 0,
        compute=_compute_pass_through,
    ),
    Kernel(
        name="macro_products",
        outputs=("yield_slope_momentum_product", "vix_reversion_product"),
        inputs=("yield_slope_z", "momentum_z_fast", "vix_z", "momentum_reversal_z"),
        memory=lambda config: 0,
        compute=_compute_products,
    ),
)
