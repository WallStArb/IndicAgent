"""As-of alignment of the daily cross-asset and beta records to intraday rows (186-12, D-25).

`build_cross_asset_series` keys the record for date d on bars through d's daily close, so an
intraday row that reads `record[row's UTC date]` sees a close that does not exist yet: a 5m bar
at 10:00 ET on d reads the 16:00 ET close of d. The record is only available from that close on.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.contract.registry import Alignment, compute_kernels, default_registry
from src.intelligence.features.kernels.macro import (
    CROSS_ASSET_SYMBOLS,
    MACRO_COLUMNS,
    CrossAssetRecord,
    bar_ts_ns,
    build_cross_asset_series,
    build_symbol_beta_series,
    daily_asof_indices,
    daily_close_availability,
)
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = ref.build_config(ref.load_manifest()["synthetic_config"])
SYMBOL = "QQQ"
N_SESSIONS = 100
INTRADAY_SESSIONS = range(70, 82)
TARGET_SESSION = 75  # an EDT date (mid-September 2022); DST ends 2022-11-06
BARS_PER_SESSION = 78


def _sessions() -> list[date]:
    days, d = [], date(2022, 6, 1)
    while len(days) < N_SESSIONS:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


SESSIONS = _sessions()


def _daily(symbol: str, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    close = np.cumprod(1.0 + rng.normal(0, 0.01, N_SESSIONS)) * 100.0
    return [
        {
            "ts": datetime(d.year, d.month, d.day, tzinfo=UTC),
            "open": float(close[i]),
            "high": float(close[i] * 1.01),
            "low": float(close[i] * 0.99),
            "close": float(close[i]),
            "volume": 1_000_000.0,
        }
        for i, d in enumerate(SESSIONS)
    ]


def _daily_bars() -> dict[str, list[dict]]:
    return {s: _daily(s, i) for i, s in enumerate((SYMBOL, *CROSS_ASSET_SYMBOLS))}


def _intraday() -> list[dict]:
    rng = np.random.default_rng(99)
    bars, price = [], 100.0
    for s in INTRADAY_SESSIONS:
        d = SESSIONS[s]
        start = datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC)  # 09:30 EDT
        for k in range(BARS_PER_SESSION):
            price *= 1.0 + rng.normal(0, 0.001)
            bars.append(
                {
                    "ts": start + timedelta(minutes=5 * k),
                    "open": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price,
                    "volume": 100_000.0 + 1000.0 * k,
                }
            )
    return bars


def _records(daily: dict[str, list[dict]], symbol: str = SYMBOL):
    cross = build_cross_asset_series(*(daily[s] for s in CROSS_ASSET_SYMBOLS), CONFIG)
    beta = build_symbol_beta_series(daily[symbol], daily["SPY"], daily["TLT"], symbol, CONFIG)
    return cross, beta


def _batch(
    daily: dict[str, list[dict]], bars: list[dict], tf: str = "5m", symbol: str = SYMBOL
) -> dict:
    cross, beta = _records(daily, symbol)
    results = FeatureFactory.compute_batch(
        bars,
        symbol,
        tf,
        FeatureCache(),
        CONFIG,
        cross_asset_by_date=cross,
        beta_by_date=beta,
    )
    return {ts: fv for ts, fv in results}


def _row_ts(session: int, hour_utc: int, minute: int) -> datetime:
    d = SESSIONS[session]
    return datetime(d.year, d.month, d.day, hour_utc, minute, tzinfo=UTC)


def test_same_day_close_does_not_reach_a_10am_row():
    """RED before the fix: changing d's SPY close changed vix_z at 10:00 ET on d."""
    bars = _intraday()
    daily = _daily_bars()
    base = _batch(daily, bars)
    changed = _daily_bars()
    changed["SPY"][TARGET_SESSION]["close"] *= 1.05
    alt = _batch(changed, bars)
    ten_am = _row_ts(TARGET_SESSION, 14, 0)  # 10:00 EDT
    assert base[ten_am].vix_z == alt[ten_am].vix_z


def test_10am_row_reads_the_prior_days_record():
    cross, _ = _records(_daily_bars())
    row = _batch(_daily_bars(), _intraday())[_row_ts(TARGET_SESSION, 14, 0)]
    prior = cross[SESSIONS[TARGET_SESSION - 1]]
    assert row.vix_z == prior.vix_z
    assert row.flight_quality == prior.flight_quality
    assert row.sb_corr_z == prior.sb_corr_z


