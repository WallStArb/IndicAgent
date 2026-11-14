"""External kernel inputs on the row grid: the bar arrays with the per-series constants, the
daily macro records, the item-8 daily-family records and the cross-timeframe values, each
aligned to the rows as of the row's bar end.

Pure functions over arrays, shared by the rebuild writer and the streaming `FeatureFactory`. The
rebuild code key hashes this module, since a builder edit changes stored values; keep
streaming-path code out of it.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from src.intelligence.features.contract.registry import Alignment, default_registry
from src.intelligence.features.kernels._cache_state import FeatureCache
from src.intelligence.features.kernels.cross_tf import CtfSeries, ctf_row_inputs
from src.intelligence.features.kernels.distribution import DISTRIBUTION_COLUMNS
from src.intelligence.features.kernels.macro import (
    RECORD_COLUMNS,
    CrossAssetRecord,
    daily_asof_indices,
    daily_close_availability,
)
from src.intelligence.features.kernels.residual import RESIDUAL_COLUMNS


def batch_kernel_inputs(
    row_ns: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    symbol: str,
    tf: str,
    volume_basis: np.ndarray,
) -> dict[str, np.ndarray]:
    """Bar arrays plus the per-row `symbol` and `tf` external inputs for compute_kernels."""
    return {
        "ts": row_ns,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "volume_basis": volume_basis,
        "symbol": np.array([symbol] * len(row_ns), dtype=object),
        "tf": np.array([tf] * len(row_ns), dtype=object),
    }


# The external-input alignments this module builds: CONSTANT_PER_SERIES by
# `batch_kernel_inputs` (the symbol), DAILY_ASOF_CLOSE by `macro_kernel_inputs`,
# DAILY_REFERENCE_GRID by `kernels.macro.daily_reference_grid` (the daily-grid kernels run on it),
# HTF_ASOF_CLOSE by `cross_tf_kernel_inputs`. A kernel module
# declaring an external with any other Alignment is refused rather than fed an unaligned value.
_BUILT_ALIGNMENTS = frozenset(
    {
        Alignment.CONSTANT_PER_SERIES,
        Alignment.DAILY_ASOF_CLOSE,
        Alignment.DAILY_REFERENCE_GRID,
        Alignment.HTF_ASOF_CLOSE,
    }
)


def _require_buildable_externals() -> None:
    for external in default_registry().external_inputs:
        if external.alignment not in _BUILT_ALIGNMENTS:
            raise ValueError(
                f"external input {external.name!r} has alignment {external.alignment.name}, "
                "and external_inputs has no builder for it"
            )


# A row with no daily record available yet is missing data (no_fill): all-NaN, so the kernels
# emit NaN instead of a fabricated 0.0 z-score.
_MISSING_CROSS_ASSET = CrossAssetRecord(*([float("nan")] * len(CrossAssetRecord._fields)))


def macro_kernel_inputs(
    row_ns: np.ndarray,
    symbol: str,
    tf: str,
    cache: FeatureCache,
    cross_asset_by_date: dict | None,
    beta_by_date: dict | None,
) -> dict[str, np.ndarray]:
    """The ten `ext_*` macro inputs on the row grid (None becomes NaN).

    Batch path: the daily records are aligned as-of the row's bar end with `daily_asof_indices`
    (a record dated d is available from the 16:00 ET close of d, so an intraday row on d reads
    d - 1; 1d rows read their own date). A row with no available record reads the default:
    NaN for the cross-asset fields, None (NaN) for the betas. Live path (cross_asset_by_date and
    beta_by_date None): the cache's values broadcast, with equity_beta_z None for SPY and
    rate_beta_z None for TLT (a self-regression is degenerate); the cache holds only
    already-closed daily values.
    """
    _require_buildable_externals()
    n = len(row_ns)
    out: dict[str, np.ndarray] = {}
    if cross_asset_by_date is not None:
        dates = sorted(cross_asset_by_date)
        index = daily_asof_indices(row_ns, tf, daily_close_availability(dates))
        records = [cross_asset_by_date[d] for d in dates]
        for name in RECORD_COLUMNS:
            # The default closes each column, so index -1 (no record available) reads it.
            column = [getattr(r, name) for r in records] + [getattr(_MISSING_CROSS_ASSET, name)]
            out[f"ext_{name}"] = np.array(column, dtype=np.float64)[index]
    else:
        for name in RECORD_COLUMNS:
            out[f"ext_{name}"] = np.full(n, getattr(cache, name), dtype=np.float64)
    if beta_by_date is not None:
        dates = sorted(beta_by_date)
        index = daily_asof_indices(row_ns, tf, daily_close_availability(dates))
        pairs = [beta_by_date[d] for d in dates] + [(None, None)]
        for position, name in enumerate(("ext_equity_beta_z", "ext_rate_beta_z")):
            column = [np.nan if p[position] is None else p[position] for p in pairs]
            out[name] = np.array(column, dtype=np.float64)[index]
    else:
        equity = None if symbol == "SPY" else cache.equity_beta_z
        rate = None if symbol == "TLT" else cache.rate_beta_z
        out["ext_equity_beta_z"] = np.full(n, np.nan if equity is None else equity)
        out["ext_rate_beta_z"] = np.full(n, np.nan if rate is None else rate)
    return out


class DailySeriesRecord(NamedTuple):
    """One symbol's daily-grain add-list records (todo 584 item 8), each keyed by date: the
    market-residual family, the return-distribution family and the dividend yield. A family left
    None (or empty) reads NaN on every row."""

    residual: dict | None = None
    distribution: dict | None = None
    dividend_yield: dict | None = None


def daily_records_kernel_inputs(
    row_ns: np.ndarray, tf: str, records: DailySeriesRecord | None
) -> dict[str, np.ndarray]:
    """The `ext_*` inputs of the item-8 daily families on the row grid, aligned as-of the row's
    bar end like the betas (a record dated d is available from d's 16:00 ET close). A row with no
    available record, or a family with no records, reads NaN: undefined, never a fill."""
    records = records or DailySeriesRecord()
    families = (
        (records.residual, RESIDUAL_COLUMNS, getattr),
        (records.distribution, DISTRIBUTION_COLUMNS, getattr),
        (records.dividend_yield, ("dividend_yield",), lambda value, name: value),
    )
    out: dict[str, np.ndarray] = {}
    for family, names, read in families:
        by_date = family or {}
        dates = sorted(by_date)
        index = daily_asof_indices(row_ns, tf, daily_close_availability(dates))
        for name in names:
            column = [read(by_date[d], name) for d in dates] + [np.nan]
            out[f"ext_{name}"] = np.array(column, dtype=np.float64)[index]
    return out


def cross_tf_kernel_inputs(
    row_ns: np.ndarray,
    tf: str,
    cache: FeatureCache,
    ctf_by_ts: CtfSeries | None,
) -> dict[str, np.ndarray]:
    """The four cross-timeframe `ext_*` inputs on the row grid.

    Batch path (`ctf_by_ts` given): `ctf_row_inputs` looks each row up among the HTF values
    keyed by their bar's close. Live path: the cache's CTF values broadcast and the
    HTF return is NaN (the divergences have no live-path plumbing).
    """
    n = len(row_ns)
    if ctf_by_ts is not None:
        out = ctf_row_inputs(row_ns, ctf_by_ts)
    else:
        out = {
            "ext_ctf_momentum": np.full(n, cache.ctf_momentum, dtype=np.float64),
            "ext_ctf_vwap_align": np.full(n, cache.ctf_vwap_align, dtype=np.float64),
            "ext_ctf_regime_align": np.full(n, cache.ctf_regime_align, dtype=np.float64),
            "ext_htf_last_log_ret": np.full(n, np.nan),
        }
    return out
