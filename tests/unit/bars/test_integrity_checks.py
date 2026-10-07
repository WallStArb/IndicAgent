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


# ---------------------------------------------------------------------------
# judge_name_1d: the per-name verdicts, on fakes (todo 494: no live D1)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, replace  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from src.intelligence.bars.daily_rule import RULE_VERSION, derive_daily_v2  # noqa: E402
from src.intelligence.bars.derivation import Observation  # noqa: E402
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


def _stored(day: date, close: float, source: str = "tradier") -> StoredBar:
    return StoredBar(
        datetime(day.year, day.month, day.day, tzinfo=UTC),
        close,
        close + 1,
        close - 1,
        close,
        1000.0,
        source,
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
            b.source,
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
        inputs, _SESSIONS, _SESSIONS[-1], _RUN_START, _Thresholds(), timings=timings
    )


def _by_check(report) -> dict:
    return {v.check: v for v in report.verdicts}


def test_clean_name_passes_all_eight_checks_in_report_order():
    report = _judge(_clean())
    assert tuple(v.check for v in report.verdicts) == CHECKS_1D
    assert all(v.passed for v in report.verdicts)
    assert {v.symbol for v in report.verdicts} == {"AAA"}
    assert {v.timeframe for v in report.verdicts} == {"1d"}
    assert report.refused_head == 0


def test_timings_record_the_checks_that_do_work():
    timings: dict[str, float] = {}
    _judge(_clean(), timings)
    assert {"canonical_recompute", "digest_fresh", "vendor_basis_run"} <= set(timings)


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


def test_a_contradicting_source_fails_policy_conformance():
    inputs = _clean()
    bad = [replace(inputs.stored[0], source="ibkr_named"), *inputs.stored[1:]]
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


def _basis_inputs(stored_source: str, tradier_steps: bool) -> NameInputs1d:
    """IBKR runs 2x Tradier for 4 sessions mid-series; one vendor steps at the boundaries."""
    days = _SESSIONS
    observations = []
    for i, day in enumerate(days):
        base = 100.0 + 0.1 * i
        in_run = 3 <= i <= 6
        tradier_close = base * (0.5 if in_run and tradier_steps else 1.0)
        ibkr_close = base * (1.0 if tradier_steps else (2.0 if in_run else 1.0))
        if tradier_steps:
            ibkr_close = base
        observations.append(_obs(day, tradier_close, "TRADIER"))
        observations.append(_obs(day, ibkr_close, "SMART"))
    inputs = replace(_clean(), observations=observations)
    stored = [replace(b, source=stored_source) for b in inputs.stored]
    return replace(inputs, stored=stored)


def test_vendor_run_blocks_only_when_the_canonical_side_is_the_one_that_steps():
    # Tradier steps down by half inside the run while IBKR is smooth: Tradier is the
    # discontinuous vendor, and the stored bars (tradier) are built from it.
    stepping = _judge(_basis_inputs("tradier", tradier_steps=True))
    assert not _by_check(stepping)["vendor_basis_run"].passed
    assert stepping.basis_runs and stepping.blocking_runs
    # IBKR steps up inside the run while Tradier is smooth: the canonical Tradier side is fine.
    smooth = _judge(_basis_inputs("tradier", tradier_steps=False))
    assert smooth.basis_runs and not smooth.blocking_runs
    assert _by_check(smooth)["vendor_basis_run"].passed
