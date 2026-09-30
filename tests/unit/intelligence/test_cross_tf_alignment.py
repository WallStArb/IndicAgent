"""Availability of higher-timeframe and lower-timeframe inputs to CTF and ret_div rows (186-15, D-25).

A lower-timeframe (LTF) row with bar start s and bar end e = s + bar duration may read a
higher-timeframe (HTF) bar only if that bar is closed by e. Higher-timeframe bars are stamped at
their period start, so a dict keyed by that start lets a row read the bar still forming around it.
Todo 243 re-keys each HTF bar to the next HTF bar's start before the join. Before 186-15 nothing
in `compute_batch` enforced that (it took any dict; this file's first version showed a start-keyed
dict passing through and a 5m row reading the unfinished 1h bar). `ctf_series_by_close` now
builds and keys in one step and `compute_batch` and `ctf_row_inputs` accept only its `CtfSeries`.

Columns under test: ctf_momentum, ctf_vwap_align, ctf_regime_align, ret_div_5m_1h,
ret_div_1h_1d and ret_div_1m_5m.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory
from src.intelligence.features.kernels.cross_tf import (
    CtfRecord,
    CtfSeries,
    _build_ltf_return_series,
    ctf_row_inputs,
    ctf_series_by_close,
)
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = ref.build_config(ref.load_manifest()["synthetic_config"])
SYMBOL = "SPY"
CTF_COLUMNS = ("ctf_momentum", "ctf_vwap_align", "ctf_regime_align")
HOUR = timedelta(hours=1)
FIVE_MIN = timedelta(minutes=5)
SESSION_OPEN_UTC = (13, 30)  # 09:30 EDT, in June
REGULAR_CLOSE_UTC = (20, 0)
HALF_DAY_CLOSE_UTC = (17, 0)
WEEKDAYS_FROM = date(2022, 6, 1)
N_SESSIONS = 14


def _by_close(htf_bars: list[dict], tf: str, htf_tf: str) -> CtfSeries:
    return ctf_series_by_close(htf_bars, CONFIG, tf, htf_tf)


def _sessions(n: int = N_SESSIONS) -> list[date]:
    days, d = [], WEEKDAYS_FROM
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _utc(d: date, hm: tuple[int, int]) -> datetime:
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=UTC)


def _ohlcv(rng: random.Random, price: float) -> tuple[dict, float]:
    price *= 1.0 + rng.gauss(0.0, 0.004)
    bar = {
        "open": price * (1.0 + rng.gauss(0.0, 0.001)),
        "high": price * 1.003,
        "low": price * 0.997,
        "close": price,
        "volume": rng.uniform(1e5, 1e6),
    }
    return bar, price


def _hour_bars(
    sessions: list[date],
    *,
    half_days: frozenset[date] = frozenset(),
    missing: frozenset[datetime] = frozenset(),
    seed: int = 3,
) -> tuple[list[dict], dict[datetime, datetime]]:
    """RTH 1h bars stamped at period start: a 30-minute bar at 13:30, then hourly bars to the
    close. Returns the bars and each bar's scheduled close (the ground truth the tests compare
    with, never read from the code under test)."""
    rng, price = random.Random(seed), 100.0
    bars, close_of = [], {}
    for d in sessions:
        end = _utc(d, HALF_DAY_CLOSE_UTC if d in half_days else REGULAR_CLOSE_UTC)
        starts = [_utc(d, SESSION_OPEN_UTC)]
        nxt = _utc(d, (14, 0))
        while nxt < end:
            starts.append(nxt)
            nxt += HOUR
        for i, start in enumerate(starts):
            bar_close = starts[i + 1] if i + 1 < len(starts) else end
            fields, price = _ohlcv(rng, price)
            if start in missing:
                continue
            bars.append({"ts": start, **fields})
            close_of[start] = bar_close
    return bars, close_of


def _five_minute_bars(
    sessions: list[date], half_days: frozenset[date] = frozenset(), seed: int = 5
):
    rng, price, bars = random.Random(seed), 100.0, []
    for d in sessions:
        end = _utc(d, HALF_DAY_CLOSE_UTC if d in half_days else REGULAR_CLOSE_UTC)
        start = _utc(d, SESSION_OPEN_UTC)
        while start < end:
            fields, price = _ohlcv(rng, price)
            bars.append({"ts": start, **fields})
            start += FIVE_MIN
    return bars


def _day_bars(sessions: list[date], seed: int = 7) -> tuple[list[dict], dict[datetime, datetime]]:
    rng, price, bars, close_of = random.Random(seed), 100.0, [], {}
    for d in sessions:
        start = datetime(d.year, d.month, d.day, tzinfo=UTC)
        fields, price = _ohlcv(rng, price)
        bars.append({"ts": start, **fields})
        close_of[start] = _utc(d, REGULAR_CLOSE_UTC)
    return bars, close_of


def _hourly_ltf(sessions: list[date], seed: int = 9) -> list[dict]:
    """1h rows on the hour grid the 1d-HTF tests use (13:30 partial, then hourly)."""
    bars, _ = _hour_bars(sessions, seed=seed)
    return bars


def _compute(bars: list[dict], tf: str, ctf, ltf_ret: dict | None = None):
    """compute_batch as `_compute_symbol_tf` calls it for the CTF and ret_div inputs."""
    ts_list = sorted(ctf.keys()) if ctf else None
    results = FeatureFactory.compute_batch(
        bars,
        SYMBOL,
        tf,
        FeatureCache(),
        CONFIG,
        warm_up_bars=0,
        ctf_by_ts=ctf or None,
        ctf_ts_list=ts_list,
        ltf_ret_by_ts=ltf_ret or None,
    )
    return {ts: fv for ts, fv in results}


def _ctf_values(fv, ret_div: str) -> tuple:
    return (*(getattr(fv, c) for c in CTF_COLUMNS), getattr(fv, ret_div))


def _perturbed(bars: list[dict], keep: callable, seed: int = 99) -> list[dict]:
    """`bars` with every bar for which keep(bar) is False replaced by seeded random OHLCV."""
    rng = random.Random(seed)
    out = []
    for bar in bars:
        if keep(bar):
            out.append(bar)
            continue
        fields, _ = _ohlcv(rng, rng.uniform(50.0, 150.0))
        out.append({"ts": bar["ts"], **fields})
    return out


def _next_start(bars: list[dict]) -> dict[datetime, datetime | None]:
    starts = [b["ts"] for b in bars]
    return {starts[i]: (starts[i + 1] if i + 1 < len(starts) else None) for i in range(len(starts))}


# ---- Test A: 5m to 1h ----------------------------------------------------------------------


def test_a_perturbing_the_open_hour_and_later_leaves_5m_rows_unchanged():
    """Replace the 1h bar in progress at a row's bar end, and every later one, with random data:
    no 5m row whose bar end is at or before that bar's close moves. Includes the 30-minute
    opening partial hour."""
    sessions = _sessions()
    hours, close_of = _hour_bars(sessions)
    rows = _five_minute_bars(sessions)
    base = _compute(rows, "5m", _by_close(hours, "5m", "1h"))
    for pivot in (hours[3], hours[7], hours[14], hours[15]):  # 15: opening partial hour
        changed = _perturbed(hours, lambda b, p=pivot["ts"]: b["ts"] < p)
        alt = _compute(rows, "5m", _by_close(changed, "5m", "1h"))
        checked = 0
        for ts, fv in base.items():
            if ts + FIVE_MIN <= close_of[pivot["ts"]]:
                assert _ctf_values(fv, "ret_div_5m_1h") == _ctf_values(alt[ts], "ret_div_5m_1h"), ts
                checked += 1
        assert checked > 0


# ---- Test B: 1h to 1d ----------------------------------------------------------------------


def test_b_perturbing_day_d_leaves_the_1h_rows_of_day_d_unchanged():
    sessions = _sessions()
    days, _ = _day_bars(sessions)
    rows = _hourly_ltf(sessions)
    base = _compute(rows, "1h", _by_close(days, "1h", "1d"))
    for k in (4, 9):
        pivot = days[k]["ts"]
        changed = _perturbed(days, lambda b, p=pivot: b["ts"] < p)
        alt = _compute(rows, "1h", _by_close(changed, "1h", "1d"))
        same_day = [ts for ts in base if ts.date() == pivot.date()]
        assert same_day
        for ts in same_day:
            assert _ctf_values(base[ts], "ret_div_1h_1d") == _ctf_values(alt[ts], "ret_div_1h_1d")


# ---- Test C: 1m to 5m ----------------------------------------------------------------------


def _minute_bars(sessions: list[date], seed: int = 11) -> list[dict]:
    """1m bars stamped at bar END (service_utils: a 1m ts is the close time)."""
    rng, price, bars = random.Random(seed), 100.0, []
    for d in sessions:
        ts = _utc(d, SESSION_OPEN_UTC) + timedelta(minutes=1)
        end = _utc(d, REGULAR_CLOSE_UTC)
        while ts <= end:
            fields, price = _ohlcv(rng, price)
            bars.append({"ts": ts, **fields})
            ts += timedelta(minutes=1)
    return bars


def test_c_1m_bars_at_or_after_a_5m_rows_end_do_not_reach_it():
    sessions = _sessions(4)
    rows = _five_minute_bars(sessions)
    minutes = _minute_bars(sessions)
    base = _compute(rows, "5m", None, _build_ltf_return_series(minutes, [b["ts"] for b in rows]))
    cut_row = rows[150]
    row_end = cut_row["ts"] + FIVE_MIN
    changed = _perturbed(minutes, lambda b: b["ts"] < row_end)
    alt = _compute(rows, "5m", None, _build_ltf_return_series(changed, [b["ts"] for b in rows]))
    earlier = [ts for ts in base if ts + FIVE_MIN <= row_end]
    assert len(earlier) > 100
    for ts in earlier:
        assert base[ts].ret_div_1m_5m == alt[ts].ret_div_1m_5m, ts


# ---- Row reads only HTF bars closed by its bar end -----------------------------------------


def _htf_bar_read_by(fv, htf_log_rets: dict[float, datetime]) -> datetime | None:
    """The HTF bar a row read, identified by its own log return (ret_lag_1 - ret_div_5m_1h)."""
    if fv.ret_div_5m_1h is None:
        return None
    got = fv.ret_lag_1 - fv.ret_div_5m_1h
    nearest = min(htf_log_rets, key=lambda value: abs(value - got))
    assert abs(nearest - got) < 1e-9, "a row read a value that belongs to no HTF bar"
    return htf_log_rets[nearest]


def _htf_returns_by_bar(hours: list[dict]) -> dict[float, datetime]:
    closes = np.array([b["close"] for b in hours])
    rets = np.concatenate(([0.0], np.diff(np.log(np.maximum(closes, 1e-10)))))
    assert len(set(rets.tolist())) == len(rets), "HTF bar returns must be distinct"
    return {float(r): hours[i]["ts"] for i, r in enumerate(rets)}


SCENARIOS = {
    "opening_partial_hour": {},
    "missing_htf_bar": {"missing": "16:00 bar of session 6"},
    "weekend_gap": {"sessions": 8},  # June 1 2022 was a Wednesday: sessions span a weekend
    "half_day": {"half_days": "session 5"},
}


def _scenario(name: str):
    sessions = _sessions()
    half_days: frozenset[date] = frozenset()
    missing: frozenset[datetime] = frozenset()
    if name == "half_day":
        half_days = frozenset({sessions[5]})
    if name == "missing_htf_bar":
        missing = frozenset({_utc(sessions[6], (16, 0))})
    hours, close_of = _hour_bars(sessions, half_days=half_days, missing=missing)
    rows = _five_minute_bars(sessions, half_days)
    return sessions, hours, close_of, rows


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_row_reads_only_htf_bars_closed_by_its_bar_end(scenario):
    _sessions_, hours, close_of, rows = _scenario(scenario)
    got = _compute(rows, "5m", _by_close(hours, "5m", "1h"))
    by_bar = _htf_returns_by_bar(hours)
    n_read = 0
    for ts, fv in got.items():
        read = _htf_bar_read_by(fv, by_bar)
        if read is None:
            continue
        n_read += 1
        assert close_of[read] <= ts + FIVE_MIN, (scenario, ts, read, close_of[read])
    assert n_read > len(got) // 2


def test_the_scenarios_cover_a_weekend_and_a_half_day():
    sessions = _sessions()
    assert any((b - a).days > 1 for a, b in zip(sessions, sessions[1:], strict=False))
    assert _sessions()[5].weekday() < 5


def test_a_plain_dict_is_refused_by_ctf_row_inputs_and_compute_batch():
    hours, _ = _hour_bars(_sessions(3))
    plain = dict(_by_close(hours, "5m", "1h"))
    assert not isinstance(plain, CtfSeries)
    with pytest.raises(TypeError, match="CtfSeries"):
        ctf_row_inputs([hours[0]["ts"]], plain, sorted(plain))
    rows = _five_minute_bars(_sessions(3))
    with pytest.raises(TypeError, match="CtfSeries"):
        FeatureFactory.compute_batch(
            rows,
            SYMBOL,
            "5m",
            FeatureCache(),
            CONFIG,
            ctf_by_ts=plain,
            ctf_ts_list=sorted(plain),
        )


def test_a_start_keyed_dict_is_the_refused_shape():
    """The dict `_build_ctf_series` returns (keyed by period start) is what the old join could
    not tell from a close-keyed one; it is a plain dict, so both entry points refuse it."""
    from src.intelligence.features.kernels.cross_tf import _build_ctf_series

    hours, _ = _hour_bars(_sessions(3))
    start_keyed = _build_ctf_series(hours, CONFIG)
    with pytest.raises(TypeError, match="CtfSeries"):
        ctf_row_inputs([hours[0]["ts"]], start_keyed, sorted(start_keyed))
    with pytest.raises(TypeError, match="CtfSeries"):
        CtfSeries(start_keyed)
    with pytest.raises(TypeError, match="CtfSeries"):
        FeatureFactory.compute_batch(
            _five_minute_bars(_sessions(3)),
            SYMBOL,
            "5m",
            FeatureCache(),
            CONFIG,
            ctf_by_ts=start_keyed,
            ctf_ts_list=sorted(start_keyed),
        )


def test_ctf_series_is_a_dict_subclass_of_close_keyed_records():
    hours, _ = _hour_bars(_sessions(3))
    series = _by_close(hours, "5m", "1h")
    assert isinstance(series, CtfSeries) and isinstance(series, dict)
    assert all(isinstance(v, CtfRecord) for v in series.values())
    assert CtfSeries.from_close_keyed(dict(series)) == series


def test_the_series_is_keyed_by_htf_close():
    hours, close_of = _hour_bars(_sessions(3))
    series = _by_close(hours, "5m", "1h")
    starts = [b["ts"] for b in hours]
    # each key is the next bar's start, which is at or after the source bar's true close
    for source, key in zip(starts[:-1], sorted(series), strict=True):
        assert key >= close_of[source]
    assert len(series) == len(hours) - 1  # the last bar has no known successor


# ---- Real data -----------------------------------------------------------------------------

REAL_ROWS = 50


def _real_case(symbol: str, tf: str):
    npz = np.load(ref.FIXTURE_DIR / "real_inputs.npz")
    prefix = f"case/{symbol}/{tf}"
    main = ref._series_bars(npz, f"{prefix}/main")
    htf = (
        ref._series_bars(npz, f"{prefix}/htf")
        if f"{prefix}/htf/ts" in npz.files
        else ref._series_bars(npz, f"d1/{symbol}")
    )
    return main, htf


@pytest.mark.parametrize(
    "symbol,tf,htf_tf", [("SPY", "5m", "1h"), ("QQQ", "15m", "1h"), ("SPY", "1h", "1d")]
)
def test_real_rows_ignore_htf_bars_not_closed_by_their_bar_end(symbol, tf, htf_tf):
    """For 50 evenly spaced rows of the stored real series, replace every HTF bar not known
    closed by the row's bar end (the next HTF bar has not started) with seeded random OHLCV and
    recompute: the row's CTF and ret_div values must not move."""
    main, htf = _real_case(symbol, tf)
    duration = {"5m": FIVE_MIN, "15m": 3 * FIVE_MIN, "1h": HOUR}[tf]
    succ = _next_start(htf)
    ret_div = "ret_div_5m_1h" if tf in ("5m", "15m") else "ret_div_1h_1d"
    base_ctf = _by_close(htf, tf, htf_tf)
    picks = np.unique(np.linspace(60, len(main) - 1, REAL_ROWS).astype(int))
    moved = 0
    for i in picks:
        window = main[i - 2 : i + 1]
        end = main[i]["ts"] + duration

        def closed(bar, end=end):
            following = succ[bar["ts"]]
            return following is not None and following <= end

        changed = _perturbed(htf, closed, seed=int(i))
        want = _compute(window, tf, base_ctf)[main[i]["ts"]]
        got = _compute(window, tf, _by_close(changed, tf, htf_tf))[main[i]["ts"]]
        if _ctf_values(want, ret_div) != _ctf_values(got, ret_div):
            moved += 1
    assert moved == 0, f"{moved} of {len(picks)} rows read an HTF bar that was not closed"
