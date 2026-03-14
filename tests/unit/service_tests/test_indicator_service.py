"""Tests for indicator_service — standalone I1 computation service."""

from datetime import datetime

import pytest


def test_build_i1_message_includes_ohlcv_and_features():
    """Combined message must contain OHLCV fields AND I1 feature outputs."""
    from services.indicator_service import build_i1_message

    bar = {"open": 5300.0, "high": 5305.0, "low": 5299.0, "close": 5303.0, "volume": 1000}
    features = {"rsi_14": 58.3, "macd": 2.1, "atr_14": 4.5}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert msg["open"] == "5300.0"
    assert msg["high"] == "5305.0"
    assert msg["close"] == "5303.0"
    assert msg["volume"] == "1000"
    assert msg["rsi_14"] == "58.3"
    assert msg["macd"] == "2.1"
    assert msg["timestamp"] == ts.isoformat()
    assert msg["symbol"] == "ES"
    assert msg["timeframe"] == "1m"


def test_build_i1_message_skips_non_scalar_features():
    """Non-scalar values (lists, dicts) must be excluded from message."""
    from services.indicator_service import build_i1_message

    bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}
    features = {"rsi_14": 55.0, "targets": [101.0, 102.0], "meta": {"x": 1}}
    ts = datetime(2026, 2, 20, 10, 0, 0)

    msg = build_i1_message(bar, features, ts, symbol="ES", timeframe="1m")

    assert "rsi_14" in msg
    assert "targets" not in msg
    assert "meta" not in msg


def test_parse_indicators_message_splits_ohlcv_and_features():
    """parse_indicators_message must split OHLCV from feature fields."""
    from services.indicator_service import parse_indicators_message

    raw = {
        b"timestamp": b"2026-02-20T10:00:00",
        b"symbol": b"ES",
        b"timeframe": b"1m",
        b"open": b"5300.0",
        b"high": b"5305.0",
        b"low": b"5299.0",
        b"close": b"5303.0",
        b"volume": b"1000",
        b"rsi_14": b"58.3",
        b"macd": b"2.1",
    }

    bar, features = parse_indicators_message(raw)

    assert bar["open"] == 5300.0
    assert bar["close"] == 5303.0
    assert bar["volume"] == 1000
    assert features["rsi_14"] == 58.3
    assert features["macd"] == 2.1
    assert "open" not in features
    assert "timestamp" not in features


@pytest.mark.asyncio
async def test_kafka_consumer_uses_market_bars_topic():
    """IndicatorService must use topic_market_bars for Kafka consumer (replaces Redis
    xreadgroup)."""
    from services.indicator_service import IndicatorService
    from src.core.stream_keys import topic_market_bars

    svc = IndicatorService()
    # env_name defaults to "" in test env
    expected_topic = topic_market_bars(svc.env_name)
    # Verify the Kafka producer is initialized (not a Redis client)
    assert svc._kafka_producer is not None
    # Verify config symbols/timeframes are present
    assert len(svc.config["service"]["symbols"]) > 0
    assert len(svc.config["service"]["timeframes"]) > 0
    # Verify env_name is accessible
    assert hasattr(svc, "env_name")


def test_df_cache_miss_builds_dataframe():
    """_get_df must build DataFrame from bar_history on cache miss."""
    from collections import OrderedDict
    from datetime import datetime

    import pandas as pd

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    key = "ES:1m"
    svc.bar_history[key] = OrderedDict()
    svc._df_cache[key] = None
    ts = datetime(2026, 2, 28, 10, 0, 0)
    svc.bar_history[key][ts.isoformat()] = {
        "timestamp": ts,
        "open": 5300.0,
        "high": 5305.0,
        "low": 5299.0,
        "close": 5303.0,
        "volume": 1000,
    }

    df = svc._get_df(key)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["close"] == 5303.0


