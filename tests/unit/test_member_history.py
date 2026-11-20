import re
from datetime import date

from src.intelligence.bars.member_history import (
    NO_BARS,
    NON_POSITIVE_PRICE,
    OHLC_INVARIANT,
    STALE_SPLITS,
    MemberStats,
    audit_members,
    bar_density,
    coverage_quantiles,
)


def _stats(symbol: str, bars: int = 10, bad: int = 0, nonpos: int = 0) -> MemberStats:
    return MemberStats(symbol, bars, date(2010, 1, 4), date(2010, 1, 15), bad, nonpos)


def test_clean_members_have_no_findings() -> None:
    assert audit_members(["AAA", "BBB"], {"AAA": _stats("AAA"), "BBB": _stats("BBB")}, {}) == []


def test_member_without_bars_is_a_finding() -> None:
    findings = audit_members(["AAA", "ZZZ"], {"AAA": _stats("AAA")}, {})
    assert [(f.symbol, f.check) for f in findings] == [("ZZZ", NO_BARS)]


def test_invariant_and_price_findings_and_stale_splits_sorted_by_symbol() -> None:
    stats = {"BBB": _stats("BBB", bad=2, nonpos=1), "AAA": _stats("AAA")}
    findings = audit_members(["BBB", "AAA"], stats, {"AAA": "split recorded x, digest y"})
    assert [(f.symbol, f.check) for f in findings] == [
        ("AAA", STALE_SPLITS),
        ("BBB", OHLC_INVARIANT),
        ("BBB", NON_POSITIVE_PRICE),
    ]


def test_only_members_are_audited() -> None:
    # An active non-member with a defect is outside this gate.
    assert audit_members(["AAA"], {"AAA": _stats("AAA"), "OUT": _stats("OUT", bad=1)}, {}) == []


def test_bar_density_counts_calendar_sessions_between_first_and_last_bar() -> None:
    calendar = [date(2010, 1, d) for d in (4, 5, 6, 7, 8)]
    span = (date(2010, 1, 4), date(2010, 1, 8))
    assert bar_density(MemberStats("A", 3, *span, 0, 0), calendar) == 0.6
    assert bar_density(MemberStats("A", 9, *span, 0, 0), calendar) == 1.0  # capped
    one = date(2010, 1, 6)
    assert bar_density(MemberStats("A", 1, one, one, 0, 0), calendar) == 1.0
    assert (
        bar_density(MemberStats("A", 1, date(2001, 1, 2), date(2001, 1, 3), 0, 0), calendar) == 1.0
    )


def test_stale_splits_sql_equals_the_membership_writer_rule() -> None:
    from scripts.ops.bars.ops_member_history_audit import _STALE_SQL
    from services.universe_membership_writer import _STALE_SPLITS_SQL

    def norm(sql: str) -> str:
        return re.sub(r"\s+", " ", sql.replace("%(s)s", "$1")).strip()

    assert norm(_STALE_SQL) == norm(_STALE_SPLITS_SQL)


def test_coverage_quantiles_nearest_rank() -> None:
    assert coverage_quantiles([], (0.5,)) == {}
    assert coverage_quantiles([0.2, 0.4, 0.6, 0.8, 1.0], (0.01, 0.5)) == {"p01": 0.2, "p50": 0.6}
    # 100 names: p01 is the minimum, p50 the lower median (rank ceil(p * n)).
    values = [0.30] + [0.35 + i * 0.001 for i in range(99)]
    q = coverage_quantiles(values, (0.01, 0.5))
    assert q["p01"] == 0.30
    assert q["p50"] == sorted(values)[49]


class _FakeConn:
    """Answers the audit's queries by SQL text; members M1 (clean) and M2 (no bars)."""

    def __init__(self, stats: list[tuple]) -> None:
        self._stats = stats

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> list[tuple]:
        if "universe_membership" in sql:
            return [("M1",), ("M2",)]
        if "is_active" in sql:
            return [("M1",), ("ACT",)]
        if "GROUP BY symbol" in sql and "market_data_ohlcv_tradeable" in sql:
            return self._stats
        if "market_data_ohlcv_tradeable" in sql:  # the stored 1d dates of the inactive members
            return [(r[0], d) for r in self._stats if r[0] in params["s"] for d in self.days.get(r[0], ())]  # type: ignore[index]
        return []  # no stale splits, no empty spans

    days: dict[str, list[date]] = {}


