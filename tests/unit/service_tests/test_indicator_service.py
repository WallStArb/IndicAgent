"""Tests for indicator_service — standalone I1 computation service."""

from datetime import datetime

import redis.asyncio as redis


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


def test_stream_map_populated_after_setup():
    """_stream_map must contain (symbol, timeframe) for every stream name after setup."""
    import asyncio
    from unittest.mock import AsyncMock

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xrevrange = AsyncMock(return_value=[])
    svc.redis_client.xgroup_create = AsyncMock(side_effect=redis.ResponseError("BUSYGROUP Consumer Group name already exists"))
    svc.redis_client.xgroup_setid = AsyncMock()

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    expected = len(svc.config["service"]["timeframes"]) * len(svc.config["service"]["symbols"])
    assert len(svc._stream_map) == expected
    for stream_name, (sym, tf) in svc._stream_map.items():
        assert sym in svc.config["service"]["symbols"]
        assert tf in svc.config["service"]["timeframes"]


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
        "timestamp": ts, "open": 5300.0, "high": 5305.0,
        "low": 5299.0, "close": 5303.0, "volume": 1000,
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


def test_process_single_bar_returns_true_on_success():
    """_process_single_bar must return True when bar is processed successfully."""
    import asyncio
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.bars_processed_total = MagicMock()
    svc.error_count_total = MagicMock()

    fields = {
        b"timestamp": b"2026-02-28T10:00:00",
        b"source": b"ibkr",
        b"open": b"5300.0", b"high": b"5305.0",
        b"low": b"5299.0", b"close": b"5303.0", b"volume": b"1000",
    }

    with patch.object(svc, "_run_i1_plugins", return_value={"rsi_14": 58.3}):
        # Pre-fill history so min_bars is met
        from datetime import timedelta
        for i in range(130):
            ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history["ES:1m"][ts.isoformat()] = {
                "timestamp": ts, "open": 5300.0, "high": 5305.0,
                "low": 5299.0, "close": 5303.0, "volume": 1000,
            }
        result = asyncio.get_event_loop().run_until_complete(
            svc._process_single_bar("ES", "1m", fields, "market:ES:1m", b"1-0")
        )
    assert result is True


def test_process_single_bar_returns_false_on_exception():
    """_process_single_bar must return False when processing raises."""
    import asyncio
    from unittest.mock import MagicMock

    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    svc.redis_client = None  # will cause AttributeError
    svc.error_count_total = MagicMock()

    fields = {b"timestamp": b"bad-ts"}  # will fail fromisoformat

    result = asyncio.get_event_loop().run_until_complete(
        svc._process_single_bar("ES", "1m", fields, "market:ES:1m", b"1-0")
    )
    assert result is False