def test_last_5m_bar_of_the_session_reads_that_days_close():
    """The 15:55 ET bar ends at 16:00 ET, when d's record becomes available."""
    cross, _ = _records(_daily_bars())
    last = _batch(_daily_bars(), _intraday())[_row_ts(TARGET_SESSION, 19, 55)]
    assert last.vix_z == cross[SESSIONS[TARGET_SESSION]].vix_z
    changed = _daily_bars()
    changed["SPY"][TARGET_SESSION]["close"] *= 1.05
    assert last.vix_z != _batch(changed, _intraday())[_row_ts(TARGET_SESSION, 19, 55)].vix_z


def test_betas_align_as_of_the_close_too():
    _, beta = _records(_daily_bars())
    bars = _intraday()
    row = _batch(_daily_bars(), bars)[_row_ts(TARGET_SESSION, 14, 0)]
    assert row.equity_beta_z == beta[SESSIONS[TARGET_SESSION - 1]][0]
    assert row.rate_beta_z == beta[SESSIONS[TARGET_SESSION - 1]][1]


def test_1d_rows_read_their_own_dates_record():
    """1d bars end after 16:00 ET, so every 1d value is what the same-date lookup gave."""
    daily = _daily_bars()
    cross, beta = _records(daily)
    rows = _batch(daily, daily[SYMBOL], tf="1d")
    for i in (40, 60, 90):
        row = rows[daily[SYMBOL][i]["ts"]]
        record = cross[SESSIONS[i]]
        assert row.vix_z == record.vix_z
        assert row.yield_slope_z == record.yield_slope_z
        assert row.equity_beta_z == beta[SESSIONS[i]][0]


@pytest.mark.parametrize(("symbol", "column"), [("SPY", "equity_beta_z"), ("TLT", "rate_beta_z")])
def test_factor_proxy_beta_stays_none(symbol, column):
    row = _batch(_daily_bars(), _intraday(), symbol=symbol)[_row_ts(TARGET_SESSION, 14, 0)]
    assert getattr(row, column) is None


def _ns(day: date, hour: int, minute: int = 0) -> int:
    return ref.dt_to_ns(datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC))


def _align(rows, tf, dates, values, default) -> list:
    """The daily record each row reads: the batch rule (`daily_asof_indices`) applied to values."""
    index = daily_asof_indices(rows, tf, daily_close_availability(dates))
    return [values[j] if j >= 0 else default for j in index.tolist()]


def test_daily_asof_rule():
    d = SESSIONS[TARGET_SESSION]
    dates = [SESSIONS[TARGET_SESSION - 1], d]
    values = ["prior", "today"]
    rows = np.array(
        [
            _ns(d, 14, 0),  # 10:00 EDT: today's close not yet known
            _ns(d, 19, 55),  # 15:55 EDT: bar ends at 16:00 EDT exactly
            _ns(d, 21, 0),  # 17:00 EDT: after the close, still today (never tomorrow)
        ],
        dtype=np.int64,
    )
    assert _align(rows, "5m", dates, values, "none") == ["prior", "today", "today"]
    assert _align(rows[:1], "1h", dates, values, "none") == ["prior"]
    assert _align(np.array([_ns(d, 19, 0)]), "1h", dates, values, "none") == ["today"]


def test_daily_asof_default_when_no_record_is_available():
    d = SESSIONS[TARGET_SESSION]
    default = CrossAssetRecord()
    out = _align(np.array([_ns(d, 14, 0)]), "5m", [d], [CrossAssetRecord(vix_z=3.0)], default)
    assert out == [default]
    assert default.vix_z == 0.0


def test_daily_asof_1d_row_reads_own_date():
    d = SESSIONS[TARGET_SESSION]
    out = _align(np.array([_ns(d, 0, 0)]), "1d", [d], ["own"], "none")
    assert out == ["own"]


def test_daily_asof_unknown_timeframe_raises():
    with pytest.raises(ValueError, match="unknown timeframe"):
        daily_asof_indices(np.array([0], dtype=np.int64), "7m", [])


def test_daily_asof_requires_sorted_dates():
    a, b = SESSIONS[10], SESSIONS[11]
    with pytest.raises(ValueError, match="sorted"):
        daily_close_availability([b, a])


# ---------------------------------------------------------------------------
# Raw-input truncation and the no-fill default (186 review F9)
# ---------------------------------------------------------------------------


