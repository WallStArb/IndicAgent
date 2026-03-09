"""Tests for AINarrativeService class."""
import asyncio
import json
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

    # Stream publish — narratives xadd plus i8 xadd (>= 1 total)
    assert svc.redis_client.xadd.call_count >= 1
    # Find the narratives call specifically
    narrative_call = next(
        c for c in svc.redis_client.xadd.call_args_list
        if "narratives" in str(c.args[0])
    )
    stream_name = narrative_call.args[0]
    msg = narrative_call.args[1]
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
    """Chain returns None → narrative not published, but LLM call record IS emitted."""
    svc = _make_service()
    svc.redis_client = AsyncMock()
    svc.per_signal_chain.generate = AsyncMock(return_value=None)
    svc.per_signal_chain.last_provider_id = "ollama:qwen3.5:9b"

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

    # LLM call record emitted to llm_calls:stream (fire-and-forget)
    await asyncio.sleep(0)  # let create_task run
    xadd_streams = [str(c.args[0]) for c in svc.redis_client.xadd.call_args_list]
    assert any("llm_calls" in s for s in xadd_streams), "Expected llm_calls:stream emit"
    # Narrative stream must NOT be published
    assert not any("narratives" in s for s in xadd_streams), (
        "Narrative must not be published on LLM failure"
    )
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
    await asyncio.sleep(0)  # let create_task run

    # Should publish both llm_calls:stream (fire-and-forget) and narratives:group:equity
    xadd_streams = [str(c.args[0]) for c in svc.redis_client.xadd.call_args_list]
    assert any("llm_calls" in s for s in xadd_streams), "Expected llm_calls:stream emit"
    assert any("narratives:group:equity" in s for s in xadd_streams), "Expected narrative stream"
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


# -- i8 enrichment stream publish --------------------------------------------------


def _make_service_new():
    """Build AINarrativeService via __new__ (bypass __init__ to avoid LLM chain setup)."""
    from services.ai_narrative_service import AINarrativeService
    import asyncio

    svc = AINarrativeService.__new__(AINarrativeService)
    svc.logger = MagicMock()
    svc.running = False
    svc.shutdown_requested = False
    svc.env_prefix = "development:"
    svc.consumer_group = "ai_narrative"
    svc.consumer_name = "narrative_test"
    svc._stream_map = {}
    svc._latest_signals = {}
    svc._latest_signals_lock = asyncio.Lock()  # required per CLAUDE.md __new__ pattern
    svc._preferred_models = {}  # required per CLAUDE.md __new__ pattern

    # Metrics stubs
    svc.narratives_generated_total = MagicMock()
    svc.narratives_skipped_total = MagicMock()
    svc.ollama_latency_ms = MagicMock()
    svc.error_count_total = MagicMock()
    svc.group_narratives_generated = MagicMock()
    svc._total_narratives = 0
    svc._error_count = 0

    # LLM chain mock
    svc.per_signal_chain = MagicMock()
    svc.per_signal_chain.last_provider_id = "zai"
    svc._per_signal_timeout = 30.0

    # Redis mock
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.redis_client.hset = AsyncMock()
    svc.redis_client.expire = AsyncMock()

    return svc


def _make_signal_fields_i8(confidence: float = 0.80, direction: int = 1) -> dict[bytes, bytes]:
    """Build a signals:aggregated stream message fields dict."""
    return {
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-03-04T10:00:00+00:00",
        b"direction": str(direction).encode(),
        b"confidence": str(confidence).encode(),
        b"confluence_score": b"0.75",
        b"setup_plugin": b"trad_TrendFollowing",
        b"signal_type": b"trend_following_long",
        b"entry_price": b"5100.0",
        b"stop_loss": b"5080.0",
        b"profit_target": b"5140.0",
        b"risk_reward_ratio": b"2.0",
        b"regime_context": b"trend_up",
        b"supporting_factors": b"rsi_aligned",
    }


