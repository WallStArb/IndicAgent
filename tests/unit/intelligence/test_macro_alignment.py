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
from src.intelligence.features.cross_asset_series import (
    CROSS_ASSET_SYMBOLS,
    CrossAssetRecord,
    build_cross_asset_series,
    build_symbol_beta_series,
)
from src.intelligence.features.kernels.macro import align_daily_asof
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


def test_align_daily_asof_rule():
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
    assert align_daily_asof(rows, "5m", dates, values, "none") == ["prior", "today", "today"]
    assert align_daily_asof(rows[:1], "1h", dates, values, "none") == ["prior"]
    assert align_daily_asof(np.array([_ns(d, 19, 0)]), "1h", dates, values, "none") == ["today"]


def test_align_daily_asof_default_when_no_record_is_available():
    d = SESSIONS[TARGET_SESSION]
    default = CrossAssetRecord()
    out = align_daily_asof(
        np.array([_ns(d, 14, 0)]), "5m", [d], [CrossAssetRecord(vix_z=3.0)], default
    )
    assert out == [default]
    assert default.vix_z == 0.0


def test_align_daily_asof_1d_row_reads_own_date():
    d = SESSIONS[TARGET_SESSION]
    out = align_daily_asof(np.array([_ns(d, 0, 0)]), "1d", [d], ["own"], "none")
    assert out == ["own"]


def test_align_daily_asof_unknown_timeframe_raises():
    with pytest.raises(ValueError, match="unknown timeframe"):
        align_daily_asof(np.array([0], dtype=np.int64), "7m", [], [], None)


def test_align_daily_asof_requires_sorted_dates():
    a, b = SESSIONS[10], SESSIONS[11]
    with pytest.raises(ValueError, match="sorted"):
        align_daily_asof(np.array([0], dtype=np.int64), "5m", [b, a], [1, 2], None)
