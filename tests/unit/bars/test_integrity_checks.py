"""Pure integrity-check arithmetic (plan 185-33 Task 1)."""

from __future__ import annotations

from datetime import date, timedelta

from src.intelligence.bars.daily_rule import PolicyRow
from src.intelligence.bars.integrity_checks import (
    Verdict,
    answered_window_spans,
    policy_conformance,
    session_coverage,
)

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


def test_verdict_is_a_plain_record():
    v = Verdict("AAA", "1d", "session_coverage", True, 1.0, 0.999)
    assert (v.symbol, v.timeframe, v.check, v.passed) == ("AAA", "1d", "session_coverage", True)


# ---------------------------------------------------------------------------
# judge_name_1d: the per-name verdicts, on fakes (todo 494: no live D1)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, replace  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from src.intelligence.bars.daily_rule import RULE_VERSION, derive_daily_v2  # noqa: E402
from src.intelligence.bars.derivation import Observation, SplitRecord  # noqa: E402
from src.intelligence.bars.integrity_checks import (  # noqa: E402
    CHECKS_1D,
    NameInputs1d,
    StoredBar,
    judge_name_1d,
    month_digests,
    stale_digest_months,
)

_SESSIONS = [date(2024, 1, 2) + timedelta(days=i) for i in range(0, 10) if (i % 7) not in (5, 6)]
_RUN_START = datetime(2024, 2, 1, 6, tzinfo=UTC)
_FETCHED = datetime(2024, 1, 20, tzinfo=UTC)


@dataclass(frozen=True)
class _Thresholds:
    session_coverage_min: float = 0.999
    vendor_run_min_sessions: int = 3
    report_max_age_hours: int = 30
    basis_window_sessions: int = 3
    basis_tolerance_bp: float = 10.0
    freshness_max_lag_sessions_1d: int = 2


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
    derived = derive_daily_v2(
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
        answered_windows=[],
        seam_findings=0,
        latest_load_at=_RUN_START - timedelta(hours=8),
    )