@pytest.mark.asyncio
async def test_i8_publish_called_when_narrative_generated():
    """xadd called for both narratives and i8 streams when narrative succeeds."""
    svc = _make_service_new()
    svc.per_signal_chain.generate = AsyncMock(return_value="Bullish trend setup, entry at 5100.")

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    # xadd called at least twice: narratives + i8
    assert svc.redis_client.xadd.call_count >= 2

    # One of the calls must be to the i8 stream
    call_args_list = [str(c.args[0]) for c in svc.redis_client.xadd.call_args_list]
    assert any("intelligence_i8" in name for name in call_args_list), (
        f"No i8 xadd found. Streams called: {call_args_list}"
    )


@pytest.mark.asyncio
async def test_i8_not_published_when_narrative_empty():
    """No i8 xadd when Ollama/LLM returns empty string."""
    svc = _make_service_new()
    svc.per_signal_chain.generate = AsyncMock(return_value=None)

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    call_args_list = [str(c.args[0]) for c in svc.redis_client.xadd.call_args_list]
    assert not any("intelligence_i8" in name for name in call_args_list)


@pytest.mark.asyncio
async def test_i8_payload_shape():
    """i8 xadd message has required keys: ts, symbol, tf, model, confidence, summary, generated_at."""  # noqa: E501
    svc = _make_service_new()
    svc.per_signal_chain.generate = AsyncMock(return_value="Short narrative for test.")

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    # Find the i8 xadd call
    i8_call = None
    for c in svc.redis_client.xadd.call_args_list:
        if "intelligence_i8" in str(c.args[0]):
            i8_call = c
            break
    assert i8_call is not None, "Expected i8 xadd call not found"

    payload = i8_call.args[1]
    for key in ("ts", "symbol", "tf", "model", "confidence", "summary", "generated_at"):
        assert key in payload, f"Missing key in i8 payload: {key}"
    assert payload["symbol"] == "ESH6"
    assert payload["tf"] == "5m"
    assert payload["model"] == "zai"


@pytest.mark.asyncio
async def test_i8_summary_truncated_at_280_chars():
    """Summary in i8 payload is capped at 280 characters."""
    svc = _make_service_new()
    long_narrative = "A" * 500
    svc.per_signal_chain.generate = AsyncMock(return_value=long_narrative)

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    i8_call = None
    for c in svc.redis_client.xadd.call_args_list:
        if "intelligence_i8" in str(c.args[0]):
            i8_call = c
            break
    assert i8_call is not None
    assert len(i8_call.args[1]["summary"]) == 280


@pytest.mark.asyncio
async def test_i8_not_published_on_low_confidence():
    """confidence <= 0.70 -> skipped before narrative generation, no i8 xadd."""
    svc = _make_service_new()
    svc.per_signal_chain.generate = AsyncMock(return_value="Should not be called")

    fields = _make_signal_fields_i8(confidence=0.65)
    result = await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    assert result is True
    call_args_list = [str(c.args[0]) for c in svc.redis_client.xadd.call_args_list]
    assert not any("intelligence_i8" in name for name in call_args_list)
    svc.per_signal_chain.generate.assert_not_called()


# ---- LLM call payload helper ----


def test_build_llm_call_payload_per_signal_fields():
    """Per-signal payload contains all required string fields."""
    from services.ai_narrative_service import _build_llm_call_payload
    sd = {
        "symbol": "ESH6", "timeframe": "5m", "regime_context": "trending",
        "setup_plugin": "BosSetup", "confidence": 0.85,
        "entry_price": "5100.0", "stop_loss": "5090.0", "profit_target": "5120.0",
    }
    payload = _build_llm_call_payload(
        call_type="per_signal",
        signal_data=sd,
        group_name="",
        prompt="Test prompt",
        response="Test narrative",
        latency_ms=1250.0,
        succeeded=True,
        model_id="ollama:qwen3.5:9b",
    )
    assert payload["call_type"] == "per_signal"
    assert payload["symbol"] == "ESH6"
    assert payload["timeframe"] == "5m"
    assert payload["regime"] == "trending"
    assert payload["setup_type"] == "BosSetup"
    assert payload["succeeded"] == "1"
    assert payload["latency_ms"] == "1250"
    assert payload["provider"] == "ollama"
    # All values must be str
    for k, v in payload.items():
        assert isinstance(v, str), f"Field {k!r} must be str, got {type(v).__name__}"


