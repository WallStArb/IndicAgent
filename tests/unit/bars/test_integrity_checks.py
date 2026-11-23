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


TRADIER = ("tradier", "consolidated")
IBKR_NAMED = ("ibkr", "named")
IBKR_FALLBACK = ("ibkr", "fallback")


def test_policy_conformance_accepts_the_primary_pair():
    d = _days(2)
    assert policy_conformance([(d[0], *TRADIER)], _POLICY, {}, symbol="AAA") == []


def test_policy_conformance_flags_a_contradicting_pair():
    d = _days(2)
    rows = [(d[0], *TRADIER), (d[1], *IBKR_NAMED)]
    assert policy_conformance(rows, _POLICY, {}, symbol="AAA") == [d[1]]


def test_fallback_only_where_tradier_has_no_observation():
    d = _days(2)
    rows = [(d[0], *IBKR_FALLBACK), (d[1], *IBKR_FALLBACK)]
    assert policy_conformance(rows, _POLICY, {"tradier": {d[1]}}, symbol="AAA") == [d[1]]


def test_ibkr_primary_symbol_row_expects_ibkr_named_and_no_fallback_pair():
    d = _days(2)
    rows = [(d[0], *IBKR_NAMED), (d[1], *IBKR_FALLBACK)]
    assert policy_conformance(rows, _IBKR_PRIMARY, {}, symbol="XYZ") == [d[1]]
    assert policy_conformance(rows[:1], _IBKR_PRIMARY, {}, symbol="XYZ") == []


_ALPACA_PRIMARY = [PolicyRow("1d", None, date(2000, 1, 1), None, "observed", "alpaca", "ibkr")]
ALPACA = ("alpaca", "sip_rth")


def test_policy_conformance_accepts_alpaca_under_an_alpaca_primary():
    d = _days(3)
    rows = [(d[0], *ALPACA), (d[1], *IBKR_FALLBACK), (d[2], *TRADIER)]
    # d[1]: Alpaca has no servable answer (absent, zero volume or before its listing).
    assert policy_conformance(rows, _ALPACA_PRIMARY, {"alpaca": {d[0]}}, symbol="AAA") == [d[2]]
    # The fallback where Alpaca could serve contradicts the policy.
    assert policy_conformance(
        rows[:2], _ALPACA_PRIMARY, {"alpaca": {d[0], d[1]}}, symbol="AAA"
    ) == [d[1]]


def test_policy_conformance_takes_an_ibkr_row_as_fallback_inside_the_alpaca_era():
    d = _days(2)
    rows = [
        PolicyRow("1d", None, date(2000, 1, 1), None, "observed", "alpaca", "ibkr"),
        PolicyRow("1d", "AAA", date(2000, 1, 1), None, "observed", "ibkr", None),
    ]
    assert policy_conformance([(d[0], *IBKR_FALLBACK)], rows, {}, symbol="AAA") == []
    assert policy_conformance([(d[1], *IBKR_NAMED)], rows, {}, symbol="AAA") == [d[1]]


def test_policy_conformance_flags_alpaca_under_a_policy_that_does_not_name_it():
    d = _days(1)
    assert policy_conformance([(d[0], *ALPACA)], _POLICY, {}, symbol="AAA") == [d[0]]


_ARCHIVE_END = date(2026, 11, 16)
# The d2-v6 default rows: Massive from 2003-09-10 to the archive end, then Alpaca with no fallback.
_D2V6 = [
    PolicyRow("1d", None, date(2003, 9, 10), _ARCHIVE_END, "observed", "massive", None),
    PolicyRow("1d", None, _ARCHIVE_END, None, "observed", "alpaca", None),
]
MASSIVE = ("massive", "sip_flat_adj")


def test_policy_conformance_under_d2v6_accepts_massive_then_alpaca_and_flags_every_ibkr_pair():
    before, after = _ARCHIVE_END - timedelta(days=3), _ARCHIVE_END + timedelta(days=1)
    good = [(before, *MASSIVE), (_ARCHIVE_END, *ALPACA), (after, *ALPACA)]
    assert policy_conformance(good, _D2V6, {"alpaca": {_ARCHIVE_END, after}}, symbol="AAA") == []
    # Each vendor on the wrong side of the seam contradicts the policy open that day.
    swapped = [(before, *ALPACA), (after, *MASSIVE)]
    assert policy_conformance(swapped, _D2V6, {}, symbol="AAA") == [before, after]
    # No d2-v6 row names IBKR, so no IBKR pair passes on any date, primary served or not.
    for day in (date(2005, 1, 3), before, after):
        ibkr = [(day, *IBKR_NAMED), (day, *IBKR_FALLBACK)]
        assert policy_conformance(ibkr, _D2V6, {}, symbol="AAA") == [day, day]


def test_verdict_is_a_plain_record():
    v = Verdict("AAA", "1d", "session_coverage", True, 1.0, 0.999)
    assert (v.symbol, v.timeframe, v.check, v.passed) == ("AAA", "1d", "session_coverage", True)


# ---------------------------------------------------------------------------
# judge_name_1d: the per-name verdicts, on fakes (todo 494: no live D1)
# ---------------------------------------------------------------------------

