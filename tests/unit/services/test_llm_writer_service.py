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


def test_upsert_i8_sql_is_upsert():
    """_UPSERT_I8_SQL must be an INSERT ... ON CONFLICT DO UPDATE targeting intelligence_ai_enrichment."""
    from services.llm_writer_service import _UPSERT_I8_SQL  # type: ignore[import]

    assert _UPSERT_I8_SQL.strip().startswith(
        "INSERT"
    ), "_UPSERT_I8_SQL must use INSERT ON CONFLICT (AI-SEP-01 separation)"
    assert "intelligence_ai_enrichment" in _UPSERT_I8_SQL
    assert "ON CONFLICT" in _UPSERT_I8_SQL


def test_process_i8_message_buffers_correctly():
    """_process_i8_message appends a 4-tuple (ts_dt, symbol, tf, i8_dict) to _i8_buffer.

    After AI-SEP-01: the 4th element is a dict (not a JSON string) — asyncpg handles
    JSONB serialization directly so json.dumps() is no longer needed (CLAUDE.md rule).
    """
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

    asyncio.run(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 1
    ts_dt, symbol, tf, i8_dict = svc._i8_buffer[0]
    assert symbol == "ES"
    assert tf == "1m"
    # After AI-SEP-01: stored as dict (asyncpg handles JSONB), not JSON string
    assert isinstance(i8_dict, dict), f"Expected dict, got {type(i8_dict)}"
    assert i8_dict["model"] == "qwen3.5:9b"


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

    asyncio.run(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 0, "Missing ts should not append to buffer"


# ---------------------------------------------------------------------------
# Phase-105 regression tests for LLMWriterAgent
# ---------------------------------------------------------------------------


def _make_llm_writer():
    """Build LLMWriterAgent using __new__ (bypasses __init__ for unit testing)."""
    import asyncio
    from unittest.mock import MagicMock

    from services.llm_writer_service import LLMWriterAgent

    w = LLMWriterAgent.__new__(LLMWriterAgent)
    w.name = "llm_writer_agent"
    w._stop_event = asyncio.Event()
    w.logger = MagicMock()
    w.settings = MagicMock(
        env_name="dev",
        kafka_bootstrap_servers="localhost:9092",
        database_url="postgresql://test",
    )
    # env_name is a property on BaseDaemon (derived from settings.env_name)
    # so we do not set it directly
    w._buffer = []
    w._i8_buffer = []
    w._consumer = None
    w.db_manager = None
    w._total_calls = 0
    w._total_outcomes = 0
    w._total_batches = 0
    w._error_count = 0
    w._last_score_recompute = 0.0
    w._kafka_bootstrap = "localhost:9092"
    w.config = {
        "database": {"dsn": "postgresql://test"},
        "service": {},
        "logging": {"level": "INFO", "file": "logs/test.log"},
    }
    # Counter mocks
    w.calls_consumed_total = MagicMock()
    w.outcomes_processed_total = MagicMock()
    w.batch_writes_total = MagicMock()
    w.score_recomputes_total = MagicMock()
    w.error_count_total = MagicMock()
    w.buffer_size_gauge = MagicMock()
    w.service_uptime_seconds = MagicMock()
    w.i8_writes_total = MagicMock()
    w.i8_update_miss_total = MagicMock()
    # BaseWriter attributes
    w._batch_latency_attrs = {"agent_id": "llm_writer"}
    from unittest.mock import MagicMock

    w._buffer_depth_gauge = MagicMock()
    w._buffer_overflow_total = MagicMock()
    w._parse_failures_total = MagicMock()
    w._flush_errors_total = MagicMock()
    w._flush_latency = MagicMock()
    w._commit_latency = MagicMock()
    w._commit_errors_total = MagicMock()
    return w


def test_llm_writer_no_self_pool_attribute() -> None:
    """LLMWriterAgent must not have a self._pool attribute.

    Phase-105 HF-3: self._pool was a ghost reference — DatabaseManager was used
    correctly via self.db_manager, but a stale self._pool assignment would shadow it.
    Regression: the parse-update path (execute_command) must run without AttributeError.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    w = _make_llm_writer()

    # db_manager.execute_command is the correct path (no _pool needed)
    mock_db = MagicMock()
    mock_db.execute_command = AsyncMock(return_value=None)
    w.db_manager = mock_db

    parse_update_payload = {
        "_parse_update": True,
        "call_id": "550e8400-e29b-41d4-a716-446655440000",
        "parse_success": False,
    }

    # Must not raise AttributeError on _pool
    asyncio.run(w._process_calls_message(parse_update_payload))

    # Assert db_manager.execute_command was awaited with correct args
    mock_db.execute_command.assert_awaited_once()
    call_args = mock_db.execute_command.await_args
    # First positional arg is the SQL string
    from services.llm_writer_service import _UPDATE_PARSE_SQL

    assert (
        call_args[0][0] == _UPDATE_PARSE_SQL
    ), "execute_command must be called with _UPDATE_PARSE_SQL as first arg"

    # Ensure no _pool attribute is present (the stale reference should be gone)
    assert not hasattr(
        w, "_pool"
    ), "LLMWriterAgent must not have a self._pool attribute — db_manager is the correct path"


def test_llm_writer_i8_writes_uses_add_not_inc() -> None:
    """i8_writes_total.add() must be called (never .inc()) when i8 batch is flushed.

    Phase-105 HF-3: OTel counters expose .add() not .inc(). .inc() raises AttributeError.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    w = _make_llm_writer()

    # Set up a minimal i8 batch
    from datetime import UTC, datetime

    w._i8_buffer = [
        (datetime(2026, 1, 1, tzinfo=UTC), "ES", "1m", {"model": "test"}),
    ]

    mock_db = MagicMock()
    mock_db.execute_batch = AsyncMock(return_value=None)
    w.db_manager = mock_db

    mock_i8_writes = MagicMock()
    w.i8_writes_total = mock_i8_writes

    asyncio.run(w._flush_i8())

    # .add() must be called with the batch length
    mock_i8_writes.add.assert_called_once_with(1)
    # .inc() must never be called
    assert (
        not mock_i8_writes.inc.called
    ), "OTel counter i8_writes_total must use .add(), never .inc()"


@pytest.mark.asyncio
async def test_llm_writer_process_loop_calls_record_message_consumed() -> None:
    """_process_loop() must call _record_message_consumed() for each consumed message.

    Phase-105 HF-5 regression: _record_message_consumed() updates the stall clock
    and liveness gauge for stall detection.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    w = _make_llm_writer()

    valid_payload = {
        "call_id": "550e8400-e29b-41d4-a716-446655440001",
        "called_at": "2026-01-01T09:30:00Z",
        "symbol": "ES",
    }

    async def one_message():
        yield ("dev.llm.calls", None, valid_payload)

    mock_consumer = MagicMock()
    mock_consumer.messages = one_message
    w._consumer = mock_consumer

    recorded_calls = []

    def spy_record():
        recorded_calls.append(1)

    w._record_message_consumed = spy_record

    with (
        patch.object(w, "_process_calls_message", new_callable=AsyncMock, return_value=True),
        patch.object(w, "maybe_flush", new_callable=AsyncMock),
    ):
        await w._process_loop()

    assert len(recorded_calls) == 1, (
        "_record_message_consumed() must be called once per consumed message "
        "for stall detection liveness tracking"
    )


def test_llm_writer_kafka_setup_uses_earliest_and_no_auto_commit() -> None:
    """KafkaConsumerClient must be constructed with auto_offset_reset='earliest' and enable_auto_commit=False.

    Phase-105 HF-6 + HF-7: earliest ensures no message loss on restart; disable
    auto-commit prevents advancing offsets before successful DB write.
    """
    import inspect

    import services.llm_writer_service as mod

    source = inspect.getsource(mod.LLMWriterAgent._setup_kafka_clients)
    assert (
        'auto_offset_reset="earliest"' in source
    ), "LLMWriterAgent._setup_kafka_clients() must set auto_offset_reset='earliest'"
    assert (
        "enable_auto_commit=False" in source
    ), "LLMWriterAgent._setup_kafka_clients() must set enable_auto_commit=False"


def test_llm_writer_subscribes_only_to_calls_topic() -> None:
    """LLMWriterAgent must subscribe only to the llm.calls topic (not llm.outcomes or intelligence.i8).

    Phase-105 HF-10: llm.outcomes and intelligence.i8 had no active publishers as of
    2026-05-23 audit. Dead subscriptions waste consumer group resources.
    Regression: only the calls topic should be in the consumer subscription.
    """
    import inspect

    import services.llm_writer_service as mod

    source = inspect.getsource(mod.LLMWriterAgent._setup_kafka_clients)

    # Strip comment lines before checking — the comment may reference removed topics
    non_comment_lines = "\n".join(
        ln for ln in source.splitlines() if not ln.strip().startswith("#")
    )

    # llm.calls must be in the subscription (actual code, not a comment)
    assert (
        "topic_llm_calls" in non_comment_lines
    ), "LLMWriterAgent._setup_kafka_clients() must subscribe to topic_llm_calls"

    # topic_llm_outcomes must not appear in actual code (only comments are OK)
    assert "topic_llm_outcomes" not in non_comment_lines, (
        "LLMWriterAgent._setup_kafka_clients() must NOT subscribe to llm.outcomes "
        "(no active publishers as of 2026-05-23 audit)"
    )


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

    asyncio.run(svc._process_i8_message(payload))

    assert len(svc._i8_buffer) == 1
    ts_dt = svc._i8_buffer[0][0]
    assert isinstance(ts_dt, datetime), f"Expected datetime, got {type(ts_dt)}"
    assert ts_dt.tzinfo is not None, "Timestamp must be timezone-aware"


def test_i8_buffer_flushed_on_shutdown():
    """_flush_i8 calls execute_batch with _UPSERT_I8_SQL and buffer contents (AI-SEP-01)."""
    import asyncio
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock

    from services.llm_writer_service import _UPSERT_I8_SQL, LLMWriterService  # type: ignore[import]

    svc = LLMWriterService.__new__(LLMWriterService)
    svc._i8_buffer = [
        (datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC), "ES", "1m", {"model": "test"}),
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

    asyncio.run(svc._flush_i8())

    mock_db.execute_batch.assert_called_once()
    call_args = mock_db.execute_batch.call_args
    assert call_args[0][0] == _UPSERT_I8_SQL
    assert len(svc._i8_buffer) == 0, "Buffer should be cleared after flush"


# ---------------------------------------------------------------------------
# Phase 68-04: Symbol-keyed LLM model scores
# ---------------------------------------------------------------------------


class TestLlmModelScoresSymbol:
    """Test llm_model_scores SQL includes symbol dimension."""

    def test_select_outcome_rows_includes_symbol(self):
        """_SELECT_OUTCOME_ROWS_SQL includes symbol in SELECT and GROUP BY."""
        from services.llm_writer_service import _SELECT_OUTCOME_ROWS_SQL

        assert "symbol" in _SELECT_OUTCOME_ROWS_SQL
        assert "GROUP BY model, regime, setup_type, call_type, symbol" in _SELECT_OUTCOME_ROWS_SQL

    def test_upsert_score_sql_includes_symbol(self):
        """_UPSERT_SCORE_SQL includes symbol column and ON CONFLICT with symbol."""
        from services.llm_writer_service import _UPSERT_SCORE_SQL

        assert "symbol" in _UPSERT_SCORE_SQL
        assert "ON CONFLICT (model, regime, setup_type, call_type, symbol)" in _UPSERT_SCORE_SQL

    @pytest.mark.asyncio
    async def test_recompute_scores_passes_symbol_in_params(self):
        """_recompute_scores passes symbol from row as 5th param in upsert tuple."""
        from unittest.mock import AsyncMock, MagicMock

        from services.llm_writer_service import _UPSERT_SCORE_SQL, LLMWriterService

        svc = LLMWriterService.__new__(LLMWriterService)
        svc.db_manager = AsyncMock()
        svc.score_recomputes_total = MagicMock()
        svc.logger = __import__("structlog").get_logger()
        svc._error_count = 0
        svc.error_count_total = MagicMock()

        # fetch is called twice: first for aggregate rows, second for confidence rows
        aggregate_rows = [
            {
                "model": "test_model",
                "regime": "trending",
                "setup_type": "trad_TrendFollowing",
                "call_type": "per_signal",
                "symbol": "ES",
                "n_calls": 50,
                "n_outcomes": 50,
                "win_rate": 0.60,
                "avg_pnl_r": 0.5,
                "avg_latency_ms": 200.0,
            },
        ]
        svc.db_manager.fetch = AsyncMock(side_effect=[aggregate_rows, []])
        svc.db_manager.execute_batch = AsyncMock()

        await svc._recompute_scores()

        svc.db_manager.execute_batch.assert_called_once()
        call_args = svc.db_manager.execute_batch.call_args
        assert call_args[0][0] == _UPSERT_SCORE_SQL
        params = call_args[0][1]
        assert len(params) == 1
        # 5th element (index 4) should be symbol
        assert params[0][4] == "ES"

    @pytest.mark.asyncio
    async def test_recompute_scores_defaults_symbol_to_star_when_null(self):
        """_recompute_scores defaults symbol to '*' when row has no symbol."""
        from unittest.mock import AsyncMock, MagicMock

        from services.llm_writer_service import LLMWriterService

        svc = LLMWriterService.__new__(LLMWriterService)
        svc.db_manager = AsyncMock()
        svc.score_recomputes_total = MagicMock()
        svc.logger = __import__("structlog").get_logger()
        svc._error_count = 0
        svc.error_count_total = MagicMock()

        # fetch is called twice: first for aggregate rows, second for confidence rows
        aggregate_rows = [
            {
                "model": "test_model",
                "regime": "trending",
                "setup_type": "trad_TrendFollowing",
                "call_type": "per_signal",
                "symbol": None,
                "n_calls": 50,
                "n_outcomes": 50,
                "win_rate": 0.60,
                "avg_pnl_r": 0.5,
                "avg_latency_ms": 200.0,
            },
        ]
        svc.db_manager.fetch = AsyncMock(side_effect=[aggregate_rows, []])
        svc.db_manager.execute_batch = AsyncMock()

        await svc._recompute_scores()

        params = svc.db_manager.execute_batch.call_args[0][1]
        assert params[0][4] == "*"


# ---------------------------------------------------------------------------
# Phase 78-04: Probabilistic calibration metrics (D-27, D-28)
# ---------------------------------------------------------------------------


class TestCalibrationMetrics:
    """Tests for _brier_score, _calibration_slope, and _ece helper functions."""

    def test_brier_perfect(self):
        """Brier score is 0.0 when confidence == outcome (perfect prediction)."""
        import numpy as np

        from services.llm_writer_service import _brier_score

        conf = np.array([0.0, 0.5, 1.0, 0.3, 0.8])
        outcome = np.array([0.0, 0.5, 1.0, 0.3, 0.8])
        assert _brier_score(conf, outcome) == pytest.approx(0.0, abs=1e-9)

    def test_brier_worst(self):
        """Brier score is 1.0 when confidence=0 but outcome=1 (worst possible)."""
        import numpy as np

        from services.llm_writer_service import _brier_score

        conf = np.array([0.0, 0.0, 0.0])
        outcome = np.array([1.0, 1.0, 1.0])
        assert _brier_score(conf, outcome) == pytest.approx(1.0, abs=1e-9)

    def test_calibration_slope_perfect(self):
        """Calibration slope is approximately 1.0 for perfectly calibrated predictions."""
        import numpy as np

        from services.llm_writer_service import _calibration_slope

        rng = np.random.default_rng(42)
        conf = rng.uniform(0.1, 0.9, 50)
        # outcomes = confidence + small noise (perfectly calibrated)
        outcome = np.clip(conf + rng.normal(0, 0.05, 50), 0.0, 1.0)
        slope = _calibration_slope(conf, outcome)
        assert slope is not None
        assert abs(slope - 1.0) < 0.3

    def test_calibration_slope_zero_variance(self):
        """Calibration slope is None when all confidences are identical (zero variance)."""
        import numpy as np

        from services.llm_writer_service import _calibration_slope

        conf = np.full(20, 0.7)
        outcome = np.array([1.0, 0.0] * 10)
        slope = _calibration_slope(conf, outcome)
        assert slope is None

    def test_ece_perfect(self):
        """ECE is 0.0 when mean confidence in each bin equals mean accuracy."""
        import numpy as np

        from services.llm_writer_service import _ece

        # Build data where confidence == outcome within each bin
        # Use midpoints of each bin for both confidence and outcome
        conf = np.array([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
        outcome = np.array([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
        assert _ece(conf, outcome) == pytest.approx(0.0, abs=1e-9)

    def test_ece_overconfident(self):
        """ECE is 0.9 when confidence=1.0 (all in top bin) but all outcomes are 0."""
        import numpy as np

        from services.llm_writer_service import _ece

        # All in last bin [0.9, 1.0], confidence mean = 1.0, outcome mean = 0.0
        # weight = N/N = 1.0, |1.0 - 0.0| = 1.0, but conf is 1.0 so it falls in last bin
        # ECE = (N/N) * |mean_conf - mean_outcome| = 1.0 * |1.0 - 0.0| = 1.0
        # But since conf=0.9 (within [0.9,1.0)), conf mean=0.9, outcome=0 → ECE=0.9
        conf = np.full(100, 0.9)
        outcome = np.zeros(100)
        result = _ece(conf, outcome)
        assert result == pytest.approx(0.9, abs=1e-9)