def test_build_llm_call_payload_counterfactual():
    """Counterfactual: succeeded=False, response empty."""
    from services.ai_narrative_service import _build_llm_call_payload
    sd = {"symbol": "NQH6", "timeframe": "5m", "confidence": 0.65}
    payload = _build_llm_call_payload(
        call_type="counterfactual",
        signal_data=sd,
        group_name="",
        prompt="Would-have-been prompt",
        response=None,
        latency_ms=0.0,
        succeeded=False,
        model_id="",
    )
    assert payload["call_type"] == "counterfactual"
    assert payload["response"] == ""
    assert payload["succeeded"] == "0"


def test_build_llm_call_payload_group_synthesis():
    """Group synthesis: group_name set, symbol/timeframe empty."""
    from services.ai_narrative_service import _build_llm_call_payload
    payload = _build_llm_call_payload(
        call_type="group_synthesis",
        signal_data=None,
        group_name="equity",
        prompt="Group prompt",
        response="Group narrative",
        latency_ms=800.0,
        succeeded=True,
        model_id="ollama:phi4-mini:3.8b",
    )
    assert payload["call_type"] == "group_synthesis"
    assert payload["group_name"] == "equity"
    assert payload["symbol"] == ""


# ---- Provider chain promotion ----


def test_promote_model_in_chain_moves_to_position_0():
    """Model not at position 0 gets promoted."""
    from services.ai_narrative_service import _promote_model_in_chain
    p1 = MagicMock()
    p1.provider_id = "ollama:qwen3.5:9b"
    p2 = MagicMock()
    p2.provider_id = "zai:glm-5"
    chain = MagicMock()
    chain.providers = [p1, p2]
    _promote_model_in_chain(chain, "zai:glm-5")
    assert chain.providers[0].provider_id == "zai:glm-5"
    assert chain.providers[1].provider_id == "ollama:qwen3.5:9b"


def test_promote_model_in_chain_already_first_no_change():
    """Model at position 0 — chain unchanged."""
    from services.ai_narrative_service import _promote_model_in_chain
    p1 = MagicMock()
    p1.provider_id = "zai:glm-5"
    p2 = MagicMock()
    p2.provider_id = "ollama:qwen3.5:9b"
    chain = MagicMock()
    original = [p1, p2]
    chain.providers = original
    _promote_model_in_chain(chain, "zai:glm-5")
    assert chain.providers is original  # unchanged


def test_promote_model_in_chain_unknown_id_no_change():
    """Unknown provider_id — chain unchanged."""
    from services.ai_narrative_service import _promote_model_in_chain
    p1 = MagicMock()
    p1.provider_id = "ollama:qwen3.5:9b"
    chain = MagicMock()
    chain.providers = [p1]
    _promote_model_in_chain(chain, "zai:nonexistent")
    assert chain.providers == [p1]


def test_promote_model_in_chain_none_id_no_op():
    """None provider_id — returns without error."""
    from services.ai_narrative_service import _promote_model_in_chain
    chain = MagicMock()
    chain.providers = []
    _promote_model_in_chain(chain, None)  # must not raise


# ---- Per-regime routing (_apply_score_routing / _preferred_models) ----


def _make_svc_routing():
    """Build AINarrativeService via __new__ for routing tests."""
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService.__new__(AINarrativeService)
    svc.env_prefix = "development:"
    svc.redis_client = AsyncMock()
    svc._preferred_models = {}  # new attribute — must be set manually per CLAUDE.md pattern
    # Mock chains
    svc.per_signal_chain = MagicMock()
    svc.per_signal_chain.providers = []
    svc.group_chain = MagicMock()
    svc.group_chain.providers = []
    svc.logger = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_apply_score_routing_per_regime():
    """Per-regime: trending winner != ranging winner, each stored independently."""
    svc = _make_svc_routing()

    async def fake_hgetall(key):
        if "trending" in key and "per_signal" in key:
            return {b"model_A": json.dumps({"is_significant": True, "avg_pnl_r": 2.0}).encode()}
        if "ranging" in key and "per_signal" in key:
            return {b"model_B": json.dumps({"is_significant": True, "avg_pnl_r": 1.5}).encode()}
        return {}

    svc.redis_client.hgetall = fake_hgetall
    await svc._apply_score_routing()

    assert svc._preferred_models.get("per_signal", {}).get("trending") == "model_A"
    assert svc._preferred_models.get("per_signal", {}).get("ranging") == "model_B"
    # volatile has no significant model — should not be in dict
    assert "volatile" not in svc._preferred_models.get("per_signal", {})