def _macro_outputs(daily: dict[str, list[dict]], bars: list[dict]) -> dict[str, np.ndarray]:
    """Macro kernel outputs on the intraday row grid, from raw daily bars and raw bars."""
    from src.intelligence.feature_factory import _macro_kernel_inputs
    from src.intelligence.features.contract.registry import compute_kernels, default_registry
    from src.intelligence.features.kernels.macro import MACRO_COLUMNS

    cross, beta = _records(daily)
    ts = np.array([ref.dt_to_ns(b["ts"]) for b in bars], dtype=np.int64)
    inputs = {
        "ts": ts,
        **_macro_kernel_inputs(ts, SYMBOL, "5m", FeatureCache(), cross, beta),
    }
    return compute_kernels(default_registry(), inputs, CONFIG, outputs=list(MACRO_COLUMNS))


def _constant_per_series_outputs(bars: list[dict]) -> dict[str, np.ndarray]:
    """The symbol and tf externals as the batch path builds them: one value on every row."""
    from src.intelligence.feature_factory import _batch_kernel_inputs

    z = np.zeros(len(bars))
    ts = np.array([ref.dt_to_ns(b["ts"]) for b in bars], dtype=np.int64)
    built = _batch_kernel_inputs(ts, z, z, z, z, z, SYMBOL, "5m")
    return {"symbol": built["symbol"], "tf": built["tf"]}


def _daily_asof_close_outputs(bars: list[dict], daily: dict[str, list[dict]]):
    return _macro_outputs(daily, bars)


def _truncate_daily_asof_close(daily, bars, cut_row):
    from src.intelligence.features.kernels.macro import _daily_close_ns

    t_end_ns = ref.dt_to_ns(bars[cut_row]["ts"]) + 300 * 1_000_000_000
    return {
        s: [b for b in series if _daily_close_ns(b["ts"].date()) <= t_end_ns]
        for s, series in daily.items()
    }


def _daily_grid_outputs(daily: dict[str, list[dict]], symbol: str = SYMBOL) -> dict:
    """The daily-grid kernels' outputs on the reference grid built from raw daily bars."""
    from src.intelligence.features.kernels.macro import (
        _BETA_OUTPUTS,
        _XA_OUTPUTS,
        daily_reference_grid,
    )

    series = {f"ref_{s.lower()}_close": daily[s] for s in CROSS_ASSET_SYMBOLS}
    series["ref_sym_close"] = daily[symbol]
    grid = daily_reference_grid(series)
    n = len(grid["ts"])
    inputs = {**grid, "symbol": np.array([symbol] * n, dtype=object)}
    return compute_kernels(
        default_registry(), inputs, CONFIG, outputs=[*_XA_OUTPUTS, *_BETA_OUTPUTS]
    )


def _cross_tf_raw() -> tuple[list[dict], list[dict]]:
    """Raw 1h bars (period start) and 1m bars (stamped at bar end) over the intraday sessions."""
    from tests.unit.intelligence.test_cross_tf_alignment import _hour_bars, _minute_bars

    sessions = [SESSIONS[s] for s in INTRADAY_SESSIONS]
    hours, _ = _hour_bars(
        [SESSIONS[s] for s in range(INTRADAY_SESSIONS.start - 4, INTRADAY_SESSIONS.stop)]
    )
    return hours, _minute_bars(sessions)


def _htf_asof_close_outputs(bars: list[dict], hours: list[dict]) -> dict:
    """The four HTF externals as the batch path builds them from raw 1h bars."""
    from src.intelligence.features.kernels.cross_tf import ctf_row_inputs, ctf_series_by_close

    series = ctf_series_by_close(hours, CONFIG, "5m", "1h")
    return ctf_row_inputs(np.array([bar_ts_ns(b["ts"]) for b in bars], dtype=np.int64), series)


def _ltf_asof_bar_start_outputs(bars: list[dict], minutes: list[dict]) -> dict:
    from src.intelligence.features.kernels.cross_tf import _build_ltf_return_series

    series = _build_ltf_return_series(minutes, [b["ts"] for b in bars])
    return {"ext_ltf_last_log_ret": np.array([series.get(b["ts"], np.nan) for b in bars])}


