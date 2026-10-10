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
    assert fq.rank(row, None, CONFIG, TODAY)[2] is True


def test_staleness_at_sla_threshold_is_not_a_breach():
    row = _row("AAA", "15m", earliest_days=7300, latest_days=3)
    assert fq.rank(row, 7300, CONFIG, TODAY)[2] is True


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


# ---------------------------------------------------------------------------
# Plan 189-10 Task 1 (amended by 185-46): two lanes, the 1d due rule, the parity sample
# ---------------------------------------------------------------------------

# Monday 2026-10-05 21:00 UTC: the last completed session closed at 20:00 that day.
_LAST_CLOSE = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
_CLOSES = [
    datetime(2026, 9, 30, 20, 0, tzinfo=UTC),
    datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
    datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
    _LAST_CLOSE,
]
_DAILY = fq.DailyRule(last_close=_LAST_CLOSE, reconcile_after=_LAST_CLOSE)


def test_reconcile_after_is_the_close_of_the_nth_latest_completed_session():
    assert fq.reconcile_after(_CLOSES, 1) == _LAST_CLOSE
    assert fq.reconcile_after(_CLOSES, 3) == datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        fq.reconcile_after(_CLOSES, 0)
    with pytest.raises(ValueError):
        fq.reconcile_after(_CLOSES, 5)


def test_daily_due_rule_queues_a_name_asked_before_the_close_and_holds_one_asked_after():
    """Owner rule (185-46 amendment B): due when the latest SMART TRADES 1d request was
    answered before the latest completed session's close; held when answered after it."""
    canonical = _LAST_CLOSE.date()
    before = _LAST_CLOSE - timedelta(hours=1)
    after = _LAST_CLOSE + timedelta(minutes=10)
    assert fq.daily_due_reason(before, canonical, _DAILY) == "reconcile_due"
    assert fq.daily_due_reason(after, canonical, _DAILY) is None
    assert fq.daily_due_reason(None, canonical, _DAILY) == "never_asked"


def test_a_stale_canonical_bar_queues_a_name_inside_a_longer_reconcile_interval():
    """The 1d pass also checks currency: with a 3-session interval a name asked two sessions
    ago is held while its canonical bar is current, and queued when it is not, unless it was
    already asked since the last close (then the freshness_1d verdict names it, no re-ask)."""
    rule = fq.DailyRule(last_close=_LAST_CLOSE, reconcile_after=fq.reconcile_after(_CLOSES, 3))
    two_sessions_ago = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)
    assert fq.daily_due_reason(two_sessions_ago, _LAST_CLOSE.date(), rule) is None
    stale = date(2026, 10, 2)
    assert fq.daily_due_reason(two_sessions_ago, stale, rule) == "not_current"
    assert fq.daily_due_reason(two_sessions_ago, None, rule) == "not_current"
    assert fq.daily_due_reason(_LAST_CLOSE + timedelta(hours=1), stale, rule) is None


def _daily_pool(coverage, answers, canonical):
    pool = _pool(coverage)
    pool.conn.tables["FROM ohlcv_request"] = answers
    pool.conn.tables["FROM market_data_ohlcv_tradeable"] = canonical
    return pool


async def test_queue_applies_the_daily_rule_with_no_tradier_hold():
    """A name asked before the close is queued, one asked after is held as current, a name
    never asked is queued; nothing is held as tradier_owned (the hold is gone)."""
    pool = _daily_pool(
        [_cov(s, "1d", 7300, 1) for s in ("OLD", "NEW", "NEVER")],
        [
            {"symbol": "OLD", "answered_at": _LAST_CLOSE - timedelta(days=1)},
            {"symbol": "NEW", "answered_at": _LAST_CLOSE + timedelta(minutes=30)},
        ],
        [{"symbol": s, "latest": _LAST_CLOSE.replace(hour=0)} for s in ("OLD", "NEW", "NEVER")],
    )
    candidates = [("OLD", "1d"), ("NEW", "1d"), ("NEVER", "1d")]
    queue = fq.PriorityQueue(CONFIG, candidates, TODAY, current_after=_LAST_CLOSE, daily=_DAILY)
    await queue.load(pool)
    assert sorted(i.row.symbol for i in queue.ranked_snapshot()) == ["NEVER", "OLD"]
    assert {(i.row.symbol, r) for i, r in queue.held_snapshot()} == {("NEW", "current")}
    assert queue.due_reason("OLD", "1d") == "reconcile_due"
    assert queue.due_reason("NEVER", "1d") == "never_asked"
    assert not any("tradier" in sql.lower() for sql in pool.conn.queries)


