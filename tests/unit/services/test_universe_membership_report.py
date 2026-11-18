"""The membership build's counts-by-year view (todo 609 gate 5), on a synthetic membership."""

from datetime import date

import numpy as np
import pytest

from services import universe_membership_report as rep
from src.intelligence.universe_membership import RULE_ID

D = date
MONTHS = [D(2020, 1, 31), D(2020, 2, 28), D(2020, 3, 31), D(2021, 1, 29), D(2021, 2, 26)]
LEDGER = [(m, RULE_ID, n) for m, n in zip(MONTHS, (2, 2, 3, 3, 3), strict=True)]
ROWS = [
    (MONTHS[0], "A", "CS", False),
    (MONTHS[0], "B", "ETF", True),
    (MONTHS[1], "A", "CS", False),
    (MONTHS[1], "B", "ETF", True),
    (MONTHS[2], "A", "CS", False),
    (MONTHS[2], "B", "ETF", True),
    (MONTHS[2], "C", "ADRC", False),
    (MONTHS[3], "A", "CS", False),
    (MONTHS[3], "B", "ETF", True),
    (MONTHS[3], "C", "ADRC", False),
    (MONTHS[4], "A", "CS", False),
    (MONTHS[4], "B", "ETF", False),
    (MONTHS[4], "C", "ADRC", False),
]
COUNTS = {m: n for m, _, n in LEDGER}


def _check(ledger=LEDGER, counts=COUNTS, months=MONTHS, **kw):
    rep.check_ledger(ledger, counts, month_ends=months, **kw)


def test_the_preregistered_ledger_passes():
    _check()


def test_another_rule_id_is_refused():
    other = [(m, "other-rule", n) for m, _, n in LEDGER]
    with pytest.raises(rep.MembershipReportRefused, match="differ from the preregistered"):
        _check(other)


def test_a_missing_or_extra_month_is_refused():
    with pytest.raises(rep.MembershipReportRefused, match="missing"):
        _check(LEDGER[:-1] + [], months=MONTHS)
    with pytest.raises(rep.MembershipReportRefused, match="extra"):
        _check(months=MONTHS[:-1])


def test_a_ledger_count_that_disagrees_with_its_rows_is_refused():
    with pytest.raises(rep.MembershipReportRefused, match="n_members"):
        _check(counts={**COUNTS, MONTHS[2]: 2})


def test_an_empty_ledger_is_refused():
    with pytest.raises(rep.MembershipReportRefused, match="has not run"):
        rep.check_ledger([], {})


def test_unplaced_share_aggregates_types_by_year():
    csv_rows = [
        {"year": "2020", "type": "CS", "rows_meeting_floor": "90", "unplaced": "9"},
        {"year": "2020", "type": "ETF", "rows_meeting_floor": "10", "unplaced": "1"},
        {"year": "2021", "type": "CS", "rows_meeting_floor": "50", "unplaced": "0"},
    ]
    assert rep.unplaced_by_year(csv_rows) == {2020: 0.1, 2021: 0.0}


def _report(unplaced=None):
    by_month = {}
    for as_of, symbol, _, _ in ROWS:
        by_month.setdefault(as_of, set()).add(symbol)
    members = {m: frozenset(s) for m, s in by_month.items()}
    days = np.arange(np.datetime64("2020-01-01"), np.datetime64("2021-03-31"))
    sessions = days[(days.astype(int) + 4) % 7 < 5]
    return rep.build_report(
        LEDGER,
        ROWS,
        members,
        sessions,
        memories=(20, 100),
        unplaced=unplaced,
        ever_after_holdout=3,
        core_members=2,
    )


def test_counts_by_year_type_tier_and_cold_start():
    report = _report({2020: 0.1})
    y20, y21 = report.years
    assert (y20.year, y20.members, y20.by_type, y20.tier_5m) == (
        2020,
        3,
        {"ADRC": 1, "CS": 1, "ETF": 1},
        1,
    )
    assert (y21.members, y21.tier_5m, y21.unplaced_share) == (3, 0, None)
    assert y20.unplaced_share == 0.1
    assert report.ever_members == 3 and report.core_members == 2 and report.months == 5
    # A longer memory leaves a larger share of member-days cold, and C (entered Mar 2020) is cold
    # for longer than the memory in 2020.
    assert y20.cold_start[100] >= y20.cold_start[20] > 0
    assert 0.0 <= y21.cold_start[20] <= y21.cold_start[100] <= 1.0


def test_render_shows_every_year_and_marks_a_missing_unplaced_share():
    text = rep.render(_report())
    assert "rule " + RULE_ID in text and "core panel 2" in text
    assert "2020" in text and "2021" in text and "n/a" in text


def test_the_module_reads_no_bar_table_and_writes_nothing():
    import inspect

    source = inspect.getsource(rep)
    for forbidden in ("ohlcv", "INSERT", "UPDATE ", "DELETE", "COPY ", "TRUNCATE"):
        assert forbidden not in source.split('"""', 2)[2], forbidden


def test_cold_start_share_is_exact_on_a_hand_computed_membership():
    days = np.arange(np.datetime64("2020-02-03"), np.datetime64("2020-02-29"))
    sessions = days[(days.astype(int) + 3) % 7 < 5]  # Mon to Fri: 20 sessions after the as_of
    ledger = [(D(2020, 1, 31), RULE_ID, 1)]
    rows = [(D(2020, 1, 31), "A", "CS", False)]
    report = rep.build_report(
        ledger,
        rows,
        {D(2020, 1, 31): frozenset({"A"})},
        sessions,
        memories=(3, 10),
        unplaced=None,
        ever_after_holdout=1,
        core_members=1,
    )
    (year,) = report.years
    assert len(sessions) == 20
    assert year.cold_start == {3: 3 / 20, 10: 10 / 20}


def test_memories_are_the_declared_rows_of_the_registered_specs():
    memories = rep._memories()
    assert 525 in memories and 1676 in memories  # M1's and the seasonality members'
    assert all(m > 252 or m in (278, 279, 294) for m in memories)
