"""Tests for the 1d primary swap measurement (scripts/research/swap_1d_primary_measure.py, 185-46).

Pure functions only, on fakes (todo 494): nothing here opens a connection.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.research import swap_1d_primary_measure as m

_T0 = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)


def _row(minute: float, latency_s: float, outcome: str = "bars") -> m.LedgerRow:
    start = _T0 + timedelta(minutes=minute)
    return m.LedgerRow(
        requested_at=start, answered_at=start + timedelta(seconds=latency_s), outcome=outcome
    )


def _pairs(ratios: list[float], start: date = date(2026, 1, 2)) -> list[tuple[date, float, float]]:
    return [(start + timedelta(days=i), 100.0, 100.0 * r) for i, r in enumerate(ratios)]


# --- request_rate_summary -------------------------------------------------------------------


def test_rate_uses_median_over_busy_hours_and_latency_quantiles() -> None:
    rows = [_row(i * 0.5, 1.0) for i in range(100)]  # hour 0: 100 requests
    rows += [_row(60 + i, 3.0, "no_data") for i in range(60)]  # hour 1: 60 requests
    rows += [_row(120 + i, 2.0, "failed") for i in range(10)]  # hour 2: 10, below the floor
    s = m.request_rate_summary(rows, min_hour_requests=50)
    assert s.n_requests == 170
    assert s.n_hours_used == 2
    assert s.requests_per_hour == pytest.approx(80.0)
    assert s.median_latency_s == pytest.approx(1.0)
    assert s.p90_latency_s == pytest.approx(3.0)
    assert s.mean_latency_s == pytest.approx((100 * 1.0 + 60 * 3.0 + 10 * 2.0) / 170)
    assert s.no_data_share == pytest.approx(60 / 170)
    assert s.failed_share == pytest.approx(10 / 170)


def test_rate_without_a_busy_hour_has_no_rate() -> None:
    s = m.request_rate_summary([_row(0, 1.0)], min_hour_requests=50)
    assert s.requests_per_hour is None and s.n_hours_used == 0


def test_rate_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        m.request_rate_summary([], min_hour_requests=50)


# --- nightly_cost_minutes -------------------------------------------------------------------


def test_nightly_cost_is_the_larger_of_pacing_and_serial_time() -> None:
    # pacing binds: 1200 names at 600 per hour is 120 minutes; serial is 1200 * 1 s = 20 minutes
    assert m.nightly_cost_minutes(1200, 600.0, 0.5, 0.5) == pytest.approx(120.0)
    # serial binds: 600 names * 3 s = 30 minutes; pacing 600 / 6000 per hour = 6 minutes
    assert m.nightly_cost_minutes(600, 6000.0, 2.0, 1.0) == pytest.approx(30.0)


@pytest.mark.parametrize("rph", [0.0, -1.0])
def test_nightly_cost_rejects_a_non_positive_rate(rph: float) -> None:
    with pytest.raises(ValueError):
        m.nightly_cost_minutes(10, rph, 2.0, 1.0)


# --- volume_ratio_summary -------------------------------------------------------------------


def test_volume_summary_per_name_median_then_quantiles() -> None:
    by_name = {
        "A": [(50, 100), (60, 100), (40, 100)],  # median 0.5
        "B": [(30, 100), (0, 100), (30, -5)],  # non-positive dropped: median 0.3
        "C": [(90, 100)],  # 0.9
        "D": [(0, 100), (None, 100), (10, 0)],  # nothing usable
    }
    s = m.volume_ratio_summary(by_name)
    assert s.n_names == 3
    assert s.unusable == ("D",)
    assert s.p50 == pytest.approx(0.5)
    assert s.p10 < s.p50 < s.p90
    assert s.share_below_half == pytest.approx(1 / 3)
    assert s.per_name["B"] == pytest.approx(0.3)


# --- classify_swap --------------------------------------------------------------------------

_KW = {"window_sessions": 20, "tolerance_bp": 10.0, "min_overlap": 60, "min_agree_share": 0.9}


def test_class_a_when_recent_median_within_tolerance() -> None:
    d = m.classify_swap(_pairs([1.05] * 100 + [1.0] * 20), **_KW)
    assert d.cls == "A" and d.n_common == 120
    assert d.median_ratio == pytest.approx(1.0)


def test_class_a_with_a_single_common_session() -> None:
    assert m.classify_swap(_pairs([1.0005]), **_KW).cls == "A"


def test_class_b_when_off_and_admission_recent_window_disagrees() -> None:
    d = m.classify_swap(_pairs([1.0] * 40 + [1.02] * 60), **_KW)
    assert d.cls == "B"
    assert d.recent_agree_share == pytest.approx(0.0)


def test_class_c_with_no_common_session() -> None:
    d = m.classify_swap([], **_KW)
    assert d.cls == "C" and d.n_common == 0 and d.median_ratio is None


def test_class_c_when_off_with_too_few_sessions() -> None:
    assert m.classify_swap(_pairs([1.02] * 59), **_KW).cls == "C"


def test_class_c_when_off_but_admission_window_agrees() -> None:
    # last 20 off (11 of 20), but the 200-session admission window agrees (189 of 200): neither
    # A nor B. With the live APR values (20 and 60) this case cannot arise.
    kw = {**_KW, "min_overlap": 200}
    assert m.classify_swap(_pairs([1.0] * 200 + [1.02] * 11), **kw).cls == "C"


# --- head_candidate -------------------------------------------------------------------------


def test_head_kept_when_first_window_agrees() -> None:
    head = [date(2000, 1, 3) + timedelta(days=i) for i in range(30)]
    h = m.head_candidate(
        _pairs([1.0] * 20 + [1.5] * 50), head, window_sessions=20, tolerance_bp=10.0
    )
    assert h.keep and h.n_bars == 30
    assert h.first == head[0] and h.last == head[-1]
    assert h.median_ratio == pytest.approx(1.0)


def test_head_dropped_when_first_window_disagrees() -> None:
    h = m.head_candidate(
        _pairs([1.5] * 20 + [1.0] * 50), [date(2000, 1, 3)], window_sessions=20, tolerance_bp=10.0
    )
    assert not h.keep and h.n_bars == 1


def test_head_not_kept_without_a_common_session() -> None:
    h = m.head_candidate([], [date(2000, 1, 3)], window_sessions=20, tolerance_bp=10.0)
    assert not h.keep and h.median_ratio is None and h.n_bars == 1


def test_no_head_is_never_kept() -> None:
    h = m.head_candidate(_pairs([1.0] * 20), [], window_sessions=20, tolerance_bp=10.0)
    assert not h.keep and h.n_bars == 0 and h.first is None


# --- read-only guard (T-185-46-02) ----------------------------------------------------------


def test_module_never_writes() -> None:
    source = Path(m.__file__).read_text()
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP)\b", source)
    assert "default_transaction_read_only" in source
