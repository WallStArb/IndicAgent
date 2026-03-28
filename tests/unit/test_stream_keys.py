"""Tests for stream key helpers."""

from src.core.stream_keys import (
    env_prefix,
    message_key,
    narratives_group,
    system_events,
    topic_indicators,
    topic_intelligence,
    topic_intelligence_i8,
    topic_llm_calls,
    topic_llm_outcomes,
    topic_market_bars,
    topic_market_ticks,
    topic_narratives,
    topic_signals,
    topic_signals_aggregated,
)


def test_narratives_group_no_prefix():
    key = narratives_group("", "equity")
    assert key == "narratives:group:equity"


def test_narratives_group_with_env_prefix():
    key = narratives_group("development:", "metals")
    assert key == "development:narratives:group:metals"


def test_narratives_group_all_groups():
    groups = ["equity", "energy", "metals", "rates", "fx_crypto", "ag"]
    for g in groups:
        key = narratives_group("", g)
        assert key == f"narratives:group:{g}"


def test_system_events_no_prefix():
    assert system_events("") == "system:events"


def test_system_events_with_env_prefix():
    assert system_events("development:") == "development:system:events"


# ---------------------------------------------------------------------------
# Kafka topic builder tests (Phase 30+)
# ---------------------------------------------------------------------------


def test_env_prefix_with_name() -> None:
    assert env_prefix("dev") == "dev."


def test_env_prefix_empty() -> None:
    assert env_prefix("") == ""


def test_topic_market_ticks_with_env() -> None:
    assert topic_market_ticks("dev") == "dev.market.ticks"


def test_topic_market_ticks_no_env() -> None:
    assert topic_market_ticks("") == "market.ticks"


def test_topic_market_bars_with_env() -> None:
    assert topic_market_bars("dev") == "dev.market.bars"


def test_topic_indicators_with_env() -> None:
    assert topic_indicators("dev") == "dev.indicators"


def test_topic_indicators_no_env() -> None:
    assert topic_indicators("") == "indicators"


def test_topic_intelligence_with_env() -> None:
    assert topic_intelligence("dev") == "dev.intelligence"


def test_topic_intelligence_i8_with_env() -> None:
    assert topic_intelligence_i8("dev") == "dev.intelligence.i8"


def test_topic_signals_with_env() -> None:
    assert topic_signals("dev") == "dev.signals"


def test_topic_signals_aggregated_with_env() -> None:
    assert topic_signals_aggregated("dev") == "dev.signals.aggregated"


def test_topic_narratives_with_env() -> None:
    assert topic_narratives("dev") == "dev.narratives"


def test_topic_llm_calls_with_env() -> None:
    assert topic_llm_calls("dev") == "dev.llm.calls"


def test_topic_llm_outcomes_with_env() -> None:
    assert topic_llm_outcomes("dev") == "dev.llm.outcomes"


def test_message_key_with_timeframe() -> None:
    assert message_key("ES", "1m") == "ES:1m"


def test_message_key_without_timeframe() -> None:
    assert message_key("ES") == "ES"


def test_message_key_none_timeframe() -> None:
    assert message_key("GC", None) == "GC"


# ---------------------------------------------------------------------------
# Provider abstraction stream key tests (Phase 54-01)
# ---------------------------------------------------------------------------


def test_topic_market_bars_raw() -> None:
    from src.core.stream_keys import topic_market_bars_raw

    assert topic_market_bars_raw("development", "ibkr") == "development.market.bars.raw.ibkr"


def test_topic_market_bars_raw_alpaca() -> None:
    from src.core.stream_keys import topic_market_bars_raw

    assert topic_market_bars_raw("development", "alpaca") == "development.market.bars.raw.alpaca"


def test_topic_market_data_quality() -> None:
    from src.core.stream_keys import topic_market_data_quality

    assert topic_market_data_quality("development") == "development.market.data.quality"


def test_topic_market_data_quality_distinct_from_pipeline() -> None:
    from src.core.stream_keys import topic_data_quality, topic_market_data_quality

    assert topic_market_data_quality("development") != topic_data_quality("development")
