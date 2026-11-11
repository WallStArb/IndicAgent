"""Massive flat-file reader: definitions as tests, then a naive reference on real sample days."""

from __future__ import annotations

import time
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import numpy as np
import pyarrow.csv as pacsv
import pytest

from src.intelligence.bars import massive_flat as mf

ROOT = Path(__file__).resolve().parents[3] / "data" / "massive" / "files"
MIN = 1_000_000_000 * 60
OPEN_2024_06_11 = int(np.datetime64("2024-06-11T13:30:00", "s").astype(int)) * 1_000_000_000
CLOSE_2024_06_11 = int(np.datetime64("2024-06-11T20:00:00", "s").astype(int)) * 1_000_000_000


def _minutes(rows, *, open_ns=OPEN_2024_06_11, close_ns=CLOSE_2024_06_11):
    """rows: (ticker, offset_minutes_from_open, o, h, l, c, volume)."""
    names = np.array(sorted({r[0] for r in rows}))
    index = {n: i for i, n in enumerate(names)}
    col = lambda i: np.array([r[i] for r in rows], dtype=float)  # noqa: E731
    return mf.aggregate_minutes_to_5m(
        names,
        np.array([index[r[0]] for r in rows], dtype=np.int32),
        np.array([open_ns + int(r[1]) * MIN for r in rows], dtype=np.int64),
        col(2),
        col(3),
        col(4),
        col(5),
        mf._volume_microshares(col(6)),
        session_open_ns=open_ns,
        session_close_ns=close_ns,
    )


