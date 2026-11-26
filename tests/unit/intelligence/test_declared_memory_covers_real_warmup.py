"""No registered feature column declares less memory than its real warmup (G2, todo 584).

The corpus screen G2 judges the first stored row of a column against its declared memory
(`stored_first_row`). A column whose kernel needs more valid observations than its declared window
holds fails it on a sparse name: amihud_illiq_z declares window + 1 bars but needs
ceil(min_valid_fraction x window) bars that carry a return, so MLSS (85 of its first 357 sessions
at zero return) reached its first finite row at 357, not 253 (pilot eca9e854, 2026-11-26).

This runs every 1d feature column through the rebuild's own kernel call on two deterministic
synthetic series, a dense one and one with 25 percent zero-return sessions (closes repeating), each
with 400 bars of macro history before the series start, and asserts the first finite row is within
the G2 tolerance of the declared first stored row. A column that cannot reach a value on a sparse
name belongs to the object-dependent class (NaN is its declared state, with a none mask), not to a
larger memory. The tolerance is the pilot gate's `threshold.pilot_gate.warmup_gap_bars` (5).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from functools import cache

import numpy as np
import pytest

from services.backfill_feature_factory import _series_kernel_inputs, stored_first_row
from src.intelligence.features.contract.registry import compute_kernels, default_registry
from src.intelligence.features.feature_vector_persistence import (
    feature_vectors_numeric_columns,
    feature_vectors_output_columns,
)
from src.intelligence.features.kernels._hmm import HmmConfig
from src.intelligence.features.kernels._primitives import none_mask_name
from src.intelligence.features.kernels.macro import (
    build_cross_asset_series,
    build_symbol_beta_series,
)
from tests.unit.intelligence import kernel_parity_reference as ref
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR

N_BARS = 1500
MACRO_HEAD = 400  # macro history before the series start, so the macro warmup is not the series'
WARMUP_GAP_BARS = 5  # threshold.pilot_gate.warmup_gap_bars
SPARSE_ZERO_RETURN_SHARE = 0.25
FIXTURES = {"dense": 0.0, "sparse": SPARSE_ZERO_RETURN_SHARE}

# The regime columns run the HMM walk-forward under their own gates (todo 583, E20).
_REGIME = frozenset({"regime", "regime_volatility"})

# Columns with no finite value on a 1d series of plain bars; listed so a column that stops
# producing values cannot leave the check unnoticed (the equality test below). Intraday calendar
# and session columns, the daily-record families (their reach is pinned in
# test_feature_memory_reach.py), and three columns that are all NaN on the 1d synthetic series.
UNMEASURED_ON_THE_1D_FIXTURE = frozenset(
    {
        "dividend_yield",
        "downside_deviation",
        "hma_slope_z",
        "hour_of_day_cos",
        "hour_of_day_sin",
        "idiosyncratic_volatility",
        "in_ny_session",
        "in_overlap",
        "market_residual_lag1_acf",
        "market_residual_return",
        "market_residual_z",
        "max_daily_return",
        "max_drawdown",
        "minute_of_hour_cos",
        "minute_of_hour_sin",
        "opening_range",
        "poc_rolling_dist_atr",
        "poc_session_rolling_divergence_atr",
        "power_hour",
        "residual_beta_stability",
        "ret_div_1h_1d",
        "ret_div_5m_1h",
        "session_time_pos",
    }
)


def _is_regime_column(column: str) -> bool:
    return column.startswith("hmm_") or column in _REGIME


def _bars(seed: int, n: int, zero_return_share: float) -> list[dict]:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.01, n)
    returns[rng.random(n) < zero_return_share] = 0.0
    close = 100.0 * np.exp(np.cumsum(returns))
    previous = np.concatenate([[100.0], close[:-1]])
    open_ = np.where(returns == 0.0, previous, previous * (1 + rng.normal(0, 0.002, n)))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    volume = rng.lognormal(13, 0.4, n).round()
    sessions: list[datetime] = []
    day = datetime(2016, 1, 4, 21, 0, tzinfo=UTC)
    while len(sessions) < n:
        if day.weekday() < 5:
            sessions.append(day)
        day += timedelta(days=1)
    return [
        {
            "ts": sessions[i],
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": float(volume[i]),
        }
        for i in range(n)
    ]


@cache
def _first_finite_rows(fixture: str) -> dict[str, int | None]:
    """Per column, the first row with a finite value after the kernel's none mask, computed as
    the rebuild computes it (one `compute_kernels` call, no warmup mask)."""
    manifest = ref.load_manifest()
    config = ref.build_config(manifest["real_config"])
    config = dataclasses.replace(config, hmm=HmmConfig.from_values(SMALL_HMM_APR.get))
    total = N_BARS + MACRO_HEAD
    macro = {symbol: _bars(10 + i, total, 0.0) for i, symbol in enumerate(ref.CROSS_ASSET_SYMBOLS)}
    series = _bars(99, total, FIXTURES[fixture])[MACRO_HEAD:]
    cross_asset = build_cross_asset_series(*(macro[s] for s in ref.CROSS_ASSET_SYMBOLS), config)
    beta = build_symbol_beta_series(series, macro["SPY"], macro["TLT"], "ZZZ", config)
    arrays = {
        "ts": np.array([int(bar["ts"].timestamp()) * 10**9 for bar in series], dtype=np.int64),
        **{
            f: np.array([bar[f] for bar in series])
            for f in ("open", "high", "low", "close", "volume")
        },
        "volume_basis": ref.constant_volume_basis(N_BARS),
    }
    inputs = _series_kernel_inputs("ZZZ", "1d", arrays, config, cross_asset, beta, series)
    registry = default_registry()
    outputs = [c for c in feature_vectors_output_columns() if not _is_regime_column(c)]
    computed = compute_kernels(registry, inputs, config, outputs=outputs)
    first: dict[str, int | None] = {}
    for column in feature_vectors_numeric_columns():
        if _is_regime_column(column) or column not in computed:
            continue
        values = np.array(computed[column], dtype=float)
        mask = computed.get(none_mask_name(column))
        if mask is not None:
            values[np.asarray(mask) > 0.5] = np.nan
        finite = np.isfinite(values)
        first[column] = int(np.argmax(finite)) if finite.any() else None
    return first


def _declared_first_row(column: str) -> int:
    """The first row the screen expects a value: the declared memory, never earlier than the
    first stored row (the rebuild stores rows from bar `momentum_zscore_window`)."""
    config = ref.build_config(ref.load_manifest()["real_config"])
    declared = stored_first_row(default_registry(), column, config, "1d")
    return max(declared, config.momentum_zscore_window)


def _checked_columns() -> list[str]:
    registry = default_registry()
    objects = set(registry.object_dependent_outputs())
    return sorted(
        c
        for c in feature_vectors_numeric_columns()
        if not _is_regime_column(c) and c not in objects and c not in UNMEASURED_ON_THE_1D_FIXTURE
    )


@pytest.mark.parametrize("fixture", sorted(FIXTURES))
@pytest.mark.parametrize("column", _checked_columns())
def test_a_column_reaches_its_first_value_within_its_declared_memory(
    column: str, fixture: str
) -> None:
    measured = _first_finite_rows(fixture)[column]
    declared = _declared_first_row(column)
    dense = _first_finite_rows("dense")[column]
    assert measured is not None or dense is None, (
        f"{column} has a value on the dense fixture (row {dense}) but never on the {fixture} one: "
        "declare it object_dependent with a none mask"
    )
    if measured is None:
        return
    assert measured <= declared + WARMUP_GAP_BARS, (
        f"{column}: declared memory puts its first value at row {declared}, its first finite row "
        f"on the {fixture} fixture is {measured} ({measured - declared} later, tolerance "
        f"{WARMUP_GAP_BARS}): declare it object_dependent with a none mask, or raise its memory"
    )


def test_every_column_that_never_has_a_value_here_is_listed() -> None:
    """A column that produces nothing on the dense 1d fixture is exempt only by name or by the
    object-dependent declaration; any other silent column fails here."""
    registry = default_registry()
    objects = set(registry.object_dependent_outputs())
    silent = {c for c, row in _first_finite_rows("dense").items() if row is None} - objects
    assert silent == UNMEASURED_ON_THE_1D_FIXTURE
