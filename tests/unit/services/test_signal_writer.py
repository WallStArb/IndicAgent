"""Unit tests for SignalWriter.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, _payload_to_grouped_rows G0 grouping, and flush behavior.
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
    agent._repo.insert_signal_with_frames = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._events_consumed = MagicMock()
    agent._signals_written = MagicMock()
    agent._write_errors = MagicMock()
    agent._batch_latency_attrs = {"agent_id": "signal_writer_agent"}
    agent._invalid_signals = []
    # OTel instruments below are mocked because __new__ bypasses BaseWriter.__init__.
    agent._buffer_depth_gauge = MagicMock()
    agent._buffer_overflow_total = MagicMock()
    agent._flush_latency = MagicMock()
    agent._commit_latency = MagicMock()
    agent._parse_failures_total = MagicMock()
    agent._flush_errors_total = MagicMock()
    agent._commit_errors_total = MagicMock()
    agent.tracer = MagicMock()
    agent.tracer.start_as_current_span = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)
        )
    )
    return agent


def _make_payload(n_signals: int = 2, winner_idx: int = 0, same_signal_id: bool = False) -> dict:
    """Build a minimal intelligence.i7.signals payload.

    Args:
        n_signals: Number of signals to include.
        winner_idx: Index of signal marked was_selected=True.
        same_signal_id: If True, all signals share signal_id "sig_0" (G0 grouping test).
    """
    signals = []
    for i in range(n_signals):
        sig_id = "sig_0" if same_signal_id else f"sig_{i}"
        signals.append(
            {
                "signal_id": sig_id,
                "setup_plugin": f"trad_Plugin{i}",
                "signal_type": "long",
                "direction": 1,
                "entry_price": 5000.0 + i,
                "stop_loss": 4990.0,
                "targets": [5020.0],
                "entry_type": "at_close",
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
        """BATCH_SIZE and FLUSH_INTERVAL_SECS are inherited from BaseWriter."""
        from services.signal_writer import SignalWriter

        assert SignalWriter.BATCH_SIZE > 0
        assert SignalWriter.FLUSH_INTERVAL_SECS > 0

    def test_signal_writer_does_not_define_batch_size_class_attr(self):
        """SignalWriter loads batch_size from APR at _setup(); no class-level override."""
        from services.signal_writer import SignalWriter

        assert "BATCH_SIZE" not in SignalWriter.__dict__
        assert "FLUSH_INTERVAL_SECS" not in SignalWriter.__dict__
        assert "MAX_BUFFER_SIZE" not in SignalWriter.__dict__

    def test_inherits_base_writer_agent(self):
        from services.signal_writer import SignalWriter
        from src.core.agent.base_writer import BaseWriter

        assert issubclass(SignalWriter, BaseWriter)


# ---------------------------------------------------------------------------
# _payload_to_grouped_rows G0 grouping
# ---------------------------------------------------------------------------


class TestPayloadToGroupedRows:
    def test_returns_one_group_per_unique_signal_id(self):
        """Each unique signal_id produces one (signal_event, trade_frames) tuple."""
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=3)
        rows = _payload_to_grouped_rows(payload)
        assert len(rows) == 3

    def test_empty_signals_returns_empty(self):
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows({"symbol": "ES", "tf": "1m", "signals": []})
        assert rows == []

    def test_g0_grouping_same_signal_id_produces_one_group(self):
        """Two signals with same signal_id → one signal_event + two trade_frames."""
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=2, same_signal_id=True)
        payload["signals"][0]["entry_type"] = "at_close"
        payload["signals"][1]["entry_type"] = "at_pullback"
        rows = _payload_to_grouped_rows(payload)
        assert len(rows) == 1
        signal_event, trade_frames = rows[0]
        assert len(trade_frames) == 2

    def test_signal_event_has_direction_text(self):
        """direction must be 'long'/'short' text in signal_events (not int)."""
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["direction"] = 1
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["direction"] == "long"

    def test_signal_event_direction_short(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["direction"] = -1
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["direction"] == "short"

    def test_winner_trade_frame_was_selected_true(self):
        """was_selected is carried per signal into the trade_frame."""
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=2, winner_idx=0)
        rows = _payload_to_grouped_rows(payload)
        # Two unique signal_ids → two groups
        was_selected_values = [rows[i][1][0]["was_selected"] for i in range(2)]
        assert True in was_selected_values
        assert False in was_selected_values

    def test_regime_suppressed_status_in_signal_event(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "regime_suppressed"
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["status"] == "regime_suppressed"

    def test_pending_status_in_signal_event(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "pending"
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["status"] == "pending"

    def test_missing_signal_id_raises(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        del payload["signals"][0]["signal_id"]
        with pytest.raises(ValueError, match="signal missing signal_id"):
            _payload_to_grouped_rows(payload)

    def test_bar_ts_parsed_as_utc_datetime(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert isinstance(signal_event["ts"], datetime)
        assert signal_event["ts"].tzinfo is not None

    def test_symbol_tf_propagated_to_signal_event(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["symbol"] == "ES"
        assert signal_event["tf"] == "1m"

    def test_is_shadow_propagated_to_signal_event(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        payload["signals"][0]["is_shadow"] = True
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["is_shadow"] is True

    def test_cis_fields_wired_from_payload(self):
        """cis_score reads filtered_cis_score; weights_version passes through."""
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["cis_score"] == pytest.approx(0.72)
        assert signal_event["weights_version"] == 3

    def test_cis_fields_none_when_absent(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = _make_payload(n_signals=1)
        for key in ("filtered_cis_score", "bucket_scores", "weights_version"):
            payload["signals"][0].pop(key, None)
        rows = _payload_to_grouped_rows(payload)
        signal_event, _ = rows[0]
        assert signal_event["cis_score"] is None
        assert signal_event["weights_version"] is None

    def test_definition_fields_in_trade_frame(self):
        """entry_price, stop_price, target_price populate trade_frame."""
        from services.signal_writer import _payload_to_grouped_rows

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
                    "entry_type": "at_close",
                    "entry_price": 5100.0,
                    "stop_loss": 5080.0,
                    "targets": [5120.0, 5150.0],
                    "zone_low": 5095.0,
                    "zone_high": 5105.0,
                }
            ],
        }
        rows = _payload_to_grouped_rows(payload)
        assert len(rows) == 1
        signal_event, trade_frames = rows[0]
        assert len(trade_frames) == 1
        tf = trade_frames[0]
        assert tf["entry_price"] == 5100.0
        assert tf["stop_price"] == 5080.0
        # target_price is the first element of targets
        assert tf["target_price"] == 5120.0

    def test_definition_fields_none_when_absent(self):
        from services.signal_writer import _payload_to_grouped_rows

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
        rows = _payload_to_grouped_rows(payload)
        _, trade_frames = rows[0]
        tf = trade_frames[0]
        assert tf["entry_price"] is None
        assert tf["stop_price"] is None
        assert tf["target_price"] is None


# ---------------------------------------------------------------------------
# Flush behavior (via _do_flush from BaseWriter)
# ---------------------------------------------------------------------------


class TestSignalWriterFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_insert_signal_with_frames(self):
        """_flush_batch calls insert_signal_with_frames once per (signal_event, frames) tuple."""
        from services.signal_writer import _payload_to_grouped_rows

        agent = _make_agent()
        payload = _make_payload(n_signals=2)
        rows = _payload_to_grouped_rows(payload)
        agent._buffer.extend(rows)
        await agent._flush_batch(rows)
        assert agent._repo.insert_signal_with_frames.call_count == 2

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        agent = _make_agent()
        # _do_flush() is no-op if buffer is empty
        await agent._flush_batch([])
        agent._repo.insert_signal_with_frames.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_error_preserves_buffer(self):
        """When insert_signal_with_frames raises, the buffer stays intact (base class retry)."""
        agent = _make_agent()
        agent._repo.insert_signal_with_frames = AsyncMock(side_effect=Exception("db down"))
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(_make_payload(n_signals=1))
        agent._buffer.extend(rows)
        with pytest.raises(Exception, match="db down"):
            await agent._flush_batch(rows)
        # Buffer not cleared by _flush_batch (BaseWriter._do_flush handles clearing)
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
# Framing audit trail fields in trade_frames (Phase 115 Wave 4 — now in frame_details)
# ---------------------------------------------------------------------------


class TestFramingAuditFieldsInTradeFrame:
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
                    "entry_type": "at_close",
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

    def test_stop_basis_in_frame_details(self):
        """stop_basis is stored in trade_frame.frame_details JSONB."""
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(self._minimal_payload())
        _, trade_frames = rows[0]
        assert trade_frames[0]["frame_details"]["stop_basis"] == "structure_snap"

    def test_stop_type_col_in_frame_details(self):
        """stop_type from payload maps to stop_type_col in frame_details."""
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(self._minimal_payload())
        _, trade_frames = rows[0]
        assert trade_frames[0]["frame_details"]["stop_type_col"] == "swing_low"

    def test_structural_stop_distance_in_frame_details(self):
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(self._minimal_payload())
        _, trade_frames = rows[0]
        assert trade_frames[0]["frame_details"]["structural_stop_distance_atr"] == pytest.approx(
            0.7
        )

    def test_adaptive_buffer_mult_in_frame_details(self):
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(self._minimal_payload())
        _, trade_frames = rows[0]
        assert trade_frames[0]["frame_details"]["adaptive_buffer_mult"] == pytest.approx(0.968)

    def test_plugin_regime_type_in_signal_event(self):
        """plugin_regime_type goes to signal_events (detection layer)."""
        from services.signal_writer import _payload_to_grouped_rows

        rows = _payload_to_grouped_rows(self._minimal_payload())
        signal_event, _ = rows[0]
        assert signal_event["plugin_regime_type"] == "trend"

    def test_missing_fields_produce_no_frame_details_keys(self):
        from services.signal_writer import _payload_to_grouped_rows

        payload = self._minimal_payload()
        del payload["signals"][0]["stop_basis"]
        del payload["signals"][0]["adaptive_buffer_mult"]
        rows = _payload_to_grouped_rows(payload)
        _, trade_frames = rows[0]
        fd = trade_frames[0].get("frame_details") or {}
        assert "stop_basis" not in fd
        assert "adaptive_buffer_mult" not in fd
