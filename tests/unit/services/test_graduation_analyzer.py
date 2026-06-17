"""Unit tests for GraduationAnalyzer.

Tests use the __new__ bypass pattern per CLAUDE.md to avoid hitting
__init__ infrastructure (asyncpg pool, Kafka clients, metrics registration).
"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from services.graduation_analyzer import (
    _EVAL_QUERY,
    CONSUMER_GROUP,
    GraduationAnalyzer,
)
from src.intelligence.swarm.graduation import EVAL_RESOLUTION_THRESHOLD

# ---------------------------------------------------------------------------
# Locked-constant tests
# ---------------------------------------------------------------------------


def test_consumer_group_locked():
    """Consumer group must not drift — coordinator depends on exact string."""
    assert CONSUMER_GROUP == "graduation_compute_group"


def test_eval_resolution_threshold_is_twenty():
    """Graduation gate: 20 new resolutions per segment before evaluation fires."""
    assert EVAL_RESOLUTION_THRESHOLD == 20


def test_eval_query_joins_signal_ledger():
    """_EVAL_QUERY must JOIN signal_ledger to obtain counterfactual_pnl_r outcome labels.

    Phase 127-00: outcome column dropped in 3-table migration; graduation now
    sources outcome from counterfactual_pnl_r (aliased AS pnl_r for the
    evaluate_all consumer). No-ops cleanly until v2.11 CounterfactualTracker
    populates counterfactual_pnl_r.
    """
    assert "JOIN signal_ledger" in _EVAL_QUERY
    assert "counterfactual_pnl_r" in _EVAL_QUERY
    assert "counterfactual_pnl_r IS NOT NULL" in _EVAL_QUERY


def test_eval_query_filters_by_transform_and_segment():
    """Query must filter by all three segment dimensions."""
    assert "transform_id" in _EVAL_QUERY
    assert "transform_version" in _EVAL_QUERY
    assert "segment_key" in _EVAL_QUERY


# ---------------------------------------------------------------------------
# Test fixture factory
# ---------------------------------------------------------------------------


def _make_agent() -> GraduationAnalyzer:
    """Bypass __init__ — set required attributes manually."""
    a = GraduationAnalyzer.__new__(GraduationAnalyzer)
    a.name = "GraduationAnalyzer"
    a.logger = MagicMock()
    a._pool = MagicMock()
    a._producer = AsyncMock()
    a._consumer = AsyncMock()
    a._counters = defaultdict(int)
    a._exits_consumed = MagicMock()
    a._evaluations_total = MagicMock()
    a._evaluation_errors = MagicMock()
    a.settings = MagicMock(env_name="dev")
    a._stop_event = MagicMock()
    a._stop_event.is_set.return_value = False
    a._dlq_attrs = {"agent_id": "GraduationAnalyzer"}
    return a


def _make_acquire_ctx(conn: MagicMock) -> MagicMock:
    """Build an async context manager that yields conn from pool.acquire()."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------------------
# _handle_transition — routing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_transition_skips_non_exit():
    """ACTIVATION transitions must not increment exits_consumed or query DB."""
    a = _make_agent()
    await a._handle_transition({"transition_type": "ACTIVATION", "signal_id": "s1"})
    a._exits_consumed.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_transition_skips_mae_mfe_update():
    """MAE_MFE_UPDATE transitions must not trigger any counter logic."""
    a = _make_agent()
    await a._handle_transition({"transition_type": "MAE_MFE_UPDATE", "signal_id": "s1"})
    a._exits_consumed.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_transition_skips_missing_signal_id():
    """EXIT without signal_id must not increment counters."""
    a = _make_agent()
    await a._handle_transition({"transition_type": "EXIT"})
    a._exits_consumed.add.assert_not_called()


@pytest.mark.asyncio
async def test_handle_transition_increments_counter_for_each_transform():
    """EXIT with two transform rows must increment both counters by 1."""
    a = _make_agent()
    rows = [
        {"transform_id": "hurst_quality", "transform_version": "v1", "segment_key": "trend.5m"},
        {"transform_id": "tod", "transform_version": "v1", "segment_key": "trend.5m.14"},
    ]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))

    await a._handle_transition({"transition_type": "EXIT", "signal_id": "abc"})

    assert a._counters[("hurst_quality", "v1", "trend.5m")] == 1
    assert a._counters[("tod", "v1", "trend.5m.14")] == 1
    a._exits_consumed.add.assert_called_once()