class TestDefinitions:
    @pytest.mark.parametrize(
        ("volume", "expected"),
        [(0.5, 0), (1.5, 2), (2.5, 2), (3.5, 4), (0.500001, 1), (2.499999, 2), (7.0, 7)],
    )
    def test_round_half_to_even_once_per_bucket(self, volume, expected):
        micro = mf._volume_microshares(np.array([volume]))
        assert mf.round_half_even_microshares(micro).tolist() == [expected]

    def test_fractional_minutes_sum_before_rounding(self):
        # 0.4 + 0.4 + 0.4 = 1.2 -> 1; rounding each minute first would give 0
        bars = _minutes([("A", i, 1, 1, 1, 1, 0.4) for i in range(3)])
        assert bars.volume.tolist() == [1]

    def test_more_than_six_decimals_raises(self):
        with pytest.raises(ValueError, match="6 decimals"):
            mf._volume_microshares(np.array([1.0000004]))

    def test_large_fractional_volume_survives_float_representation(self):
        # 2026-03-05 style: ~1e9 shares with 6 decimals; v * 1e6 is off by float spacing, not data
        micro = mf._volume_microshares(np.array([1234567890.123456, 2.000001]))
        assert micro.tolist() == [1234567890123456, 2000001]

    def test_open_inclusive_close_exclusive(self):
        bars = _minutes(
            [
                ("A", -1, 9, 9, 9, 9, 10),  # one minute before the open: out
                ("A", 0, 1, 1, 1, 1, 10),  # the open minute: in
                ("A", 389, 2, 2, 2, 2, 10),  # last in-session minute 15:59: in
                ("A", 390, 8, 8, 8, 8, 10),  # the close minute 16:00: out
            ]
        )
        assert bars.open.tolist() == [1.0, 2.0]
        assert bars.volume.tolist() == [10, 10]

    def test_after_close_minute_stays_out_of_the_last_bucket(self):
        # close at offset 210: 205..209 is the last in-session bucket; minute 210 is out of it
        close = OPEN_2024_06_11 + 210 * MIN
        bars = _minutes(
            [("A", 205, 1, 1, 1, 1, 1), ("A", 209, 2, 2, 2, 2, 1), ("A", 210, 99, 99, 99, 99, 50)],
            close_ns=close,
        )
        assert (bars.close.tolist(), bars.high.tolist(), bars.volume.tolist()) == (
            [2.0],
            [2.0],
            [2],
        )

    def test_empty_bucket_has_no_bar_and_one_traded_minute_makes_one(self):
        bars = _minutes([("A", 0, 1, 1, 1, 1, 5), ("A", 14, 2, 3, 1, 2, 5)])
        assert (bars.t_ns - OPEN_2024_06_11).tolist() == [0, 10 * MIN]  # bucket 5..9 absent
        assert bars.volume.tolist() == [5, 5]

    def test_ohlc_first_max_min_last_in_time_order_whatever_the_row_order(self):
        rows = [
            ("A", 3, 4, 5, 4, 4.5, 1),
            ("A", 0, 1, 2, 0.5, 1.5, 1),
            ("A", 4, 4.6, 9, 4.6, 4.7, 1),
        ]
        shuffled = _minutes(rows)
        assert (shuffled.open[0], shuffled.high[0], shuffled.low[0], shuffled.close[0]) == (
            1.0,
            9.0,
            0.5,
            4.7,
        )

    def test_zero_volume_row_is_not_a_traded_minute(self):
        bars = _minutes([("A", 0, 1, 1, 1, 1, 0), ("A", 1, 2, 2, 2, 2, 3)])
        assert (bars.open.tolist(), bars.volume.tolist(), bars.n_untraded_rows) == ([2.0], [3], 1)

    def test_duplicate_minute_raises(self):
        with pytest.raises(ValueError, match="duplicate"):
            _minutes([("A", 0, 1, 1, 1, 1, 1), ("A", 0, 1, 1, 1, 1, 1)])

    def test_tickers_are_independent(self):
        bars = _minutes([("A", 0, 1, 1, 1, 1, 1), ("B", 0, 2, 2, 2, 2, 2), ("A", 1, 1, 1, 1, 1, 1)])
        assert {k: v["v"].tolist() for k, v in bars.frames().items()} == {"A": [2], "B": [2]}

    def test_frames_follow_the_ingress_contract(self):
        frame = _minutes([("A", 0, 1, 2, 0.5, 1.5, 7)]).frames()["A"]
        assert list(frame.columns) == ["t", "o", "h", "l", "c", "v"]
        assert str(frame["t"].dt.tz) == "UTC"
        assert frame["t"].iloc[0].isoformat() == "2024-06-11T13:30:00+00:00"

    def test_rows_with_no_in_session_minute_raise(self):
        with pytest.raises(ValueError, match="no in-session minute"):
            _minutes([("A", -5, 1, 1, 1, 1, 1)])

    def test_session_of_only_untraded_minutes_gives_no_bars(self):
        bars = _minutes([("A", 0, 1, 1, 1, 1, 0)])
        assert (len(bars), bars.n_untraded_rows) == (0, 1)

    def test_file_window_is_the_new_york_calendar_day(self):
        first, last = mf.extended_bounds_ns(date(2024, 6, 11))
        assert str(np.datetime64(first, "ns")) == "2024-06-11T04:00:00.000000000"
        assert str(np.datetime64(last, "ns")) == "2024-06-12T03:59:00.000000000"

    def test_mis_dated_file_raises(self, tmp_path):
        src = ROOT / "minute_aggs_v1" / "2024/06/2024-06-11.csv.gz"
        if not src.exists():
            pytest.skip("minute file not in this checkout")
        wrong = tmp_path / "2024-06-12.csv.gz"
        wrong.write_bytes(src.read_bytes())
        with pytest.raises(ValueError, match="outside the New York calendar day"):
            mf.read_minute_file(wrong)

    def test_session_bounds_regular_early_and_irregular_close(self):
        def hm(day, which):
            return np.datetime64(mf.session_bounds_ns(day)[which], "ns").astype("datetime64[m]")

        assert str(hm(date(2024, 6, 11), 0)) == "2024-06-11T13:30"
        assert str(hm(date(2024, 7, 3), 1)) == "2024-07-03T17:00"  # 13:00 ET early close
        assert str(hm(date(2005, 6, 1), 1)) == "2005-06-01T19:56"  # irregular 15:56 close
        assert str(hm(date(2024, 3, 11), 0)) == "2024-03-11T13:30"  # first session after DST
        with pytest.raises(ValueError, match="not an NYSE session"):
            mf.session_bounds_ns(date(2024, 6, 9))

    def test_file_name_date(self):
        assert mf.file_trading_date(Path("x/2024-06-11.csv.gz")) == date(2024, 6, 11)
        with pytest.raises(ValueError):
            mf.file_trading_date(Path("x/notes.txt"))


