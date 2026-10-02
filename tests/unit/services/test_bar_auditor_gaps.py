"""Tests for BarAuditor market_data_gaps write path and DLQ routing."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bar_auditor import BarAuditor


@pytest.mark.asyncio
async def test_upsert_gap_on_incomplete_audit():
    """UPSERT a gap row when completeness < threshold."""
    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="test")

    conn = AsyncMock()
    conn.execute = AsyncMock()

    gap_start_ts = datetime(2026, 4, 13, 9, 30, 0, tzinfo=UTC)

    await agent._upsert_market_data_gap(
        conn, symbol="ES", tf="1m", gap_start_ts=gap_start_ts, bars_expected=390, bars_missing=45
    )

    assert conn.execute.called
    sql = conn.execute.call_args[0][0]
    assert "INSERT INTO market_data_gaps" in sql
    assert "ON CONFLICT" in sql


@pytest.mark.asyncio
async def test_resolve_gap_on_complete_audit():
    """Mark an open gap as resolved when completeness reaches 100%."""
    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="test")

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=123)  # Existing gap ID
    conn.execute = AsyncMock()

    gap_start_ts = datetime(2026, 4, 13, 9, 30, 0, tzinfo=UTC)

    await agent._resolve_market_data_gap(conn, symbol="ES", tf="1m", gap_start_ts=gap_start_ts)

    assert conn.fetchval.called
    assert conn.execute.called
    sql = conn.execute.call_args[0][0]
    assert "UPDATE market_data_gaps" in sql
    assert "resolved_at" in sql


@pytest.mark.asyncio
async def test_resolve_gap_noop_when_no_open_gap():
    """No UPDATE when no open gap exists (fetchval returns None)."""
    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="test")

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=None)  # No open gap
    conn.execute = AsyncMock()

    gap_start_ts = datetime(2026, 4, 13, 9, 30, 0, tzinfo=UTC)

    await agent._resolve_market_data_gap(conn, symbol="ES", tf="1m", gap_start_ts=gap_start_ts)

    assert conn.fetchval.called
    assert not conn.execute.called  # No UPDATE executed


@pytest.mark.asyncio
async def test_gap_requests_topic_name():
    """Verify topic_gap_requests returns expected topic string."""
    from src.core.stream_keys import topic_gap_requests

    # Verify topic_gap_requests exists in stream_keys
    topic = topic_gap_requests("test")
    assert "gap_requests" in topic


@pytest.mark.asyncio
async def test_dlq_published_on_retry_exhaustion():
    """Unresolvable gap request published to DLQ after retry exhaustion."""

    mock_dlq_depth = MagicMock()

    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    agent._kafka_producer = AsyncMock()
    agent._kafka_producer.publish = AsyncMock()
    agent._gap_fill_dlq_depth = mock_dlq_depth

    start_ts = datetime(2026, 4, 13, 9, 30, 0, tzinfo=UTC)
    end_ts = datetime(2026, 4, 13, 16, 0, 0, tzinfo=UTC)

    await agent._publish_gap_fill_dlq(
        symbol="ES", tf="1m", start_ts=start_ts, end_ts=end_ts, retry_count=3, error="timeout"
    )

    assert agent._kafka_producer.publish.called
    topic = agent._kafka_producer.publish.call_args[0][0]
    assert "gap_fill.dlq" in topic
    # OTel up_down_counter: .add(1) must have been called
    mock_dlq_depth.add.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# Plan 185-18 task 1a: the HTF gap plan comes from the shared pure planner
# (src/intelligence/bars/gap_plan.py). The auditor's count for a symbol and
# timeframe equals the length of plan_gaps' output for the same inputs.
# ---------------------------------------------------------------------------

from datetime import date, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from src.intelligence.bars import gap_plan  # noqa: E402

# Friday 2026-01-02, regular NYSE session 14:30-21:00 UTC.
_WIN_START = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
_WIN_END = datetime(2026, 1, 2, 21, 0, tzinfo=UTC)
_INSTRUMENT = SimpleNamespace(symbol="SPY", session_id="nyse", exchange="NYSE")


def _auditor() -> BarAuditor:
    agent = BarAuditor.__new__(BarAuditor)
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    agent.name = "bar-auditor"
    return agent


def _async_conn(fetch_results: list[list]) -> AsyncMock:
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=list(fetch_results))
    return conn


@pytest.mark.asyncio
async def test_htf_gap_plan_matches_the_shared_planner():
    """The auditor's plan IS plan_gaps for the same inputs (plan acceptance)."""
    agent = _auditor()
    stored = [(datetime(2026, 1, 2, h, 30, tzinfo=UTC),) for h in range(14, 21) if h != 16]
    conn = _async_conn([stored, [], []])  # stored, answered, empty span

    plan = await agent._plan_htf_gaps(
        conn,
        _INSTRUMENT,
        "1h",
        _WIN_START,
        _WIN_END,
        now=_WIN_END,
        reverify_days=7,
        min_confirmations=2,
    )

    slots = gap_plan.expected_grid_slots("nyse", "NYSE", "1h", _WIN_START, _WIN_END)
    expected = gap_plan.plan_gaps(
        [s for s in slots],
        [r[0] for r in stored],
        gap_plan.AnsweredWindows(),
        timedelta(hours=1),
        run_end=_WIN_END,
    )
    assert (
        plan
        == expected
        == [(datetime(2026, 1, 2, 16, 30, tzinfo=UTC), datetime(2026, 1, 2, 17, 30, tzinfo=UTC))]
    )