import math  # noqa: E402
from dataclasses import dataclass, replace  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from src.intelligence.bars.daily_rule import RULE_VERSION, derive_daily  # noqa: E402
from src.intelligence.bars.derivation import Observation, SplitRecord  # noqa: E402
from src.intelligence.bars.integrity_checks import (  # noqa: E402
    CHECKS_1D,
    NameInputs1d,
    StoredBar,
    judge_name_1d,
    month_digests,
    proven_start,
    request_boundaries,
    split_discontinuities,
    stale_digest_months,
)

_SESSIONS = [date(2024, 1, 2) + timedelta(days=i) for i in range(0, 10) if (i % 7) not in (5, 6)]
_RUN_START = datetime(2024, 2, 1, 6, tzinfo=UTC)
_FETCHED = datetime(2024, 1, 20, tzinfo=UTC)
_ERA = date(2005, 1, 3)


@dataclass(frozen=True)
class _Thresholds:
    session_coverage_min: float = 0.999
    report_max_age_hours: int = 30
    basis_window_sessions: int = 3
    basis_tolerance_bp: float = 10.0
    freshness_max_lag_sessions_1d: int = 2
    split_continuity_rel_tol: float = 0.3


def _obs(day: date, close: float, route: str = "TRADIER") -> Observation:
    return Observation(
        request_id=f"{route}-{day}",
        route=route,
        bar_date=day,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        fetched_at=_FETCHED,
        legacy=False,
    )


def _stored(day: date, close: float, vendor: str = "tradier", kind: str = "consolidated"):
    return StoredBar(
        datetime(day.year, day.month, day.day, tzinfo=UTC),
        close,
        close + 1,
        close - 1,
        close,
        1000.0,
        vendor,
        kind,
    )


def _clean() -> NameInputs1d:
    observations = [_obs(d, 100.0 + i) for i, d in enumerate(_SESSIONS)]
    derived = derive_daily(
        observations,
        _POLICY,
        [],
        symbol="AAA",
        basis_window_sessions=3,
        basis_tolerance_bp=10.0,
    )
    stored = [
        StoredBar(
            datetime(b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC),
            b.open,
            b.high,
            b.low,
            b.close,
            float(b.volume),
            b.vendor,
            b.kind,
        )
        for b in derived.bars
    ]
    return NameInputs1d(
        symbol="AAA",
        observations=observations,
        policy_rows=_POLICY,
        splits=[],
        stored=stored,
        flags=[],
        current_digests={s: (d, RULE_VERSION) for s, d in month_digests(stored, []).items()},
        lineage_missing_dates=[],
        empty_spans=[],
        seam_findings=0,
        latest_load_at=_RUN_START - timedelta(hours=8),
    )


def _judge(inputs: NameInputs1d, timings=None):
    return judge_name_1d(
        inputs, _SESSIONS, _SESSIONS[-1], _RUN_START, _Thresholds(), era_start=_ERA, timings=timings
    )


def _by_check(report) -> dict:
    return {v.check: v for v in report.verdicts}


def test_clean_name_passes_all_checks_in_report_order():
    report = _judge(_clean())
    assert tuple(v.check for v in report.verdicts) == CHECKS_1D
    assert all(v.passed for v in report.verdicts)
    assert {v.symbol for v in report.verdicts} == {"AAA"}
    assert {v.timeframe for v in report.verdicts} == {"1d"}
    assert report.refused_head == 0


def test_timings_record_the_checks_that_do_work():
    timings: dict[str, float] = {}
    _judge(_clean(), timings)
    assert {"canonical_recompute", "digest_fresh", "split_continuity"} <= set(timings)


def test_an_unanswered_last_session_fails_and_an_interior_hole_moves_the_proven_start():
    inputs = _clean()
    # a dropped head is outside the judged range: coverage counts from the first bar
    head = replace(inputs, stored=inputs.stored[1:])
    assert _by_check(_judge(head))["session_coverage"].passed
    # an interior hole is missing depth: the name passes from the first session after it
    interior = replace(inputs, stored=inputs.stored[:2] + inputs.stored[3:])
    report = _judge(interior)
    assert _by_check(report)["session_coverage"].passed
    assert report.proven_start == _SESSIONS[3]
    covered = replace(interior, empty_spans=[(_SESSIONS[2], _SESSIONS[2])])
    assert _judge(covered).proven_start == _SESSIONS[0]
    # a missing latest session leaves no span that passes
    tail = replace(inputs, stored=inputs.stored[:-1])
    verdict = _by_check(_judge(tail))["session_coverage"]
    assert not verdict.passed and verdict.metric_value < 1.0 and _judge(tail).proven_start is None


def _era_report(bar_days: list[date], sessions: list[date], **kw):
    stored = [_stored(d, 100.0) for d in bar_days]
    inputs = replace(_clean(), stored=stored, **kw)
    return judge_name_1d(inputs, sessions, sessions[-1], _RUN_START, _Thresholds(), era_start=_ERA)


def _era_coverage(bar_days: list[date], sessions: list[date], **kw):
    return _by_check(_era_report(bar_days, sessions, **kw))["session_coverage"]


def test_a_missing_session_before_the_era_is_ignored_and_on_the_era_start_moves_the_start():
    # 2004-12-31 is the last session before the era; 2005-01-03 is its first
    pre, start, nxt = date(2004, 12, 31), date(2005, 1, 3), date(2005, 1, 4)
    head = date(2004, 12, 30)
    sessions = [head, pre, start, nxt]
    on_start = _era_report([head, pre, nxt], sessions)  # 2005-01-03 missing: depth, not failure
    assert on_start.proven_start == nxt
    pre_hole = _era_report([head, start, nxt], sessions)  # 2004-12-31 missing: ignored
    assert pre_hole.proven_start == start
    assert _by_check(pre_hole)["session_coverage"].metric_value == 1.0