async def test_a_1d_series_that_last_errored_is_never_held():
    pool = _daily_pool(
        [_cov("ERR", "1d", 7300, 1, status="error", failures=1)],
        [{"symbol": "ERR", "answered_at": _LAST_CLOSE + timedelta(minutes=30)}],
        [{"symbol": "ERR", "latest": _LAST_CLOSE.replace(hour=0)}],
    )
    queue = fq.PriorityQueue(
        CONFIG, [("ERR", "1d")], TODAY, current_after=_LAST_CLOSE, daily=_DAILY
    )
    await queue.load(pool)
    assert [i.row.symbol for i in queue.ranked_snapshot()] == ["ERR"]


def test_a_due_1d_item_precedes_a_5m_item_with_a_larger_gap():
    """185-46 amendment B: a due 1d item ranks ahead of every 5m item, even a 5m series with
    the whole 20-year gap and an SLA breach."""
    five = _row("AAA", "5m", earliest_days=None, latest_days=None, status=None)
    five_breached = _row("BBB", "5m", earliest_days=100, latest_days=9)
    daily = _row("ZZZ", "1d", earliest_days=7300, latest_days=1)
    config = replace(CONFIG, priority_tf_order=("5m",))
    proven = {"AAA": 7300, "BBB": 7300, "ZZZ": 7300}
    items = fq.queue_items([five, five_breached, daily], config, TODAY, proven)
    assert items[0].row is daily
    assert items[1].gap_days > 0 and items[0].gap_days == 0


def test_gap_fill_cadence_is_one_session_in_every_n_per_series():
    """The gap-fill lane: over any N consecutive weekday sessions each series is due exactly
    once, deterministically, and series spread over the cycle; interval 1 is every session."""
    sessions = [date(2026, 10, 5) + timedelta(days=d) for d in range(21)]
    sessions = [d for d in sessions if d.weekday() < 5][:10]
    symbols = [f"S{i:03d}" for i in range(200)]
    slots = []
    for symbol in symbols:
        due = [d for d in sessions[:7] if fq.gap_fill_due(symbol, "5m", d, 7)]
        assert len(due) == 1
        slots.append(sessions.index(due[0]))
        assert fq.gap_fill_due(symbol, "5m", due[0], 7)  # stable on a second call
        assert all(fq.gap_fill_due(symbol, "5m", d, 1) for d in sessions)
    assert len(set(slots)) == 7  # the work spreads over the whole cycle
    assert fq.gap_fill_due("AAA", "5m", sessions[0], 7) == fq.gap_fill_due(
        "AAA", "5m", sessions[7], 7
    )


def test_parity_sample_is_stable_within_an_iso_week_and_changes_the_next_week():
    eligible = [f"N{i:03d}" for i in range(60)]
    monday, friday = date(2026, 10, 5), date(2026, 10, 9)
    week = fq.parity_sample(eligible, monday, 10)
    assert len(week) == 10 and set(week) <= set(eligible)
    assert fq.parity_sample(eligible, friday, 10) == week
    assert fq.parity_sample(list(reversed(eligible)), friday, 10) == week
    assert fq.parity_sample(eligible, monday + timedelta(days=7), 10) != week
    assert fq.parity_sample(eligible, monday, 0) == []
    assert sorted(fq.parity_sample(eligible[:4], monday, 10)) == eligible[:4]
    assert fq.parity_week_start(friday) == datetime(2026, 10, 5, tzinfo=UTC)


