"""Unit tests for SignalAuditor.

Tests verify:
- Signal coverage gap detection and event emission
- Coverage 1.0 when signals are present in the session window
- Non-trading day skipped (session_window returns (None, None))
- CIS distribution mean/stddev metric observation
- topics_produced contains signal_audit topic
- topics_consumed is empty

Phase 130: pipeline lag P50/P95 tests removed — _check_pipeline_lag removed from
SignalAuditor (column dropped from schema).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.signal_auditor import (
    _COVERAGE_TFS,
    SignalAuditor,
)
from src.core import timeframe_vocabulary
from src.core.stream_keys import topic_signal_audit


@pytest.fixture()
def agent():
    """Create SignalAuditor without __init__ (bypasses DB/Kafka setup)."""
    a = SignalAuditor.__new__(SignalAuditor)
    a.name = "signal_auditor_agent"
    a.logger = MagicMock()
    a.settings = MagicMock(env_name="dev")
    a._db_pool = AsyncMock()
    a._kafka_producer = AsyncMock()
    a._audits_run = MagicMock()
    a._coverage_gaps_published = MagicMock()
    a._audit_duration = MagicMock()
    a._audit_duration.__enter__ = MagicMock(return_value=None)
    a._audit_duration.__exit__ = MagicMock(return_value=False)
    a._audit_errors = MagicMock()
    a._signal_coverage_pct = MagicMock()
    a._signal_coverage_pct.labels.return_value = MagicMock()
    a._cis_mean = MagicMock()
    a._cis_mean.labels.return_value = MagicMock()
    a._cis_stddev = MagicMock()
    a._cis_stddev.labels.return_value = MagicMock()
    # APR-backed config (defaults from migration 142)
    a._audit_lookback_hours = 1
    return a


def _make_instrument(symbol: str = "SPY", session_id: str = "nyse"):
    """Create a lightweight instrument mock with a mocked trading_session.

    TradingSession is a frozen dataclass, so session_window_for_date cannot be
    patched directly on an instance. We return a MagicMock that mimics the fields
    accessed by SignalAuditor: instrument.symbol and
    instrument.trading_session.session_window_for_date.
    """
    instrument = MagicMock()
    instrument.symbol = symbol
    # trading_session is itself a MagicMock; callers configure
    # instrument.trading_session.session_window_for_date as needed.
    return instrument


def _make_conn_mock(coverage_count: int = 0, cis_row=None):
    """Build asyncpg connection mock.

    coverage_count: returned by fetchval (coverage COUNT queries).
    cis_row: dict with keys cis_mean, cis_stddev returned by fetchrow for CIS queries.
    """
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=coverage_count)

    async def fetchrow_side(query, *args):
        if "cis_mean" in query:
            return cis_row
        return None

    conn.fetchrow = AsyncMock(side_effect=fetchrow_side)
    return conn


def _set_db_pool(agent, mock_conn) -> None:
    """Wire the agent's db_pool so that `async with pool.acquire() as conn` yields mock_conn.

    asyncpg pool.acquire() returns a context manager (not a coroutine).
    Use MagicMock (not AsyncMock) for acquire so the return value is treated as a
    context manager, not a coroutine.
    """
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    agent._db_pool.acquire = MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_coverage_gap_when_zero_signals(agent):
    """_check_coverage returns one gap event per tf when count = 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    _set_db_pool(agent, conn)

    session_start = datetime(2026, 4, 5, 14, 30, tzinfo=UTC)
    session_end = datetime(2026, 4, 5, 21, 0, tzinfo=UTC)
    instrument.trading_session.session_window_for_date = MagicMock(
        return_value=(session_start, session_end)
    )

    with patch("services.signal_auditor._SIGNAL_COVERAGE_PCT") as mock_cov:
        gaps = await agent._check_coverage([instrument])

    assert len(gaps) == len(_COVERAGE_TFS)
    for gap in gaps:
        assert gap["symbol"] == "SPY"
        assert gap["signals_found"] == 0
        assert "session_date" in gap
        assert "ts" in gap
        assert "expected_session_start" in gap
        assert "expected_session_end" in gap

    # OTel up_down_counter: .add(0.0, {...}) called once per tf
    assert mock_cov.add.call_count == len(_COVERAGE_TFS)
    for call in mock_cov.add.call_args_list:
        assert call.args[0] == 0.0