def _external_outputs(alignment, bars, daily):
    """(outputs on the row grid, the columns that carry every external of `alignment`)."""
    from src.intelligence.features.contract.registry import default_registry

    declared = [e.name for e in default_registry().external_inputs if e.alignment is alignment]
    if alignment is Alignment.DAILY_ASOF_CLOSE:
        out = _daily_asof_close_outputs(bars, daily)
        # macro_pass_through emits each ext_<column> as <column>
        assert {f"ext_{c}" for c in out if c in MACRO_COLUMNS} == set(declared)
        return out
    if alignment is Alignment.CONSTANT_PER_SERIES:
        return _constant_per_series_outputs(bars)
    if alignment is Alignment.DAILY_REFERENCE_GRID:
        from src.intelligence.features.kernels.macro import _CLOSE_EXTERNALS

        assert set(declared) == {*_CLOSE_EXTERNALS, "ref_sym_close"}
        return _daily_grid_outputs(daily)
    if alignment in (Alignment.HTF_ASOF_CLOSE, Alignment.LTF_ASOF_BAR_START):
        hours, minutes = _cross_tf_raw()
        if alignment is Alignment.HTF_ASOF_CLOSE:
            out = _htf_asof_close_outputs(bars, hours)
        else:
            out = _ltf_asof_bar_start_outputs(bars, minutes)
        assert set(out) == set(declared)
        return out
    raise AssertionError(f"no truncation runner for alignment {alignment}")


@pytest.mark.parametrize("alignment", list(Alignment), ids=lambda a: a.name)
@pytest.mark.parametrize("cut_row", [3, BARS_PER_SESSION * 5 + 30, BARS_PER_SESSION * 6 + 77])
def test_every_alignment_has_causal_rows_up_to_t(alignment, cut_row):
    """For every external declared with `alignment`: truncate the raw bars at row t and the raw
    daily records to those known by the end of row t's bar, run the real `_macro_kernel_inputs`
    and kernels; rows <= t must not move. A new Alignment member without a runner fails here."""
    bars, daily = _intraday(), _daily_bars()
    full = _external_outputs(alignment, bars, daily)
    if alignment is Alignment.DAILY_REFERENCE_GRID:
        # rows are dates: keep the daily bars dated on or before the cut row's date
        last = bars[cut_row]["ts"].date()
        known_daily = {s: [b for b in v if b["ts"].date() <= last] for s, v in daily.items()}
        cut = _external_outputs(alignment, bars, known_daily)
        assert set(cut) == set(full)
        for name, values in cut.items():
            np.testing.assert_array_equal(values, full[name][: len(values)], err_msg=name)
        return
    if alignment in (Alignment.HTF_ASOF_CLOSE, Alignment.LTF_ASOF_BAR_START):
        # raw inputs known by the cut row: HTF bars started by its bar end (the in-progress bar
        # is then the last and has no known close), 1m bars stamped by its bar start
        cut_bars = bars[: cut_row + 1]
        row_end = bars[cut_row]["ts"] + timedelta(minutes=5)
        hours, minutes = _cross_tf_raw()
        if alignment is Alignment.HTF_ASOF_CLOSE:
            cut = _htf_asof_close_outputs(cut_bars, [b for b in hours if b["ts"] <= row_end])
        else:
            cut = _ltf_asof_bar_start_outputs(
                cut_bars, [b for b in minutes if b["ts"] <= bars[cut_row]["ts"]]
            )
        for name, values in cut.items():
            np.testing.assert_array_equal(values, full[name][: cut_row + 1], err_msg=name)
        return
    known = (
        _truncate_daily_asof_close(daily, bars, cut_row)
        if alignment is Alignment.DAILY_ASOF_CLOSE
        else daily
    )
    cut = _external_outputs(alignment, bars[: cut_row + 1], known)
    assert set(cut) == set(full)
    for name, values in cut.items():
        np.testing.assert_array_equal(values, full[name][: cut_row + 1], err_msg=name)


def test_the_factory_refuses_an_external_whose_alignment_it_cannot_build(monkeypatch):
    from src.intelligence import feature_factory

    monkeypatch.setattr(
        feature_factory, "_BUILT_ALIGNMENTS", frozenset({Alignment.CONSTANT_PER_SERIES})
    )
    ts = np.array([0], dtype=np.int64)
    with pytest.raises(ValueError, match="no builder"):
        feature_factory._macro_kernel_inputs(ts, SYMBOL, "5m", FeatureCache(), None, None)


def test_rows_before_the_first_daily_record_are_nan_not_zero():
    """No record available is missing data: NaN, never a fabricated 0.0 z-score."""
    bars, daily = _intraday(), _daily_bars()
    late = {s: series[TARGET_SESSION:] for s, series in daily.items()}
    out = _macro_outputs(late, bars)
    first_session_rows = BARS_PER_SESSION * (TARGET_SESSION - INTRADAY_SESSIONS.start)
    before = slice(0, first_session_rows)  # sessions 70-74: no record yet on 5m rows
    for name in ("vix_z", "flight_quality", "yield_slope_z", "sb_corr_z"):
        assert np.isnan(out[name][before]).all(), name