def test_the_proven_start_is_anchored_inside_the_era_span():
    early = [date(2004, 12, 20) + timedelta(days=i) for i in range(0, 11) if i % 7 not in (1, 2)]
    sessions = early + [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 5), date(2005, 1, 6)]
    bars = early + [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 6)]  # 05 missing
    report = _era_report(bars, sessions)
    assert report.proven_start == date(2005, 1, 6)  # early sessions are outside the era
    assert _by_check(report)["session_coverage"].passed


def test_a_name_whose_first_bar_is_after_the_era_start_counts_from_its_first_bar():
    sessions = [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 5), date(2005, 1, 6)]
    v = _era_coverage([sessions[2], sessions[3]], sessions)
    assert v.passed and v.metric_value == 1.0


def test_empty_history_still_answers_a_session_inside_the_era():
    sessions = [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 5)]
    bars = [sessions[0], sessions[2]]
    assert _era_report(bars, sessions).proven_start == sessions[2]  # the hole is depth
    covered = _era_report(bars, sessions, empty_spans=[(sessions[1], sessions[1])])
    assert covered.proven_start == sessions[0]


def test_proven_start_scans_for_the_earliest_passing_start():
    days = [date(2005, 1, 3) + timedelta(days=i) for i in range(2000)]
    answered = set(days) - {days[10], days[1500]}
    # two holes in 2000 sessions: 1998/2000 = 0.999 passes from the first session
    assert proven_start(days, answered, 0.999) == days[0]
    # at 0.9995 no suffix holding a hole passes, so the start is the session after the last hole
    assert proven_start(days, answered, 0.9995) == days[1501]
    assert proven_start(days, answered - {days[-1]}, 0.999) is None  # latest session unanswered
    assert proven_start([], set(), 0.999) is None


def test_a_proven_start_rests_on_bar_presence_only():
    sessions = [date(2005, 1, 3) + timedelta(days=i) for i in range(5)]
    assert proven_start(sessions, set(sessions[2:]), 1.0) == sessions[2]


def test_a_name_with_early_holes_only_passes():
    pre = [date(2004, 11, 1) + timedelta(days=i) for i in range(5)]
    era = [date(2005, 1, 3), date(2005, 1, 4), date(2005, 1, 5)]
    v = _era_coverage([pre[0], *era], [*pre, *era])  # four early sessions missing
    assert v.passed and v.metric_value == 1.0


def test_a_name_with_no_stored_bar_fails_coverage():
    verdict = _by_check(_judge(replace(_clean(), stored=[])))["session_coverage"]
    assert not verdict.passed and verdict.metric_value == 0.0


def test_a_contradicting_pair_fails_policy_conformance():
    inputs = _clean()
    bad = [replace(inputs.stored[0], vendor="ibkr", kind="named"), *inputs.stored[1:]]
    verdict = _by_check(_judge(replace(inputs, stored=bad)))["policy_conformance"]
    assert not verdict.passed and verdict.metric_value == 1.0


def test_lineage_missing_counts_visible_bars_without_lineage():
    inputs = replace(_clean(), lineage_missing_dates=[_SESSIONS[1], _SESSIONS[2]])
    verdict = _by_check(_judge(inputs))["lineage_missing"]
    assert not verdict.passed and verdict.metric_value == 2.0 and verdict.threshold_value == 0.0


def test_recompute_fails_on_a_changed_extra_or_missing_bar():
    inputs = _clean()
    changed = [replace(inputs.stored[0], close=inputs.stored[0].close + 0.01), *inputs.stored[1:]]
    assert not _by_check(_judge(replace(inputs, stored=changed)))["canonical_recompute"].passed
    extra = [*inputs.stored, _stored(date(2024, 1, 20), 50.0)]
    assert not _by_check(_judge(replace(inputs, stored=extra)))["canonical_recompute"].passed
    missing = _by_check(_judge(replace(inputs, stored=inputs.stored[:-1])))["canonical_recompute"]
    assert not missing.passed and missing.metric_value == 1.0


def test_digest_fresh_fails_on_drift_missing_month_or_old_rule_version():
    inputs = _clean()
    month = next(iter(inputs.current_digests))
    drifted = {**inputs.current_digests, month: ("0" * 64, RULE_VERSION)}
    assert not _by_check(_judge(replace(inputs, current_digests=drifted)))["digest_fresh"].passed
    assert not _by_check(_judge(replace(inputs, current_digests={})))["digest_fresh"].passed
    old = {m: (d, "d2-v1") for m, (d, _) in inputs.current_digests.items()}
    assert not _by_check(_judge(replace(inputs, current_digests=old)))["digest_fresh"].passed


def test_digest_covers_the_quarantine_free_flag_rules_of_each_row():
    inputs = _clean()
    stamp = inputs.stored[0].timestamp
    flagged = month_digests(inputs.stored, [(stamp, "no_provider_volume", False)])
    quarantined = month_digests(inputs.stored, [(stamp, "bad", True)])
    plain = month_digests(inputs.stored, [])
    assert quarantined == plain and flagged != plain
    assert stale_digest_months(plain, {m: (d, RULE_VERSION) for m, d in plain.items()}) == []


