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
        patch(
            "services.ai_narrative_service.get_active_contracts",
            return_value=["ESH6", "NQH6", "RTYH6"],
        ),
    ):
        mock_settings.return_value.env_name = ""
        mock_settings.return_value.openrouter_api_key = ""
        from services.ai_narrative_service import AINarrativeService
        return AINarrativeService()


def test_service_initializes_with_default_config():
    """Service creates expected attributes from default config."""
    svc = _make_service()
    assert hasattr(svc, "per_signal_chain")
    assert hasattr(svc, "group_chain")
    assert svc._per_signal_timeout == 30.0   # OpenRouter timeout
    assert "ESH6" in svc.config["service"]["symbols"]
    assert svc.env_prefix == ""


@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    """direction=0 → no LLM call, message acked anyway."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock()

    fields = {
        b"direction": b"0",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
    }
    await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )
    svc.per_signal_chain.generate.assert_not_called()
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_publishes_narrative():
    """Valid bullish signal → chain called → narrative published to stream + hash."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    fake_narrative = "ES is establishing a trend-following setup at 5102.50."
    svc.per_signal_chain.generate = AsyncMock(return_value=fake_narrative)
    svc.per_signal_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

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
    assert "openrouter" in msg["model"]
    # Hash cache
    svc.redis_client.hset.assert_called_once()
    svc.redis_client.expire.assert_called_once()
    # Ack
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_handles_ollama_failure():
    """Chain returns None → no stream publish, message still acked."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock(return_value=None)

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
    await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )

    svc.redis_client.xadd.assert_not_called()
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_skips_1m_timeframe():
    """1m signals are always skipped — never worth per-signal LLM cost."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"1m",
        b"timestamp": b"2026-02-26T10:01:00",
        b"confidence": b"0.85",  # high confidence but 1m — still skip
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    await svc._process_single_message(
        "ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0"
    )
    svc.per_signal_chain.generate.assert_not_called()
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_skips_low_confidence():
    """Confidence ≤ 0.70 is skipped even on an eligible timeframe."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-26T10:05:00",
        b"confidence": b"0.65",  # below threshold
        b"confluence_score": b"0.70",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )
    svc.per_signal_chain.generate.assert_not_called()
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_allows_5m_high_confidence():
    """5m signal with confidence > 0.70 proceeds to LLM chain."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock(return_value="ES bullish setup forming.")
    svc.per_signal_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-26T10:05:00",
        b"confidence": b"0.75",  # above threshold
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )
    svc.per_signal_chain.generate.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_acks_on_redis_publish_failure():
    """Even if xadd raises, message must still be acked to avoid PEL accumulation."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd.side_effect = Exception("Redis write failed")
    svc.per_signal_chain.generate = AsyncMock(return_value="Some narrative.")
    svc.per_signal_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

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
    await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )

    # Must ack even though xadd raised
    svc.redis_client.xack.assert_not_called()


@pytest.mark.asyncio
async def test_latest_signals_cache_updated_for_any_signal():
    """_latest_signals is updated even for 1m/low-confidence signals (group loop needs them)."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock()

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"1m",
        b"timestamp": b"2026-02-26T10:01:00",
        b"confidence": b"0.85",
        b"confluence_score": b"0.80",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following",
        b"entry_price": b"5100.00",
        b"stop_loss": b"5092.00",
        b"targets": b"5110.00",
        b"regime_context": b"trending_up",
        b"supporting_factors": b"BOS",
    }
    await svc._process_single_message(
        "ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0"
    )
    # Cache updated even though 1m is filtered from per-signal narration
    assert "ESH6:1m" in svc._latest_signals
    assert svc._latest_signals["ESH6:1m"]["direction"] == 1


@pytest.mark.asyncio
async def test_group_synthesis_fires_on_fingerprint_change():
    """Group synthesis loop publishes a narrative when fingerprint changes."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    # Simulate a cached signal for an equity member
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1, "direction_label": "Bullish", "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing", "regime_context": "trending_up",
        "symbol": "ESH6", "timeframe": "5m",
    }
    # Redis: no prior state (returns None → fingerprint mismatch → synthesize)
    svc.redis_client.hget.return_value = None
    svc.group_chain.generate = AsyncMock(return_value="Equity group showing bullish momentum.")
    svc.group_chain.last_provider_id = "openrouter:stepfun/step-3.5-flash:free"

    await svc._synthesize_group("equity")

    # Should publish stream + update state
    svc.redis_client.xadd.assert_called_once()
    svc.redis_client.hset.assert_called()


@pytest.mark.asyncio
async def test_group_synthesis_skips_when_fingerprint_unchanged():
    """Group synthesis loop does NOT call LLM if nothing changed."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1, "regime_context": "trending_up",
        "direction_label": "Bullish", "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing",
        "symbol": "ESH6", "timeframe": "5m",
    }
    import json
    # Pre-populate Redis state with the same fingerprint
    prior_fp = {"ESH6:5m": [1, "trending_up"]}
    svc.redis_client.hget.return_value = json.dumps(prior_fp).encode()
    svc.group_chain.generate = AsyncMock()

    await svc._synthesize_group("equity")
    svc.group_chain.generate.assert_not_called()

    svc.redis_client.xadd.assert_not_called()


def test_service_has_shutdown_event():
    """Service exposes an asyncio.Event for clean shutdown coordination."""
    svc = _make_service()
    assert hasattr(svc, "shutdown_event")
    import asyncio
    assert isinstance(svc.shutdown_event, asyncio.Event)
    assert not svc.shutdown_event.is_set()


def test_stream_map_populated_after_setup():
    """_stream_map must contain all signal streams after setup."""
    import asyncio
    from unittest.mock import AsyncMock

    import redis.asyncio as redis

    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("BUSYGROUP Consumer Group name already exists")
    )
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    tfs = svc.config["service"]["timeframes"]
    assert len(svc._stream_map) == len(symbols) * len(tfs)
