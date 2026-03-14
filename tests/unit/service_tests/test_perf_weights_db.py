"""Unit tests for perf_weights DB-direct read in signal_generator_service.

Tests for:
- _load_perf_weights() reads from setup_performance DB table (not Redis)
- _load_perf_weights() populates _perf_weights dict correctly
- _load_perf_weights() is no-op when no db_manager
- No redis_client required for perf_weights load
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# SignalGeneratorService: _load_perf_weights from DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_perf_weights_populates_from_db():
    """_load_perf_weights() must read from setup_performance table via asyncpg."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._perf_weights = {}
    svc.logger = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(
        return_value=[
            {"setup_plugin": "trad_TrendFollowing", "win_rate": 0.60, "avg_pnl_r": 1.2},
            {"setup_plugin": "trad_MeanReversion", "win_rate": 0.45, "avg_pnl_r": 0.8},
        ]
    )

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool = mock_pool
    svc.db_manager = mock_db

    await svc._load_perf_weights()

    # Both plugins should be in _perf_weights
    assert "trad_TrendFollowing" in svc._perf_weights
    assert "trad_MeanReversion" in svc._perf_weights
    # Values should be floats
    assert isinstance(svc._perf_weights["trad_TrendFollowing"], float)
    assert isinstance(svc._perf_weights["trad_MeanReversion"], float)


@pytest.mark.asyncio
async def test_load_perf_weights_no_op_when_no_db():
    """_load_perf_weights() is no-op when db_manager is None."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._perf_weights = {}
    svc.db_manager = None
    svc.logger = MagicMock()

    await svc._load_perf_weights()
    assert svc._perf_weights == {}


@pytest.mark.asyncio
async def test_load_perf_weights_does_not_use_redis():
    """_load_perf_weights() must not call redis_client.get."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._perf_weights = {}
    svc.logger = MagicMock()

    # No Redis client set
    svc.redis_client = None

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool = mock_pool
    svc.db_manager = mock_db

    # Should not raise even without redis_client
    await svc._load_perf_weights()


@pytest.mark.asyncio
async def test_load_perf_weights_empty_table_leaves_empty_dict():
    """Empty setup_performance table → _perf_weights stays empty."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._perf_weights = {}
    svc.logger = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool = mock_pool
    svc.db_manager = mock_db

    await svc._load_perf_weights()
    assert svc._perf_weights == {}


# ---------------------------------------------------------------------------
# stream_keys.py: only topic_* builders + message_key remain
# ---------------------------------------------------------------------------


def test_stream_keys_has_no_setup_performance_weights_cache():
    """setup_performance_weights_cache must be removed from stream_keys."""
    import src.core.stream_keys as sk

    assert not hasattr(
        sk, "setup_performance_weights_cache"
    ), "setup_performance_weights_cache should be removed from stream_keys.py"


def test_stream_keys_has_no_drift_ks():
    """drift_ks must be removed from stream_keys."""
    import src.core.stream_keys as sk

    assert not hasattr(sk, "drift_ks"), "drift_ks should be removed from stream_keys.py"


def test_stream_keys_has_no_drift_cusum():
    """drift_cusum must be removed from stream_keys."""
    import src.core.stream_keys as sk

    assert not hasattr(sk, "drift_cusum"), "drift_cusum should be removed from stream_keys.py"


def test_stream_keys_has_no_get_stream_maxlen():
    """get_stream_maxlen must be removed from stream_keys."""
    import src.core.stream_keys as sk

    assert not hasattr(
        sk, "get_stream_maxlen"
    ), "get_stream_maxlen should be removed from stream_keys.py"


def test_stream_keys_has_no_quote_latest():
    """quote_latest must be removed from stream_keys."""
    import src.core.stream_keys as sk

    assert not hasattr(sk, "quote_latest"), "quote_latest should be removed from stream_keys.py"


def test_stream_keys_topic_builders_still_present():
    """All topic_* builders must remain in stream_keys."""
    import src.core.stream_keys as sk

    for fn in [
        "topic_market_ticks",
        "topic_market_bars",
        "topic_indicators",
        "topic_intelligence",
        "topic_intelligence_i7",
        "topic_intelligence_i8",
        "topic_signals",
        "topic_signals_aggregated",
        "topic_narratives",
        "topic_llm_calls",
        "topic_llm_outcomes",
        "message_key",
        "env_prefix",
    ]:
        assert hasattr(sk, fn), f"Expected {fn} to remain in stream_keys.py"
