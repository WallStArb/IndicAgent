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

import bisect
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
from src.intelligence.features.kernels.macro import bar_ts_ns
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
    results = FeatureFactory.compute_batch(
        bars,
        SYMBOL,
        tf,
        FeatureCache(),
        CONFIG,
        warm_up_bars=0,
        ctf_by_ts=ctf or None,
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
    series = _by_close(hours, "5m", "1h")
    plain = {
        ns: CtfRecord(*vals)
        for ns, *vals in zip(
            series.close_ns.tolist(), *series.asof(series.close_ns)[:4], strict=True
        )
    }
    with pytest.raises(TypeError, match="CtfSeries"):
        ctf_row_inputs(np.array([bar_ts_ns(hours[0]["ts"])]), plain)
    rows = _five_minute_bars(_sessions(3))
    with pytest.raises(TypeError, match="CtfSeries"):
        FeatureFactory.compute_batch(rows, SYMBOL, "5m", FeatureCache(), CONFIG, ctf_by_ts=plain)


def test_a_start_keyed_dict_is_the_refused_shape():
    """The dict `_build_ctf_series` returns (keyed by period start) is what the old join could
    not tell from a close-keyed one; it is a plain dict, so every entry point refuses it, and a
    CtfSeries cannot be built by calling the constructor."""
    from src.intelligence.features.kernels.cross_tf import _build_ctf_series

    hours, _ = _hour_bars(_sessions(3))
    start_keyed = _build_ctf_series(hours, CONFIG)
    with pytest.raises(TypeError, match="CtfSeries"):
        ctf_row_inputs(np.array([bar_ts_ns(hours[0]["ts"])]), start_keyed)
    with pytest.raises(TypeError, match="CtfSeries"):
        CtfSeries(*([np.zeros(1)] * 5))
    with pytest.raises(TypeError, match="CtfSeries"):
        FeatureFactory.compute_batch(
            _five_minute_bars(_sessions(3)),
            SYMBOL,
            "5m",
            FeatureCache(),
            CONFIG,
            ctf_by_ts=start_keyed,
        )


def test_ctf_series_is_an_immutable_close_keyed_object():
    hours, _ = _hour_bars(_sessions(3))
    series = _by_close(hours, "5m", "1h")
    assert isinstance(series, CtfSeries) and not isinstance(series, dict)
    assert series.close_ns.dtype == np.int64 and np.all(np.diff(series.close_ns) > 0)
    with pytest.raises(AttributeError):
        series.close_ns = series.close_ns  # type: ignore[misc]
    with pytest.raises(ValueError):
        series.close_ns[0] = 0
    with pytest.raises(ValueError, match="distinct"):
        CtfSeries.from_close_keyed(
            {
                datetime(2022, 6, 1, 14): CtfRecord(0.0, 0.0, 0.0, 0.0),
                datetime(2022, 6, 1, 14, tzinfo=UTC): CtfRecord(1.0, 1.0, 1.0, 1.0),
            }
        )


def test_the_series_is_keyed_by_htf_close():
    hours, close_of = _hour_bars(_sessions(3))
    series = _by_close(hours, "5m", "1h")
    starts = [b["ts"] for b in hours]
    # each key is the next bar's start, which is at or after the source bar's true close
    for source, key in zip(starts[:-1], series.close_ns.tolist(), strict=True):
        assert key >= bar_ts_ns(close_of[source])
    assert len(series) == len(hours) - 1  # the last bar has no known successor


def _bisect_reference(series_by_close: dict[datetime, CtfRecord], row_ts: list[datetime]) -> dict:
    """The pre-CtfSeries join, kept as the slow reference: bisect_right over sorted datetimes."""
    keys = sorted(series_by_close)
    out = {c: np.zeros(len(row_ts)) for c in CTF_COLUMNS}
    out["ext_htf_last_log_ret"] = np.full(len(row_ts), np.nan)
    for i, ts in enumerate(row_ts):
        idx = bisect.bisect_right(keys, ts) - 1
        if idx >= 0:
            value = series_by_close[keys[idx]]
            out["ctf_momentum"][i] = value.ctf_momentum
            out["ctf_vwap_align"][i] = value.ctf_vwap_align
            out["ctf_regime_align"][i] = value.ctf_regime_align
            out["ext_htf_last_log_ret"][i] = value.htf_last_log_ret
    return out


def _period_start_records(hours: list[dict], tf: str, htf_tf: str) -> dict[datetime, CtfRecord]:
    from src.intelligence.features.kernels.cross_tf import (
        _build_ctf_series,
    )

    per_start = _build_ctf_series(hours, CONFIG)
    if tf == htf_tf:
        return per_start
    keys = sorted(per_start)
    return {keys[i + 1]: per_start[keys[i]] for i in range(len(keys) - 1)}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_asof_equals_the_bisect_reference_on_the_scenarios(scenario):
    _sessions_, hours, _close_of, rows = _scenario(scenario)
    records = _period_start_records(hours, "5m", "1h")
    series = _by_close(hours, "5m", "1h")
    row_ts = [b["ts"] for b in rows]
    # also rows exactly on a close, one microsecond either side, and before the first close
    keys = sorted(records)
    row_ts += [keys[0] - timedelta(hours=3), keys[0], keys[5]]
    row_ts += [
        k + d for k in keys[:20] for d in (timedelta(microseconds=1), -timedelta(microseconds=1))
    ]
    row_ns = np.array([bar_ts_ns(t) for t in row_ts], dtype=np.int64)
    want = _bisect_reference(records, row_ts)
    got = ctf_row_inputs(row_ns, series)
    for want_name, got_name in zip(
        (*CTF_COLUMNS, "ext_htf_last_log_ret"),
        ("ext_ctf_momentum", "ext_ctf_vwap_align", "ext_ctf_regime_align", "ext_htf_last_log_ret"),
        strict=True,
    ):
        assert want[want_name].tobytes() == got[got_name].tobytes(), (scenario, want_name)


def test_asof_equals_the_bisect_reference_on_random_keys_and_naive_rows():
    rng = np.random.default_rng(4)
    base = datetime(2022, 6, 1, 13, 30, tzinfo=UTC)
    offsets = np.unique(rng.integers(0, 10**7, size=200))
    keys = [base + timedelta(seconds=int(o)) for o in offsets]
    records = {k: CtfRecord(*map(float, rng.normal(size=4))) for k in keys}
    series = CtfSeries.from_close_keyed(records)
    row_ts = [base + timedelta(seconds=int(o)) for o in rng.integers(-1000, 10**7 + 1000, size=500)]
    row_ts += keys[:50]
    want = _bisect_reference(records, row_ts)
    got = ctf_row_inputs(np.array([bar_ts_ns(t) for t in row_ts], dtype=np.int64), series)
    assert want["ctf_momentum"].tobytes() == got["ext_ctf_momentum"].tobytes()
    assert want["ext_htf_last_log_ret"].tobytes() == got["ext_htf_last_log_ret"].tobytes()
    naive = [t.replace(tzinfo=None) for t in row_ts]
    again = ctf_row_inputs(np.array([bar_ts_ns(t) for t in naive], dtype=np.int64), series)
    assert again["ext_ctf_regime_align"].tobytes() == got["ext_ctf_regime_align"].tobytes()


def test_an_empty_series_reads_zeros_and_nan():
    empty = CtfSeries.from_close_keyed({})
    out = ctf_row_inputs(np.array([1, 2, 3], dtype=np.int64), empty)
    assert not out["ext_ctf_momentum"].any() and np.isnan(out["ext_htf_last_log_ret"]).all()


@pytest.mark.parametrize("tf", ["5m", "15m"])
def test_the_backfill_shares_one_period_start_series_per_higher_tf(monkeypatch, tf):
    """5m and 15m both map to 1h: the second (symbol, tf) call reuses the cached period-start
    series instead of re-fetching and rebuilding, and gets the series the uncached call builds."""
    import services.backfill_feature_factory as bff

    hours, _ = _hour_bars(_sessions(4))
    fetched: list[str] = []

    def fake_fetch(conn, symbol, fetch_tf):
        fetched.append(fetch_tf)
        if fetch_tf == "1h":
            return hours
        return _five_minute_bars(_sessions(4)) if fetch_tf == tf else []

    seen: list = []
    monkeypatch.setattr(bff, "_fetch_bars_from_db", fake_fetch)
    monkeypatch.setattr(
        bff.FeatureFactory,
        "compute_batch",
        staticmethod(lambda *a, **kw: seen.append(kw["ctf_by_ts"]) or []),
    )

    def run(cache):
        bff._compute_symbol_tf(
            conn=None,
            symbol=SYMBOL,
            tf=tf,
            config=CONFIG,
            pipeline_version="t",
            warm_up_bars=0,
            cross_asset_by_date={},
            beta_by_date={},
            symbol_1d_bars=_day_bars(_sessions(4))[0],
            ctf_period_start_by_htf=cache,
        )

    shared: dict = {}
    run(shared)
    n_fetched = fetched.count("1h")
    run(shared)
    assert fetched.count("1h") == n_fetched  # second call read the cache
    run(None)
    cached_first, cached_second, uncached = seen
    for series in (cached_first, cached_second):
        assert series.close_ns.tobytes() == uncached.close_ns.tobytes()
        probe = uncached.close_ns
        for left, right in zip(series.asof(probe), uncached.asof(probe), strict=True):
            assert left.tobytes() == right.tobytes()
    assert cached_first.close_ns.tobytes() == _by_close(hours, tf, "1h").close_ns.tobytes()


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


def _naive(bars: list[dict]) -> list[dict]:
    return [{**b, "ts": b["ts"].replace(tzinfo=None)} for b in bars]


def test_naive_and_aware_timestamps_give_the_same_ltf_return_input():
    """The 1m return lookup uses the same UTC-nanosecond convention as the CTF and macro paths, so
    naive bars (taken as UTC) read the same values as aware bars. RED before: every
    ext_ltf_last_log_ret was NaN for naive rows against an aware-keyed series."""
    from src.intelligence.feature_factory import _cross_tf_kernel_inputs

    rows = _five_minute_bars(_sessions(3))
    minutes = _minute_bars(_sessions(3))
    series = _build_ltf_return_series(minutes, [b["ts"] for b in rows])
    assert series

    def run(bars, ltf):
        ns = np.array([bar_ts_ns(b["ts"]) for b in bars], dtype=np.int64)
        return _cross_tf_kernel_inputs(ns, "5m", FeatureCache(), None, ltf)["ext_ltf_last_log_ret"]

    aware = run(rows, series)
    assert np.isfinite(aware).any()
    naive_rows = _naive(rows)
    naive_series = _build_ltf_return_series(_naive(minutes), [b["ts"] for b in naive_rows])
    for got in (
        run(naive_rows, series),
        run(rows, naive_series),
        run(naive_rows, naive_series),
    ):
        assert got.tobytes() == aware.tobytes()
