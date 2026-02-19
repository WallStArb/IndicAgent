"""Tests for AINarrativeService class."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_service():
    """Instantiate AINarrativeService with all external deps mocked."""
    with (
        patch("services.ai_narrative_service.start_metrics_server"),
        patch("services.ai_narrative_service.counter", return_value=MagicMock()),
        patch("services.ai_narrative_service.gauge", return_value=MagicMock()),
        patch("services.ai_narrative_service.Settings") as mock_settings,
    ):
        mock_settings.return_value.env_name = ""
        from services.ai_narrative_service import AINarrativeService
        return AINarrativeService()


def test_service_initializes_with_default_config():
    """Service creates expected attributes from default config."""
    svc = _make_service()
    assert svc.ollama_model == "qwen3:8b"
    assert svc.ollama_timeout == 15.0
    assert "ESH6" in svc.config["service"]["symbols"]
    assert svc.env_prefix == ""


@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    """direction=0 → no Ollama call, message acked anyway."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"0",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
    }
    with patch("services.ai_narrative_service.call_ollama_async") as mock_ollama:
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )
        mock_ollama.assert_not_called()
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_publishes_narrative():
    """Valid bullish signal → Ollama called → narrative published to stream + hash."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"confidence": b"0.74",
        b"confluence_score": b"0.81",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS confirmed",
    }
    fake_narrative = "ES is establishing a trend-following setup at 5102.50."

    with patch(
        "services.ai_narrative_service.call_ollama_async",
        return_value=fake_narrative,
    ):
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )

    # Stream publish
    svc.redis_client.xadd.assert_called_once()
    call_args = svc.redis_client.xadd.call_args[0]
    stream_name = call_args[0]
    msg = call_args[1]
    assert "narratives:ESH6:5m" in stream_name
    assert msg["narrative"] == fake_narrative
    assert msg["action_bias"] == "bullish"
    # Hash cache
    svc.redis_client.hset.assert_called_once()
    svc.redis_client.expire.assert_called_once()
    # Ack
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_handles_ollama_failure():
    """Ollama returns None → no stream publish, message still acked."""
    svc = _make_service()
    svc.redis_client = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"confidence": b"0.74",
        b"confluence_score": b"0.0",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"RSI bullish",
    }
    with patch("services.ai_narrative_service.call_ollama_async", return_value=None):
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )

    svc.redis_client.xadd.assert_not_called()
    svc.redis_client.xack.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_acks_on_redis_publish_failure():
    """Even if xadd raises, message must still be acked to avoid PEL accumulation."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd.side_effect = Exception("Redis write failed")

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
        b"confidence": b"0.74",
        b"confluence_score": b"0.0",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5102.50",
        b"stop_loss": b"5094.00",
        b"targets": b"5112.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS confirmed",
    }
    with patch("services.ai_narrative_service.call_ollama_async", return_value="Some narrative."):
        await svc._process_single_message(
            "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
        )

    # Must ack even though xadd raised
    svc.redis_client.xack.assert_called_once()