def _judge(inputs: NameInputs1d, timings=None):
    return judge_name_1d(
        inputs, _SESSIONS, _SESSIONS[-1], _RUN_START, _Thresholds(), timings=timings
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
    assert {"canonical_recompute", "digest_fresh", "alpaca_basis_run"} <= set(timings)


def test_a_missing_session_fails_coverage_unless_answered_empty():
    inputs = _clean()
    # a dropped head is outside the judged range: coverage counts from the first bar
    head = replace(inputs, stored=inputs.stored[1:])
    assert _by_check(_judge(head))["session_coverage"].passed
    interior = replace(inputs, stored=inputs.stored[:2] + inputs.stored[3:])
    verdict = _by_check(_judge(interior))["session_coverage"]
    assert not verdict.passed and verdict.metric_value < 1.0
    covered = replace(interior, empty_spans=[(_SESSIONS[2], _SESSIONS[2])])
    assert _by_check(_judge(covered))["session_coverage"].passed


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
    derived = derive_daily_v2(
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
    for check in ("policy_conformance", "canonical_recompute", "digest_fresh", "alpaca_basis_run"):
        assert checks[check].passed, check


# ---------------------------------------------------------------------------
# Intraday checks (plan 185-40 Task 1)
# ---------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from services.bar_reconciliation_audit import completeness_cells, session_slots  # noqa: E402
from src.intelligence.bars.gap_plan import AnsweredWindows  # noqa: E402
from src.intelligence.bars.integrity_checks import (  # noqa: E402
    answered_slots,
    grid_parity,
    rebucket_5m,
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


_T0 = datetime(2025, 6, 2, 13, 30, tzinfo=UTC)
_BAR = (1.0, 2.0, 0.5, 1.5, 100.0)


def test_grid_parity_identical_buckets_have_no_mismatch():
    derived = {_T0: _BAR, _T0 + timedelta(minutes=15): _BAR}
    assert grid_parity(derived, dict(derived), timeframe="15m") == (2, 0)


def test_grid_parity_one_differing_volume_is_one_mismatch():
    derived = {_T0: _BAR, _T0 + timedelta(minutes=15): _BAR}
    archived = {_T0: _BAR, _T0 + timedelta(minutes=15): (1.0, 2.0, 0.5, 1.5, 101.0)}
    assert grid_parity(derived, archived, timeframe="15m") == (2, 1)


def test_grid_parity_1h_compares_only_the_shared_keys():
    derived = {_T0: _BAR, _T0 + timedelta(minutes=30): _BAR}
    archived = {_T0 + timedelta(minutes=30): _BAR}  # vendor grid lacks the 09:30 half hour
    assert grid_parity(derived, archived, timeframe="1h") == (1, 0)


def test_grid_parity_rejects_a_timeframe_it_does_not_define():
    with pytest.raises(ValueError):
        grid_parity({}, {}, timeframe="5m")


def _five_minute_bars(first: datetime, n: int) -> tuple[np.ndarray, ...]:
    ts = np.array([int(first.timestamp()) + 300 * i for i in range(n)], dtype=np.int64)
    base = np.arange(n, dtype=np.float64)
    return ts, base + 10, base + 12, base + 9, base + 11, np.full(n, 10.0)


def test_rebucket_1h_follows_the_archive_clock_hour_edges_not_the_derived_edges():
    # 14:30 UTC (09:30 EDT) for two hours of 5m bars: the archive's keys are 14:30 (half hour),
    # 15:00, 16:00
    ts, o, h, lo, c, v = _five_minute_bars(datetime(2025, 6, 2, 13, 30, tzinfo=UTC), 24)
    starts = [
        int(datetime(2025, 6, 2, hour, minute, tzinfo=UTC).timestamp())
        for hour, minute in ((13, 30), (14, 0))
    ]
    out = rebucket_5m(ts, o, h, lo, c, v, starts, timeframe="1h")
    half_hour = out[starts[0]]
    assert half_hour == (10.0, 12 + 5, 9.0, 16.0, 60.0)  # six bars: 13:30..13:55
    full_hour = out[starts[1]]
    assert full_hour == (16.0, 12 + 17, 15.0, 28.0, 120.0)  # twelve bars: 14:00..14:55


def test_rebucket_drops_a_bucket_missing_a_constituent():
    ts, o, h, lo, c, v = _five_minute_bars(datetime(2025, 6, 2, 13, 30, tzinfo=UTC), 3)
    keep = np.array([True, False, True])
    start = int(datetime(2025, 6, 2, 13, 30, tzinfo=UTC).timestamp())
    assert (
        rebucket_5m(
            ts[keep], o[keep], h[keep], lo[keep], c[keep], v[keep], [start], timeframe="15m"
        )
        == {}
    )
    assert start in rebucket_5m(ts, o, h, lo, c, v, [start], timeframe="15m")


def test_rebucket_of_no_bars_is_empty():
    empty = np.array([], dtype=np.float64)
    assert (
        rebucket_5m(
            np.array([], dtype=np.int64), empty, empty, empty, empty, empty, [0], timeframe="15m"
        )
        == {}
    )


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


def test_judge_name_1d_passes_the_listing_end_to_freshness():
    clean = _clean()
    last_bar = max(b.timestamp for b in clean.stored[:3]).date()
    stopped = replace(clean, stored=list(clean.stored[:3]))
    assert not _by_check(_judge(stopped))[CHECK_FRESHNESS_1D].passed
    ended = replace(stopped, listing_end=last_bar)
    assert _by_check(_judge(ended))[CHECK_FRESHNESS_1D].passed


def test_judge_name_1d_reports_freshness_after_the_eight_checks():
    report = _judge(_clean())
    by = _by_check(report)
    assert by[CHECK_FRESHNESS_1D].passed and by[CHECK_FRESHNESS_1D].metric_value == 0.0
    extra = [_SESSIONS[-1] + timedelta(days=k) for k in (1, 2, 3)]
    stale = judge_name_1d(_clean(), _SESSIONS + extra, extra[-1], _RUN_START, _Thresholds())
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
    derived = derive_daily_v2(
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


# --- alpaca_basis_run: Alpaca against IBKR, successor of the retired Tradier check (todo 545 step 5a) ---

from src.intelligence.bars.integrity_checks import alpaca_basis_runs  # noqa: E402
from src.intelligence.bars.vendor_arbitration import ARBITRATED_THROUGH  # noqa: E402

_D191Q = [
    PolicyRow("1d", None, date(2000, 1, 1), date(2016, 1, 4), "observed", "ibkr", None),
    PolicyRow("1d", None, date(2016, 1, 4), None, "observed", "alpaca", "ibkr"),
]


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _pair_obs(days, ibkr_close, alpaca_close, *, alpaca_volume=1000):
    return [replace(_obs(d, ibkr_close(d), "SMART"), volume=1000) for d in days] + [
        replace(_obs(d, alpaca_close(d), "ALPACA"), volume=alpaca_volume) for d in days
    ]


def _runs(observations, policy=_D191Q, splits=(), min_sessions=5):
    return alpaca_basis_runs(
        observations,
        list(splits),
        policy,
        symbol="AAA",
        since=ARBITRATED_THROUGH,
        tolerance_bp=10.0,
        min_sessions=min_sessions,
    )


_AFTER = _weekdays(date(2026, 10, 7), 30)
_SPIN = _AFTER[20]


def _spin_obs():
    # a spin-off after the arbitration: IBKR adjusts the pre-spin history, Alpaca does not
    return _pair_obs(
        _AFTER,
        lambda d: 52.0 if d < _SPIN else 49.0,
        lambda d: 68.8 if d < _SPIN else 49.0,
    )


def test_a_disagreement_run_after_the_arbitration_is_reported():
    (run,) = _runs(_spin_obs())
    assert (run.start, run.end, run.n_sessions) == (_AFTER[0], _AFTER[19], 20)


def test_a_run_inside_the_arbitrated_span_is_not_judged_again():
    days = _weekdays(date(2026, 8, 3), 30)
    assert _runs(_pair_obs(days, lambda d: 52.0, lambda d: 68.8)) == []


def test_a_run_shorter_than_the_minimum_is_noise():
    obs = _pair_obs(_AFTER, lambda d: 50.0, lambda d: 51.0 if d in _AFTER[3:6] else 50.0)
    assert _runs(obs) == []


def test_an_ibkr_symbol_row_over_the_run_explains_it():
    row = PolicyRow("1d", "AAA", _AFTER[0], _SPIN, "observed", "ibkr", None)
    assert _runs(_spin_obs(), policy=[*_D191Q, row]) == []


def test_a_recorded_corporate_action_ending_the_run_explains_it():
    action = SplitRecord(_SPIN, datetime(2026, 11, 20, tzinfo=UTC), 1.404)
    assert _runs(_spin_obs(), splits=[action]) == []


def test_zero_volume_alpaca_bars_are_no_disagreement():
    obs = _pair_obs(_AFTER, lambda d: 50.0, lambda d: 60.0, alpaca_volume=0)
    assert _runs(obs) == []


def test_judge_reports_alpaca_basis_run_and_fails_an_unexplained_run():
    assert "alpaca_basis_run" in CHECKS_1D
    clean = _by_check(_judge(_clean()))
    assert clean["alpaca_basis_run"].passed and clean["alpaca_basis_run"].metric_value == 0
    report = judge_name_1d(
        replace(_clean(), observations=_spin_obs(), policy_rows=_D191Q),
        _SESSIONS,
        _SESSIONS[-1],
        _RUN_START,
        _Thresholds(),
    )
    verdict = _by_check(report)["alpaca_basis_run"]
    assert not verdict.passed and verdict.metric_value == 1
    assert [(r.start, r.end) for r in report.alpaca_runs] == [(_AFTER[0], _AFTER[19])]


# ---------------------------------------------------------------------------
# Sessions a successful canonical-vendor 1d request answers (the 1d analogue of todo 565)
# ---------------------------------------------------------------------------

_JAN = [date(2024, 1, day) for day in range(1, 32)]


def _bars(days, route="SMART"):
    return [_obs(day, 100.0, route) for day in days]


def _midnight(day):
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def test_a_missing_day_inside_a_window_with_bars_either_side_is_answered():
    bars = _bars([_JAN[1], _JAN[2], _JAN[4], _JAN[5]])  # the 4th has no bar
    window = ("ibkr", _midnight(_JAN[0]), _midnight(_JAN[9]))
    assert answered_window_spans([window], bars) == [(_JAN[1], _JAN[5])]


def test_a_window_with_none_of_the_vendors_bars_answers_nothing():
    window = ("ibkr", _midnight(_JAN[0]), _midnight(_JAN[9]))
    assert answered_window_spans([window], []) == []
    # another vendor's bars, and the same vendor's bars outside the window, do not corroborate
    assert answered_window_spans([window], _bars(_JAN[1:5], "ALPACA")) == []
    assert answered_window_spans([window], _bars(_JAN[12:15])) == []


def test_days_before_the_first_and_after_the_last_bar_stay_unanswered():
    window = ("ibkr", _midnight(_JAN[0]), _midnight(_JAN[19]))
    spans = answered_window_spans([window], _bars([_JAN[4], _JAN[8]]))
    assert spans == [(_JAN[4], _JAN[8])]


def test_a_midnight_window_end_is_exclusive_and_a_midday_end_takes_its_day():
    bars = _bars([_JAN[2], _JAN[6]])
    exclusive = ("ibkr", _midnight(_JAN[0]), _midnight(_JAN[6]))
    assert answered_window_spans([exclusive], bars) == [(_JAN[2], _JAN[2])]
    midday = ("ibkr", _midnight(_JAN[0]), _midnight(_JAN[6]) + timedelta(hours=17, minutes=30))
    assert answered_window_spans([midday], bars) == [(_JAN[2], _JAN[6])]
    # the window start day is in the window
    first_day = ("ibkr", _midnight(_JAN[2]), _midnight(_JAN[9]))
    assert answered_window_spans([first_day], bars) == [(_JAN[2], _JAN[6])]


def test_a_session_inside_an_answered_span_passes_coverage_in_the_judge():
    inputs = _clean()
    gap = _SESSIONS[2]
    interior = replace(
        inputs,
        stored=[b for b in inputs.stored if b.timestamp.date() != gap],
        observations=[replace(o, route="SMART") for o in inputs.observations if o.bar_date != gap],
    )
    assert not _by_check(_judge(interior))["session_coverage"].passed
    window = ("ibkr", _midnight(_SESSIONS[0]), _midnight(_SESSIONS[-1]) + timedelta(days=1))
    covered = replace(interior, answered_windows=[window])
    assert _by_check(_judge(covered))["session_coverage"].passed
    # the same window of a vendor with no bars of its own answers nothing
    other = replace(interior, answered_windows=[("alpaca", window[1], window[2])])
    assert not _by_check(_judge(other))["session_coverage"].passed


def test_a_session_with_a_raw_bar_but_no_stored_bar_is_a_derivation_gap_not_an_answer():
    inputs = _clean()
    gap = _SESSIONS[2]
    smart = [replace(o, route="SMART") for o in inputs.observations]
    window = ("ibkr", _midnight(_SESSIONS[0]), _midnight(_SESSIONS[-1]) + timedelta(days=1))
    unstored = replace(
        inputs,
        stored=[b for b in inputs.stored if b.timestamp.date() != gap],
        observations=smart,  # the raw bar of `gap` is still there
        answered_windows=[window],
    )
    assert not _by_check(_judge(unstored))["session_coverage"].passed