@pytest.mark.asyncio
async def test_no_gap_when_signals_present(agent):
    """_check_coverage returns no gap events when count > 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=42)
    _set_db_pool(agent, conn)

    instrument.trading_session.session_window_for_date = MagicMock(
        return_value=(
            datetime(2026, 4, 5, 14, 30, tzinfo=UTC),
            datetime(2026, 4, 5, 21, 0, tzinfo=UTC),
        )
    )

    with patch("services.signal_auditor._SIGNAL_COVERAGE_PCT") as mock_cov:
        gaps = await agent._check_coverage([instrument])

    assert gaps == []
    for call in mock_cov.add.call_args_list:
        assert call.args[0] == 1.0


@pytest.mark.asyncio
async def test_coverage_skips_non_trading_day(agent):
    """_check_coverage skips instruments where session_window returns (None, None)."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    _set_db_pool(agent, conn)

    instrument.trading_session.session_window_for_date = MagicMock(return_value=(None, None))

    gaps = await agent._check_coverage([instrument])

    assert gaps == []
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_cis_distribution_sets_gauges(agent):
    """_check_cis_distribution sets cis_mean and cis_stddev gauges per tf."""
    cis_row = {"cis_mean": 0.52, "cis_stddev": 0.18}
    conn = _make_conn_mock(cis_row=cis_row)
    _set_db_pool(agent, conn)

    with (
        patch("services.signal_auditor._CIS_MEAN") as mock_mean,
        patch("services.signal_auditor._CIS_STDDEV") as mock_stddev,
    ):
        await agent._check_cis_distribution()

    # OTel up_down_counter: .add(value, attrs) called once per tf
    assert mock_mean.add.call_count == len(_COVERAGE_TFS)
    assert mock_stddev.add.call_count == len(_COVERAGE_TFS)
    # Verify the actual values passed
    mean_vals = [call.args[0] for call in mock_mean.add.call_args_list]
    assert all(v == 0.52 for v in mean_vals)
    stddev_vals = [call.args[0] for call in mock_stddev.add.call_args_list]
    assert all(v == 0.18 for v in stddev_vals)


def test_topics_produced(agent):
    """topics_produced returns the signal audit topic for the configured env."""
    assert topic_signal_audit(agent.env_name) in agent.topics_produced


def test_topics_consumed_is_empty(agent):
    """topics_consumed is empty — AuditorAgent pulls from DB, not Kafka."""
    assert agent.topics_consumed == []


# ---------------------------------------------------------------------------
# _setup() prewarms VocabularyService and asserts _COVERAGE_TFS subset (todo 327)
# ---------------------------------------------------------------------------


class _FakeVocabularyService:
    """Stands in for VocabularyService -- records initialize() and reports a
    CVR-registered timeframe set that is a strict superset of _COVERAGE_TFS, so a
    passing assertion proves _setup() actually consulted CVR rather than skipping
    the check via the no-VocabularyService-registered no-op path."""

    def __init__(self, database_url, pool=None):
        self.database_url = database_url
        self.pool = pool
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    def active_codes(self, namespace: str) -> list[str]:
        assert namespace == "timeframe"
        return ["1m", "5m", "15m", "1h", "4h", "1d"]


class _FakeVocabularyServiceMissingTf:
    """Reports a CVR set that omits "1h", one of _COVERAGE_TFS's members -- proves
    _setup() actually raises via assert_known_subset on a real drift case, not just
    on the always-passing path."""

    def __init__(self, database_url, pool=None):
        self.database_url = database_url
        self.pool = pool

    async def initialize(self) -> None:
        pass

    def active_codes(self, namespace: str) -> list[str]:
        assert namespace == "timeframe"
        return ["1m", "5m", "15m", "4h", "1d"]


def _make_setup_agent():
    """Build SignalAuditor via __new__ (bypasses __init__) with just enough
    attributes for _setup() -- matches this file's `agent` fixture pattern."""
    a = SignalAuditor.__new__(SignalAuditor)
    a.name = "signal_auditor_agent"
    a.logger = MagicMock()
    a.settings = MagicMock(
        database_url="postgresql://test", kafka_bootstrap_servers="localhost:9092"
    )
    a._config_cache = {}
    return a


@pytest.mark.asyncio
async def test_setup_asserts_coverage_tfs_subset_of_cvr():
    """_setup() prewarms VocabularyService and validates _COVERAGE_TFS is a subset of
    CVR's registered timeframe codes -- catches drift without changing behavior."""
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    agent = _make_setup_agent()

    with (
        patch("services.signal_auditor.create_db_pool", new=AsyncMock(return_value=MagicMock())),
        patch("services.signal_auditor.KafkaProducerClient", return_value=AsyncMock()),
        patch("services.signal_auditor.VocabularyService", _FakeVocabularyService),
    ):
        await agent._setup()

    assert timeframe_vocabulary._vocab_service is not None
    assert timeframe_vocabulary._vocab_service.initialized is True

    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.asyncio
async def test_setup_raises_when_coverage_tfs_not_subset_of_cvr():
    """_setup() raises ValueError when _COVERAGE_TFS references a timeframe CVR does
    not have registered -- proves assert_known_subset actually gates startup rather
    than being wired in but never exercised on the failing path."""
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    agent = _make_setup_agent()

    with (
        patch("services.signal_auditor.create_db_pool", new=AsyncMock(return_value=MagicMock())),
        patch("services.signal_auditor.KafkaProducerClient", return_value=AsyncMock()),
        patch("services.signal_auditor.VocabularyService", _FakeVocabularyServiceMissingTf),
    ):
        with pytest.raises(ValueError):
            await agent._setup()

    timeframe_vocabulary.reset_vocabulary_service_for_test()
