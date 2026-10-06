"""Priority queue over ohlcv_coverage (phase 189 plan 02, CD-05/CD-06/CD-08).

Pure tests with a fixed `today` and fixture CoverageRow lists; the loaders run against
fake connections. No database, no IBKR.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.infrastructure.backfill import _fetch_queue as fq

TODAY = date(2026, 10, 2)


def _ts(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC)


def _days_ago(n: int) -> datetime:
    return _ts(TODAY - timedelta(days=n))


def _row(
    symbol: str,
    timeframe: str,
    *,
    earliest_days: int | None,
    latest_days: int | None,
    status: str | None = "ok",
    failures: int = 0,
    floor_days: int | None = None,
) -> fq.CoverageRow:
    return fq.CoverageRow(
        symbol=symbol,
        timeframe=timeframe,
        earliest_timestamp=None if earliest_days is None else _days_ago(earliest_days),
        latest_timestamp=None if latest_days is None else _days_ago(latest_days),
        last_fetch_status=status,
        consecutive_failures=failures,
        floor_timestamp=None if floor_days is None else _days_ago(floor_days),
    )


CONFIG = fq.QueueConfig(
    max_consecutive_failures=5,
    max_staleness_days_before_preempt=3,
    priority_tf_order=("15m", "1h"),
    depth_days={"1d": 7300, "1h": 7300, "15m": 7300, "5m": 7300, "1m": 90},
    history_request_timeout_s=900.0,
    history_request_retries=2,
    run_budget_minutes=240,
    default_scopes={"compute": ("1d", "1h", "15m", "5m"), "backfill": ("1h", "15m")},
)


# -- staleness and coverage gap -------------------------------------------------------


def test_staleness_none_when_never_fetched():
    assert fq.staleness_days(_row("A", "15m", earliest_days=None, latest_days=None), TODAY) is None


def test_staleness_counts_utc_days_since_latest():
    assert fq.staleness_days(_row("A", "15m", earliest_days=100, latest_days=4), TODAY) == 4


def test_inception_wall_gap_is_zero():
    # Young ETF: 15m and 1d both start in 2024; its proven depth is its own shallow history.
    rows = [
        _row("IBIT", "15m", earliest_days=640, latest_days=1),
        _row("IBIT", "1d", earliest_days=640, latest_days=1),
    ]
    proven = fq.proven_days_by_symbol(rows, TODAY)
    assert proven["IBIT"] == 640
    for row in rows:
        assert fq.coverage_gap_days(row, proven["IBIT"], 7300, TODAY) == 0


def test_bby_like_full_depth_gap_is_zero():
    row = _row("BBY", "15m", earliest_days=7305, latest_days=1)
    assert fq.coverage_gap_days(row, 7305, 7300, TODAY) == 0


def test_hpq_like_gap_uses_real_earliest():
    # 15m archive coverage reaches back 3000 days; 1d proves 7300 days.
    rows = [
        _row("HPQ", "15m", earliest_days=3000, latest_days=1),
        _row("HPQ", "1d", earliest_days=7300, latest_days=1),
    ]
    proven = fq.proven_days_by_symbol(rows, TODAY)
    assert fq.coverage_gap_days(rows[0], proven["HPQ"], 7300, TODAY) == 4300


def test_never_fetched_series_gap_uses_symbol_proven_depth():
    row = _row("XYZ", "15m", earliest_days=None, latest_days=None, status=None)
    assert fq.coverage_gap_days(row, 7300, 7300, TODAY) == 7300


def test_unknown_proven_depth_falls_back_to_target():
    # A symbol with nothing stored anywhere has no proven depth: the target stands in, so
    # a newly onboarded name is fetched once instead of scoring a permanent zero gap.
    row = _row("NEW", "1d", earliest_days=None, latest_days=None, status=None)
    assert fq.coverage_gap_days(row, None, 7300, TODAY) == 7300


def test_provider_floor_caps_the_gap():
    # Venue-boundary name (TLT-like): IBKR's verified floor sits 3650 days back.
    row = _row("TLT", "15m", earliest_days=3650, latest_days=1, floor_days=3650)
    assert fq.coverage_gap_days(row, 7300, 7300, TODAY) == 0


# -- rank -----------------------------------------------------------------------------


def test_sla_preemption_over_zero_coverage():
    covered_stale = _row("AAA", "5m", earliest_days=7300, latest_days=5)
    never_fetched = _row("ZZZ", "15m", earliest_days=None, latest_days=None, status=None)
    ordered = fq.order_queue([never_fetched, covered_stale], CONFIG, TODAY)
    assert ordered[0] is covered_stale


def test_never_fetched_is_not_in_preempt_band():
    row = _row("ZZZ", "15m", earliest_days=None, latest_days=None, status=None)
    assert fq.rank(row, None, CONFIG, TODAY)[1] is True


def test_staleness_at_sla_threshold_is_not_a_breach():
    row = _row("AAA", "15m", earliest_days=7300, latest_days=3)
    assert fq.rank(row, 7300, CONFIG, TODAY)[1] is True


def test_tf_class_ordering_beats_larger_gap():
    fifteen = _row("AAA", "15m", earliest_days=7000, latest_days=1)
    five = _row("BBB", "5m", earliest_days=100, latest_days=1)
    proven = {"AAA": 7300, "BBB": 7300}
    ordered = fq.order_queue([five, fifteen], CONFIG, TODAY, proven)
    assert [r.symbol for r in ordered] == ["AAA", "BBB"]


def test_larger_gap_first_then_staler_first():
    small_gap = _row("AAA", "15m", earliest_days=7000, latest_days=1)
    big_gap = _row("BBB", "15m", earliest_days=1000, latest_days=1)
    stale = _row("CCC", "15m", earliest_days=7300, latest_days=2)
    fresh = _row("DDD", "15m", earliest_days=7300, latest_days=1)
    proven = dict.fromkeys(["AAA", "BBB", "CCC", "DDD"], 7300)
    ordered = fq.order_queue([fresh, stale, small_gap, big_gap], CONFIG, TODAY, proven)
    assert [r.symbol for r in ordered] == ["BBB", "AAA", "CCC", "DDD"]


def test_failure_threshold_exclusion_boundary():
    kept = _row("KEEP", "15m", earliest_days=10, latest_days=1, status="error", failures=5)
    dropped = _row("DROP", "15m", earliest_days=10, latest_days=1, status="error", failures=6)
    ordered = fq.order_queue([kept, dropped], CONFIG, TODAY)
    assert [r.symbol for r in ordered] == ["KEEP"]
    assert fq.rank(dropped, 10, CONFIG, TODAY)[0] is True
    assert fq.rank(kept, 10, CONFIG, TODAY)[0] is False


def test_no_data_never_excluded():
    row = _row("ND", "15m", earliest_days=None, latest_days=None, status="no_data", failures=0)
    assert fq.order_queue([row], CONFIG, TODAY) == [row]


def test_two_timeframes_of_one_symbol_never_tie():
    a = _row("SAME", "15m", earliest_days=7300, latest_days=1)
    b = replace(a, timeframe="1h")
    assert fq.rank(a, 7300, CONFIG, TODAY) != fq.rank(b, 7300, CONFIG, TODAY)


def test_deterministic_tie_break_under_shuffling():
    rows = [
        _row(sym, tf, earliest_days=e, latest_days=lt, status=s, failures=f)
        for sym, tf, e, lt, s, f in [
            ("BBB", "15m", 7300, 1, "ok", 0),
            ("AAA", "15m", 7300, 1, "ok", 0),
            ("CCC", "1h", 3000, 2, "ok", 0),
            ("DDD", "5m", None, None, None, 0),
            ("EEE", "1d", 7300, 6, "ok", 0),
            ("FFF", "15m", 500, 1, "error", 3),
            ("GGG", "15m", 500, 1, "error", 9),
            ("AAA", "1h", 7300, 1, "ok", 0),
        ]
    ]
    expected = fq.order_queue(rows, CONFIG, TODAY)
    assert expected[0].symbol == "EEE"  # SLA breach first
    assert expected.index(next(r for r in rows if r.symbol == "AAA" and r.timeframe == "15m")) < (
        expected.index(next(r for r in rows if r.symbol == "BBB"))
    )
    rng = random.Random(189)
    for _ in range(100):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        assert fq.order_queue(shuffled, CONFIG, TODAY) == expected


def test_ranked_items_report_components():
    row = _row("AAA", "15m", earliest_days=3000, latest_days=5)
    (item,) = fq.queue_items([row], CONFIG, TODAY, {"AAA": 7300})
    assert item.sla_breach is True
    assert item.tf_class == -1
    assert item.gap_days == 4300
    assert item.staleness_days == 5
    assert item.rank == fq.rank(row, 7300, CONFIG, TODAY)


# -- load_queue_config ----------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


_FULL_ROWS = [
    ("infra.backfill.max_consecutive_failures", "7"),
    ("infra.backfill.max_staleness_days_before_preempt", "2"),
    ("infra.backfill.priority_tf_order", '["1h"]'),
    ("infra.backfill.default_scopes", '{"compute": ["1d", "1h"], "backfill": ["15m"]}'),
    ("infra.backfill.run_budget_minutes", "120"),
    ("infra.ibkr.history_request_timeout", "800"),
    ("infra.ibkr.history_request_retries", "3"),
    ("infra.ibkr.rate_limit_window_sec", "600.0"),
    ("infra.backfill.depth_days.15m", "5000"),
    ("infra.backfill.depth_days.1d", "7300"),
]


def test_load_queue_config_parses_apr_rows(caplog):
    cfg = fq.load_queue_config(_FakeConn(_FULL_ROWS))
    assert cfg.max_consecutive_failures == 7
    assert cfg.max_staleness_days_before_preempt == 2
    assert cfg.priority_tf_order == ("1h",)
    assert cfg.default_scopes == {"compute": ("1d", "1h"), "backfill": ("15m",)}
    assert cfg.run_budget_minutes == 120
    assert cfg.history_request_timeout_s == 800.0
    assert cfg.history_request_retries == 3
    assert cfg.depth_days["15m"] == 5000
    # unset depth keys keep the pipeline's _TF_FETCH_CONFIG depth
    assert cfg.depth_days["1m"] == 90


def test_load_queue_config_single_query():
    conn = _FakeConn(_FULL_ROWS)
    fq.load_queue_config(conn)
    assert len(conn.cursor_obj.executed) == 1
    assert "config_state" in conn.cursor_obj.executed[0][0]


def test_load_queue_config_falls_back_with_one_warning(monkeypatch):
    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(fq.logger, "warning", lambda event, **kw: warnings.append((event, kw)))
    cfg = fq.load_queue_config(_FakeConn([]))
    assert cfg.max_consecutive_failures == 5
    assert cfg.max_staleness_days_before_preempt == 3
    assert cfg.priority_tf_order == ("15m", "1h")
    assert cfg.history_request_timeout_s == 900.0
    assert cfg.depth_days["15m"] == 7300
    assert len(warnings) == 1
    assert "infra.backfill.max_consecutive_failures" in warnings[0][1]["keys"]


def test_load_queue_config_rejects_timeout_not_above_rate_limit_window():
    rows = [r for r in _FULL_ROWS if r[0] != "infra.ibkr.history_request_timeout"]
    rows.append(("infra.ibkr.history_request_timeout", "600"))
    with pytest.raises(ValueError, match="rate_limit_window_sec"):
        fq.load_queue_config(_FakeConn(rows))


def test_load_queue_config_malformed_json_is_loud():
    rows = [r for r in _FULL_ROWS if r[0] != "infra.backfill.priority_tf_order"]
    rows.append(("infra.backfill.priority_tf_order", "[15m"))
    with pytest.raises(ValueError):
        fq.load_queue_config(_FakeConn(rows))


# -- PriorityQueue with a fake asyncpg pool -------------------------------------------


class _FakeAsyncConn:
    def __init__(self, tables):
        self.tables = tables
        self.queries: list[str] = []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        for marker, rows in self.tables.items():
            if marker in sql:
                return rows
        raise AssertionError(f"unexpected query: {sql}")


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, tables):
        self.conn = _FakeAsyncConn(tables)

    def acquire(self):
        return _FakeAcquire(self.conn)


def _pool(coverage, heads=(), empty=(), config=None):
    if config is None:
        config = [
            {"config_key": "infra.backfill.empty_history_reverify_days", "config_value": "90"},
            {"config_key": "infra.ibkr.no_data_confirmation_chunks", "config_value": "2"},
        ]
    return _FakePool(
        {
            "FROM config_state": config,
            "FROM ohlcv_coverage": coverage,
            "FROM ohlcv_provider_head": list(heads),
            "FROM ohlcv_empty_history": list(empty),
        }
    )


def _cov(symbol, timeframe, earliest_days, latest_days, status="ok", failures=0, fetched=None):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "earliest_timestamp": None if earliest_days is None else _days_ago(earliest_days),
        "latest_timestamp": None if latest_days is None else _days_ago(latest_days),
        "last_fetch_status": status,
        "consecutive_failures": failures,
        "last_fetched_at": fetched,
    }


async def test_priority_queue_visited_set_and_exhaustion():
    pool = _pool(
        [
            _cov("AAA", "15m", 7300, 1),
            _cov("BBB", "15m", 1000, 1),
            _cov("BBB", "1d", 7300, 1),
        ]
    )
    queue = fq.PriorityQueue(CONFIG, [("AAA", "15m"), ("BBB", "15m")], TODAY)
    visited: set[tuple[str, str]] = set()
    first = await queue.next(pool, visited)
    assert (first.symbol, first.timeframe) == ("BBB", "15m")
    visited.add(("BBB", "15m"))
    second = await queue.next(pool, visited)
    assert (second.symbol, second.timeframe) == ("AAA", "15m")
    visited.add(("AAA", "15m"))
    assert await queue.next(pool, visited) is None


async def test_priority_queue_candidate_without_ledger_row():
    pool = _pool([_cov("AAA", "1d", 7300, 1)])
    queue = fq.PriorityQueue(CONFIG, [("AAA", "15m")], TODAY)
    item = await queue.next(pool, set())
    assert item == fq.CoverageRow("AAA", "15m", None, None, None, 0, None)


async def test_priority_queue_ranks_only_candidates_but_proves_depth_from_all_rows():
    # 1d is out of scope, yet its depth is the ceiling for the in-scope 15m series.
    pool = _pool([_cov("AAA", "15m", 1000, 1), _cov("AAA", "1d", 7300, 1)])
    queue = fq.PriorityQueue(CONFIG, [("AAA", "15m")], TODAY)
    await queue.load(pool)
    snapshot = queue.ranked_snapshot()
    assert [(i.row.symbol, i.row.timeframe) for i in snapshot] == [("AAA", "15m")]
    assert snapshot[0].gap_days == 6300


async def test_priority_queue_floor_is_later_of_head_and_empty_range():
    head = {"symbol": "TLT", "head_ts": _days_ago(4000)}
    empty = {"symbol": "TLT", "timeframe": "15m", "empty_through": _days_ago(3650)}
    pool = _pool(
        [_cov("TLT", "15m", 3650, 1), _cov("TLT", "1d", 7300, 1)], heads=[head], empty=[empty]
    )
    queue = fq.PriorityQueue(CONFIG, [("TLT", "15m"), ("TLT", "1d")], TODAY)
    await queue.load(pool)
    by_tf = {i.row.timeframe: i for i in queue.ranked_snapshot()}
    assert by_tf["15m"].row.floor_timestamp == _days_ago(3650)
    assert by_tf["15m"].gap_days == 0
    assert by_tf["1d"].row.floor_timestamp == _days_ago(4000)


async def test_priority_queue_raises_without_reverify_days():
    pool = _pool([], config=[])
    queue = fq.PriorityQueue(CONFIG, [("AAA", "15m")], TODAY)
    with pytest.raises(RuntimeError, match="empty_history_reverify_days"):
        await queue.load(pool)


# ---------------------------------------------------------------------------
# Current hold (phase 189 plan 04): nothing new to ask before the next session close
# ---------------------------------------------------------------------------

_CLOSE = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)


def _fetched_row(status, fetched):
    return fq.CoverageRow("AAA", "15m", None, None, status, 0, None, fetched)


def test_is_current_needs_a_settled_fetch_at_or_after_the_close():
    after, before = _CLOSE + timedelta(minutes=5), _CLOSE - timedelta(minutes=5)
    assert fq.is_current(_fetched_row("ok", after), _CLOSE)
    assert fq.is_current(_fetched_row("no_data", _CLOSE), _CLOSE)
    assert not fq.is_current(_fetched_row("error", after), _CLOSE)
    assert not fq.is_current(_fetched_row("ok", before), _CLOSE)
    assert not fq.is_current(_fetched_row(None, None), _CLOSE)
    assert not fq.is_current(_fetched_row("ok", after), None)


async def test_priority_queue_holds_current_series_and_reports_held_reasons():
    after = _CLOSE + timedelta(hours=1)
    pool = _pool(
        [
            _cov("AAA", "15m", 7300, 1, fetched=after),
            _cov("BBB", "15m", 7300, 1, fetched=_CLOSE - timedelta(hours=1)),
            _cov("CCC", "15m", 7300, 1, status="error", failures=99, fetched=after),
            _cov("DDD", "15m", 7300, 1, status="error", fetched=after),
        ]
    )
    candidates = [("AAA", "15m"), ("BBB", "15m"), ("CCC", "15m"), ("DDD", "15m")]
    queue = fq.PriorityQueue(CONFIG, candidates, TODAY, current_after=_CLOSE)
    await queue.load(pool)
    assert [(i.row.symbol) for i in queue.ranked_snapshot()] == ["BBB", "DDD"]
    held = {(i.row.symbol, reason) for i, reason in queue.held_snapshot()}
    assert held == {("AAA", "current"), ("CCC", "excluded")}
    visited: set[tuple[str, str]] = set()
    assert (await queue.next(pool, visited)).symbol == "BBB"


async def test_priority_queue_without_current_after_holds_nothing_current():
    pool = _pool([_cov("AAA", "15m", 7300, 1, fetched=_CLOSE + timedelta(hours=1))])
    queue = fq.PriorityQueue(CONFIG, [("AAA", "15m")], TODAY)
    await queue.load(pool)
    assert [i.row.symbol for i in queue.ranked_snapshot()] == ["AAA"]
    assert queue.held_snapshot() == []