@pytest.mark.asyncio
async def test_htf_gap_plan_counts_a_definitive_no_data_window_as_covered():
    agent = _auditor()
    stored = [(datetime(2026, 1, 2, h, 30, tzinfo=UTC),) for h in range(15, 21)]
    answered = [
        (datetime(2026, 1, 2, 14, 30, tzinfo=UTC), datetime(2026, 1, 2, 15, 30, tzinfo=UTC))
    ]
    conn = _async_conn([stored, answered, []])

    plan = await agent._plan_htf_gaps(
        conn,
        _INSTRUMENT,
        "1h",
        _WIN_START,
        _WIN_END,
        now=_WIN_END,
        reverify_days=7,
        min_confirmations=2,
    )
    assert plan == []


@pytest.mark.asyncio
async def test_htf_gap_plan_reads_the_archive_for_15m_1h_and_the_grid_for_5m():
    for tf, table in (("15m", "ohlcv_intraday_raw_archive"), ("5m", "market_data_ohlcv")):
        agent = _auditor()
        conn = _async_conn([[], [], []])
        await agent._plan_htf_gaps(
            conn,
            _INSTRUMENT,
            tf,
            _WIN_START,
            _WIN_END,
            now=_WIN_END,
            reverify_days=7,
            min_confirmations=2,
        )
        stored_sql = conn.fetch.call_args_list[0].args[0]
        assert table in stored_sql


@pytest.mark.asyncio
async def test_htf_gap_plan_folds_a_fresh_confirmed_empty_span():
    agent = _auditor()
    empty_row = [
        (
            datetime(2026, 1, 2, 14, 30, tzinfo=UTC),  # empty_from
            datetime(2026, 1, 2, 15, 30, tzinfo=UTC),  # empty_through
            datetime(2026, 1, 2, 20, 0, tzinfo=UTC),  # verified_at
            3,  # n_confirming_chunks
        )
    ]
    stored = [(datetime(2026, 1, 2, h, 30, tzinfo=UTC),) for h in range(15, 21)]
    conn = _async_conn([stored, [], empty_row])

    plan = await agent._plan_htf_gaps(
        conn,
        _INSTRUMENT,
        "1h",
        _WIN_START,
        _WIN_END,
        now=_WIN_END,
        reverify_days=7,
        min_confirmations=2,
    )
    assert plan == []


@pytest.mark.asyncio
async def test_detect_gaps_htf_alarm_comes_from_the_shared_planner(monkeypatch):
    """A window whose HTF completeness is below the gate has its alarm derived
    from the shared planner (n_gaps == len(plan)); 4h stays on the legacy
    count-only warning."""
    from services import bar_auditor as mod

    class _FakeSession:
        def session_window_for_date(self, d: date):
            if d.weekday() >= 5:
                return (None, None)
            return (
                datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC),
                datetime(d.year, d.month, d.day, 21, 0, tzinfo=UTC),
            )

        def _break_minutes(self) -> int:
            return 0

        def max_achievable_pct(self) -> float:
            return 1.0

    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return date(2026, 10, 1)  # Thursday

    instrument = SimpleNamespace(
        symbol="SPY", trading_session=_FakeSession(), session_id="nyse", exchange="NYSE"
    )
    agent = _auditor()
    agent._is_roll_suppressed = lambda symbol: False
    agent._upsert_market_data_gap = AsyncMock()
    agent._resolve_market_data_gap = AsyncMock()

    conn = AsyncMock()
    # Bulk count: 1m complete (390 of 390); every HTF tf empty -> planner path.
    win_start = datetime(2026, 9, 30, 14, 30, tzinfo=UTC)
    conn.fetch = AsyncMock(
        return_value=[{"sym": "SPY", "win_start": win_start, "timeframe": "1m", "cnt": 390}]
    )
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    agent._db_pool = pool

    plan_return = [
        (datetime(2026, 9, 30, 15, 0, tzinfo=UTC), datetime(2026, 9, 30, 16, 0, tzinfo=UTC))
    ]
    planner = AsyncMock(return_value=plan_return)
    monkeypatch.setattr(BarAuditor, "_plan_htf_gaps", planner)
    monkeypatch.setattr(mod, "_CANONICAL_COMPLETENESS", MagicMock())
    monkeypatch.setattr(mod, "date", _FixedDate)

    gaps = await agent._detect_gaps([instrument], lookback_days=1)

    assert gaps == []  # 1m complete: no gap request emitted
    assert planner.await_count == 3  # 5m, 15m, 1h -- never 4h
    planned_tfs = {call.args[2] for call in planner.await_args_list}
    assert planned_tfs == {"5m", "15m", "1h"}
    for call in planner.await_args_list:
        assert call.args[0] is conn
        assert call.args[1] is instrument
        assert call.args[3] == win_start
    alarm = [
        log
        for log in agent.logger.warning.call_args_list
        if log.args[0] == "bar_auditor.htf_gap_plan"
    ]
    assert len(alarm) == 3
    for log in alarm:
        assert log.kwargs["n_gaps"] == 1