def _naive_5m(path: Path, trading_date: date, tickers: set[str]):
    """Row-by-row reference: Decimal volume, plain dict grouping, no numpy reductions."""
    open_ns, close_ns = mf.session_bounds_ns(trading_date)
    table = pacsv.read_csv(path).to_pylist()
    groups: dict[tuple[str, int], list[dict]] = {}
    for row in sorted(table, key=lambda r: (r["ticker"], r["window_start"])):
        if row["ticker"] not in tickers or not open_ns <= row["window_start"] < close_ns:
            continue
        if Decimal(str(row["volume"])) <= 0:
            continue
        key = (row["ticker"], row["window_start"] - row["window_start"] % mf.BUCKET_NS)
        groups.setdefault(key, []).append(row)
    out = {}
    for key, rows in sorted(groups.items()):
        volume = sum((Decimal(str(r["volume"])) for r in rows), Decimal(0))
        out[key] = (
            rows[0]["open"],
            max(r["high"] for r in rows),
            min(r["low"] for r in rows),
            rows[-1]["close"],
            int(volume.quantize(Decimal(1), rounding=ROUND_HALF_EVEN)),
        )
    return out


SAMPLE_DAYS = [
    ("2003/09/2003-09-10", date(2003, 9, 10)),  # first archive day
    ("2005/06/2005-06-01", date(2005, 6, 1)),  # irregular 15:56 close
    ("2024/03/2024-03-11", date(2024, 3, 11)),  # first session after DST start
    ("2024/07/2024-07-03", date(2024, 7, 3)),  # 13:00 early close
    ("2026/02/2026-02-23", date(2026, 2, 23)),  # first fractional-volume day
    ("2026/02/2026-02-25", date(2026, 2, 25)),
]


@pytest.mark.parametrize(("stem", "day"), SAMPLE_DAYS)
def test_bucketing_matches_naive_reference_on_real_days(stem, day):
    path = ROOT / "minute_aggs_v1" / f"{stem}.csv.gz"
    if not path.exists():
        pytest.skip(f"{path} not in this checkout")
    bars = mf.read_minute_file(path)
    names = bars.tickers[:: max(1, len(bars.tickers) // 150)]  # deterministic spread of tickers
    expected = _naive_5m(path, day, set(map(str, names)))
    picked = np.isin(bars.tickers[bars.ticker_index], names)
    got = {
        (str(bars.tickers[i]), int(t)): (float(o), float(h), float(low), float(c), int(v))
        for i, t, o, h, low, c, v in zip(
            bars.ticker_index[picked],
            bars.t_ns[picked],
            bars.open[picked],
            bars.high[picked],
            bars.low[picked],
            bars.close[picked],
            bars.volume[picked],
            strict=True,
        )
    }
    assert got == expected and len(got) > 0
    open_ns, close_ns = mf.session_bounds_ns(day)
    assert bars.t_ns.min() >= open_ns and bars.t_ns.max() < close_ns
    assert np.all(bars.t_ns % mf.BUCKET_NS == 0)


def test_day_file_is_served_as_is_one_row_per_ticker():
    path = ROOT / "day_aggs_v1" / "2003/09/2003-09-10.csv.gz"
    if not path.exists():
        pytest.skip("day file not in this checkout")
    bars = mf.read_day_file(path)
    raw = {r["ticker"]: r for r in pacsv.read_csv(path).to_pylist()}
    assert len(bars) == len(raw)
    i = int(np.flatnonzero(bars.tickers[bars.ticker_index] == "A")[0])
    assert (bars.open[i], bars.high[i], bars.low[i], bars.close[i], bars.volume[i]) == (
        raw["A"]["open"],
        raw["A"]["high"],
        raw["A"]["low"],
        raw["A"]["close"],
        raw["A"]["volume"],
    )


def test_whole_2024_day_throughput():
    path = ROOT / "minute_aggs_v1" / "2024/06/2024-06-11.csv.gz"
    if not path.exists():
        pytest.skip("minute file not in this checkout")
    mf.read_minute_file(path)  # warm the calendar cache and page cache
    start = time.perf_counter()
    bars = mf.read_minute_file(path)
    assert len(bars) > 100_000
    assert time.perf_counter() - start < 3.0