async def test_queue_holds_a_parity_series_already_asked_this_week():
    week_start = datetime(2026, 9, 28, tzinfo=UTC)
    pool = _pool(
        [
            _cov("PAR", "15m", 7300, 1, fetched=week_start + timedelta(days=1)),
            _cov("PAR", "1h", 7300, 1, fetched=week_start - timedelta(days=1)),
        ]
    )
    queue = fq.PriorityQueue(
        CONFIG,
        [("PAR", "15m"), ("PAR", "1h")],
        TODAY,
        current_after=_LAST_CLOSE,
        current_after_by_series={("PAR", "15m"): week_start, ("PAR", "1h"): week_start},
    )
    await queue.load(pool)
    assert [(i.row.symbol, i.row.timeframe) for i in queue.ranked_snapshot()] == [("PAR", "1h")]


def test_a_split_restated_overlap_escalates_the_name():
    """The stored closes are on the old scale: the stored/fresh ratio is the split factor."""
    pairs = [(100.0 + i, (100.0 + i) / 2.0) for i in range(20)]
    for restated_escalates in (True, False):
        verdict = fq.judge_overlap(pairs, 10.0, escalate_on_restated=restated_escalates)
        assert verdict.escalate
        assert verdict.median_ratio == pytest.approx(2.0)
        assert verdict.n_restated == 20
        assert verdict.reason == "ratio_outside_tolerance"


def test_an_unchanged_overlap_does_not_escalate():
    pairs = [(100.0 + i, 100.0 + i) for i in range(20)]
    for restated_escalates in (True, False):
        verdict = fq.judge_overlap(pairs, 10.0, escalate_on_restated=restated_escalates)
        assert not verdict.escalate
        assert verdict.n_restated == 0 and verdict.reason is None
    assert not fq.judge_overlap([], 10.0, escalate_on_restated=True).escalate


def test_one_restated_1d_close_escalates_but_routine_5m_restatements_do_not():
    """1d: any restated close escalates (rare: 1 in 5,558 repeated observations). 5m: IBKR
    restates 15 to 40 recent rows a name routinely; they are written and recorded by the
    ingress contract, and only a scale change (median ratio) escalates."""
    pairs = [(100.0, 100.0)] * 30 + [(100.0, 100.05)]
    assert fq.judge_overlap(pairs, 10.0, escalate_on_restated=True).reason == "restated_row"
    assert not fq.judge_overlap(pairs, 10.0, escalate_on_restated=False).escalate


_LANE_ROWS = [
    ("infra.backfill.ibkr_1d_reconcile_interval_days", "1"),
    ("infra.backfill.update_overlap_sessions_1d", "20"),
    ("infra.backfill.update_overlap_days_5m", "3"),
    ("infra.backfill.gap_fill_interval_days", "7"),
    ("infra.backfill.grid_parity_sample_names_per_week", "10"),
    ("threshold.bar_integrity.fallback_basis_tolerance_bp", "10"),
]


def test_load_lane_config_reads_every_key_in_one_query():
    conn = _FakeConn(_LANE_ROWS)
    lanes = fq.load_lane_config(conn)
    assert lanes == fq.LaneConfig(
        reconcile_interval_sessions=1,
        update_overlap_sessions_1d=20,
        update_overlap_days_5m=3,
        gap_fill_interval_days=7,
        parity_names_per_week=10,
        basis_tolerance_bp=10.0,
    )
    assert len(conn.cursor_obj.executed) == 1


def test_load_lane_config_has_no_fallback_for_a_missing_key():
    with pytest.raises(RuntimeError, match="gap_fill_interval_days"):
        fq.load_lane_config(_FakeConn([r for r in _LANE_ROWS if "gap_fill" not in r[0]]))


# ---------------------------------------------------------------------------
# Phase 190 plan 03 Task 1: ProviderPlan, per-provider APR reads and validation
# ---------------------------------------------------------------------------


def _plan_get(rows):
    values = dict(rows)

    def get(key):
        return values.get(key)

    return get


_IBKR_PLAN_ROWS = (
    ("infra.ibkr.history_request_timeout", "800"),
    ("infra.ibkr.history_request_retries", "3"),
    ("infra.ibkr.rate_limit_window_sec", "600.0"),
    ("infra.ibkr.no_data_confirmation_chunks", "2"),
    ("infra.ibkr.inter_item_pause_s", "2.0"),
)


