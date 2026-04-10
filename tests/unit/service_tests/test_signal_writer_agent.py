"""Unit tests for SignalWriterAgent.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, _payload_to_ledger_entries conversion, and flush behavior.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from prometheus_client import Counter, Gauge, Histogram

# Module-level test metrics to avoid duplicate registration
_TEST_EVENTS = Counter("test_swa_events_total", "Events (test)")
_TEST_SIGNALS = Counter("test_swa_signals_total", "Signals (test)")
_TEST_ERRORS = Counter("test_swa_errors_total", "Errors (test)")
_TEST_LATENCY = Histogram("test_swa_latency_seconds", "Latency (test)", ["agent"])
_TEST_LAG = Gauge("test_swa_lag", "Lag (test)", ["agent"])
_TEST_DEPTH = Gauge("test_swa_depth", "Depth (test)")


def _make_agent():
    """Build a minimal SignalWriterAgent bypassing __init__."""
    from services.signal_writer_agent import SignalWriterAgent

    agent = SignalWriterAgent.__new__(SignalWriterAgent)
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._consumer = MagicMock()
    agent._repo = MagicMock()
    agent._repo.insert_signals = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._events_consumed = _TEST_EVENTS
    agent._signals_written = _TEST_SIGNALS
    agent._write_errors = _TEST_ERRORS
    agent._batch_latency = _TEST_LATENCY.labels(agent="test")
    agent._consumer_lag = _TEST_LAG.labels(agent="test")
    agent._buffer_depth = _TEST_DEPTH
    return agent


def _make_payload(n_signals: int = 2, winner_idx: int = 0) -> dict:
    """Build a minimal intelligence.i7.signals payload."""
    signals = []
    for i in range(n_signals):
        signals.append({
            "signal_id": f"sig_{i}",
            "setup_plugin": f"trad_Plugin{i}",
            "signal_type": "long",
            "direction": 1,
            "entry_price": 5000.0 + i,
            "stop_loss": 4990.0,
            "targets": [5020.0],
            "confidence": 0.6 - i * 0.1,
            "confluence_score": 0.7,
            "regime_context": "trending",
            "supporting_factors": ["rsi_cross"],
            "was_selected": i == winner_idx,
            "num_signals_bar": n_signals,
            "composite_rank": i + 1,
            "status": "pending",
            "is_shadow": False,
            "pre_quality_confidence": 0.65,
            "pre_calibration_confidence": 0.62,
            "regime_type": "trend",
        })
    return {
        "symbol": "ES",
        "tf": "1m",
        "bar_ts": "2026-03-30T12:00:00+00:00",
        "computed_at": "2026-03-30T12:00:01+00:00",
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Structural contract
# ---------------------------------------------------------------------------


class TestSignalWriterAgentStructure:
    def test_consumer_group_constant(self):
        from services.signal_writer_agent import CONSUMER_GROUP

        assert CONSUMER_GROUP == "signal_writer_consumer"

    def test_batch_size_and_flush_interval_defined(self):
        from services.signal_writer_agent import BATCH_SIZE, FLUSH_INTERVAL_SECS

        assert BATCH_SIZE > 0
        assert FLUSH_INTERVAL_SECS > 0


# ---------------------------------------------------------------------------
# _payload_to_ledger_entries conversion
# ---------------------------------------------------------------------------


class TestPayloadToLedgerEntries:
    def test_returns_one_entry_per_signal(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=3)
        entries = _payload_to_ledger_entries(payload)
        assert len(entries) == 3

    def test_empty_signals_returns_empty(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries({"symbol": "ES", "tf": "1m", "signals": []})
        assert entries == []

    def test_winner_entry_was_selected_true(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=2, winner_idx=0)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].was_selected is True
        assert entries[1].was_selected is False

    def test_regime_suppressed_status_mapped(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "regime_suppressed"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.REGIME_SUPPRESSED

    def test_pending_status_mapped(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "pending"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.PENDING

    def test_missing_signal_id_gets_uuid(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        del payload["signals"][0]["signal_id"]
        entries = _payload_to_ledger_entries(payload)
        # Must be a valid UUID string
        UUID(entries[0].signal_id)

    def test_bar_ts_parsed_as_utc_datetime(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert isinstance(entries[0].timestamp, datetime)
        assert entries[0].timestamp.tzinfo is not None

    def test_symbol_tf_propagated(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].symbol == "ES"
        assert entries[0].timeframe == "1m"
        assert entries[0].feature_tf == "1m"

    def test_attribution_fields_preserved(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].pre_quality_confidence == pytest.approx(0.65)
        assert entries[0].pre_calibration_confidence == pytest.approx(0.62)

    def test_is_shadow_propagated(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["is_shadow"] = True
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].is_shadow is True

    def test_num_signals_bar_set_from_payload(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=3)
        entries = _payload_to_ledger_entries(payload)
        assert all(e.num_signals_bar == 3 for e in entries)

    def test_composite_rank_set(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        payload = _make_payload(n_signals=2)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].composite_rank == 1
        assert entries[1].composite_rank == 2


# ---------------------------------------------------------------------------
# Flush behavior
# ---------------------------------------------------------------------------


class TestSignalWriterAgentFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_insert_signals(self):
        from services.signal_writer_agent import _payload_to_ledger_entries

        agent = _make_agent()
        payload = _make_payload(n_signals=2)
        entries = _payload_to_ledger_entries(payload)
        agent._buffer.extend(entries)
        await agent._flush()
        agent._repo.insert_signals.assert_called_once_with(entries)
        assert agent._buffer == []

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        agent = _make_agent()
        await agent._flush()
        agent._repo.insert_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_error_increments_counter(self):
        agent = _make_agent()
        agent._repo.insert_signals = AsyncMock(side_effect=Exception("db down"))
        from services.signal_writer_agent import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(_make_payload(n_signals=1))
        agent._buffer.extend(entries)
        before = _TEST_ERRORS._value.get()
        await agent._flush()
        assert _TEST_ERRORS._value.get() > before
        # Buffer should NOT be cleared on error
        assert len(agent._buffer) == 1


# ---------------------------------------------------------------------------
# _parse_ts helper
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_parses_iso_with_tz(self):
        from services.signal_writer_agent import _parse_ts

        result = _parse_ts("2026-03-30T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_naive_gets_utc(self):
        from services.signal_writer_agent import _parse_ts

        result = _parse_ts("2026-03-30T12:00:00")
        assert result.tzinfo is not None

    def test_none_returns_none(self):
        from services.signal_writer_agent import _parse_ts

        assert _parse_ts(None) is None

    def test_invalid_returns_none(self):
        from services.signal_writer_agent import _parse_ts

        assert _parse_ts("not-a-date") is None
