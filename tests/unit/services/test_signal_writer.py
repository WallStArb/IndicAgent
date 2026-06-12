"""Unit tests for SignalWriter.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, _payload_to_ledger_entries conversion, and flush behavior.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    """Build a minimal SignalWriter bypassing __init__."""
    from services.signal_writer import SignalWriter

    agent = SignalWriter.__new__(SignalWriter)
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._consumer = AsyncMock()
    agent._repo = MagicMock()
    agent._repo.insert_signals = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._events_consumed = MagicMock()
    agent._signals_written = MagicMock()
    agent._write_errors = MagicMock()
    agent._batch_latency_attrs = {"agent_id": "signal_writer_agent"}
    agent._invalid_signals = []
    # OTel instruments below are mocked because __new__ bypasses BaseWriter.__init__.
    # _consumer_lag was removed from SignalWriter — do not add it back here.
    agent._buffer_depth_gauge = MagicMock()
    agent._buffer_overflow_total = MagicMock()
    agent._flush_latency = MagicMock()
    agent._commit_latency = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._commit_errors_total = MagicMock()
    return agent


def _make_payload(n_signals: int = 2, winner_idx: int = 0) -> dict:
    """Build a minimal intelligence.i7.signals payload."""
    signals = []
    for i in range(n_signals):
        signals.append(
            {
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
                "status": "pending",
                "is_shadow": False,
                "filtered_cis_score": 0.72,
                "bucket_scores": {"trend": 0.8, "momentum": 0.6},
                "weights_version": 3,
                "regime_type": "trend",
            }
        )
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


class TestSignalWriterStructure:
    def test_consumer_group_constant(self):
        from services.signal_writer import CONSUMER_GROUP

        assert CONSUMER_GROUP == "signal_writer_group"

    def test_batch_size_and_flush_interval_defined(self):
        """BATCH_SIZE and FLUSH_INTERVAL_SECS are class-level on BaseWriter subclass."""
        from services.signal_writer import SignalWriter

        assert SignalWriter.BATCH_SIZE > 0
        assert SignalWriter.FLUSH_INTERVAL_SECS > 0

    def test_inherits_base_writer_agent(self):
        from services.signal_writer import SignalWriter
        from src.core.agent.base_writer import BaseWriter

        assert issubclass(SignalWriter, BaseWriter)


# ---------------------------------------------------------------------------
# _payload_to_ledger_entries conversion
# ---------------------------------------------------------------------------


class TestPayloadToLedgerEntries:
    def test_returns_one_entry_per_signal(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=3)
        entries = _payload_to_ledger_entries(payload)
        assert len(entries) == 3

    def test_empty_signals_returns_empty(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries({"symbol": "ES", "tf": "1m", "signals": []})
        assert entries == []

    def test_winner_entry_was_selected_true(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=2, winner_idx=0)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].was_selected is True
        assert entries[1].was_selected is False

    def test_regime_suppressed_status_mapped(self):
        from services.signal_writer import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "regime_suppressed"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.REGIME_SUPPRESSED

    def test_pending_status_mapped(self):
        from services.signal_writer import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "pending"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.PENDING

    def test_missing_signal_id_raises(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        del payload["signals"][0]["signal_id"]
        with pytest.raises(ValueError, match="signal missing signal_id"):
            _payload_to_ledger_entries(payload)

    def test_bar_ts_parsed_as_utc_datetime(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert isinstance(entries[0].timestamp, datetime)
        assert entries[0].timestamp.tzinfo is not None

    def test_symbol_tf_propagated(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].symbol == "ES"
        assert entries[0].timeframe == "1m"
        assert entries[0].feature_tf == "1m"

    def test_is_shadow_propagated(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["is_shadow"] = True
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].is_shadow is True

    def test_cis_fields_wired_from_payload(self):
        """cis_score reads filtered_cis_score; bucket_scores/weights_version pass through."""
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].cis_score == pytest.approx(0.72)
        assert entries[0].bucket_scores == {"trend": 0.8, "momentum": 0.6}
        assert entries[0].weights_version == 3

    def test_cis_fields_none_when_absent(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = _make_payload(n_signals=1)
        for key in ("filtered_cis_score", "bucket_scores", "weights_version"):
            del payload["signals"][0][key]
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].cis_score is None
        assert entries[0].bucket_scores is None
        assert entries[0].weights_version is None

    def test_definition_fields_populated(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = {
            "symbol": "ES",
            "tf": "5m",
            "bar_ts": "2026-01-01T10:00:00Z",
            "computed_at": "2026-01-01T10:00:01Z",
            "signals": [
                {
                    "signal_id": "aaaaaaaa-0000-0000-0000-000000000001",
                    "setup_plugin": "momentum_breakout",
                    "signal_type": "breakout",
                    "direction": 1,
                    "was_selected": True,
                    "entry_price": 5100.0,
                    "stop_loss": 5080.0,
                    "targets": [5120.0, 5150.0],
                    "zone_low": 5095.0,
                    "zone_high": 5105.0,
                }
            ],
        }
        entries = _payload_to_ledger_entries(payload)
        assert len(entries) == 1
        e = entries[0]
        assert e.entry_price == 5100.0
        assert e.stop_loss == 5080.0
        assert e.targets == [5120.0, 5150.0]
        assert e.entry_zone_low == 5095.0
        assert e.entry_zone_high == 5105.0

    def test_definition_fields_none_when_absent(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = {
            "symbol": "ES",
            "tf": "5m",
            "bar_ts": "2026-01-01T10:00:00Z",
            "computed_at": "2026-01-01T10:00:01Z",
            "signals": [
                {
                    "signal_id": "aaaaaaaa-0000-0000-0000-000000000002",
                    "setup_plugin": "momentum_breakout",
                    "signal_type": "breakout",
                    "direction": 1,
                    "was_selected": False,
                }
            ],
        }
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].entry_price is None
        assert entries[0].stop_loss is None
        assert entries[0].targets is None
        assert entries[0].entry_zone_low is None
        assert entries[0].entry_zone_high is None


# ---------------------------------------------------------------------------
# Flush behavior (via _do_flush from BaseWriter)
# ---------------------------------------------------------------------------


class TestSignalWriterFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_insert_signals(self):
        from services.signal_writer import _payload_to_ledger_entries

        agent = _make_agent()
        payload = _make_payload(n_signals=2)
        entries = _payload_to_ledger_entries(payload)
        agent._buffer.extend(entries)
        await agent._do_flush()
        agent._repo.insert_signals.assert_called_once_with(entries)
        assert agent._buffer == []

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        agent = _make_agent()
        await agent._do_flush()
        agent._repo.insert_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_error_preserves_buffer(self):
        agent = _make_agent()
        agent._repo.insert_signals = AsyncMock(side_effect=Exception("db down"))
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(_make_payload(n_signals=1))
        agent._buffer.extend(entries)
        # _do_flush no longer raises; it logs and leaves buffer intact for retry
        await agent._do_flush()
        assert len(agent._buffer) == 1


# ---------------------------------------------------------------------------
# parse_iso_ts helper (moved from signal_writer_agent to src.core.service_utils)
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_parses_iso_with_tz(self):
        from src.core.service_utils import parse_iso_ts

        result = parse_iso_ts("2026-03-30T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_naive_gets_utc(self):
        from src.core.service_utils import parse_iso_ts

        result = parse_iso_ts("2026-03-30T12:00:00")
        assert result.tzinfo is not None

    def test_none_returns_none(self):
        from src.core.service_utils import parse_iso_ts

        assert parse_iso_ts(None) is None

    def test_invalid_returns_none(self):
        from src.core.service_utils import parse_iso_ts

        assert parse_iso_ts("not-a-date") is None


# ---------------------------------------------------------------------------
# Framing audit trail fields in LedgerEntry (Phase 115 Wave 4)
# ---------------------------------------------------------------------------


class TestFramingAuditFieldsInLedgerEntry:
    def _minimal_payload(self) -> dict:
        return {
            "symbol": "ES",
            "tf": "5m",
            "bar_ts": "2026-01-01T10:00:00Z",
            "computed_at": "2026-01-01T10:00:01Z",
            "signals": [
                {
                    "signal_id": "00000000-0000-0000-0000-000000000001",
                    "signal_type": "trend_long",
                    "setup_plugin": "TrendFollowingPlugin",
                    "direction": 1,
                    "was_selected": True,
                    "entry_price": 5000.0,
                    "stop_loss": 4980.0,
                    "targets": [5030.0],
                    "zone_low": 4995.0,
                    "zone_high": 5005.0,
                    "ttl_bars": 10,
                    "stop_basis": "structure_snap",
                    "stop_type": "swing_low",
                    "structural_stop_distance_atr": 0.7,
                    "adaptive_buffer_mult": 0.968,
                    "plugin_regime_type": "trend",
                }
            ],
        }

    def test_stop_basis_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].stop_basis == "structure_snap"

    def test_stop_type_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(self._minimal_payload())
        # Field renamed to stop_type_col to match DB column name (WR-03)
        assert entries[0].stop_type_col == "swing_low"

    def test_structural_stop_distance_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].structural_stop_distance_atr == pytest.approx(0.7)

    def test_adaptive_buffer_mult_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].adaptive_buffer_mult == pytest.approx(0.968)

    def test_plugin_regime_type_extracted(self):
        from services.signal_writer import _payload_to_ledger_entries

        entries = _payload_to_ledger_entries(self._minimal_payload())
        assert entries[0].plugin_regime_type == "trend"

    def test_missing_fields_default_to_none(self):
        from services.signal_writer import _payload_to_ledger_entries

        payload = self._minimal_payload()
        del payload["signals"][0]["stop_basis"]
        del payload["signals"][0]["adaptive_buffer_mult"]
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].stop_basis is None
        assert entries[0].adaptive_buffer_mult is None
