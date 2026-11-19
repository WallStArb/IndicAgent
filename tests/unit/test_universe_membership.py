"""Stage 2 universe membership rule (preregistration 2026-11-13) on synthetic daily bars."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.intelligence.bars.split_rescale import SplitFactor
from src.intelligence.universe_membership import (
    CLOSED_LIST_RULE_ID,
    ELIGIBLE_TYPES,
    LAST_LIST_DATE,
    RULE,
    RULE_ID,
    MembershipRule,
    SecurityHistory,
    as_traded_close,
    decide,
    ledger_rule_label,
    ledger_rule_problem,
    memberships_for_security,
    month_end_sessions,
    rule_id_for,
    type_list_date,
)

START = date(2020, 1, 6)


def _days(n: int, start: date = START) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _history(days: list[date], dollar: float | list[float], close: float = 10.0, symbol="AAA"):
    dollars = dollar if isinstance(dollar, list) else [dollar] * len(days)
    return SecurityHistory(
        symbol=symbol,
        days=np.array(days, dtype="datetime64[D]"),
        close=np.full(len(days), close),
        volume=np.array([x / close for x in dollars]),
    )


def test_preregistered_constants():
    assert RULE.entry_floor == 1_000_000.0
    assert RULE.exit_floor == 500_000.0
    assert RULE.window_sessions == 60
    assert RULE.min_history_sessions == 60
    assert RULE.min_close == 1.0
    assert ELIGIBLE_TYPES == {"CS", "ADRC", "ETF"}


def test_entry_at_floor_inclusive_and_below_is_out():
    days = _days(60)
    assert decide(_history(days, 1_000_000.0), days[-1], "CS", False) is not None
    assert decide(_history(days, 999_999.0), days[-1], "CS", False) is None


def test_entry_is_the_window_median_not_the_mean():
    days = _days(60)
    # 31 of 60 sessions at $1.2M and 29 at $0: median $1.2M, mean $0.62M
    dollars = [1_200_000.0] * 31 + [1.0] * 29
    row = decide(_history(days, dollars), days[-1], "CS", False)
    assert row is not None and row.median_dollar_volume == pytest.approx(1_200_000.0)
    # 29 high of 60: median is low
    assert decide(_history(days, [1_200_000.0] * 29 + [1.0] * 31), days[-1], "CS", False) is None


def test_window_is_the_last_60_sessions_only():
    days = _days(120)
    dollars = [0.0 + 1.0] * 60 + [2_000_000.0] * 60
    row = decide(_history(days, dollars), days[-1], "CS", False)
    assert row is not None and row.sessions == 120


def test_hysteresis_member_stays_between_floors_non_member_does_not_enter():
    days = _days(60)
    mid = _history(days, 700_000.0)
    assert decide(mid, days[-1], "CS", True) is not None
    assert decide(mid, days[-1], "CS", False) is None


def test_hysteresis_exit_below_half_floor_and_boundary_stays():
    days = _days(60)
    assert decide(_history(days, 500_000.0), days[-1], "CS", True) is not None
    assert decide(_history(days, 499_999.0), days[-1], "CS", True) is None


def test_entered_flag_distinguishes_entry_from_retention():
    days = _days(60)
    assert decide(_history(days, 2e6), days[-1], "CS", False).entered is True
    assert decide(_history(days, 7e5), days[-1], "CS", True).entered is False


def test_price_floor_is_hard_even_for_a_member():
    days = _days(60)
    assert decide(_history(days, 2e6, close=0.99), days[-1], "CS", True) is None
    assert decide(_history(days, 2e6, close=1.0), days[-1], "CS", True) is not None


def test_history_needs_60_own_sessions():
    days = _days(59)
    assert decide(_history(days, 2e6), days[-1], "CS", False) is None
    days = _days(60)
    assert decide(_history(days, 2e6), days[-1], "CS", False) is not None


def test_history_floor_is_hard_for_a_member():
    days = _days(59)
    assert decide(_history(days, 2e6), days[-1], "CS", True) is None


@pytest.mark.parametrize(
    "kind,ok",
    [
        ("CS", True),
        ("ADRC", True),
        ("ETF", True),
        ("PFD", False),
        ("WARRANT", False),
        ("UNIT", False),
        ("ETN", False),
        (None, False),
    ],
)
def test_types(kind, ok):
    days = _days(60)
    assert (decide(_history(days, 2e6), days[-1], kind, False) is not None) is ok


def test_type_is_hard_for_a_member():
    days = _days(60)
    assert decide(_history(days, 2e6), days[-1], "PFD", True) is None


def test_no_bar_on_t_is_not_a_member_delisting():
    days = _days(80)
    hist = _history(days[:70], 2e6)  # delisted after day 70
    assert decide(hist, days[69], "CS", False) is not None
    assert decide(hist, days[79], "CS", True) is None


def test_decision_ignores_bars_after_t():
    days = _days(120)
    base = _history(days[:60], 2e6)
    extended_dollars = [2e6] * 60 + [1.0] * 60  # collapse after t
    extended = _history(days, extended_dollars)
    assert decide(base, days[59], "CS", False) == decide(extended, days[59], "CS", False)


def test_nan_in_window_is_not_a_member_and_is_not_filled():
    days = _days(60)
    hist = _history(days, 2e6)
    hist.volume[10] = np.nan
    assert decide(hist, days[-1], "CS", False) is None


def test_walk_enters_holds_exits_and_reenters_only_at_entry_floor():
    days = _days(60 * 5)
    ends = [days[59], days[119], days[179], days[239], days[299]]
    # 60-session blocks of dollar volume: 2M enter, 0.7M hold, 0.4M exit, 0.7M stay out, 2M re-enter
    dollars = [2e6] * 60 + [7e5] * 60 + [4e5] * 60 + [7e5] * 60 + [2e6] * 60
    rows = memberships_for_security(_history(days, dollars), ends, {e: "CS" for e in ends})
    assert [r.as_of for r in rows] == [ends[0], ends[1], ends[4]]
    assert [r.entered for r in rows] == [True, False, True]


def test_walk_seed_resumes_hysteresis_state():
    days = _days(60)
    hist = _history(days, 7e5)
    types = {days[-1]: "CS"}
    assert memberships_for_security(hist, [days[-1]], types, was_member=True)
    assert not memberships_for_security(hist, [days[-1]], types, was_member=False)


def test_walk_missing_type_is_unknown_and_excluded():
    days = _days(60)
    assert memberships_for_security(_history(days, 2e6), [days[-1]], {}) == []


def test_rule_validates_floor_order_and_window():
    with pytest.raises(ValueError):
        MembershipRule(entry_floor=1.0, exit_floor=2.0)
    with pytest.raises(ValueError):
        MembershipRule(window_sessions=60, min_history_sessions=59)


def test_history_rejects_unsorted_days():
    with pytest.raises(ValueError):
        SecurityHistory(
            "X",
            np.array(["2020-01-02", "2020-01-01"], dtype="datetime64[D]"),
            np.ones(2),
            np.ones(2),
        )


def test_month_end_sessions_takes_last_session_per_month():
    days = [date(2020, 1, 30), date(2020, 1, 31), date(2020, 2, 3), date(2020, 2, 28)]
    assert month_end_sessions(days) == [date(2020, 1, 31), date(2020, 2, 28)]


def test_as_traded_close_undoes_splits_on_or_after_t_only():
    splits = [SplitFactor(date(2020, 6, 1), 10.0), SplitFactor(date(2019, 1, 1), 2.0)]
    # t before both: both undone is wrong for the older one; only splits effective >= t count
    assert as_traded_close(0.5, date(2020, 3, 31), splits) == pytest.approx(5.0)
    assert as_traded_close(0.5, date(2020, 6, 1), splits) == pytest.approx(5.0)  # effective day
    assert as_traded_close(0.5, date(2020, 6, 2), splits) == pytest.approx(0.5)
    assert as_traded_close(0.5, date(2018, 1, 1), splits) == pytest.approx(10.0)


def test_future_reverse_split_name_is_not_admitted_and_future_split_name_is_kept():
    days = _days(60)
    penny = _history(days, 2e6, close=8.0)  # as traded 0.40, then a 1:20 reverse split
    object.__setattr__(penny, "splits", (SplitFactor(date(2021, 1, 4), 0.05),))
    assert decide(penny, days[-1], "CS", False) is None
    rich = _history(days, 2e6, close=0.5)  # as traded 5.0, then a 10:1 split
    object.__setattr__(rich, "splits", (SplitFactor(date(2021, 1, 4), 10.0),))
    row = decide(rich, days[-1], "CS", False)
    assert row is not None and row.close == pytest.approx(5.0)


# --- 5m tier (amendment 2026-11-15) --------------------------------------------------------


def test_tier_constants_and_validation():
    assert RULE.tier_entry_floor == 25_000_000.0 and RULE.tier_exit_floor == 12_500_000.0
    with pytest.raises(ValueError):  # a tier floor below the membership floor is not nested
        MembershipRule(tier_entry_floor=500_000.0, tier_exit_floor=400_000.0)
    with pytest.raises(ValueError):
        MembershipRule(tier_entry_floor=2e7, tier_exit_floor=3e7)


def test_tier_enters_at_the_tier_floor_inclusive_and_implies_membership():
    days = _days(60)
    at = decide(_history(days, 25_000_000.0), days[-1], "CS", False)
    below = decide(_history(days, 24_999_999.0), days[-1], "CS", False)
    assert at is not None and at.tier_5m
    assert below is not None and not below.tier_5m  # a member, not in the tier


def test_tier_hysteresis_holds_between_the_floors_and_leaves_below_the_exit():
    days = _days(60)
    hist = _history(days, 15e6)  # between 12.5M and 25M
    assert not decide(hist, days[-1], "CS", True).tier_5m
    assert decide(hist, days[-1], "CS", True, was_tier=True).tier_5m
    low = _history(days, 12_000_000.0)
    assert not decide(low, days[-1], "CS", True, was_tier=True).tier_5m


def test_tier_state_is_lost_with_the_membership():
    days = _days(60 * 4)
    ends = [days[59], days[119], days[179], days[239]]
    # tier, then out of the universe (below 0.5M), then 15M: a re-entrant needs the 25M floor
    dollars = [3e7] * 60 + [4e5] * 60 + [15e6] * 60 + [3e7] * 60
    rows = memberships_for_security(_history(days, dollars), ends, {e: "CS" for e in ends})
    assert [(r.as_of, r.tier_5m) for r in rows] == [
        (ends[0], True),
        (ends[2], False),
        (ends[3], True),
    ]


def test_walk_seed_resumes_the_tier_state():
    days = _days(60)
    hist = _history(days, 15e6)
    types = {days[-1]: "CS"}
    assert memberships_for_security(hist, [days[-1]], types, was_member=True, was_tier=True)[
        0
    ].tier_5m
    assert not memberships_for_security(hist, [days[-1]], types, was_member=True)[0].tier_5m


# --- closed list (amendment 2026-11-18) --------------------------------------------------------


def test_L_and_the_closed_list_id_are_the_amendments_constants():
    assert LAST_LIST_DATE == date(2026, 11, 9)
    assert CLOSED_LIST_RULE_ID == "stage2-closed-list"
    assert RULE_ID == "stage2-2026-11-15"  # the Massive-listed months keep their id


@pytest.mark.parametrize(
    "as_of, rule_id, list_date",
    [
        (date(2003, 9, 30), RULE_ID, date(2003, 9, 30)),
        (date(2026, 10, 30), RULE_ID, date(2026, 10, 30)),
        (LAST_LIST_DATE, RULE_ID, LAST_LIST_DATE),  # at L: the old rule
        (date(2026, 11, 10), CLOSED_LIST_RULE_ID, LAST_LIST_DATE),
        (date(2026, 11, 30), CLOSED_LIST_RULE_ID, LAST_LIST_DATE),
        (date(2031, 1, 31), CLOSED_LIST_RULE_ID, LAST_LIST_DATE),
    ],
)
def test_the_schedule_is_a_pure_function_of_the_month_end(as_of, rule_id, list_date):
    assert rule_id_for(as_of) == rule_id
    assert type_list_date(as_of) == list_date


def test_ledger_rule_problem_accepts_the_schedule_and_names_the_first_violation():
    ok = [(date(2026, 10, 30), RULE_ID), (date(2026, 11, 30), CLOSED_LIST_RULE_ID)]
    assert ledger_rule_problem(ok) is None
    assert ledger_rule_problem([]) is None
    early = [(date(2026, 10, 30), CLOSED_LIST_RULE_ID)]
    assert "2026-10-30" in ledger_rule_problem(early)
    late = [(date(2026, 11, 30), RULE_ID)]
    assert "stage2-closed-list" in ledger_rule_problem(late)


def test_ledger_rule_label_is_the_single_id_or_the_sorted_join():
    one = [(date(2024, 1, 31), RULE_ID), (date(2024, 2, 29), RULE_ID)]
    assert ledger_rule_label(one) == RULE_ID  # what min(rule_id) returned
    crossing = [(date(2026, 11, 30), CLOSED_LIST_RULE_ID), *one]
    assert ledger_rule_label(crossing) == f"{RULE_ID}+{CLOSED_LIST_RULE_ID}"


def test_decide_is_unchanged_by_the_closed_list_a_name_the_list_lacks_has_no_type():
    days = np.array([np.datetime64("2026-08-03") + i for i in range(120)], dtype="datetime64[D]")
    days = days[np.is_busday(days)][:90]
    hist = SecurityHistory("X", days, np.full(len(days), 10.0), np.full(len(days), 3e5), splits=())
    as_of = days[-1].astype(object)
    assert decide(hist, as_of, "CS", False) is not None
    assert decide(hist, as_of, None, False) is None  # absent from the list at L: no entrant