def test_seam_findings_become_the_verdict_metric():
    verdict = _by_check(_judge(replace(_clean(), seam_findings=2)))["unexplained_seam"]
    assert not verdict.passed and verdict.metric_value == 2.0


def test_report_age_fails_only_when_a_load_postdates_the_run():
    assert _by_check(_judge(_clean()))["report_age"].metric_value == 8.0
    late = replace(_clean(), latest_load_at=_RUN_START + timedelta(hours=1))
    assert not _by_check(_judge(late))["report_age"].passed
    assert _by_check(_judge(replace(_clean(), latest_load_at=None)))["report_age"].passed


# --- a split after Tradier's last fetch (d2-v3, plan 185-52, todo 517) ---------------------

_SPLIT_RECORDED = _FETCHED + timedelta(days=1)
_IBKR_REFETCH = _FETCHED + timedelta(days=2)


def _restated_inputs() -> NameInputs1d:
    """Tradier old scale (fetched before the split was recorded), IBKR re-fetched on the new
    scale; stored bars are what d2-v3 derives (the restated IBKR fallback)."""
    split = SplitRecord(_SESSIONS[-1] + timedelta(days=30), _SPLIT_RECORDED, 2.0)
    observations = []
    for i, day in enumerate(_SESSIONS):
        base = 100.0 + 0.1 * i
        observations.append(_obs(day, base * 2, "TRADIER"))
        observations.append(replace(_obs(day, base, "SMART"), fetched_at=_IBKR_REFETCH))
    derived = derive_daily(
        observations,
        _POLICY,
        [split],
        symbol="AAA",
        basis_window_sessions=3,
        basis_tolerance_bp=10.0,
    )
    stored = [
        StoredBar(
            datetime(b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC),
            b.open,
            b.high,
            b.low,
            b.close,
            float(b.volume),
            b.vendor,
            b.kind,
        )
        for b in derived.bars
    ]
    return replace(
        _clean(),
        observations=observations,
        splits=[split],
        stored=stored,
        current_digests={s: (d, RULE_VERSION) for s, d in month_digests(stored, []).items()},
    )


def test_a_restated_fallback_name_conforms_and_recomputes():
    inputs = _restated_inputs()
    assert {(b.vendor, b.kind) for b in inputs.stored} == {IBKR_FALLBACK}
    checks = _by_check(_judge(inputs))
    for check in ("policy_conformance", "canonical_recompute", "digest_fresh"):
        assert checks[check].passed, check


# ---------------------------------------------------------------------------
# Intraday checks (plan 185-40 Task 1)
# ---------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from services.bar_reconciliation_audit import completeness_cells, session_slots  # noqa: E402
from src.intelligence.bars.gap_plan import AnsweredWindows  # noqa: E402
from src.intelligence.bars.integrity_checks import (  # noqa: E402
    answered_slots,
    slot_coverage_by_year,
)
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "bars"
_FIVE = timedelta(minutes=5)


def _fixture_stamps(name: str) -> list[datetime]:
    frame = pd.read_csv(_FIXTURES / name)
    return [pd.Timestamp(t).to_pydatetime() for t in frame["timestamp"]]


def _slots(day_from: date, day_to: date) -> tuple[dict, list[datetime]]:
    sessions = nyse_sessions(day_from, day_to)
    start = datetime(day_from.year, day_from.month, day_from.day, tzinfo=UTC)
    end = datetime(day_to.year, day_to.month, day_to.day, tzinfo=UTC) + timedelta(days=1)
    return sessions, session_slots(sessions, 5, start, end)


def _closes(sessions: dict) -> dict:
    return {day: close for day, (_open, close) in sessions.items()}


def test_slot_coverage_counts_the_half_day_session_only():
    sessions, slots = _slots(date(2025, 11, 28), date(2025, 11, 28))
    stamps = _fixture_stamps("spy_5m_2025_11_28_half_day.csv")
    assert len(slots) == 42 == len(stamps)
    done = answered_slots(slots, stamps, AnsweredWindows(), _FIVE, _closes(sessions))
    assert slot_coverage_by_year(slots, done) == {2025: 1.0}


def test_slot_coverage_dst_slots_anchor_at_nine_thirty_new_york_in_both_regimes():
    sessions, slots = _slots(date(2025, 3, 10), date(2025, 11, 3))
    stamps = set(_fixture_stamps("spy_5m_dst_2025_03_10_2025_11_03.csv"))
    opens = {sessions[day][0] for day in (date(2025, 3, 10), date(2025, 11, 3))}
    assert {s for s in slots if s in opens} == {
        datetime(2025, 3, 10, 13, 30, tzinfo=UTC),  # EDT
        datetime(2025, 11, 3, 14, 30, tzinfo=UTC),  # EST
    }
    # the fixture's two days sit on those slots, so every fixture stamp is an expected slot
    assert stamps <= set(slots)


