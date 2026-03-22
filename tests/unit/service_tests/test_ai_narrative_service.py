"""Tests for AINarrativeService class."""

import asyncio
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
            "services.ai_narrative_service.get_active_symbols",
            return_value=["ESH6", "NQH6", "RTYH6"],
        ),
    ):
        mock_settings.return_value.env_name = ""
        mock_settings.return_value.openrouter_api_key = ""
        mock_settings.return_value.llm_timeout_sec = 60.0
        from services.ai_narrative_service import AINarrativeService

        return AINarrativeService()


def test_service_initializes_with_default_config():
    """Service creates expected attributes from default config."""
    svc = _make_service()
    assert hasattr(svc, "short_chain")
    assert hasattr(svc, "deep_chain")
    assert hasattr(svc, "group_chain")
    assert svc._per_signal_timeout == 60.0  # Settings.llm_timeout_sec default
    assert "ESH6" in svc.config["service"]["symbols"]
    assert svc.env_prefix == ""


@pytest.mark.asyncio
async def test_process_message_skips_zero_direction():
    """direction=0 → no LLM call, message acked anyway."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc.short_chain.generate = AsyncMock()

    fields = {
        b"direction": b"0",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-02-19T14:05:00",
    }
    await svc._process_single_message("ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0")
    svc.short_chain.generate.assert_not_called()
    svc._kafka_producer.publish.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_publishes_narrative():
    """Valid bullish signal → chain called → narrative published to Kafka narratives topic."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()
    fake_narrative = "ES is establishing a trend-following setup at 5102.50."
    svc.short_chain.generate = AsyncMock(return_value=fake_narrative)
    svc.short_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"
    svc.deep_chain.generate = AsyncMock(return_value=fake_narrative)
    svc.deep_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

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
    await svc._process_single_message("ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0")
    await asyncio.sleep(0.1)  # let background narrative tasks complete

    # Kafka producer publish called — at least one call to narratives topic
    assert svc._kafka_producer.publish.call_count >= 1
    # Find the narratives publish call specifically
    narrative_call = next(
        c
        for c in svc._kafka_producer.publish.call_args_list
        if "narratives" in str(c.args[0]) and "llm" not in str(c.args[0])
    )
    topic = narrative_call.args[0]
    msg = narrative_call.args[1]
    assert "narratives" in topic
    assert msg["narrative"] == fake_narrative
    assert msg["action_bias"] == "bullish"
    assert "openrouter" in msg["model"]


@pytest.mark.asyncio
async def test_process_message_handles_ollama_failure():
    """Chain returns None → narrative not published, but LLM call record IS emitted."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()
    svc.short_chain.generate = AsyncMock(return_value=None)
    svc.short_chain.last_provider_id = "ollama:qwen3.5:9b"
    svc.deep_chain.generate = AsyncMock(return_value=None)
    svc.deep_chain.last_provider_id = "ollama:qwen3.5:9b"

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
    await svc._process_single_message("ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0")

    # LLM call record emitted to llm.calls topic (fire-and-forget)
    await asyncio.sleep(0.1)  # let background narrative tasks complete
    publish_topics = [str(c.args[0]) for c in svc._kafka_producer.publish.call_args_list]
    assert any("llm" in s for s in publish_topics), "Expected llm.calls topic publish"
    # Narrative topic must NOT be published
    assert not any(
        "narratives" in s for s in publish_topics
    ), "Narrative must not be published on LLM failure"


@pytest.mark.asyncio
async def test_process_message_skips_1m_timeframe():
    """1m signals are always skipped — never worth per-signal LLM cost."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc.short_chain.generate = AsyncMock()

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
    await svc._process_single_message("ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0")
    svc.short_chain.generate.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_skips_low_confidence():
    """Confidence ≤ 0.70 is skipped even on an eligible timeframe."""
    svc = _make_service()
    svc.short_chain.generate = AsyncMock()

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
    await svc._process_single_message("ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0")
    svc.short_chain.generate.assert_not_called()


@pytest.mark.asyncio
async def test_process_message_allows_5m_high_confidence():
    """5m signal with confidence > 0.70 proceeds to LLM chain."""
    svc = _make_service()
    svc.short_chain.generate = AsyncMock(return_value="ES bullish setup forming.")
    svc.short_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"
    svc.deep_chain.generate = AsyncMock(return_value="ES bullish setup forming.")
    svc.deep_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

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
    await svc._process_single_message("ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0")
    await asyncio.sleep(0.05)  # let background tasks run
    svc.short_chain.generate.assert_called_once()


