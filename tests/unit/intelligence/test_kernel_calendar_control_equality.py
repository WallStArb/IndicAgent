"""Calendar and canary-noise kernels equal the per-row scalar calls, bit for bit, on unsorted
timestamps with duplicates and on rows whose symbol changes."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from src.intelligence.features.contract.derived_inputs import (
    DERIVED_INPUTS,
    TS_DATETIME,
    ts_ns_to_datetimes,
)
from src.intelligence.features.kernels import _primitives, control
from src.intelligence.features.kernels import calendar as cal
from src.intelligence.features.kernels._primitives import unique_datetimes
from tests.unit.intelligence import kernel_parity_reference as ref
from tests.unit.intelligence.test_feature_kernels import MANIFEST


def _ts():
    rng = np.random.default_rng(3)
    base = ref.dt_to_ns(datetime(2023, 12, 28, 14, 30, tzinfo=UTC))
    ts = base + rng.integers(0, 400, 300).astype(np.int64) * 3600 * 10**9 * 7 + 13 * 10**9
    return np.concatenate([ts, ts[:40], ts[::-1][:25]])  # duplicates, unsorted


def _config():
    return ref.build_config(MANIFEST["real_config"])


def _assert_rows_equal(got, want):
    for name, w in want.items():
        assert got[name].tobytes() == np.array(w).tobytes(), name


def _with_dt(ts, **extra):
    """Kernel inputs with the derived `ts_dt` the registry layer supplies."""
    return {"ts": ts, TS_DATETIME: DERIVED_INPUTS[TS_DATETIME][1]({"ts": ts}), **extra}


def test_derived_ts_datetime_matches_scalar_conversion_and_shares_objects():
    ts = _ts()
    dt_col = _with_dt(ts)[TS_DATETIME]
    assert list(dt_col) == ts_ns_to_datetimes(ts)
    assert len({id(d) for d in dt_col}) == len(np.unique(ts))


def test_unique_datetimes_round_trip_and_holds_no_state():
    ts = _ts()
    dt_col = _with_dt(ts)[TS_DATETIME]
    inverse, dts = unique_datetimes(dt_col)
    assert [dts[k] for k in inverse] == ts_ns_to_datetimes(ts)
    assert len(dts) == len(set(dts))
    again = unique_datetimes(dt_col[:10])
    assert [again[1][k] for k in again[0]] == ts_ns_to_datetimes(ts[:10])
    assert not [n for n in vars(_primitives) if n.startswith("_LAST")]


def test_calendar_kernels_equal_per_row_scalars():
    ts, config = _ts(), _config()
    inputs = _with_dt(ts)
    dts = ts_ns_to_datetimes(ts)
    session = cal._compute_session(inputs, config)
    _assert_rows_equal(
        session,
        {
            "in_ny_session": [cal._in_ny_session(d, config) for d in dts],
            "in_london_kz": [cal._in_london_kz(d, config) for d in dts],
            "in_overlap": [cal._in_overlap(d, config) for d in dts],
            "power_hour": [cal._power_hour(d, config) for d in dts],
            "opening_range": [cal._opening_range(d, config) for d in dts],
            "session_time_pos": [cal._session_time_pos(d, config) for d in dts],
        },
    )
    cycles = cal._compute_cycles(inputs, config)
    _assert_rows_equal(
        cycles,
        {
            "dow_sin": [cal._dow_encoding(d)[0] for d in dts],
            "dow_cos": [cal._dow_encoding(d)[1] for d in dts],
            "month_position": [cal._month_position(d) for d in dts],
            "tdom_sin": [cal._tdom_encoding(d)[0] for d in dts],
            "tdom_cos": [cal._tdom_encoding(d)[1] for d in dts],
            "quarter_cycle_cos": [cal._quarter_cycle_encoding(d)[1] for d in dts],
            "week_of_year_sin": [cal._week_of_year_sin(d) for d in dts],
            "hour_of_day_cos": [cal._hour_of_day_cos(d) for d in dts],
            "month_sin": [cal._month_sin(d) for d in dts],
        },
    )
    events = cal._compute_events(inputs, config)
    _assert_rows_equal(
        events,
        {
            "opex_flag": [cal._opex_flag(d) for d in dts],
            "quad_witching_flag": [cal._quad_witching_flag(d) for d in dts],
            "earnings_season_flag": [cal._earnings_season_flag(d, config) for d in dts],
            "days_since_quarter_end": [cal._days_since_quarter_end(d) for d in dts],
        },
    )
    assert set(session) == set(cal._SESSION_OUTPUTS)
    assert set(cycles) == set(cal._CYCLE_OUTPUTS) and set(events) == set(cal._EVENT_OUTPUTS)


def test_noise_kernel_equals_public_noise_functions():
    ts, config = _ts(), _config()
    n = len(ts)
    symbols = np.array([("SPY", "QQQ", "TLT")[i % 3] for i in range(n)], dtype=object)
    dts = ts_ns_to_datetimes(ts)
    seed = config.canary_rng_seed
    for sym_input, sym_of in (
        (symbols, lambda i: str(symbols[i])),
        (np.array(["SPY"] * n, dtype=object), lambda i: "SPY"),
        (np.array(["SPY"], dtype=object), lambda i: "SPY"),  # one symbol for the series
    ):
        got = control._compute_noise(_with_dt(ts, symbol=sym_input), config)
        _assert_rows_equal(
            got,
            {
                "canary_noise_gaussian": [
                    control._canary_noise_gaussian(dts[i], sym_of(i), seed) for i in range(n)
                ],
                "canary_noise_uniform": [
                    control._canary_noise_uniform(dts[i], sym_of(i), seed) for i in range(n)
                ],
                "canary_near_constant": [
                    control._canary_near_constant(dts[i], sym_of(i), seed) for i in range(n)
                ],
            },
        )
