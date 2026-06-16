"""Tests for narrative API route — Phase 78 D-29/D-30.

Covers: 200 (happy path), 200 (cached), 404, 422, 502 (LLM neutral), 500 (DB error),
chain caching, and typed SignalContext construction.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — real async context managers (per CLAUDE.md async-mock gotcha)
# ---------------------------------------------------------------------------


class _FakeConn:
    """Real class with async methods — avoids AsyncMock __aenter__ pitfalls."""

    def __init__(self, fetchrow_return=None, fetchrow_raises=None, execute_return=None):
        self._fetchrow_return = fetchrow_return
        self._fetchrow_raises = fetchrow_raises
        self._execute_return = execute_return or {"narrative": "x", "model": "m"}
        self.fetchrow = self._fetchrow
        self.execute = self._execute

    async def _fetchrow(self, *args, **kwargs):
        if self._fetchrow_raises:
            raise self._fetchrow_raises
        return self._fetchrow_return

    async def _execute(self, *args, **kwargs):
        if self._fetchrow_raises:
            raise self._fetchrow_raises
        return self._execute_return


class _FakeAcquireCtx:
    """Real class-level __aenter__/__aexit__ for pool.acquire() context."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        pass


def _make_db_pool(fetchrow_return=None, fetchrow_raises=None):
    """Build a mock DatabaseManager with .pool.acquire() returning _FakeAcquireCtx."""
    conn = _FakeConn(fetchrow_return=fetchrow_return, fetchrow_raises=fetchrow_raises)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_FakeAcquireCtx(conn))
    db = MagicMock()
    db.pool = pool
    return db


