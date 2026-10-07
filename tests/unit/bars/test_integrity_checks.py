"""Pure integrity-check arithmetic (plan 185-33 Task 1)."""

from __future__ import annotations

from datetime import date, timedelta

from src.intelligence.bars.daily_rule import PolicyRow
from src.intelligence.bars.integrity_checks import Verdict, policy_conformance, session_coverage

_D = date(2024, 1, 1)
_POLICY = [PolicyRow("1d", None, date(2000, 1, 1), None, "observed", "tradier", "ibkr")]
_IBKR_PRIMARY = [
    PolicyRow("1d", None, date(2000, 1, 1), None, "observed", "tradier", "ibkr"),
    PolicyRow("1d", "XYZ", date(2000, 1, 1), None, "observed", "ibkr", None),
]


def _days(n: int) -> list[date]:
    return [_D + timedelta(days=i) for i in range(n)]


def test_full_series_is_fully_covered():
    days = _days(10)
    assert session_coverage(days, [], days) == 1.0


def test_answered_empty_sessions_count_as_covered():
    days = _days(10)
    assert session_coverage(days[:8], days[8:], days) == 1.0
    assert session_coverage(days[:8], [], days) == 0.8


def test_dates_outside_the_sessions_do_not_inflate_coverage():
    days = _days(4)
    assert session_coverage(days[:2] + [_D + timedelta(days=99)], [], days) == 0.5


def test_no_sessions_is_vacuously_covered():
    assert session_coverage([], [], []) == 1.0


def test_policy_conformance_accepts_the_primary_label():
    d = _days(2)
    assert policy_conformance([(d[0], "tradier")], _POLICY, set(), symbol="AAA") == []


def test_policy_conformance_flags_a_contradicting_source():
    d = _days(2)
    rows = [(d[0], "tradier"), (d[1], "ibkr_named")]
    assert policy_conformance(rows, _POLICY, set(), symbol="AAA") == [d[1]]


def test_fallback_only_where_tradier_has_no_observation():
    d = _days(2)
    rows = [(d[0], "ibkr_fallback"), (d[1], "ibkr_fallback")]
    assert policy_conformance(rows, _POLICY, {d[1]}, symbol="AAA") == [d[1]]


def test_ibkr_primary_symbol_row_expects_ibkr_named_and_no_fallback_label():
    d = _days(2)
    rows = [(d[0], "ibkr_named"), (d[1], "ibkr_fallback")]
    assert policy_conformance(rows, _IBKR_PRIMARY, set(), symbol="XYZ") == [d[1]]
    assert policy_conformance(rows[:1], _IBKR_PRIMARY, set(), symbol="XYZ") == []


def test_verdict_is_a_plain_record():
    v = Verdict("AAA", "1d", "session_coverage", True, 1.0, 0.999)
    assert (v.symbol, v.timeframe, v.check, v.passed) == ("AAA", "1d", "session_coverage", True)