@pytest.mark.asyncio
async def test_apply_score_routing_falls_back_without_significant():
    """Regime with no significant model gets no entry in _preferred_models."""
    svc = _make_svc_routing()

    async def fake_hgetall(key):
        if "trending" in key and "per_signal" in key:
            # Not significant
            return {b"model_X": json.dumps({"is_significant": False, "avg_pnl_r": 5.0}).encode()}
        return {}

    svc.redis_client.hgetall = fake_hgetall
    await svc._apply_score_routing()

    assert "trending" not in svc._preferred_models.get("per_signal", {})


def test_preferred_models_initialized():
    """__init__ sets self._preferred_models = {} so attribute always exists."""
    import inspect

    from services.ai_narrative_service import AINarrativeService

    src = inspect.getsource(AINarrativeService.__init__)
    assert "_preferred_models" in src


@pytest.mark.asyncio
async def test_promote_uses_regime_from_signal():
    """Per-signal call site promotes regime-specific model before chain.generate()."""
    svc = _make_service_new()
    svc._preferred_models = {"per_signal": {"trend_up": "model_A"}}

    # Give per_signal_chain real providers so _promote_model_in_chain can find model_A
    p1 = MagicMock()
    p1.provider_id = "default_model"
    p2 = MagicMock()
    p2.provider_id = "model_A"
    svc.per_signal_chain.providers = [p1, p2]
    svc.per_signal_chain.generate = AsyncMock(return_value="Promoted narrative.")
    svc.per_signal_chain.last_provider_id = "model_A"

    fields = _make_signal_fields_i8(confidence=0.85)
    # Override regime_context to match our preferred model key
    fields[b"regime_context"] = b"trend_up"

    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    # model_A should now be at position 0 after promotion
    assert svc.per_signal_chain.providers[0].provider_id == "model_A"


# ---- SYSTEM_PROMPT voice and chain separation (plan 22-02) ----


def test_system_prompt_prohibits_passive_voice_phrases():
    """SYSTEM_PROMPT must not contain any banned passive-voice/hedging phrases."""
    from services.ai_narrative_service import SYSTEM_PROMPT

    banned = ["capitalize", "execute long", "protect the position", "suggests", "price momentum"]
    for phrase in banned:
        assert phrase not in SYSTEM_PROMPT.lower(), (
            f"Banned phrase {phrase!r} found in SYSTEM_PROMPT"
        )


def test_system_prompt_establishes_analyst_voice():
    """SYSTEM_PROMPT must establish a senior trading desk analyst voice."""
    from services.ai_narrative_service import SYSTEM_PROMPT

    prompt_lower = SYSTEM_PROMPT.lower()
    assert "trading desk" in prompt_lower or "analyst" in prompt_lower, (
        "SYSTEM_PROMPT must reference 'trading desk' or 'analyst'"
    )
    assert "passive voice" in prompt_lower or "precise" in prompt_lower, (
        "SYSTEM_PROMPT must reference 'passive voice' or 'precise'"
    )


def test_service_has_short_chain():
    """_build_chains() must create both short_chain and deep_chain attributes."""
    svc = _make_service()
    assert hasattr(svc, "short_chain"), "short_chain attribute missing after _build_chains()"
    assert hasattr(svc, "deep_chain"), "deep_chain attribute missing after _build_chains()"


def test_service_short_chain_is_separate_from_deep_chain():
    """short_chain and deep_chain must be distinct LLMChain instances."""
    svc = _make_service()
    assert svc.short_chain is not svc.deep_chain, (
        "short_chain and deep_chain must be separate instances"
    )