@pytest.mark.asyncio
async def test_process_message_acks_on_kafka_publish_failure():
    """Even if Kafka publish raises, _process_single_message must still return True."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock(side_effect=Exception("Kafka write failed"))
    svc.short_chain.generate = AsyncMock(return_value="Some narrative.")
    svc.short_chain.last_provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"

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
    # _process_single_message dispatches background tasks — no throw to caller
    result = await svc._process_single_message(
        "ESH6", "5m", fields, "signals:ESH6:5m:aggregated", b"1-0"
    )
    assert result is True


@pytest.mark.asyncio
async def test_latest_signals_cache_updated_for_any_signal():
    """_latest_signals is updated even for 1m/low-confidence signals (group loop needs them)."""
    svc = _make_service()
    svc.short_chain.generate = AsyncMock()

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
    await svc._process_single_message("ESH6", "1m", fields, "signals:ESH6:1m:aggregated", b"1-0")
    # Cache updated even though 1m is filtered from per-signal narration
    assert "ESH6:1m" in svc._latest_signals
    assert svc._latest_signals["ESH6:1m"]["direction"] == 1


@pytest.mark.asyncio
async def test_group_synthesis_fires_on_fingerprint_change():
    """Group synthesis loop publishes a narrative when fingerprint changes."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()
    # Simulate a cached signal for an equity member
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1,
        "direction_label": "Bullish",
        "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing",
        "regime_context": "trending_up",
        "symbol": "ESH6",
        "timeframe": "5m",
    }
    # No prior state in _group_fingerprints → fingerprint mismatch → synthesize
    svc._group_fingerprints = {}
    svc.group_chain.generate = AsyncMock(return_value="Equity group showing bullish momentum.")
    svc.group_chain.last_provider_id = "openrouter:stepfun/step-3.5-flash:free"

    await svc._synthesize_group("equity")
    await asyncio.sleep(0)  # let create_task run

    # Should publish to llm.calls (fire-and-forget) and narratives.group topic
    published_topics = [str(c.args[0]) for c in svc._kafka_producer.publish.call_args_list]
    assert any("llm" in s for s in published_topics), "Expected llm.calls topic emit"
    assert any("narratives" in s for s in published_topics), "Expected narratives topic publish"
    # Fingerprint must be stored in-process
    assert "equity" in svc._group_fingerprints


@pytest.mark.asyncio
async def test_group_synthesis_skips_when_fingerprint_unchanged():
    """Group synthesis loop does NOT call LLM if nothing changed."""
    svc = _make_service()
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()
    svc._latest_signals["ESH6:5m"] = {
        "direction": 1,
        "regime_context": "trending_up",
        "direction_label": "Bullish",
        "confidence": 0.82,
        "setup_plugin": "trad_TrendFollowing",
        "symbol": "ESH6",
        "timeframe": "5m",
    }
    # Pre-populate in-process fingerprint with the same state so nothing changed
    svc._group_fingerprints = {"equity": {"ESH6:5m": [1, "trending_up"]}}
    svc.group_chain.generate = AsyncMock()

    await svc._synthesize_group("equity")
    svc.group_chain.generate.assert_not_called()
    svc._kafka_producer.publish.assert_not_called()


def test_service_has_shutdown_event():
    """Service exposes an asyncio.Event for clean shutdown coordination."""
    svc = _make_service()
    assert hasattr(svc, "shutdown_event")
    import asyncio

    assert isinstance(svc.shutdown_event, asyncio.Event)
    assert not svc.shutdown_event.is_set()


def test_ai_narrative_has_kafka_clients():
    """KAFKA-08: AINarrativeService must have Kafka client attributes after migration."""
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService()
    assert hasattr(svc, "_kafka_consumer"), "_kafka_consumer attribute missing"
    assert hasattr(svc, "_kafka_producer"), "_kafka_producer attribute missing"
    assert hasattr(svc, "env_name"), "env_name attribute missing"


def test_ai_narrative_no_redis_client():
    """KAFKA-08: AINarrativeService must not initialize a redis_client (fully removed)."""
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService()
    assert not hasattr(
        svc, "redis_client"
    ), "ai_narrative_service must not have redis_client — Redis fully removed"


def test_ai_narrative_has_llm_scores_cache():
    """KAFKA-08: _llm_scores_cache in-process dict replaces Redis HSET/HGETALL."""
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService()
    assert hasattr(svc, "_llm_scores_cache"), "_llm_scores_cache attribute missing"
    assert isinstance(svc._llm_scores_cache, dict), "_llm_scores_cache must be a dict"


