"""TDD RED tests for llm_writer_service — stream key helpers and pure logic functions.

Phase 16-01: Schema foundation. These tests define the expected behaviour of functions
that will be implemented in services/llm_writer_service.py.

All imports from services.llm_writer_service will raise ImportError / ModuleNotFoundError
at this stage — that is the expected RED state confirming the contract before implementation.

Stream key tests import from src.core.stream_keys (already implemented in this plan).
"""

import pytest

# ── Stream key helpers (implemented in stream_keys.py) ────────────────────────


def test_llm_calls_stream_key_format():
    from src.core.stream_keys import llm_calls_stream

    assert llm_calls_stream("development:") == "development:llm_calls:stream"
    assert llm_calls_stream("production:") == "production:llm_calls:stream"
    assert llm_calls_stream("") == "llm_calls:stream"


def test_llm_outcomes_stream_key_format():
    from src.core.stream_keys import llm_outcomes_stream

    assert llm_outcomes_stream("development:") == "development:llm_outcomes:stream"
    assert llm_outcomes_stream("") == "llm_outcomes:stream"


# test_llm_scores_cache_key_format removed — llm_scores_cache removed in Phase 30
# test_get_stream_maxlen_llm_calls removed — get_stream_maxlen removed in Phase 30
# test_get_stream_maxlen_llm_outcomes removed — get_stream_maxlen removed in Phase 30


# ── Pure functions from llm_writer_service (NOT YET IMPLEMENTED — RED) ────────
#
# These imports will fail until services/llm_writer_service.py is created in Plan 16-02.
# Failure mode: ModuleNotFoundError or ImportError — both are valid RED states.


