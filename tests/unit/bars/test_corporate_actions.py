"""Split inference and disputed-date tests (D-21, D-23).

infer_split turns a seam into a corporate-action record only when its factor
snaps to a rational p/q (p, q <= 50) within ratio_snap_tol: a news-shaped or
drift-shaped ratio stays unexplained rather than becoming a fake split. The
disputed-date rule turns each near-miss dividend pair into one record whose
span marks every return crossing it unknown, instead of keeping both rows or
rolling the symbol back.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from src.intelligence.bars.corporate_actions import (
    SplitRatioRule,
    disputed_dates,
    infer_split,
    recognised_split_ratio,
    unknown_return_mask,
)
from src.intelligence.bars.seams import Seam

_SNAP_TOL = 0.01
_WED_THU = (date(2025, 3, 12), date(2025, 3, 13))


def _seam(factor: float, n_days: int = 120) -> Seam:
    return Seam(
        start=date(2025, 1, 6),
        end=date(2025, 6, 27),
        factor=factor,
        n_days=n_days,
    )


def test_infer_split_two_for_one() -> None:
    seam = _seam(2.0, n_days=180)
    record = infer_split(seam, ratio_snap_tol=_SNAP_TOL)
    assert record is not None
    assert record.effective_date == seam.end
    assert record.factor == pytest.approx(2.0)
    assert record.kind == "split"


def test_infer_split_one_for_eight_is_reverse_split() -> None:
    record = infer_split(_seam(0.125), ratio_snap_tol=_SNAP_TOL)
    assert record is not None
    assert record.factor == pytest.approx(0.125)
    assert record.kind == "reverse_split"
    assert record.effective_date == date(2025, 6, 27)


def test_infer_split_noisy_factor_snaps_to_rational() -> None:
    record = infer_split(_seam(1.993), ratio_snap_tol=_SNAP_TOL)
    assert record is not None
    assert record.factor == pytest.approx(2.0)
    assert record.kind == "split"
    three_halves = infer_split(_seam(1.502), ratio_snap_tol=0.005)
    assert three_halves is not None
    assert three_halves.factor == pytest.approx(1.5)


def test_infer_split_irrational_ratio_stays_unexplained() -> None:
    # sqrt(3): nearest p/q with p, q <= 50 is 26/15 = 1.7333, 0.0012 away.
    assert infer_split(_seam(1.7321), ratio_snap_tol=0.0005) is None


def test_disputed_dates_turn_pairs_into_ordered_records() -> None:
    records = disputed_dates(
        "JPM",
        [(date(2025, 3, 12), date(2025, 3, 14)), (date(2025, 6, 2), date(2025, 5, 30))],
    )
    assert len(records) == 2
    first, second = records
    assert (first.first_date, first.last_date) == (date(2025, 3, 12), date(2025, 3, 14))
    assert first.dates_by_source == {
        "ibkr_adjusted_last_ratio": date(2025, 3, 12),
        "yahoo": date(2025, 3, 14),
    }
    # The second pair arrives yahoo-earlier; the record is still ordered and the
    # source attribution is preserved.
    assert (second.first_date, second.last_date) == (date(2025, 5, 30), date(2025, 6, 2))
    assert second.dates_by_source == {
        "ibkr_adjusted_last_ratio": date(2025, 6, 2),
        "yahoo": date(2025, 5, 30),
    }


def test_disputed_dates_rejects_same_day_pair() -> None:
    with pytest.raises(ValueError, match="same date"):
        disputed_dates("KO", [(date(2025, 3, 12), date(2025, 3, 12))])


def _mask_sessions() -> list[date]:
    # Two business weeks; 2025-03-10 is a Monday.
    start = date(2025, 3, 10)
    sessions: list[date] = []
    day = start
    while len(sessions) < 10:
        if day.weekday() < 5:
            sessions.append(day)
        day = date.fromordinal(day.toordinal() + 1)
    return sessions


def test_unknown_return_mask_marks_span_crossings() -> None:
    sessions = _mask_sessions()
    mon, tue, wed, thu, fri = range(5)
    next_mon, next_wed = 5, 7
    entry = np.array([tue, wed, mon, thu, fri, fri, mon, next_mon])
    exit_ = np.array([wed, thu, tue, fri, fri, next_mon, thu, next_wed])
    disputes = disputed_dates("JPM", [_WED_THU])
    mask = unknown_return_mask(np.array(sessions, dtype=object), entry, exit_, disputes)
    # [entry, exit] intersecting [first_date - 1 session, last_date] = [Tue, Thu].
    expected = [True, True, True, True, False, False, True, False]
    assert mask.tolist() == expected
    assert mask.dtype == np.bool_


def test_unknown_return_mask_dispute_at_calendar_start_has_no_lower_bound() -> None:
    sessions = _mask_sessions()
    disputes = disputed_dates("JPM", [(sessions[0], sessions[1])])
    mask = unknown_return_mask(
        np.array(sessions, dtype=object), np.array([0]), np.array([0]), disputes
    )
    # The span extends before the calendar, so even the first session's own
    # same-day return crosses it.
    assert mask.tolist() == [True]


def test_unknown_return_mask_dispute_wholly_before_calendar_marks_nothing() -> None:
    sessions = _mask_sessions()
    disputes = disputed_dates("JPM", [(date(2024, 3, 6), date(2024, 3, 8))])
    mask = unknown_return_mask(
        np.array(sessions, dtype=object), np.array([0, 8]), np.array([4, 9]), disputes
    )
    assert mask.tolist() == [False, False]


def test_unknown_return_mask_validates_inputs() -> None:
    sessions = np.array(_mask_sessions(), dtype=object)
    disputes = disputed_dates("JPM", [_WED_THU])
    with pytest.raises(ValueError, match="length"):
        unknown_return_mask(sessions, np.array([0, 1]), np.array([2]), disputes)
    with pytest.raises(ValueError, match="ascending"):
        unknown_return_mask(sessions[::-1].copy(), np.array([0]), np.array([1]), disputes)
    with pytest.raises(ValueError, match="bounds"):
        unknown_return_mask(sessions, np.array([0]), np.array([10]), disputes)


# --- recognised split ratios (plan 185-51, todo 515) ---------------------------------------
# The migration 461 seeds: p <= 50, q <= 4, 0.2 % relative tolerance.
_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)


def test_ctva_spin_off_rescale_is_not_a_recognised_split_ratio() -> None:
    # IBKR's CTVA restatement after the Vylor spin-off: 39/7, measured 5.5711 over 1,848 dates.
    assert recognised_split_ratio(39 / 7, _RULE) is None
    assert recognised_split_ratio(5.5711, _RULE) is None
    assert recognised_split_ratio(7 / 39, _RULE) is None  # the same rescale read the other way


def test_a_rescale_that_lands_on_a_small_ratio_passes_the_rule() -> None:
    # The rule's known limit, measured on the same event: Tradier's CTVA factor 6.665 sits
    # 0.025 % from 20/3 and would read as a 20-for-3 split. The rule bounds the false-split rate,
    # it does not identify spin-offs; the company record does.
    assert recognised_split_ratio(6.665, _RULE) == pytest.approx(20 / 3)


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        (1 / 3, 1 / 3),  # ETHA 1-for-3 reverse split
        (0.33331, 1 / 3),  # measured, inside the tolerance
        (1.5, 1.5),  # 3-for-2
        (0.05, 0.05),  # 1-for-20 reverse split
        (2.0, 2.0),
        (4.0, 4.0),
        (1.25, 1.25),  # 5-for-4
        (50.0, 50.0),
    ],
)
def test_small_integer_split_ratios_are_recognised_exactly(factor: float, expected: float) -> None:
    assert recognised_split_ratio(factor, _RULE) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("factor", [1.0, 1.001, 1.05, 2.02, 60.0, 1 / 60, 7 / 5, 1.73])
def test_no_split_near_one_beyond_the_caps_or_outside_the_tolerance(factor: float) -> None:
    assert recognised_split_ratio(factor, _RULE) is None


def test_the_caps_are_parameters_not_constants() -> None:
    assert recognised_split_ratio(7 / 5, SplitRatioRule(50, 5, 0.002)) == pytest.approx(1.4)
    assert recognised_split_ratio(50.0, SplitRatioRule(40, 4, 0.002)) is None


@pytest.mark.parametrize("bad", [0.0, -2.0, float("inf"), float("nan")])
def test_a_non_positive_or_non_finite_factor_raises(bad: float) -> None:
    with pytest.raises(ValueError, match="factor"):
        recognised_split_ratio(bad, _RULE)


def test_an_unusable_rule_raises() -> None:
    with pytest.raises(ValueError, match="rule"):
        recognised_split_ratio(2.0, SplitRatioRule(1, 4, 0.002))
    with pytest.raises(ValueError, match="rule"):
        recognised_split_ratio(2.0, SplitRatioRule(50, 0, 0.002))
    with pytest.raises(ValueError, match="rule"):
        recognised_split_ratio(2.0, SplitRatioRule(50, 4, 0.0))