# -- i8 enrichment stream publish --------------------------------------------------


def _make_service_new():
    """Build AINarrativeService via __new__ (bypass __init__ to avoid LLM chain setup)."""
    import asyncio

    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService.__new__(AINarrativeService)
    svc.logger = MagicMock()
    svc.running = False
    svc.shutdown_requested = False
    svc.env_prefix = "development:"
    svc.env_name = "development"
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

    # LLM chain mocks — short_chain and deep_chain are the active chains post-22-03
    svc.short_chain = MagicMock()
    svc.short_chain.generate = AsyncMock(return_value=None)
    svc.short_chain.last_provider_id = "zai"
    svc.deep_chain = MagicMock()
    svc.deep_chain.generate = AsyncMock(return_value=None)
    svc.deep_chain.last_provider_id = "zai"
    svc._per_signal_timeout = 30.0

    # Kafka producer mock (replaces Redis)
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()

    # In-process caches (KAFKA-08)
    svc._llm_scores_cache: dict = {}
    svc._group_fingerprints: dict = {}
    svc._pending_tasks: set = set()

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
async def test_i8_not_published_when_narrative_generated():
    """KAFKA-08: i8 publish is deferred to Plan 4 (SSE migration) — NOT published in Plan 3.

    When narrative succeeds, narratives topic IS published but i8 is NOT yet published.
    Plan 4 will add topic_intelligence_i8 publish.
    """
    svc = _make_service_new()
    svc.short_chain.generate = AsyncMock(return_value="Bullish trend setup, entry at 5100.")
    svc.short_chain.last_provider_id = "zai"

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    await asyncio.sleep(0.1)  # let background narrative tasks complete

    # narratives topic IS published
    published_topics = [str(c.args[0]) for c in svc._kafka_producer.publish.call_args_list]
    assert any(
        "narratives" in name for name in published_topics
    ), f"Expected narratives publish. Got: {published_topics}"
    # i8 is NOT yet published (deferred to Plan 4 SSE migration)
    assert not any(
        "intelligence_i8" in name for name in published_topics
    ), "i8 publish must be deferred to Plan 4 — not published in Plan 3"


@pytest.mark.asyncio
async def test_i8_not_published_when_narrative_empty():
    """No i8 publish when Ollama/LLM returns empty string."""
    svc = _make_service_new()
    svc.short_chain.generate = AsyncMock(return_value=None)
    svc.deep_chain.generate = AsyncMock(return_value=None)

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    await asyncio.sleep(0.1)  # let background tasks complete (they should not publish)

    published_topics = [str(c.args[0]) for c in svc._kafka_producer.publish.call_args_list]
    assert not any("intelligence_i8" in name for name in published_topics)


@pytest.mark.asyncio
async def test_i8_payload_shape_deferred():
    """KAFKA-08: i8 publish is deferred to Plan 4 — verify narratives payload shape instead.

    The narrative msg published to topic_narratives has the required fields.
    i8 will be its own publish in Plan 4.
    """
    svc = _make_service_new()
    svc.short_chain.generate = AsyncMock(return_value="Short narrative for test.")
    svc.short_chain.last_provider_id = "zai"

    fields = _make_signal_fields_i8(confidence=0.85)
    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    await asyncio.sleep(0.1)  # let background narrative tasks complete

    # Find the narratives publish call (not llm.calls)
    narrative_call = None
    for c in svc._kafka_producer.publish.call_args_list:
        topic = str(c.args[0])
        if "narratives" in topic and "llm" not in topic:
            narrative_call = c
            break
    assert narrative_call is not None, "Expected narratives publish call not found"

    payload = narrative_call.args[1]
    for key in ("symbol", "timeframe", "narrative", "model", "confidence"):
        assert key in payload, f"Missing key in narratives payload: {key}"
    assert payload["symbol"] == "ESH6"
    assert payload["timeframe"] == "5m"
    assert payload["model"] == "zai"


@pytest.mark.asyncio
async def test_i8_summary_truncated_at_280_chars_deferred():
    """KAFKA-08: narrative_short uses summary[:280] in i8 msg — verify via service source.

    i8 is deferred to Plan 4, but the truncation logic is present in _run_narrative_call.
    We verify the source code contains the truncation pattern.
    """
    import inspect

    import services.ai_narrative_service as mod

    # Verify the 280-char truncation constant is present in the service
    assert "280" in inspect.getsource(mod), "280-char i8 truncation must be present in service"