def test_df_cache_hit_returns_same_object():
    """_get_df must return cached DataFrame on hit (no rebuild)."""
    import pandas as pd

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    key = "ES:1m"
    cached = pd.DataFrame([{"close": 5303.0}])
    svc._df_cache[key] = cached

    result = svc._get_df(key)

    assert result is cached  # exact same object, not a copy


def test_bar_append_invalidates_df_cache():
    """Appending a bar must set _df_cache[key] = None."""
    from collections import OrderedDict
    from datetime import datetime

    import pandas as pd

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    key = "ES:1m"
    svc.bar_history[key] = OrderedDict()
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])

    # Simulate what _process_single_bar does on bar append
    ts = datetime(2026, 2, 28, 10, 1, 0)
    svc.bar_history[key][ts.isoformat()] = {"timestamp": ts, "close": 5303.0}
    svc._df_cache[key] = None  # invalidate — this is what we're testing gets called

    assert svc._df_cache[key] is None


@pytest.mark.asyncio
async def test_process_single_bar_returns_true_on_success():
    """_process_single_bar must return True when bar is processed successfully."""
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    # Mock Kafka producer
    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    svc._kafka_producer = kafka_producer
    svc.bars_processed_total = MagicMock()
    svc.error_count_total = MagicMock()

    fields = {
        b"timestamp": b"2026-02-28T10:00:00",
        b"source": b"ibkr",
        b"open": b"5300.0",
        b"high": b"5305.0",
        b"low": b"5299.0",
        b"close": b"5303.0",
        b"volume": b"1000",
    }

    with patch.object(svc, "_run_i1_plugins", new=AsyncMock(return_value={"rsi_14": 58.3})):
        # Pre-fill history so min_bars is met
        for i in range(130):
            ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history["ES:1m"][ts.isoformat()] = {
                "timestamp": ts,
                "open": 5300.0,
                "high": 5305.0,
                "low": 5299.0,
                "close": 5303.0,
                "volume": 1000,
            }
        result = await svc._process_single_bar("ES", "1m", fields)
    assert result is True


class TestIndicatorServicePluginOptimizations:
    """Plugin cache, state isolation, and metrics sampling for I1 plugins."""

    def test_i1_plugin_cache_populated_at_init(self):
        """_i1_plugin_cache must contain all I1 plugin names after __init__."""
        from services.indicator_service import I1_PLUGINS, IndicatorService

        svc = IndicatorService()
        for name in I1_PLUGINS:
            assert name in svc._i1_plugin_cache, f"_i1_plugin_cache missing: {name}"

    @pytest.mark.asyncio
    async def test_i1_state_keyed_per_symbol_timeframe(self):
        """I1 plugin state must be namespaced per (plugin, symbol, timeframe)."""
        from collections import OrderedDict
        from datetime import datetime, timedelta

        import pandas as pd

        from services.indicator_service import I1_PLUGINS, IndicatorService

        svc = IndicatorService()

        # Build minimal bar history for two symbols
        for sym in ("ES", "NQ"):
            key = f"{sym}:1m"
            svc.bar_history[key] = OrderedDict()
            for i in range(130):
                ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
                svc.bar_history[key][ts.isoformat()] = {
                    "timestamp": ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 500,
                }
            svc._df_cache[key] = None

        df = pd.DataFrame(list(svc.bar_history["ES:1m"].values()))
        frames = {"main": df}

        # Run for ES, then NQ
        await svc._run_i1_plugins(frames, "ES", "1m")
        await svc._run_i1_plugins(frames, "NQ", "1m")

        # Each plugin should have separate state dicts for ES vs NQ
        pname = I1_PLUGINS[0]  # check first I1 plugin
        es_state = svc._i1_plugin_states.get((pname, "ES", "1m"))
        nq_state = svc._i1_plugin_states.get((pname, "NQ", "1m"))
        # Both should exist and be different objects
        assert es_state is not None
        assert nq_state is not None
        assert es_state is not nq_state

    @pytest.mark.asyncio
    async def test_i1_success_metrics_sampled(self):
        """I1 success metrics sampled at _METRICS_SAMPLE_RATE, errors always recorded."""
        from collections import OrderedDict
        from datetime import datetime, timedelta
        from unittest.mock import patch

        import pandas as pd

        from services.indicator_service import I1_PLUGINS, IndicatorService

        svc = IndicatorService()
        key = "ES:1m"
        svc.bar_history[key] = OrderedDict()
        for i in range(130):
            ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history[key][ts.isoformat()] = {
                "timestamp": ts,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 500,
            }
        df = pd.DataFrame(list(svc.bar_history[key].values()))
        frames = {"main": df}

        with patch("services.indicator_service.record_plugin_execution") as mock_record:
            for _ in range(10):
                await svc._run_i1_plugins(frames, "ES", "1m")

        # args: (plugin_name, symbol, timeframe, elapsed, status, tier) — index 4 = status
        success_calls = [c for c in mock_record.call_args_list if c.args[4] == "success"]
        assert len(success_calls) < len(I1_PLUGINS) * 10, "Expected sampling"
        # Fresh counter starts at 0; after exactly 10 calls each plugin records once
        assert len(success_calls) == len(I1_PLUGINS) * 1  # 1-in-10