# ---------------------------------------------------------------------------
# Counter threshold + evaluation trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counter_threshold_triggers_evaluation():
    """When counter reaches EVAL_RESOLUTION_THRESHOLD, _evaluate_segment is called."""
    a = _make_agent()
    a._counters[("hurst_quality", "v1", "trend.5m")] = EVAL_RESOLUTION_THRESHOLD - 1

    rows = [{"transform_id": "hurst_quality", "transform_version": "v1", "segment_key": "trend.5m"}]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))
    a._evaluate_segment = AsyncMock()

    await a._handle_transition({"transition_type": "EXIT", "signal_id": "abc"})

    a._evaluate_segment.assert_awaited_once_with("hurst_quality", "v1", "trend.5m")
    # Counter must be reset to 0 after evaluation
    assert a._counters[("hurst_quality", "v1", "trend.5m")] == 0


@pytest.mark.asyncio
async def test_counter_below_threshold_does_not_evaluate():
    """Counter below threshold must not trigger _evaluate_segment."""
    a = _make_agent()
    a._counters[("hurst_quality", "v1", "trend.5m")] = EVAL_RESOLUTION_THRESHOLD - 2

    rows = [{"transform_id": "hurst_quality", "transform_version": "v1", "segment_key": "trend.5m"}]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))
    a._evaluate_segment = AsyncMock()

    await a._handle_transition({"transition_type": "EXIT", "signal_id": "abc"})

    a._evaluate_segment.assert_not_awaited()
    assert a._counters[("hurst_quality", "v1", "trend.5m")] == EVAL_RESOLUTION_THRESHOLD - 1


# ---------------------------------------------------------------------------
# _evaluate_segment — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_segment_publishes_to_kafka(monkeypatch):
    """Successful evaluation must publish GraduationResult to transform_graduation topic."""
    a = _make_agent()
    rows = [
        {"multiplier": 0.5, "pnl_r": 1.0, "ts": pd.Timestamp("2026-01-01")},
        {"multiplier": 0.9, "pnl_r": 2.0, "ts": pd.Timestamp("2026-01-02")},
    ]
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))

    fake_result = {
        "transform_id": "hurst_quality",
        "transform_version": "v1",
        "segment_key": "trend.5m",
        "n": 2,
        "spearman_rho": 0.5,
        "spearman_p": 0.1,
        "calibration_max_error": 0.05,
        "cvar_bottom_decile": -0.6,
        "mde": 0.4,
        "val_rho": 0.5,
        "overfitting_risk": False,
        "sharpe_delta": 0.2,
        "is_graduated": True,
        "evaluated_at": "2026-04-24T00:00:00Z",
        "expires_at": "2026-07-23T00:00:00Z",
    }
    monkeypatch.setattr(
        "services.graduation_analyzer.evaluate_all",
        lambda df, **kw: fake_result,
    )

    await a._evaluate_segment("hurst_quality", "v1", "trend.5m")

    a._producer.publish.assert_awaited_once()
    call = a._producer.publish.await_args
    # publish(topic, msg, key=...) — topic is first positional arg, msg is second
    topic = call.args[0]
    assert "intelligence.transform.graduation" in topic
    payload = call.args[1]
    assert isinstance(payload, dict)
    assert payload["is_graduated"] is True
    a._evaluations_total.add.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_segment_skips_when_no_rows(monkeypatch):
    """When DB returns no rows, evaluation must be skipped without error."""
    a = _make_agent()
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))

    eval_mock = MagicMock()
    monkeypatch.setattr("services.graduation_analyzer.evaluate_all", eval_mock)

    await a._evaluate_segment("hurst_quality", "v1", "trend.5m")

    eval_mock.assert_not_called()
    a._evaluations_total.add.assert_not_called()
    a._evaluation_errors.add.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_segment — error path / DLQ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_segment_dlq_on_db_exception():
    """DB failure during evaluation must increment error counter and publish to DLQ."""
    a = _make_agent()
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=RuntimeError("DB down"))
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))

    await a._evaluate_segment("hurst_quality", "v1", "trend.5m")

    a._evaluation_errors.add.assert_called_once()
    # DLQ publish must have been called
    assert a._producer.publish.await_count >= 1
    last_call = a._producer.publish.await_args_list[-1]
    dlq_topic = last_call.args[0]
    assert "dlq" in dlq_topic


@pytest.mark.asyncio
async def test_evaluate_segment_dlq_payload_contains_error():
    """DLQ payload must include error string and transform metadata."""
    a = _make_agent()
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))
    a._pool.acquire = MagicMock(return_value=_make_acquire_ctx(conn))

    await a._evaluate_segment("hurst_quality", "v1", "trend.5m")

    last_call = a._producer.publish.await_args_list[-1]
    dlq_payload = last_call.args[1]
    # DLQPayload schema: error_message field, original payload nested under "payload"
    assert "connection refused" in dlq_payload["error_message"]
    assert dlq_payload["payload"]["transform_id"] == "hurst_quality"
    assert dlq_payload["payload"]["segment_key"] == "trend.5m"