def test_zero_volume_bar_and_answered_empty_window_are_answered_a_missing_slot_is_not():
    sessions, slots = _slots(date(2025, 11, 28), date(2025, 11, 28))
    stamps = _fixture_stamps("spy_5m_2025_11_28_half_day.csv")
    missing = stamps[:3]  # three unanswered slots
    window = (stamps[3], stamps[3] + 2 * _FIVE)  # answered no_data over two slots
    kept = stamps[5:]  # zero-volume provider bars are passed in as stored slots like any real bar
    done = answered_slots(
        slots, kept, AnsweredWindows.from_rows([window]), _FIVE, _closes(sessions)
    )
    assert all(s not in done for s in missing)
    assert stamps[3] in done and stamps[4] in done
    coverage = slot_coverage_by_year(slots, done)[2025]
    assert coverage == pytest.approx(39 / 42)


def test_answered_slot_outside_the_expected_set_does_not_inflate_a_year():
    sessions, slots = _slots(date(2025, 11, 28), date(2025, 11, 28))
    stray = datetime(2025, 11, 28, 22, 0, tzinfo=UTC)
    assert slot_coverage_by_year(slots[:2], {slots[0], stray}) == {2025: 0.5}


def test_slot_coverage_is_split_per_calendar_year():
    slots = [datetime(2024, 12, 31, 15, tzinfo=UTC), datetime(2025, 1, 2, 15, tzinfo=UTC)]
    assert slot_coverage_by_year(slots, {slots[1]}) == {2024: 0.0, 2025: 1.0}


def test_slot_coverage_equals_the_completeness_cells_quantity_on_the_same_inputs():
    sessions, slots = _slots(date(2025, 11, 26), date(2025, 11, 28))
    stored = slots[::2]
    window = AnsweredWindows.from_rows([(slots[3], slots[5])])
    cells = completeness_cells("SPY", "5m", slots, stored, window, _FIVE, sessions)
    done = answered_slots(slots, stored, window, _FIVE, _closes(sessions))
    assert slot_coverage_by_year(slots, done)[2025] == pytest.approx(cells[0].share)


def _load(day: int, first: date | None, last: date | None):
    return (datetime(2026, 10, day, tzinfo=UTC), first, last)


_PREV = datetime(2026, 10, 3, 6, tzinfo=UTC)


def test_digest_scope_is_every_month_on_a_full_sweep_first_run_or_a_previous_failure():
    from src.intelligence.bars.integrity_checks import digest_scope

    for kwargs in (
        {"full_sweep": True, "previous_at": _PREV, "previous_passed": True},
        {"full_sweep": False, "previous_at": None, "previous_passed": None},
        {"full_sweep": False, "previous_at": _PREV, "previous_passed": False},
    ):
        assert digest_scope(loads=[], **kwargs) is None


def test_digest_scope_is_the_months_of_loads_written_since_the_previous_report():
    from src.intelligence.bars.integrity_checks import digest_scope

    scope = digest_scope(
        full_sweep=False,
        previous_at=_PREV,
        previous_passed=True,
        loads=[
            _load(2, date(2020, 1, 1), date(2020, 3, 1)),  # before the report: ignored
            _load(5, date(2025, 12, 20), date(2026, 2, 3)),
        ],
    )
    assert scope == frozenset(
        datetime(y, m, 1, tzinfo=UTC) for y, m in ((2025, 12), (2026, 1), (2026, 2))
    )


def test_digest_scope_is_empty_when_nothing_was_written_and_all_when_a_load_has_no_span():
    from src.intelligence.bars.integrity_checks import digest_scope

    base = {"full_sweep": False, "previous_at": _PREV, "previous_passed": True}
    assert digest_scope(loads=[], **base) == frozenset()
    assert digest_scope(loads=[_load(5, None, None)], **base) is None


# ---------------------------------------------------------------------------
# freshness_1d (plan 185-46 Task 3)
# ---------------------------------------------------------------------------

from src.intelligence.bars.integrity_checks import CHECK_FRESHNESS_1D, freshness_1d  # noqa: E402

# Mon 2026-09-28 .. Fri 2026-10-09, NYSE sessions only
_FRESH_SESSIONS = [
    date(2026, 9, 28) + timedelta(days=i) for i in range(12) if (i % 7) not in (5, 6)
]


def _fresh(latest, last, *, spans=(), max_lag=2):
    return freshness_1d(latest, list(spans), last, _FRESH_SESSIONS, max_lag, symbol="AAA")


def test_freshness_passes_on_the_last_completed_session():
    v = _fresh(date(2026, 10, 7), date(2026, 10, 7))
    assert v.check == CHECK_FRESHNESS_1D == "freshness_1d"
    assert (v.symbol, v.timeframe, v.passed, v.metric_value, v.threshold_value) == (
        "AAA",
        "1d",
        True,
        0.0,
        2.0,
    )


def test_freshness_counts_uncovered_sessions_and_passes_up_to_max_lag():
    assert _fresh(date(2026, 10, 5), date(2026, 10, 7)).metric_value == 2.0
    assert _fresh(date(2026, 10, 5), date(2026, 10, 7)).passed
    v = _fresh(date(2026, 10, 2), date(2026, 10, 7))  # Mon, Tue, Wed behind (weekend skipped)
    assert (v.passed, v.metric_value) == (False, 3.0)


def test_freshness_sessions_inside_answered_empty_spans_do_not_count():
    v = _fresh(date(2026, 10, 1), date(2026, 10, 7), spans=[(date(2026, 10, 2), date(2026, 10, 8))])
    assert (v.passed, v.metric_value) == (True, 0.0)
    # Fri and Mon covered; Tue and Wed are not: 2 behind, at the limit
    v = _fresh(date(2026, 10, 1), date(2026, 10, 7), spans=[(date(2026, 10, 2), date(2026, 10, 5))])
    assert (v.passed, v.metric_value) == (True, 2.0)