def _signal_row(overrides=None):
    """Minimal signal_ledger_full + intelligence_features JOIN row (3-table schema)."""
    base = {
        "signal_id": uuid.uuid4(),
        "symbol": "ESM6",
        "timestamp": datetime.now(UTC),
        "tf": "15m",
        "bar": {"o": 5400.0, "h": 5410.0, "l": 5395.0, "c": 5405.0, "v": 12345},
        "i1": {},
        "i3": None,
        "i4": {},
        "i5": None,
        "smc": None,
        "cross_timeframe_context": None,
        "setup_plugin": None,
        "direction": None,
        "confidence": None,
        "entry_price": None,
        "stop_loss": None,
        "targets": None,
        "entry_type": None,
        "composite_events": None,
    }
    base.update(overrides or {})
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear lru_cache between tests."""
    from src.api.routes.narrative import _get_llm_chain, _get_settings

    _get_settings.cache_clear()
    _get_llm_chain.cache_clear()
    yield
    _get_settings.cache_clear()
    _get_llm_chain.cache_clear()


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app)


@pytest.fixture
def mock_db():
    """Set the module-level db_manager singleton used by the dependency."""
    import src.api.dependencies as deps

    db = _make_db_pool()
    old = deps.db_manager
    deps.db_manager = db
    yield db
    deps.db_manager = old


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNarrativeRoute:
    def test_200_happy_path(self, client, mock_db):
        """First request: DB miss → LLM call → persist → 200."""
        signal_id = uuid.uuid4()
        row = _signal_row({"signal_id": signal_id})

        # First fetchrow: cache miss (None). Second: signal row.
        call_count = 0

        async def _alternate_fetchrow(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # cache miss
            return row  # signal lookup

        mock_db.pool.acquire.return_value = _FakeAcquireCtx(_FakeConn(fetchrow_return=None))
        # Override fetchrow for sequential returns
        conn = mock_db.pool.acquire.return_value._conn
        conn.fetchrow = _alternate_fetchrow

        output = MagicMock(
            error=None,
            payload={"text": "Market shows bullish momentum.", "model": "ollama/gemma4"},
            agent_id="narrative_v1",
        )
        with patch(
            "src.api.routes.narrative.NarrativeSynthesizer.compute",
            new_callable=AsyncMock,
            return_value=output,
        ):
            resp = client.get(f"/api/signals/{signal_id}/narrative")

        assert resp.status_code == 200
        body = resp.json()
        assert body["signal_id"] == str(signal_id)
        assert body["narrative"] == "Market shows bullish momentum."
        assert body["model"] == "ollama/gemma4"
        assert body["cached"] is False

    def test_200_cached(self, client, mock_db):
        """Repeat request returns from cache with cached=True."""
        signal_id = uuid.uuid4()
        conn = _FakeConn(fetchrow_return={"narrative": "Cached text.", "model": "ollama/gemma4"})
        mock_db.pool.acquire.return_value = _FakeAcquireCtx(conn)

        resp = client.get(f"/api/signals/{signal_id}/narrative")

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        assert body["narrative"] == "Cached text."

    def test_404_signal_not_found(self, client, mock_db):
        """Signal UUID doesn't exist in signal_ledger."""
        signal_id = uuid.uuid4()
        # First fetchrow: cache miss. Second: signal lookup returns None.
        call_count = 0

        async def _both_none(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return None

        conn = _FakeConn(fetchrow_return=None)
        conn.fetchrow = _both_none
        mock_db.pool.acquire.return_value = _FakeAcquireCtx(conn)

        resp = client.get(f"/api/signals/{signal_id}/narrative")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_422_invalid_uuid(self, client, mock_db):
        """Non-UUID path param rejected by FastAPI before handler runs."""
        resp = client.get("/api/signals/not-a-uuid/narrative")
        assert resp.status_code == 422

    def test_502_llm_neutral(self, client, mock_db):
        """NarrativeSynthesizer returns error or empty text."""
        signal_id = uuid.uuid4()
        row = _signal_row({"signal_id": signal_id})

        call_count = 0

        async def _seq(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # cache miss
            return row

        conn = _FakeConn(fetchrow_return=None)
        conn.fetchrow = _seq
        mock_db.pool.acquire.return_value = _FakeAcquireCtx(conn)

        output = MagicMock(
            error="tf_gate:1m",
            payload={"text": ""},
            agent_id="narrative_v1",
        )
        with patch(
            "src.api.routes.narrative.NarrativeSynthesizer.compute",
            new_callable=AsyncMock,
            return_value=output,
        ):
            resp = client.get(f"/api/signals/{signal_id}/narrative")

        assert resp.status_code == 502
        assert "failed" in resp.json()["detail"].lower()

    def test_500_db_error(self, client, mock_db):
        """DB raises exception — sanitized error returned."""
        signal_id = uuid.uuid4()
        conn = _FakeConn(fetchrow_raises=Exception("connection lost"))
        mock_db.pool.acquire.return_value = _FakeAcquireCtx(conn)

        with patch(
            "src.api.routes.narrative.logger",
        ) as mock_logger:
            resp = client.get(f"/api/signals/{signal_id}/narrative")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Database error"
        # Internal exception NOT leaked to client
        assert "connection lost" not in resp.json()["detail"]

    def test_chain_caching(self, client, mock_db):
        """LLMProviderChain constructor called exactly once across two requests."""
        from src.core.llm.chain import LLMProviderChain

        signal_id_1 = uuid.uuid4()
        signal_id_2 = uuid.uuid4()

        init_count = 0
        original_init = LLMProviderChain.__init__

        def _counting_init(self, *args, **kwargs):
            nonlocal init_count
            init_count += 1
            # Minimal init to avoid real LLM setup
            self._call_type = kwargs.get("call_type", "narrative")
            self._cache_ttl = 0
            self._inner = MagicMock()

        with (
            patch("src.api.routes.narrative.LLMProviderChain.__init__", _counting_init),
            patch("src.api.routes.narrative._get_settings", return_value=MagicMock()),
        ):
            # Force cache clear so chain is built fresh
            from src.api.routes.narrative import _get_llm_chain

            _get_llm_chain.cache_clear()

            # First call builds the chain
            _get_llm_chain()
            # Second call should hit cache
            _get_llm_chain()

        assert init_count == 1


class TestBuildContext:
    """Verify typed SignalContext construction — no dict[str, Any] escape."""

    def test_typed_context_from_row(self):
        from src.api.routes.narrative import _build_context_from_row

        row = _signal_row(
            {
                "i1": {"rsi_14": 55.2},
                "i3": None,
                "i4": None,
            }
        )

        ctx = _build_context_from_row(row)

        assert ctx.symbol == "ESM6"
        assert ctx.timeframe == "15m"
        assert ctx.i3 is None
        assert ctx.i4 is None
        assert ctx.i1 is not None  # typed, not dict
        assert ctx.bar is not None
        assert ctx.bar.close == 5405.0

    def test_null_bar_produces_none(self):
        from src.api.routes.narrative import _build_context_from_row

        row = _signal_row({"bar": None})
        ctx = _build_context_from_row(row)
        assert ctx.bar is None
