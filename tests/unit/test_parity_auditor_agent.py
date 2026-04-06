"""Tests for ParityAuditorAgent lifecycle, _compare_cycle logic, and certification.

TDD RED phase — tests written before agent implementation.
Phase 52.5: ParityAuditorAgent
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Test 1: ParityAuditorAgent inherits BaseAgent ────────────────────────────


def test_parity_auditor_agent_inherits_base_agent():
    """Test 1: ParityAuditorAgent inherits BaseAgent."""
    from services.parity_auditor_agent import ParityAuditorAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(ParityAuditorAgent, BaseAgent)


# ── Test 2: Constants ─────────────────────────────────────────────────────────


def test_comparison_interval_and_threshold_constants():
    """Test 2: COMPARISON_INTERVAL_SECS == 300 and CERTIFICATION_THRESHOLD == 12."""
    from services.parity_auditor_agent import CERTIFICATION_THRESHOLD, COMPARISON_INTERVAL_SECS

    assert COMPARISON_INTERVAL_SECS == 300
    assert CERTIFICATION_THRESHOLD == 12


# ── Test 3: _compare_cycle skips primary-only rows ────────────────────────────


@pytest.mark.asyncio
async def test_compare_cycle_primary_only_rows_skipped():
    """Test 3: _compare_cycle joins rows by (ts, symbol, tf); primary-only rows are skipped."""
    from services.parity_auditor_agent import ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary_row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}
    # shadow has NO matching row

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(
        side_effect=[
            [primary_row],  # intelligence_features
            [],  # feature_snapshots_shadow — empty
        ]
    )
    mock_repo.insert_violations = AsyncMock()
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=0)
    agent._repo = mock_repo

    await agent._compare_cycle()

    # insert_violations should NOT be called (no matched rows to compare)
    mock_repo.insert_violations.assert_not_called()


# ── Test 4: shadow-only rows increment counter, not FieldViolation ────────────


@pytest.mark.asyncio
async def test_compare_cycle_shadow_only_rows_increment_counter():
    """Test 4: shadow-only rows increment shadow_ahead_rows_total counter, NOT FieldViolation."""
    from services.parity_auditor_agent import ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    shadow_row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}
    # primary has NO matching row

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(
        side_effect=[
            [],  # intelligence_features — empty
            [shadow_row],  # feature_snapshots_shadow — has row
        ]
    )
    mock_repo.insert_violations = AsyncMock()
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=0)
    agent._repo = mock_repo

    with patch("services.parity_auditor_agent.SHADOW_AHEAD_ROWS_TOTAL") as mock_counter:
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        await agent._compare_cycle()

        # Counter was incremented for shadow-only row
        mock_counter.labels.assert_called_with(symbol="ES", tf="1m")
        mock_labels.inc.assert_called_once()

    # insert_violations NOT called (no FieldViolation for shadow-only rows)
    mock_repo.insert_violations.assert_not_called()


# ── Test 5: matched rows with violations call insert_violations ───────────────


@pytest.mark.asyncio
async def test_compare_cycle_violations_stored():
    """Test 5: _compare_cycle matched rows with violations are stored via insert_violations."""
    from services.parity_auditor_agent import ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    primary_row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}
    shadow_row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.80}  # diverges

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(
        side_effect=[
            [primary_row],
            [shadow_row],
        ]
    )
    mock_repo.insert_violations = AsyncMock()
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=0)
    agent._repo = mock_repo

    await agent._compare_cycle()

    # insert_violations was called with the violation
    mock_repo.insert_violations.assert_called_once()
    violations, run_id = mock_repo.insert_violations.call_args[0]
    assert len(violations) == 1
    assert violations[0].field_name == "winner_confidence"
    assert isinstance(run_id, uuid.UUID)


# ── Test 6: parity_match_rate gauge emitted per (symbol, tf) ─────────────────


@pytest.mark.asyncio
async def test_compare_cycle_emits_parity_match_rate():
    """Test 6: _compare_cycle emits parity_match_rate gauge per (symbol, tf) pair."""
    from services.parity_auditor_agent import ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Two rows: one clean, one with violation
    primary_rows = [
        {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75, "session_type": "rth"},
        {
            "ts": datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC),
            "symbol": "ES",
            "tf": "1m",
            "winner_confidence": 0.80,
            "session_type": "rth",
        },
    ]
    shadow_rows = [
        {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75, "session_type": "rth"},
        {
            "ts": datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC),
            "symbol": "ES",
            "tf": "1m",
            "winner_confidence": 0.99,
            "session_type": "rth",
        },  # diverges
    ]

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(side_effect=[primary_rows, shadow_rows])
    mock_repo.insert_violations = AsyncMock()
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=0)
    agent._repo = mock_repo

    with patch("services.parity_auditor_agent.PARITY_MATCH_RATE") as mock_gauge:
        mock_labels = MagicMock()
        mock_gauge.labels.return_value = mock_labels

        await agent._compare_cycle()

        mock_gauge.labels.assert_called_with(symbol="ES", tf="1m")
        # match_rate = 1 clean / 2 matched = 0.5
        mock_labels.set.assert_called_with(0.5)


# ── Test 7: certification uses fetch_clean_cycles, not in-memory counters ─────


@pytest.mark.asyncio
async def test_compare_cycle_certification_uses_fetch_clean_cycles():
    """Test 7: Certification check uses fetch_clean_cycles (derived) not in-memory counters."""
    from services.parity_auditor_agent import CERTIFICATION_THRESHOLD, ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(side_effect=[[row], [row]])
    mock_repo.insert_violations = AsyncMock()
    # Return NOT certified — not enough clean cycles
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=5)
    agent._repo = mock_repo

    await agent._compare_cycle()

    # fetch_clean_cycles was called for (ES, 1m) with CERTIFICATION_THRESHOLD
    mock_repo.fetch_clean_cycles.assert_called_once_with("ES", "1m", CERTIFICATION_THRESHOLD)
    # NOT certified — no SHADOW_PARITY_CERTIFIED event published
    agent._producer.send_and_wait.assert_not_called()


# ── Test 8: all pairs certified publishes SHADOW_PARITY_CERTIFIED ────────────


@pytest.mark.asyncio
async def test_compare_cycle_publishes_certified_when_all_pairs_clean():
    """Test 8: All pairs reaching CERTIFICATION_THRESHOLD clean cycles triggers certification."""
    from services.parity_auditor_agent import CERTIFICATION_THRESHOLD, ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._settings.kafka_bootstrap_servers = "localhost:9092"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    row = {"ts": ts, "symbol": "ES", "tf": "1m", "winner_confidence": 0.75}

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(side_effect=[[row], [row]])  # identical rows
    mock_repo.insert_violations = AsyncMock()
    # All clean — returns CERTIFICATION_THRESHOLD
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=CERTIFICATION_THRESHOLD)
    agent._repo = mock_repo

    from src.core.stream_keys import topic_system_events

    expected_topic = topic_system_events("development")

    await agent._compare_cycle()

    # SHADOW_PARITY_CERTIFIED published to topic_system_events
    agent._producer.send_and_wait.assert_called_once()
    call_kwargs = agent._producer.send_and_wait.call_args
    assert call_kwargs[0][0] == expected_topic
    assert call_kwargs[1]["key"] == b"parity_certification"


# ── Test 9: Agent uses port :9120 ─────────────────────────────────────────────


def test_agent_uses_port_9133():
    """Test 9: Agent uses port :9133 (per D-04/D-08)."""
    from services.parity_auditor_agent import METRICS_PORT

    assert METRICS_PORT == 9133


# ── Test 10: Comparison window is 10 minutes (2x COMPARISON_INTERVAL_SECS) ───


@pytest.mark.asyncio
async def test_compare_cycle_uses_10_minute_window():
    """Test 10: Comparison window is time-based: since = NOW() - 10 minutes."""
    from services.parity_auditor_agent import ParityAuditorAgent

    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent.logger = MagicMock()
    agent.logger.info = MagicMock()
    agent.logger.debug = MagicMock()
    agent.logger.error = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "development"
    agent._producer = AsyncMock()
    agent._producer.send_and_wait = AsyncMock()

    mock_repo = AsyncMock()
    mock_repo.fetch_window = AsyncMock(return_value=[])
    mock_repo.insert_violations = AsyncMock()
    mock_repo.fetch_clean_cycles = AsyncMock(return_value=0)
    agent._repo = mock_repo

    # Capture the 'since' and 'until' timestamps passed to fetch_window
    captured = {}

    async def capture_fetch_window(table_name, since, until):
        captured["since"] = since
        captured["until"] = until
        return []

    mock_repo.fetch_window = capture_fetch_window

    await agent._compare_cycle()

    since = captured["since"]
    until = captured["until"]

    # Window should be ~10 minutes
    window_seconds = (until - since).total_seconds()
    assert 590 <= window_seconds <= 610, f"Expected ~600s window, got {window_seconds}s"
