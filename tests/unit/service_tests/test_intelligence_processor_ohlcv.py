"""Tests that intelligence_processor_service enriches published messages with OHLCV."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_publish_intelligence_includes_ohlcv_fields():
    """Published intelligence message must include open/high/low/close/volume."""
    from services.intelligence_processor_service import IntelligenceProcessorService

    with patch("services.intelligence_processor_service.start_metrics_server"):
        svc = IntelligenceProcessorService()

    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.env_prefix = ""

    bar_data = {
        "open": 5100.25, "high": 5105.50, "low": 5098.75,
        "close": 5103.00, "volume": 12345,
    }
    intelligence = {"trend_regime": 0.65, "atr_14": 12.5}
    from datetime import datetime, timezone
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    await svc._publish_intelligence("ESH6", "5m", intelligence, ts, bar_data)

    call_args = svc.redis_client.xadd.call_args
    message = call_args[0][1]  # second positional arg is the message dict

    assert message["open"] == "5100.25"
    assert message["high"] == "5105.5"
    assert message["low"] == "5098.75"
    assert message["close"] == "5103.0"
    assert message["volume"] == "12345"
    assert message["trend_regime"] == "0.65"


@pytest.mark.asyncio
async def test_publish_intelligence_backward_compat_no_bar_data():
    """bar_data is optional — existing callers without it still work."""
    from services.intelligence_processor_service import IntelligenceProcessorService

    with patch("services.intelligence_processor_service.start_metrics_server"):
        svc = IntelligenceProcessorService()

    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()
    svc.env_prefix = ""

    from datetime import datetime, timezone
    ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

    # Must not raise even without bar_data
    await svc._publish_intelligence("ESH6", "5m", {"trend_regime": 0.5}, ts)

    assert svc.redis_client.xadd.called