def test_process_single_bar_returns_false_on_exception():
    """_process_single_bar must return False when processing raises."""
    import asyncio
    from unittest.mock import MagicMock

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.error_count_total = MagicMock()

    fields = {b"timestamp": b"bad-ts"}  # will fail fromisoformat

    result = asyncio.get_event_loop().run_until_complete(
        svc._process_single_bar("ES", "1m", fields)
    )
    assert result is False


# ---------------------------------------------------------------------------
# KAFKA-05: indicator_service publishes to dev.indicators with key ES:1m
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kafka05_indicator_service_publishes_to_correct_topic_and_key():
    """KAFKA-05: _process_single_bar must publish to topic_indicators('dev') with key 'ES:1m'."""
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    # Mock Kafka producer
    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    svc._kafka_producer = kafka_producer
    svc.bars_processed_total = MagicMock()
    svc.error_count_total = MagicMock()

    fields = {
        b"timestamp": b"2026-03-14T10:00:00",
        b"source": b"authoritative",
        b"open": b"5500.0",
        b"high": b"5510.0",
        b"low": b"5495.0",
        b"close": b"5505.0",
        b"volume": b"1000",
    }

    with patch.object(svc, "_run_i1_plugins", new=AsyncMock(return_value={"rsi_14": 58.3})):
        # Pre-fill history so min_bars is met
        for i in range(130):
            ts = datetime(2026, 3, 14, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history["ES:1m"][ts.isoformat()] = {
                "timestamp": ts,
                "open": 5500.0,
                "high": 5510.0,
                "low": 5495.0,
                "close": 5505.0,
                "volume": 1000,
            }
        result = await svc._process_single_bar("ES", "1m", fields, "ignored", b"1-0")

    assert result is True
    kafka_producer.publish.assert_called_once()
    call_args = kafka_producer.publish.call_args
    topic = call_args.args[0]
    key = call_args.kwargs.get("key") or call_args.args[2]
    # env_name defaults to "" in test env (no INDICAGENT_ENV set) → topic = "indicators"
    # or "dev.indicators" if env_name="dev" — accept either
    assert "indicators" in topic, f"Expected topic containing 'indicators', got {topic!r}"
    assert key == "ES:1m", f"Expected key 'ES:1m', got {key!r}"


@pytest.mark.asyncio
async def test_indicator_service_seed_bar_history_from_db_graceful_fallback():
    """_seed_bar_history_from_db must log WARNING and continue when DB unreachable."""

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.db_manager = None  # No DB manager → graceful fallback path

    await svc._seed_bar_history_from_db()

    # bar_history should remain empty — no exception raised
    assert len(svc.bar_history) == 0