def test_freshness_a_friday_bar_on_the_weekend_is_not_behind():
    for judged_on in (date(2026, 10, 10), date(2026, 10, 11)):  # Saturday, Sunday
        v = _fresh(date(2026, 10, 9), judged_on, max_lag=0)
        assert (v.passed, v.metric_value) == (True, 0.0)


def test_freshness_a_name_with_no_bars_fails():
    v = _fresh(None, date(2026, 10, 7))
    assert not v.passed
    assert v.metric_value == float(sum(1 for s in _FRESH_SESSIONS if s <= date(2026, 10, 7)))


def test_freshness_counts_no_session_after_a_listing_end():
    """Todo 519: an ended name (merger, buyout) is judged against its recorded last session."""
    v = freshness_1d(
        date(2026, 10, 2),
        [],
        date(2026, 10, 9),
        _FRESH_SESSIONS,
        0,
        symbol="QRVO",
        listing_end=date(2026, 10, 2),
    )
    assert (v.passed, v.metric_value) == (True, 0.0)
    # bars stopping before the recorded last session still count the gap up to it
    v = freshness_1d(
        date(2026, 9, 30),
        [],
        date(2026, 10, 9),
        _FRESH_SESSIONS,
        0,
        symbol="QRVO",
        listing_end=date(2026, 10, 2),
    )
    assert (v.passed, v.metric_value) == (False, 2.0)


def test_judge_name_1d_passes_the_listing_end_to_freshness_and_session_coverage():
    clean = _clean()
    last_bar = max(b.timestamp for b in clean.stored[:3]).date()
    stopped = replace(clean, stored=list(clean.stored[:3]))
    by = _by_check(_judge(stopped))
    assert not by[CHECK_FRESHNESS_1D].passed and not by["session_coverage"].passed
    ended = replace(stopped, listing_end=last_bar)
    by = _by_check(_judge(ended))
    assert by[CHECK_FRESHNESS_1D].passed and by["session_coverage"].passed


def test_judge_name_1d_reports_freshness_after_the_eight_checks():
    report = _judge(_clean())
    by = _by_check(report)
    assert by[CHECK_FRESHNESS_1D].passed and by[CHECK_FRESHNESS_1D].metric_value == 0.0
    extra = [_SESSIONS[-1] + timedelta(days=k) for k in (1, 2, 3)]
    stale = judge_name_1d(
        _clean(), _SESSIONS + extra, extra[-1], _RUN_START, _Thresholds(), era_start=_ERA
    )
    verdict = _by_check(stale)[CHECK_FRESHNESS_1D]
    assert (verdict.passed, verdict.metric_value, verdict.threshold_value) == (False, 3.0, 2.0)


def _alpaca_inputs(dead: date | None = None) -> NameInputs1d:
    """An Alpaca-primary name (D-191-Q): Alpaca and IBKR agree on every session; `dead` is an
    Alpaca zero-volume placeholder session that the IBKR fallback serves."""
    observations = []
    for i, day in enumerate(_SESSIONS):
        close = 100.0 + 0.1 * i
        observations.append(_obs(day, close, "SMART"))
        alpaca = _obs(day, close, "ALPACA")
        observations.append(replace(alpaca, volume=0) if day == dead else alpaca)
    derived = derive_daily(
        observations,
        _ALPACA_PRIMARY,
        [],
        symbol="AAA",
        basis_window_sessions=3,
        basis_tolerance_bp=10.0,
    )
    stored = [
        StoredBar(
            datetime(b.bar_date.year, b.bar_date.month, b.bar_date.day, tzinfo=UTC),
            b.open,
            b.high,
            b.low,
            b.close,
            float(b.volume),
            b.vendor,
            b.kind,
        )
        for b in derived.bars
    ]
    return replace(
        _clean(),
        observations=observations,
        policy_rows=_ALPACA_PRIMARY,
        stored=stored,
        current_digests={s: (d, RULE_VERSION) for s, d in month_digests(stored, []).items()},
    )


def test_an_alpaca_primary_name_conforms_and_recomputes():
    inputs = _alpaca_inputs(dead=_SESSIONS[4])
    pairs = {b.timestamp.date(): (b.vendor, b.kind) for b in inputs.stored}
    assert pairs[_SESSIONS[4]] == IBKR_FALLBACK
    assert {p for d, p in pairs.items() if d != _SESSIONS[4]} == {ALPACA}
    checks = _by_check(_judge(inputs))
    for check in ("policy_conformance", "canonical_recompute", "digest_fresh"):
        assert checks[check].passed, check


def test_an_ibkr_fallback_where_alpaca_could_serve_fails_conformance():
    inputs = _alpaca_inputs()
    first = inputs.stored[0]
    bad = [replace(first, vendor="ibkr", kind="fallback"), *inputs.stored[1:]]
    assert not _by_check(_judge(replace(inputs, stored=bad)))["policy_conformance"].passed


# --- todo 587: split_continuity ----------------------------------------------------------


