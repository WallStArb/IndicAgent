"""Massive load checks, systemic half: pure math on synthetic fixtures (design 8a, stages A and B)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.bars import massive_load_checks as lc

MIN = 60 * 1_000_000_000


def _sanity(o, h, low, c, v, code=None, ws=None):
    n = len(o)
    code = np.zeros(n, dtype=np.int64) if code is None else np.asarray(code)
    ws = np.arange(n, dtype=np.int64) if ws is None else np.asarray(ws)
    return lc.record_sanity(code, ws, *(np.asarray(a, dtype=float) for a in (o, h, low, c, v)))[0]


def test_sanity_clean_file_is_ok() -> None:
    counts = _sanity([10, 11], [12, 12], [9, 10], [11, 11.5], [100, 0])
    assert counts.n_rows == 2 and lc.sanity_verdict(counts) == "ok"


def test_sanity_counts_each_violation() -> None:
    counts = _sanity(
        [10, 10, -1, 10, 10],
        [9, 12, 5, 12, 12],  # row 0: high below open
        [9, 9, 4, 9, 9],
        [10, 11, 4.5, 11, 11],
        [1, 1, 1, -5, 1],
        code=[0, 0, 0, 0, 0],
        ws=[0, 1, 2, 3, 3],  # row 4 duplicates the key of row 3
    )
    assert counts.n_ohlc_inconsistent >= 1
    assert counts.n_nonpositive_price == 1
    assert counts.n_negative_volume == 1
    assert counts.n_duplicate_keys == 1
    assert lc.sanity_verdict(counts) == "stop"


def test_sanity_inconsistency_share_threshold() -> None:
    n = 2000
    o = np.full(n, 10.0)
    h = np.full(n, 11.0)
    low = np.full(n, 9.0)
    h[:2] = 9.5  # 2 of 2000 bars: 99.9 percent consistent holds exactly
    ok = _sanity(o, h, low, o, np.ones(n))
    assert lc.sanity_verdict(ok) == "ok"
    h[:3] = 9.5  # 3 of 2000: below 99.9 percent
    assert lc.sanity_verdict(_sanity(o, h, low, o, np.ones(n))) == "stop"


def test_sanity_nan_price_is_not_positive() -> None:
    counts = _sanity([np.nan], [np.nan], [np.nan], [np.nan], [1])
    assert counts.n_nonpositive_price == 1


def test_sanity_vacuous_inputs_raise() -> None:
    with pytest.raises(lc.VacuousCheckError):
        _sanity([], [], [], [], [])
    with pytest.raises(lc.VacuousCheckError):
        lc.sanity_verdict(lc.SanityCounts(0, 0, 0, 0, 0))


def test_dst_transitions_and_post_dst_sessions() -> None:
    assert lc.dst_transition_sessions(date(2024, 1, 1), date(2024, 12, 31)) == [
        date(2024, 3, 10),
        date(2024, 11, 3),
    ]
    sessions = [
        date(2024, 3, 8),
        date(2024, 3, 11),
        date(2024, 3, 12),
        date(2024, 11, 1),
        date(2024, 11, 4),
    ]
    assert lc.post_dst_sessions(sessions) == [date(2024, 3, 11), date(2024, 11, 4)]


def test_early_close_detection_uses_session_length() -> None:
    open_ = datetime(2024, 11, 29, 14, 30, tzinfo=UTC)
    bounds = {
        date(2024, 11, 28): (open_, open_ + timedelta(hours=6, minutes=30)),
        date(2024, 11, 29): (open_, open_ + timedelta(hours=3, minutes=30)),
    }
    assert lc.early_close_sessions(bounds) == [date(2024, 11, 29)]


def test_seeded_draw_is_deterministic_and_forces_early_close_and_post_dst() -> None:
    sessions = [date(2010, 1, 4) + timedelta(days=i) for i in range(0, 360)]
    early, dst = [date(2010, 11, 26)], [date(2010, 3, 15)]
    a = lc.seeded_session_draw(sessions, per_era=3, seed=7, early_closes=early, post_dst=dst)
    b = lc.seeded_session_draw(sessions, per_era=3, seed=7, early_closes=early, post_dst=dst)
    c = lc.seeded_session_draw(sessions, per_era=3, seed=8, early_closes=early, post_dst=dst)
    assert a == b and a != c
    assert set(early) & set(a) and set(dst) & set(a)
    assert a == sorted(set(a))


def test_peak_offset_finds_shifted_open() -> None:
    open_ns = 1_000_000 * MIN
    stamps = open_ns + np.arange(-10, 10) * MIN
    volume = np.ones(20)
    volume[10] = 50.0  # the minute at offset 0
    assert lc.volume_peak_offset_minutes(stamps, volume, open_ns) == 0
    # a one-hour shift (a DST slip) puts the same peak at an offset of -60 minutes: outside the window
    shifted = stamps + 60 * MIN
    with pytest.raises(lc.VacuousCheckError):
        lc.volume_peak_offset_minutes(shifted - 120 * MIN, volume, open_ns)
    shifted_in = stamps + 20 * MIN
    assert lc.volume_peak_offset_minutes(shifted_in, volume, open_ns) == 20


def test_session_day_result_and_era_verdict() -> None:
    open_ns, close_ns = 0, 390 * MIN
    stamps = np.array([0, 389, 390]) * MIN
    good = lc.session_day_result(
        date(2010, 3, 15), stamps, np.array([9.0, 9.0, 1.0]), open_ns, close_ns
    )
    assert good.open_offset_min == 0 and good.close_offset_min == -1 and good.passed
    # the closing peak stamped on the close minute is the early-close convention: still passes
    on_close = lc.session_day_result(
        date(2010, 3, 16), stamps, np.array([9.0, 1.0, 9.0]), open_ns, close_ns
    )
    assert on_close.passed
    bad = lc.SessionDayResult(date(2010, 3, 17), 2010, 60, -1)
    verdict = lc.session_verdict_by_era([good, on_close, bad])
    assert verdict[2010]["verdict"] == "ok" and verdict[2010]["failing_days"] == ["2010-03-17"]
    shifted = [lc.SessionDayResult(date(2010, 3, d), 2010, 60, 60) for d in (1, 2, 3)]
    assert lc.session_verdict_by_era(shifted)[2010]["verdict"] == "stop"
    with pytest.raises(lc.VacuousCheckError):
        lc.session_verdict_by_era([])


def test_publish_lag_requires_tz() -> None:
    close = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
    assert lc.publish_lag_hours(close + timedelta(hours=2, minutes=30), close) == 2.5
    with pytest.raises(ValueError):
        lc.publish_lag_hours(datetime(2026, 11, 6, 23), close)


def test_manifest_completeness_lists_missing_and_malformed() -> None:
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    good = {"sha256": "a" * 64, "rows": 5, "gzip_ok": True}
    manifest = {
        "minute": {days[0]: good, days[1]: good, days[2]: good},
        "day": {days[0]: good, days[2]: {**good, "sha256": "short"}},
    }
    out = lc.manifest_completeness(days, manifest)
    assert out["minute"]["complete"] is True
    assert out["day"]["missing"] == ["2024-01-03"] and out["day"]["malformed"] == ["2024-01-04"]
    assert out["day"]["complete"] is False
    with pytest.raises(lc.VacuousCheckError):
        lc.manifest_completeness([], manifest)


def test_survivorship_readings() -> None:
    end = date(2026, 11, 9)
    r = lc.survivorship_reading
    assert r(None, None, None, end) == "absent"
    assert r(date(2010, 1, 4), date(2026, 11, 9), None, end) == "present_active"
    assert r(date(2010, 1, 4), date(2020, 5, 1), None, end) == "no_listing_end_ended"
    assert r(date(2010, 1, 4), date(2020, 5, 1), date(2020, 5, 1), end) == "ends_at_listing_end"
    assert r(date(2010, 1, 4), date(2019, 1, 1), date(2020, 5, 1), end) == "ends_before"
    assert r(date(2010, 1, 4), date(2021, 1, 1), date(2020, 5, 1), end) == "ends_after"


def _file(rows):
    """rows: (ticker, ts_min, o, h, l, c, v)"""
    names = np.array(sorted({r[0] for r in rows}))
    code = np.array([int(np.searchsorted(names, r[0])) for r in rows])
    cols = [np.array([r[i] for r in rows], dtype=float) for i in range(1, 7)]
    return names, code, cols


def test_aggregate_by_ticker_rth_vs_all_hours() -> None:
    rows = [
        ("A", 0, 10, 11, 9, 10.5, 100),  # pre-market
        ("A", 5, 10.5, 12, 10, 11, 200),  # regular
        ("A", 6, 11, 13, 10.5, 12, 300),  # regular
        ("A", 9, 12, 12.5, 11.5, 12.2, 50),  # post
        ("B", 5, 20, 21, 19, 20.5, 10),
    ]
    names, code, (ts, o, h, low, c, v) = _file(rows)
    rth = lc.aggregate_by_ticker(names, code, ts, o, h, low, c, v, (ts >= 5) & (ts < 8))
    allh = lc.aggregate_by_ticker(names, code, ts, o, h, low, c, v, np.ones(len(ts), bool))
    assert (rth.open[0], rth.high[0], rth.low[0], rth.close[0], rth.volume[0]) == (
        10.5,
        13,
        10,
        12,
        500,
    )
    assert (allh.open[0], allh.close[0], allh.volume[0]) == (10, 12.2, 650)
    only_b = lc.aggregate_by_ticker(names, code, ts, o, h, low, c, v, ts == 5)
    assert not np.isnan(only_b.close[1])
    none = lc.aggregate_by_ticker(names, code, ts, o, h, low, c, v, ts == 99)
    assert np.isnan(none.close).all()


def test_compare_day_to_minutes_counts_and_day_only() -> None:
    names, code, (ts, o, h, low, c, v) = _file(
        [("A", 5, 10, 12, 9, 11, 100), ("B", 5, 20, 21, 19, 20, 10)]
    )
    agg = lc.aggregate_by_ticker(names, code, ts, o, h, low, c, v, np.ones(2, bool))
    day = {
        "A": (10, 12, 9, 11.5, 100),  # close differs
        "B": (20, 21, 19, 20, 10),
        "C": (1, 1, 1, 1, 1),  # no minute rows: counted day-only, never matched
    }
    counts = lc.compare_day_to_minutes(day, agg)
    assert counts.n_names == 2 and counts.n_day_only == 1
    assert counts.mismatch_close == 1 and counts.mismatch_open == 0 and counts.mismatch_volume == 0
    with pytest.raises(lc.VacuousCheckError):
        lc.compare_day_to_minutes({}, agg)


def test_day_vs_minute_decision_threshold_and_vacuous_era() -> None:
    ok = lc.DayVsMinuteCounts(1000, 0, 0, 0, 0, 10, 0)  # exactly 1 percent: not more than
    bad = lc.DayVsMinuteCounts(1000, 0, 0, 0, 0, 11, 0)
    assert lc.day_vs_minute_verdict({2010: ok})["decision"] == "served"
    out = lc.day_vs_minute_verdict({2010: ok, 2011: bad})
    # the eras over the limit are reported, but the 1d kind is always the served day file
    assert out["decision"] == "served" and out["eras_over_limit"] == [2011]
    with pytest.raises(lc.VacuousCheckError):
        lc.day_vs_minute_verdict({2010: lc.DayVsMinuteCounts(0, 5, 0, 0, 0, 0, 0)})


def _cells(medians: dict[tuple[int, str], float], n: int = 50):
    return {k: {f"S{i}": v for i in range(n)} for k, v in medians.items()}


def test_volume_bands_smooth_drift_is_a_data_note_not_a_stop() -> None:
    # 1.0 in 2003 to 0.5 in 2025 over 22 eras: each step is far below ln(1.5)
    eras = range(2003, 2026)
    ratio = {(e, "XNYS"): 1.0 * (0.5 ** ((e - 2003) / 22)) for e in eras}
    rows = lc.volume_bands(_cells(ratio))
    assert all(r.verdict == "ok" for r in rows)
    assert rows[0].note == "" and rows[-1].note == "drift_outside_design_band"
    assert math.isnan(rows[0].step_log) and rows[1].step_log < 0


def test_volume_bands_stops_on_a_step_or_an_absolute_miss() -> None:
    near = lc.volume_bands(_cells({(2010, "XNAS"): 1.0, (2011, "XNAS"): 1.45}))
    assert near[1].verdict == "ok"  # ln(1.45) is below ln(1.5)
    big = lc.volume_bands(_cells({(2010, "XNAS"): 1.0, (2011, "XNAS"): 1.6}))
    assert big[1].verdict == "stop" and big[0].verdict == "ok"
    out = lc.volume_bands(_cells({(2010, "XNAS"): 0.2}))
    assert out[0].verdict == "stop"  # outside [0.25, 4.0]
    out = lc.volume_bands(_cells({(2010, "XNAS"): 5.0}))
    assert out[0].verdict == "stop"
    # a step is judged within one exchange only
    mixed = lc.volume_bands(_cells({(2010, "XNAS"): 1.0, (2011, "XNYS"): 1.6}))
    assert [r.verdict for r in mixed] == ["ok", "ok"]
    with pytest.raises(lc.VacuousCheckError):
        lc.volume_bands({(2010, "XNYS"): {}})
    with pytest.raises(lc.VacuousCheckError):
        lc.volume_bands({(2010, "XNYS"): {"A": 0.0, "B": float("nan")}})


def test_sanity_unowned_rows_are_listed_apart_and_never_stop() -> None:
    n = 100
    o = np.full(n, 10.0)
    h = np.full(n, 11.0)
    low = np.full(n, 9.0)
    owned = np.ones(n, dtype=bool)
    o[:5] = h[:5] = low[:5] = 0.0  # five zero rows with no ticker
    owned[:5] = False
    counts, defective = lc.record_sanity(
        np.arange(n), np.arange(n, dtype=np.int64), o, h, low, o.copy(), np.ones(n), owned
    )
    assert defective[:5].all() and not defective[5:].any()  # the mask the counts came from
    assert counts.n_rows == 95 and counts.n_unowned_rows == 5 and counts.n_unowned_defective == 5
    assert counts.n_nonpositive_price == 0 and lc.sanity_verdict(counts) == "ok"
    with pytest.raises(lc.VacuousCheckError):
        lc.record_sanity(
            np.arange(3),
            np.arange(3),
            o[:3],
            h[:3],
            low[:3],
            o[:3],
            np.ones(3),
            np.zeros(3, dtype=bool),
        )


def test_sanity_single_named_defect_is_not_systematic() -> None:
    n = 100_000
    o = np.full(n, 10.0)
    low = np.full(n, 9.0)
    low[7] = 0.0  # one named-instrument bar with a zero low: a gap-list item, not a stop
    counts, _ = lc.record_sanity(
        np.arange(n), np.arange(n, dtype=np.int64), o, np.full(n, 11.0), low, o.copy(), np.ones(n)
    )
    assert counts.n_nonpositive_price == 1 and lc.sanity_verdict(counts) == "ok"


def test_clean_vendor_passes_every_systemic_check() -> None:
    """Calibration: a vendor with clean rows, an exact day file, a flat volume ratio passes."""
    n = 500
    ts = np.arange(n, dtype=np.int64)
    px = np.linspace(20, 30, n)
    counts, _ = lc.record_sanity(
        np.zeros(n, dtype=np.int64), ts, px, px + 1, px - 1, px, np.full(n, 100.0)
    )
    assert lc.sanity_verdict(counts) == "ok"
    open_ns, close_ns = 0, 390 * MIN
    stamps = np.array([0, 100, 389]) * MIN
    day = lc.session_day_result(
        date(2010, 3, 15), stamps, np.array([9.0, 1.0, 9.0]), open_ns, close_ns
    )
    assert lc.session_verdict_by_era([day])[2010]["verdict"] == "ok"
    names, code, (t, o2, h2, l2, c2, v2) = _file(
        [("A", 1, 10, 12, 9, 11, 5), ("A", 2, 11, 13, 10, 12, 7)]
    )
    agg = lc.aggregate_by_ticker(names, code, t, o2, h2, l2, c2, v2, np.ones(2, bool))
    dvm = lc.compare_day_to_minutes({"A": (10, 13, 9, 12, 12)}, agg)
    assert dvm.mismatch_close == 0
    assert lc.day_vs_minute_verdict({2010: dvm})["decision"] == "served"
    ratios = {(e, "XNYS"): {f"S{i}": 0.95 for i in range(30)} for e in (2010, 2011, 2012)}
    assert all(r.verdict == "ok" for r in lc.volume_bands(ratios))


def test_split_scale_matches_scales_for_sessions() -> None:
    from src.intelligence.bars.split_rescale import SplitFactor, scales_for_sessions

    splits = [SplitFactor(date(2014, 6, 6), 7.0), SplitFactor(date(2020, 8, 28), 4.0)]
    days = [
        date(2014, 6, 5),
        date(2014, 6, 6),
        date(2014, 6, 9),
        date(2020, 8, 28),
        date(2021, 1, 4),
    ]
    want = scales_for_sessions(days, splits)
    got = lc.split_scale_for_days(np.array(days, dtype="datetime64[D]"), splits)
    assert got.tolist() == [want[d] for d in days]
    assert got.tolist() == [28.0, 28.0, 4.0, 4.0, 1.0]


def test_volume_bands_thin_cells_are_listed_and_never_judged() -> None:
    thin = {(2010, "XNYS"): {f"S{i}": 1.0 for i in range(30)}, (2011, "XNYS"): {"A": 9.0, "B": 9.0}}
    rows = lc.volume_bands(thin)
    assert [r.verdict for r in rows] == ["ok", "thin"] and rows[1].note == "thin"
    with pytest.raises(lc.VacuousCheckError):
        lc.volume_bands({(2010, "XNYS"): {"A": 1.0, "B": 1.0}})  # no cell reaches the minimum


def test_volume_step_compares_across_a_missing_era_and_flags_it() -> None:
    rows = lc.volume_bands(_cells({(2010, "XNAS"): 1.0, (2013, "XNAS"): 1.6}))
    assert rows[1].verdict == "stop" and rows[1].note == "step_across_gap"
    # a thin era between two judged ones is skipped, and the step still compares the judged pair
    cells = _cells({(2010, "XNAS"): 1.0, (2012, "XNAS"): 1.6})
    cells[(2011, "XNAS")] = {"A": 1.0}
    out = lc.volume_bands(cells)
    assert [r.verdict for r in out] == ["ok", "thin", "stop"]


def test_one_nan_volume_minute_does_not_move_the_session_peak() -> None:
    minutes = np.arange(-30, 30, dtype=np.int64)
    window = minutes * 60 * 1_000_000_000
    volume = np.ones(len(minutes))
    volume[40] = 500.0  # the true peak, +10 minutes
    clean = lc.volume_peak_offset_minutes(window, volume, 0)
    volume[5] = np.nan  # an unknown minute elsewhere in the window
    assert lc.volume_peak_offset_minutes(window, volume, 0) == clean == 10
    volume[40] = np.nan  # the peak minute itself unknown: the next-best minute, never NaN-driven
    assert lc.volume_peak_offset_minutes(window, volume, 0) != 10