def test_parse_llm_call_fields_valid():
    """_parse_llm_call_fields returns a dict with all required keys for a full payload."""
    from services.llm_writer_service import _parse_llm_call_fields  # type: ignore[import]

    fields = {
        b"call_id": b"550e8400-e29b-41d4-a716-446655440000",
        b"called_at": b"2026-03-05T10:00:00+00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"call_type": b"per_signal",
        b"model": b"qwen3.5:9b",
        b"provider": b"ollama",
        b"prompt": b"Analyze this setup...",
        b"latency_ms": b"342",
        b"succeeded": b"true",
        b"regime": b"trending",
    }
    result = _parse_llm_call_fields(fields)
    assert result is not None
    assert result["call_id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert result["symbol"] == "ESH6"
    assert result["latency_ms"] == 342
    assert result["succeeded"] is True


def test_parse_llm_call_fields_missing_required_returns_none():
    """_parse_llm_call_fields returns None when call_id, called_at, or symbol is absent."""
    from services.llm_writer_service import _parse_llm_call_fields  # type: ignore[import]

    # Missing call_id
    fields_no_call_id = {
        b"called_at": b"2026-03-05T10:00:00+00:00",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
    }
    assert _parse_llm_call_fields(fields_no_call_id) is None

    # Missing called_at
    fields_no_ts = {
        b"call_id": b"550e8400-e29b-41d4-a716-446655440000",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
    }
    assert _parse_llm_call_fields(fields_no_ts) is None

    # Missing symbol
    fields_no_symbol = {
        b"call_id": b"550e8400-e29b-41d4-a716-446655440000",
        b"called_at": b"2026-03-05T10:00:00+00:00",
        b"timeframe": b"5m",
    }
    assert _parse_llm_call_fields(fields_no_symbol) is None


def test_parse_outcome_fields_valid():
    """_parse_outcome_fields returns dict with outcome keys for a full payload."""
    from services.llm_writer_service import _parse_outcome_fields  # type: ignore[import]

    fields = {
        b"signal_id": b"a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        b"outcome": b"target_1",
        b"pnl_r": b"1.23",
        b"mae": b"0.42",
        b"mfe": b"1.85",
        b"bars_in_trade": b"7",
        b"outcome_at": b"2026-03-05T11:30:00+00:00",
    }
    result = _parse_outcome_fields(fields)
    assert result is not None
    assert result["signal_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert result["outcome"] == "target_1"
    assert abs(result["pnl_r"] - 1.23) < 1e-9
    assert result["bars_in_trade"] == 7


def test_parse_outcome_fields_missing_signal_id_returns_none():
    """_parse_outcome_fields returns None when signal_id is absent."""
    from services.llm_writer_service import _parse_outcome_fields  # type: ignore[import]

    fields = {
        b"outcome": b"stopped_in_trade",
        b"pnl_r": b"-1.0",
        b"mae": b"1.1",
        b"mfe": b"0.3",
        b"bars_in_trade": b"3",
    }
    assert _parse_outcome_fields(fields) is None


def test_build_score_insert_params_below_min_n_not_significant():
    """With n < 30, is_significant must be False regardless of p_value."""
    from services.llm_writer_service import _build_score_insert_params  # type: ignore[import]

    # Simulate 10 rows, p_value would be irrelevant
    rows = [
        {"pnl_r": 0.5, "win": True},
        {"pnl_r": -1.0, "win": False},
        {"pnl_r": 1.2, "win": True},
        {"pnl_r": 0.8, "win": True},
        {"pnl_r": -0.5, "win": False},
        {"pnl_r": 1.0, "win": True},
        {"pnl_r": -1.0, "win": False},
        {"pnl_r": 0.3, "win": True},
        {"pnl_r": 2.1, "win": True},
        {"pnl_r": -0.8, "win": False},
    ]
    result = _build_score_insert_params(
        model="qwen3.5:9b",
        regime="trending",
        setup_type="BullishEngulfing",
        call_type="per_signal",
        rows=rows,
    )
    assert result is not None
    assert result["n_outcomes"] == 10
    assert result["is_significant"] is False  # n < 30 gate


def test_build_score_insert_params_meets_gate_significant():
    """With n >= 30 and p < 0.05, is_significant must be True."""
    from services.llm_writer_service import _build_score_insert_params  # type: ignore[import]

    # 35 wins out of 35 — strong signal, p << 0.05
    rows = [{"pnl_r": 1.0, "win": True}] * 35
    result = _build_score_insert_params(
        model="qwen3.5:9b",
        regime="trending",
        setup_type="__all__",
        call_type="per_signal",
        rows=rows,
    )
    assert result is not None
    assert result["n_outcomes"] == 35
    assert result["win_rate"] == pytest.approx(1.0)
    assert result["is_significant"] is True


def test_build_score_insert_params_high_p_not_significant():
    """With n >= 30 but p >= 0.05, is_significant must be False."""
    from services.llm_writer_service import _build_score_insert_params  # type: ignore[import]

    # 40 rows, exactly 50% win rate — p ≈ 1.0, clearly not significant
    rows = [{"pnl_r": 1.0, "win": True}] * 20 + [{"pnl_r": -1.0, "win": False}] * 20
    result = _build_score_insert_params(
        model="qwen3.5:9b",
        regime="ranging",
        setup_type="__all__",
        call_type="per_signal",
        rows=rows,
    )
    assert result is not None
    assert result["n_outcomes"] == 40
    assert result["is_significant"] is False  # p >= 0.05


# ── i8 UPSERT wiring tests (TDD RED — will fail until implementation added) ──


def test_upsert_i8_sql_is_update_not_insert():
    """_UPDATE_I8_SQL must start with UPDATE (not INSERT) to avoid phantom rows."""
    from services.llm_writer_service import _UPDATE_I8_SQL  # type: ignore[import]

    assert _UPDATE_I8_SQL.strip().startswith("UPDATE"), (
        "_UPDATE_I8_SQL must use UPDATE not INSERT ON CONFLICT to avoid phantom rows"
    )


def test_process_i8_message_buffers_correctly():
    """_process_i8_message appends a 4-tuple (ts_dt, symbol, tf, i8_json) to _i8_buffer."""
    import asyncio

    from services.llm_writer_service import LLMWriterService  # type: ignore[import]

    svc = LLMWriterService.__new__(LLMWriterService)
    svc._i8_buffer = []
    svc.logger = __import__("structlog").get_logger()

    payload = {
        "ts": "2026-03-21T10:00:00+00:00",
        "symbol": "ES",
        "tf": "1m",
        "model": "qwen3.5:9b",
        "confidence": "0.75",
        "summary": "Bullish breakout expected",
        "generated_at": "2026-03-21T10:00:01+00:00",
    }

    asyncio.get_event_loop().run_until_complete(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 1
    ts_dt, symbol, tf, i8_json = svc._i8_buffer[0]
    assert symbol == "ES"
    assert tf == "1m"
    import json as _json
    parsed = _json.loads(i8_json)
    assert parsed["model"] == "qwen3.5:9b"


def test_process_i8_message_missing_ts_logs_warning():
    """_process_i8_message with no ts field should NOT append to _i8_buffer."""
    import asyncio

    from services.llm_writer_service import LLMWriterService  # type: ignore[import]

    svc = LLMWriterService.__new__(LLMWriterService)
    svc._i8_buffer = []
    svc.logger = __import__("structlog").get_logger()

    payload = {
        "symbol": "ES",
        "tf": "1m",
        "model": "qwen3.5:9b",
    }

    asyncio.get_event_loop().run_until_complete(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 0, "Missing ts should not append to buffer"


def test_process_i8_message_uses_parse_ts():
    """_process_i8_message uses _parse_ts for timestamp parsing (returns datetime, not str)."""
    import asyncio
    from datetime import datetime

    from services.llm_writer_service import LLMWriterService  # type: ignore[import]

    svc = LLMWriterService.__new__(LLMWriterService)
    svc._i8_buffer = []
    svc.logger = __import__("structlog").get_logger()

    payload = {
        "ts": "2026-03-21T10:00:00+00:00",
        "symbol": "NQ",
        "tf": "5m",
        "model": "test",
    }

    asyncio.get_event_loop().run_until_complete(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 1
    ts_dt = svc._i8_buffer[0][0]
    assert isinstance(ts_dt, datetime), f"Expected datetime, got {type(ts_dt)}"
    assert ts_dt.tzinfo is not None, "Timestamp must be timezone-aware"


def test_i8_buffer_flushed_on_shutdown():
    """_flush_i8 calls execute_batch with _UPDATE_I8_SQL and buffer contents."""
    import asyncio
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock

    from services.llm_writer_service import _UPDATE_I8_SQL, LLMWriterService  # type: ignore[import]

    svc = LLMWriterService.__new__(LLMWriterService)
    svc._i8_buffer = [
        (datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC), "ES", "1m", '{"model": "test"}'),
    ]
    svc.logger = __import__("structlog").get_logger()

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.executemany = AsyncMock(return_value=None)

    # Set up db_manager mock
    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock(return_value=None)
    svc.db_manager = mock_db

    # Set up metrics
    svc.i8_writes_total = MagicMock()
    svc.i8_writes_total.inc = MagicMock()
    svc.i8_update_miss_total = MagicMock()

    asyncio.get_event_loop().run_until_complete(svc._flush_i8())

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    assert call_args[0][0] == _UPDATE_I8_SQL
    assert len(svc._i8_buffer) == 0, "Buffer should be cleared after flush"