def _closes_stored(closes):
    return [
        StoredBar(datetime(d.year, d.month, d.day, tzinfo=UTC), c, c, c, c, 1000.0, "ibkr", "named")
        for d, c in closes
    ]


def _split(day, factor):
    return SplitRecord(
        effective_date=day, recorded_at=datetime(2026, 11, 4, tzinfo=UTC), factor=factor
    )


def test_split_continuity_names_an_unadjusted_and_a_double_adjusted_split():
    d = [date(2010, 6, 10), date(2010, 6, 11), date(2010, 6, 14), date(2010, 6, 15)]
    # effective_date is the last day on the old scale (2010-06-11); the step lands on 06-14.
    unadjusted = _closes_stored([(d[0], 100.0), (d[1], 100.0), (d[2], 50.0), (d[3], 50.0)])
    assert split_discontinuities(unadjusted, [_split(d[1], 2.0)], 0.3) == [(d[1], "unadjusted")]
    doubled = _closes_stored([(d[0], 25.0), (d[1], 25.0), (d[2], 50.0), (d[3], 50.0)])
    assert split_discontinuities(doubled, [_split(d[1], 2.0)], 0.3) == [(d[1], "double_adjusted")]
    adjusted = _closes_stored([(d[0], 50.0), (d[1], 50.5), (d[2], 50.0), (d[3], 51.0)])
    assert split_discontinuities(adjusted, [_split(d[1], 2.0)], 0.3) == []


def test_a_split_outside_the_stored_span_is_not_judged():
    stored = _closes_stored([(date(2012, 1, 3), 10.0), (date(2012, 1, 4), 10.0)])
    assert split_discontinuities(stored, [_split(date(2010, 6, 11), 2.0)], 0.3) == []


def test_split_continuity_never_measures_across_a_hole_or_an_untradeable_bar():
    d = [date(2010, 6, 10), date(2010, 6, 11), date(2010, 9, 14)]
    across_hole = _closes_stored([(d[0], 100.0), (d[1], 100.0), (d[2], 50.0)])
    assert split_discontinuities(across_hole, [_split(d[1], 2.0)], 0.3) == []
    e = [date(2010, 6, 10), date(2010, 6, 11), date(2010, 6, 14), date(2010, 6, 15)]
    stored = _closes_stored([(e[0], 50.0), (e[1], 50.0), (e[2], 100.0), (e[3], 50.0)])
    # A quarantined old-scale print on 06-14 is not what research reads.
    assert split_discontinuities(stored, [_split(e[1], 2.0)], 0.3, quarantined={e[2]}) == []


def _routed(rows):
    return [
        StoredBar(datetime(d.year, d.month, d.day, tzinfo=UTC), c, c, c, c, 1000.0, v, k)
        for d, c, v, k in rows
    ]


def _rescale(day, factor, routes=frozenset({"SMART", "LEGACY_IMPORT", "ALPACA"})):
    return SplitRecord(day, datetime(2026, 11, 4, tzinfo=UTC), factor, (), routes)


# IBKR serves through 2015, Alpaca from 2016-01-04; a 2:1 calendar split on 2016-01-06 rescaled
# both series. Then IBKR restates its history on the new scale (last-wins raw): the rule divides
# the restated IBKR span a second time while Alpaca is right.
_SEAM = [date(2015, 12, 30), date(2015, 12, 31), date(2016, 1, 4), date(2016, 1, 5)]
_SEAM_AFTER = [date(2016, 1, 6), date(2016, 1, 7)]


def test_a_partial_restatement_is_caught_at_the_route_seam_not_only_at_the_split_date():
    rows = [
        (_SEAM[0], 25.0, "ibkr", "named"),
        (_SEAM[1], 25.0, "ibkr", "named"),
        (_SEAM[2], 50.0, "alpaca", "sip_rth"),
        (_SEAM[3], 50.0, "alpaca", "sip_rth"),
        (_SEAM_AFTER[0], 50.0, "alpaca", "sip_rth"),
        (_SEAM_AFTER[1], 50.5, "alpaca", "sip_rth"),
    ]
    split = _rescale(_SEAM[3], 2.0)
    assert split_discontinuities(_routed(rows), [split], 0.3) == [(_SEAM[1], "double_adjusted")]
    healthy = [(d, 50.0 if c == 25.0 else c, v, k) for d, c, v, k in rows]
    assert split_discontinuities(_routed(healthy), [split], 0.3) == []


def test_a_seam_step_of_a_partial_product_of_the_splits_fails_by_name():
    """Two later splits (2:1 then 3:2): a seam broken by 3.0 (both) or by 1.5 (the later one
    alone) is a scale the splits explain; the seam before the first split judges both runs."""
    rows = [
        (_SEAM[0], 75.0, "ibkr", "named"),
        (_SEAM[1], 75.0, "ibkr", "named"),
        (_SEAM[2], 50.0, "alpaca", "sip_rth"),
        (_SEAM[3], 50.0, "alpaca", "sip_rth"),
    ]
    splits = [_rescale(date(2016, 3, 1), 2.0), _rescale(date(2017, 3, 1), 1.5)]
    assert split_discontinuities(_routed(rows), splits, 0.3) == [(_SEAM[1], "unadjusted")]
    tripled = [(d, 150.0 if c == 75.0 else c, v, k) for d, c, v, k in rows]
    assert split_discontinuities(_routed(tripled), splits, 0.3) == [(_SEAM[1], "unadjusted")]