def test_load_provider_plan_reads_per_provider_apr_keys():
    plan = fq.load_provider_plan("ibkr", _plan_get(_IBKR_PLAN_ROWS))
    assert plan.name == "ibkr"
    assert plan.request_timeout_s == 800.0
    assert plan.request_retries == 3
    assert plan.rate_limit_window_s == 600.0
    assert plan.confirmation_chunks == 2
    assert plan.inter_item_pause_s == 2.0


def test_load_provider_plan_keys_are_built_per_provider():
    # one vendor's keys are never read for another vendor (two-tier rule)
    seen = []

    def get(key):
        seen.append(key)
        return None

    with pytest.raises(RuntimeError, match="infra.alpaca"):
        fq.load_provider_plan("alpaca", get)
    assert seen and all(k.startswith("infra.alpaca.") for k in seen)


def test_ibkr_plan_answers_1d_with_the_smart_trades_filter():
    plan = fq.load_provider_plan("ibkr", _plan_get(_IBKR_PLAN_ROWS))
    assert plan.answers_1d is True
    assert plan.daily_answer_filter == "route = 'SMART' AND what_to_show = 'TRADES'"


def test_a_rest_vendor_plan_carries_answers_1d_false():
    plan = fq.ProviderPlan(
        name="alpaca",
        request_timeout_s=60.0,
        request_retries=2,
        rate_limit_window_s=60.0,
        confirmation_chunks=1,
        inter_item_pause_s=0.0,
        answers_1d=False,
        daily_answer_filter=None,
    )
    assert plan.answers_1d is False and plan.daily_answer_filter is None


def test_load_provider_plan_rejects_timeout_not_above_window_per_provider():
    rows = tuple(r for r in _IBKR_PLAN_ROWS if r[0] != "infra.ibkr.history_request_timeout")
    rows += (("infra.ibkr.history_request_timeout", "600"),)
    with pytest.raises(ValueError, match="infra.ibkr.rate_limit_window_sec"):
        fq.load_provider_plan("ibkr", _plan_get(rows))
    # the same values under another provider's keys validate independently
    alp = tuple((k.replace("ibkr", "alpaca"), v) for k, v in rows)
    with pytest.raises(ValueError, match="infra.alpaca.rate_limit_window_sec"):
        fq.load_provider_plan("alpaca", _plan_get(alp))


def test_load_provider_plan_raises_on_a_missing_planner_input():
    rows = tuple(r for r in _IBKR_PLAN_ROWS if r[0] != "infra.ibkr.no_data_confirmation_chunks")
    with pytest.raises(RuntimeError, match="no_data_confirmation_chunks"):
        fq.load_provider_plan("ibkr", _plan_get(rows))


def test_load_provider_plan_falls_back_on_a_leaf_native_limit(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(fq.logger, "warning", lambda event, **kw: warnings.append(event))
    rows = tuple(r for r in _IBKR_PLAN_ROWS if r[0] != "infra.ibkr.rate_limit_window_sec")
    plan = fq.load_provider_plan("ibkr", _plan_get(rows))
    assert plan.rate_limit_window_s == 600.0
    assert any("rate_limit_window" in w for w in warnings)


def test_depth_override_reads_per_provider_depth_keys():
    rows = _IBKR_PLAN_ROWS + (("infra.ibkr.depth_days.5m", "1000"),)
    plan = fq.load_provider_plan("ibkr", _plan_get(rows), depth_tfs=("5m", "1d"))
    assert plan.depth_overrides == {"5m": 1000}


def test_depth_override_wins_over_the_neutral_map_per_row():
    row = _row("AAA", "5m", earliest_days=100, latest_days=1)
    plan = fq.ProviderPlan(
        name="ibkr",
        request_timeout_s=900.0,
        request_retries=2,
        rate_limit_window_s=600.0,
        confirmation_chunks=2,
        inter_item_pause_s=2.0,
        depth_overrides={"5m": 1000},
    )
    plans = {"ibkr": plan}
    # neutral depth 7300 gives a 7200-day gap; the provider override caps the target at 1000
    assert fq.rank(row, 7300, CONFIG, TODAY)[4] == -7200
    assert fq.rank(row, 7300, CONFIG, TODAY, plans)[4] == -900