def _run(
    monkeypatch, tmp_path, stats: list[tuple], *, apply: bool = False, days=None
) -> tuple[int, dict]:
    import json

    from scripts.ops.bars import ops_member_history_audit as audit

    conn = _FakeConn(stats)
    conn.days = days or {}
    monkeypatch.setattr(audit.psycopg, "connect", lambda _url: conn)

    async def coverage_min() -> float:
        return 0.999

    monkeypatch.setattr(audit, "_read_coverage_min", coverage_min)
    written: list[tuple] = []

    async def write_facts(_settings, facts: list[tuple]) -> int:
        written.extend(facts)
        return len(facts)

    monkeypatch.setattr(audit, "_write_facts", write_facts)
    settings = type("S", (), {"database_url": "x"})()
    code = audit.run(settings, tmp_path, apply=apply)  # type: ignore[arg-type]
    summary = json.loads((tmp_path / "summary.json").read_text())
    summary["_written"] = written
    return code, summary


def test_run_fails_on_a_member_without_bars_and_writes_the_outputs(monkeypatch, tmp_path) -> None:
    row = lambda s: (s, 5, date(2024, 1, 2), date(2024, 1, 8), 0, 0)  # noqa: E731
    code, summary = _run(monkeypatch, tmp_path, [row("M1"), row("ACT")])
    assert code == 1
    assert summary["passed"] is False
    assert summary["findings_by_check"] == {NO_BARS: 1}
    assert (tmp_path / "findings.csv").read_text().splitlines()[1].startswith("M2,")


def test_run_passes_when_every_member_is_clean(monkeypatch, tmp_path) -> None:
    row = lambda s: (s, 5, date(2024, 1, 2), date(2024, 1, 8), 0, 0)  # noqa: E731
    code, summary = _run(monkeypatch, tmp_path, [row("M1"), row("M2"), row("ACT")])
    assert (code, summary["passed"]) == (0, True)


def test_apply_writes_a_start_for_inactive_members_only(monkeypatch, tmp_path) -> None:
    # M1 is active (and a member); M2 is inactive with bars; ACT is active, not a member.
    sessions = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    row = lambda s: (s, 4, sessions[0], sessions[-1], 0, 0)  # noqa: E731
    days = {"M2": sessions, "M1": sessions}
    code, summary = _run(
        monkeypatch, tmp_path, [row("M1"), row("M2"), row("ACT")], apply=True, days=days
    )
    assert code == 0
    assert [f[1] for f in summary["_written"]] == ["M2|1d"]
    assert summary["_written"][0][5] is True
    assert summary["proven_starts"]["with_start"] == 1
    assert summary["proven_starts"]["facts_written"] == 1
    assert (tmp_path / "proven_starts.csv").read_text().splitlines()[1].startswith("M2,")


def test_default_run_writes_nothing_and_a_name_without_a_start_is_a_failing_fact(
    monkeypatch, tmp_path
) -> None:
    # M2's stored dates miss its last bar: no start, so a failing fact under --apply.
    first, last = date(2024, 1, 2), date(2024, 1, 8)
    row = ("M2", 3, first, last, 0, 0)
    code, summary = _run(monkeypatch, tmp_path, [row], days={"M2": [first]})
    assert summary["_written"] == [] and summary["proven_starts"]["without_start"] == 1
    assert summary["proven_starts"]["applied"] is False
    _, applied = _run(monkeypatch, tmp_path, [row], apply=True, days={"M2": [first]})
    assert [f[5] for f in applied["_written"]] == [False]


def test_run_with_no_bars_at_all_reports_instead_of_crashing(monkeypatch, tmp_path) -> None:
    code, summary = _run(monkeypatch, tmp_path, [])
    assert code == 1
    assert summary["findings_by_check"] == {NO_BARS: 2}


# ---------------------------------------------------------------------------
# member proven start (the dead names' start record, docs/plans/2026-11-20-member-proven-start.md)

from datetime import UTC, datetime, timedelta  # noqa: E402

from scripts.ops.bars import ops_member_history_audit as audit_script  # noqa: E402
from services import bar_reconciliation_audit as verdict_run  # noqa: E402
from src.intelligence.bars.integrity_checks import INFO_PROVEN_START  # noqa: E402
from src.intelligence.bars.member_history import (  # noqa: E402
    member_proven_start,
    proven_start_fact,
)