def test_seams_are_judged_only_for_a_name_with_a_calendar_rescale():
    rows = [
        (_SEAM[0], 25.0, "ibkr", "named"),
        (_SEAM[1], 25.0, "ibkr", "named"),
        (_SEAM[2], 50.0, "alpaca", "sip_rth"),
        (_SEAM[3], 50.0, "alpaca", "sip_rth"),
    ]
    stale_semantics = SplitRecord(date(2016, 3, 1), datetime(2026, 11, 4, tzinfo=UTC), 2.0)
    assert split_discontinuities(_routed(rows), [stale_semantics], 0.3) == []


def test_a_split_on_a_spin_off_day_is_judged_against_the_calendars_real_move():
    """EXPE 2011-12-21 (review 2026-11-05): a 1-for-2 reverse split on the TripAdvisor spin-off
    day. Raw is continuous (+0.038), the calendar's adjusted close drops 0.717, so after the
    rescale canonical drops 0.656: a real move, not a double adjustment."""
    d = [date(2011, 12, 19), date(2011, 12, 20), date(2011, 12, 21), date(2011, 12, 22)]
    before, after = 100.0, 100.0 * math.exp(-0.656)
    stored = _closes_stored([(d[0], before), (d[1], before), (d[2], after), (d[3], after)])
    split = SplitRecord(
        d[1], datetime(2026, 11, 4, tzinfo=UTC), 0.5, (), frozenset({"SMART"}), -0.716536
    )
    assert split_discontinuities(stored, [split], 0.3) == []
    no_move = replace(split, calendar_adjusted_step=0.0)
    assert split_discontinuities(stored, [no_move], 0.3) == [(d[1], "double_adjusted")]


def test_a_market_route_split_is_judged_against_its_recorded_real_move():
    """HON 2026-06-26 (todo 633): a 1-for-2 reverse split after the Aerospace separation. Canonical
    drops 0.7123 (the separation), about the split's own ratio, so unless the row's recorded real
    move is netted out it reads as a double adjustment."""
    d = [date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 29), date(2026, 6, 30)]
    stored = _closes_stored([(d[0], 462.48), (d[1], 464.42), (d[2], 227.8), (d[3], 223.9)])
    split = SplitRecord(
        d[1],
        datetime(2026, 11, 17, tzinfo=UTC),
        0.5,
        calendar_adjusted_step=-0.7123,
        market_fact=True,
    )
    assert split_discontinuities(stored, [split], 0.3) == []
    no_move = replace(split, calendar_adjusted_step=0.0)
    assert split_discontinuities(stored, [no_move], 0.3) == [(d[1], "double_adjusted")]


def test_a_sub_window_restated_inside_a_rescaled_span_fails_at_its_request_boundary():
    """IBKR restates 2010-03 on the new scale (a later request, last-wins raw); the rule divides
    that window by the 2:1 factor a second time. Canonical is ibkr/named throughout, so no seam;
    the request boundaries name the break."""
    days = [date(2010, 3, 1) + timedelta(days=i) for i in range(12)]
    days = [d for d in days if d.weekday() < 5]
    restated = set(days[3:6])
    closes = [(d, 25.0 if d in restated else 50.0) for d in days]
    stored = _closes_stored(closes)
    split = _rescale(date(2011, 6, 1), 2.0, frozenset({"SMART", "LEGACY_IMPORT"}))
    observations = [
        replace(_obs(d, c, "SMART"), request_id="late" if d in restated else "early")
        for d, c in closes
    ]
    boundaries = request_boundaries(observations, [split])
    assert boundaries == {days[2], days[5]}
    assert split_discontinuities(stored, [split], 0.3) == []  # no seam, no split date in range
    found = split_discontinuities(stored, [split], 0.3, boundaries=boundaries)
    assert [day for day, _ in found] == [days[2], days[5]]


# ---------------------------------------------------------------------------
# grid_recompute_findings: stored 15m/1h rows against the derivation of current 5m
# ---------------------------------------------------------------------------

from src.intelligence.bars.integrity_checks import grid_recompute_findings  # noqa: E402
from src.intelligence.bars.write_contract import BarValues  # noqa: E402


def _grid(*stamps: datetime) -> dict[datetime, BarValues]:
    return {
        stamp: BarValues(10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i, 100 * (i + 1), "derived", "5m_grid")
        for i, stamp in enumerate(stamps)
    }


def test_grid_recompute_flags_a_changed_extra_or_missing_bucket():
    t0, t1, t2 = (datetime(2026, 6, 2, h, 30, tzinfo=UTC) for h in (13, 14, 15))
    derived = _grid(t0, t1)
    assert grid_recompute_findings(derived, dict(derived)) == []
    changed = {**derived, t1: derived[t1]._replace(close=derived[t1].close + 0.01)}
    assert grid_recompute_findings(derived, changed) == [t1]
    extra = {**derived, t2: _grid(t0, t1, t2)[t2]}
    assert grid_recompute_findings(derived, extra) == [t2]
    missing = {t0: derived[t0]}
    assert grid_recompute_findings(derived, missing) == [t1]
    # An identity-only difference (a vendor row where the grid belongs) is a finding too.
    vendor = {**derived, t0: derived[t0]._replace(vendor="massive", kind="sip_flat_adj")}
    assert grid_recompute_findings(derived, vendor) == [t0]
