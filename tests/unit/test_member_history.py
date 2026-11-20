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
        if "market_data_ohlcv_tradeable" in sql:
            return self._stats
        return []  # no stale splits


def _run(monkeypatch, tmp_path, stats: list[tuple]) -> tuple[int, dict]:
    import json

    from scripts.ops.bars import ops_member_history_audit as audit

    monkeypatch.setattr(audit.psycopg, "connect", lambda _url: _FakeConn(stats))
    settings = type("S", (), {"database_url": "x"})()
    code = audit.run(settings, tmp_path)  # type: ignore[arg-type]
    return code, json.loads((tmp_path / "summary.json").read_text())


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


def test_run_with_no_bars_at_all_reports_instead_of_crashing(monkeypatch, tmp_path) -> None:
    code, summary = _run(monkeypatch, tmp_path, [])
    assert code == 1
    assert summary["findings_by_check"] == {NO_BARS: 2}