# Mon 2010-01-04 .. Fri 2010-03-05 weekdays stand in for NYSE sessions (a sorted date list).
_CAL = [date(2010, 1, 4) + timedelta(days=i) for i in range(70) if (i % 7) < 5]
_ERA = date(2000, 1, 3)


def _span_stats(first: date, last: date) -> MemberStats:
    return MemberStats("X", 1, first, last, 0, 0)


def test_a_dead_names_start_is_judged_over_its_own_span_not_the_calendars_end() -> None:
    sessions = _CAL[:20]
    # The name dies on sessions[-1]; the calendar runs on for 40 more sessions. Judged to the
    # calendar's end its last session would read unanswered (the verdict run's None).
    start = member_proven_start(
        _span_stats(sessions[0], sessions[-1]), _CAL, sessions, [], 0.999, era_start=_ERA
    )
    assert start == sessions[0]


def test_a_hole_moves_the_start_after_it() -> None:
    sessions = _CAL[:30]
    stored = [s for s in sessions if s != sessions[5]]
    start = member_proven_start(
        _span_stats(sessions[0], sessions[-1]), _CAL, stored, [], 0.999, era_start=_ERA
    )
    assert start == sessions[6]


def test_an_answered_empty_span_credits_only_its_sessions() -> None:
    sessions = _CAL[:30]
    stored = [s for s in sessions if s not in sessions[5:8]]
    credited = member_proven_start(
        _span_stats(sessions[0], sessions[-1]),
        _CAL,
        stored,
        [(sessions[5], sessions[7])],
        0.999,
        era_start=_ERA,
    )
    assert credited == sessions[0]
    short = member_proven_start(
        _span_stats(sessions[0], sessions[-1]),
        _CAL,
        stored,
        [(sessions[5], sessions[6])],  # sessions[7] stays a hole
        0.999,
        era_start=_ERA,
    )
    assert short == sessions[8]


def test_a_span_before_the_calendar_era_is_clipped_to_it() -> None:
    # Bars from before the era start: sessions before it are not judged (no calendar session).
    start = member_proven_start(
        _span_stats(date(1998, 1, 5), _CAL[10]),
        _CAL,
        _CAL[:11],
        [],
        0.999,
        era_start=_CAL[3],
    )
    assert start == _CAL[3]


def test_a_name_that_dies_before_the_calendar_has_no_start() -> None:
    assert (
        member_proven_start(
            _span_stats(date(1998, 1, 5), date(1998, 6, 1)),
            _CAL,
            [date(1998, 1, 5)],
            [],
            0.999,
            era_start=_ERA,
        )
        is None
    )


def test_a_name_whose_last_bar_is_not_a_stored_session_has_no_start() -> None:
    sessions = _CAL[:10]
    assert (
        member_proven_start(
            _span_stats(sessions[0], sessions[-1]), _CAL, sessions[:-1], [], 0.999, era_start=_ERA
        )
        is None
    )


def test_a_stored_date_outside_the_span_is_not_credited() -> None:
    sessions = _CAL[:10]
    start = member_proven_start(
        _span_stats(sessions[2], sessions[-1]),
        _CAL,
        _CAL[:10] + _CAL[30:40],
        [],
        0.999,
        era_start=_ERA,
    )
    assert start == sessions[2]


def test_the_fact_has_the_verdict_runs_shape() -> None:
    twe = datetime(2026, 11, 20, tzinfo=UTC)
    assert proven_start_fact("AAA", date(2010, 1, 4), twe) == (
        "bar_integrity",
        "AAA|1d",
        INFO_PROVEN_START,
        float(date(2010, 1, 4).toordinal()),
        None,
        True,
        twe,
    )
    assert proven_start_fact("AAA", None, twe)[3:6] == (0.0, None, False)


def test_the_empty_span_sql_is_the_verdict_runs() -> None:
    assert audit_script._EMPTY_SQL.split() == verdict_run._EMPTY_SESSIONS_SQL.split()


def test_the_script_writes_through_the_verdict_runs_batch_writer() -> None:
    assert audit_script.emit_integrity_facts_async is verdict_run.emit_integrity_facts_async