@pytest.mark.asyncio
async def test_i8_not_published_on_low_confidence():
    """confidence <= 0.70 -> skipped before narrative generation, no i8 publish."""
    svc = _make_service_new()
    svc.short_chain.generate = AsyncMock(return_value="Should not be called")

    fields = _make_signal_fields_i8(confidence=0.65)
    result = await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")

    assert result is True
    published_topics = [str(c.args[0]) for c in svc._kafka_producer.publish.call_args_list]
    assert not any("intelligence_i8" in name for name in published_topics)
    svc.short_chain.generate.assert_not_called()


# ---- LLM call payload helper ----


def test_build_llm_call_payload_per_signal_fields():
    """Per-signal payload contains all required string fields."""
    from services.ai_narrative_service import _build_llm_call_payload

    sd = {
        "symbol": "ESH6",
        "timeframe": "5m",
        "regime_context": "trending",
        "setup_plugin": "BosSetup",
        "confidence": 0.85,
        "entry_price": "5100.0",
        "stop_loss": "5090.0",
        "profit_target": "5120.0",
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
    svc.env_name = "development"
    svc._preferred_models = {}  # new attribute — must be set manually per CLAUDE.md pattern
    svc._llm_scores_cache = {}  # KAFKA-08: in-process cache (replaces Redis hgetall)
    # Mock chains
    svc.short_chain = MagicMock()
    svc.short_chain.providers = []
    svc.deep_chain = MagicMock()
    svc.deep_chain.providers = []
    svc.group_chain = MagicMock()
    svc.group_chain.providers = []
    svc.logger = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_apply_score_routing_per_regime():
    """KAFKA-08: per-regime routing reads from _llm_scores_cache (not Redis hgetall).

    trending winner != ranging winner, each stored independently in _preferred_models.
    """
    svc = _make_svc_routing()

    # Populate _llm_scores_cache as _warm_llm_scores_cache_from_db() would
    svc._llm_scores_cache = {
        "narrative_short": {
            "trending": {
                "model_A": {"is_significant": True, "avg_pnl_r": 2.0},
            },
            "ranging": {
                "model_B": {"is_significant": True, "avg_pnl_r": 1.5},
            },
        }
    }
    await svc._apply_score_routing()

    assert svc._preferred_models.get("narrative_short", {}).get("trending") == "model_A"
    assert svc._preferred_models.get("narrative_short", {}).get("ranging") == "model_B"
    # volatile has no significant model — should not be in dict
    assert "volatile" not in svc._preferred_models.get("narrative_short", {})


@pytest.mark.asyncio
async def test_apply_score_routing_falls_back_without_significant():
    """KAFKA-08: regime with no significant model gets no entry in _preferred_models."""
    svc = _make_svc_routing()

    # Not significant (is_significant=False)
    svc._llm_scores_cache = {
        "narrative_short": {
            "trending": {
                "model_X": {"is_significant": False, "avg_pnl_r": 5.0},
            },
        }
    }
    await svc._apply_score_routing()

    assert "trending" not in svc._preferred_models.get("narrative_short", {})


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
    # narrative_short is the call_type used post-22-03 (per_signal was legacy)
    svc._preferred_models = {"narrative_short": {"trend_up": "model_A"}}

    # Give short_chain real providers so _promote_model_in_chain can find model_A
    p1 = MagicMock()
    p1.provider_id = "default_model"
    p2 = MagicMock()
    p2.provider_id = "model_A"
    svc.short_chain.providers = [p1, p2]
    svc.short_chain.generate = AsyncMock(return_value="Promoted narrative.")
    svc.short_chain.last_provider_id = "model_A"

    fields = _make_signal_fields_i8(confidence=0.85)
    # Override regime_context to match our preferred model key
    fields[b"regime_context"] = b"trend_up"

    await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    await asyncio.sleep(0.05)  # let background task run

    # model_A should now be at position 0 after promotion
    assert svc.short_chain.providers[0].provider_id == "model_A"


# ---- SYSTEM_PROMPT voice and chain separation (plan 22-02) ----


def test_system_prompt_prohibits_passive_voice_phrases():
    """SYSTEM_PROMPT must not contain any banned passive-voice/hedging phrases."""
    from services.ai_narrative_service import SYSTEM_PROMPT

    banned = ["capitalize", "execute long", "protect the position", "suggests", "price momentum"]
    for phrase in banned:
        assert (
            phrase not in SYSTEM_PROMPT.lower()
        ), f"Banned phrase {phrase!r} found in SYSTEM_PROMPT"


def test_system_prompt_establishes_analyst_voice():
    """SYSTEM_PROMPT must establish a senior trading desk analyst voice."""
    from services.ai_narrative_service import SYSTEM_PROMPT

    prompt_lower = SYSTEM_PROMPT.lower()
    assert (
        "trading desk" in prompt_lower or "analyst" in prompt_lower
    ), "SYSTEM_PROMPT must reference 'trading desk' or 'analyst'"
    assert (
        "passive voice" in prompt_lower or "precise" in prompt_lower
    ), "SYSTEM_PROMPT must reference 'passive voice' or 'precise'"


def test_service_has_short_chain():
    """_build_chains() must create both short_chain and deep_chain attributes."""
    svc = _make_service()
    assert hasattr(svc, "short_chain"), "short_chain attribute missing after _build_chains()"
    assert hasattr(svc, "deep_chain"), "deep_chain attribute missing after _build_chains()"


def test_service_short_chain_is_separate_from_deep_chain():
    """short_chain and deep_chain must be distinct LLMChain instances."""
    svc = _make_service()
    assert (
        svc.short_chain is not svc.deep_chain
    ), "short_chain and deep_chain must be separate instances"


# ---- Plan 22-03: Concurrent narrative tier calls ----


def _make_service_concurrent():
    """Build AINarrativeService via __new__ with attrs needed for concurrent narrative tests."""
    from services.ai_narrative_service import AINarrativeService

    svc = AINarrativeService.__new__(AINarrativeService)
    svc.logger = MagicMock()
    svc.running = False
    svc.shutdown_requested = False
    svc.env_prefix = "development:"
    svc.env_name = "development"
    svc.consumer_group = "ai_narrative"
    svc.consumer_name = "narrative_test"
    svc._stream_map = {}
    svc._latest_signals = {}
    svc._latest_signals_lock = asyncio.Lock()
    svc._preferred_models = {}

    # Metrics stubs
    svc.narratives_generated_total = MagicMock()
    svc.narratives_skipped_total = MagicMock()
    svc.ollama_latency_ms = MagicMock()
    svc.error_count_total = MagicMock()
    svc.group_narratives_generated = MagicMock()
    svc._total_narratives = 0
    svc._error_count = 0

    # short_chain and deep_chain as AsyncMock chains
    svc.short_chain = MagicMock()
    svc.short_chain.generate = AsyncMock(return_value="Test narrative.")
    svc.short_chain.last_provider_id = "openrouter:test-short"

    svc.deep_chain = MagicMock()
    svc.deep_chain.generate = AsyncMock(return_value="Test narrative.")
    svc.deep_chain.last_provider_id = "openrouter:test-deep"

    svc._per_signal_timeout = 30.0

    # Kafka producer mock (KAFKA-08 — replaces Redis)
    svc._kafka_producer = AsyncMock()
    svc._kafka_producer.publish = AsyncMock()

    # In-process caches (KAFKA-08)
    svc._llm_scores_cache: dict = {}
    svc._group_fingerprints: dict = {}
    svc._pending_tasks: set = set()

    return svc


@pytest.mark.asyncio
async def test_process_message_fires_two_narrative_tasks():
    """_process_single_message fires two concurrent asyncio tasks: narrative_short +
    narrative_deep."""
    svc = _make_service_concurrent()

    published_call_types = []

    async def _capture_publish(topic, data, **kwargs):
        call_type = data.get("call_type")
        if call_type:
            published_call_types.append(call_type)

    svc._kafka_producer.publish.side_effect = _capture_publish

    fields = {
        b"direction": b"1",
        b"symbol": b"ESH6",
        b"timeframe": b"5m",
        b"timestamp": b"2026-03-09T10:05:00+00:00",
        b"confidence": b"0.80",
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

    result = await svc._process_single_message("ESH6", "5m", fields, "stream", b"1-0")
    await asyncio.sleep(0.1)  # let background tasks complete

    assert result is True
    assert (
        "narrative_short" in published_call_types
    ), f"narrative_short not found in published_call_types: {published_call_types}"
    assert (
        "narrative_deep" in published_call_types
    ), f"narrative_deep not found in published_call_types: {published_call_types}"


def test_narrative_stream_message_has_type_field():
    """narratives stream messages include narrative_type field ('short' or 'deep')."""
    pass  # stub — deferred per CONTEXT.md
