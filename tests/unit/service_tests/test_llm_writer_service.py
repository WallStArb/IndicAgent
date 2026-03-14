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
