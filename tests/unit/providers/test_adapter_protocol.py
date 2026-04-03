"""Tests for DataProviderAdapter Protocol and ProviderQualityEvent schema.

TDD RED phase — all tests fail until production code is implemented in Task 2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest


class TestDataProviderAdapterProtocol:
    def test_protocol_is_runtime_checkable(self):
        """DataProviderAdapter must be runtime_checkable so isinstance() works."""
        from src.providers.base import DataProviderAdapter

        class NotAnAdapter:
            pass

        # A bare class without the required attributes must NOT satisfy the protocol
        assert not isinstance(NotAnAdapter(), DataProviderAdapter)

    def test_protocol_requires_provider_name(self):
        """Protocol must declare provider_name: str attribute."""
        from src.providers.base import DataProviderAdapter

        assert "provider_name" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_connect(self):
        """Protocol must declare async connect() -> bool."""
        from src.providers.base import DataProviderAdapter

        assert "connect" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_disconnect(self):
        """Protocol must declare async disconnect() -> None."""
        from src.providers.base import DataProviderAdapter

        assert "disconnect" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_is_connected(self):
        """Protocol must declare is_connected() -> bool."""
        from src.providers.base import DataProviderAdapter

        assert "is_connected" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_stream_bars(self):
        """Protocol must declare async stream_bars(instruments) -> AsyncIterator[BarMessage]."""
        from src.providers.base import DataProviderAdapter

        assert "stream_bars" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_fetch_historical(self):
        """Protocol must declare async fetch_historical(symbol, tf, start, end) -> list[BarMessage]."""
        from src.providers.base import DataProviderAdapter

        assert "fetch_historical" in DataProviderAdapter.__protocol_attrs__

    def test_protocol_requires_qualify_instrument(self):
        """Protocol must declare async qualify_instrument(instrument) -> Instrument."""
        from src.providers.base import DataProviderAdapter

        assert "qualify_instrument" in DataProviderAdapter.__protocol_attrs__

    def test_minimal_implementation_satisfies_protocol(self):
        """A class implementing all methods must satisfy isinstance check."""
        from src.core.models import Instrument
        from src.core.schemas.bar_message import BarMessage
        from src.providers.base import DataProviderAdapter

        class MinimalAdapter:
            provider_name = "test"

            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            async def stream_bars(self, instruments: list) -> AsyncIterator[BarMessage]:
                async def _gen():
                    return
                    yield  # pragma: no cover
                return _gen()

            async def fetch_historical(
                self, symbol: str, tf: str, start: datetime, end: datetime
            ) -> list[BarMessage]:
                return []

            async def qualify_instrument(self, instrument: Instrument) -> Instrument:
                return instrument

        assert isinstance(MinimalAdapter(), DataProviderAdapter)


class TestProviderQualityEvent:
    def _make_event(self, **overrides):
        from src.core.schemas.provider_quality import ProviderQualityEvent

        defaults = {
            "ts": datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            "symbol": "ES",
            "tf": "1m",
            "provider": "ibkr",
            "event_type": "bar_received",
            "publish_ts": datetime(2026, 3, 28, 10, 0, 0, tzinfo=UTC),
            "consume_ts": datetime(2026, 3, 28, 10, 0, 1, tzinfo=UTC),
            "latency_ms": 123.4,
        }
        defaults.update(overrides)
        return ProviderQualityEvent(**defaults)

    def test_provider_quality_event_fields(self):
        """ProviderQualityEvent must construct and serialize with all required fields."""
        event = self._make_event()
        data = event.model_dump()
        assert data["symbol"] == "ES"
        assert data["tf"] == "1m"
        assert data["provider"] == "ibkr"
        assert data["event_type"] == "bar_received"
        assert data["latency_ms"] == pytest.approx(123.4)
        assert data["promoted_provider"] is None

    def test_provider_quality_event_ts_must_be_utc(self):
        """ProviderQualityEvent must reject naive datetime for ts field."""
        from pydantic import ValidationError

        from src.core.schemas.provider_quality import ProviderQualityEvent

        with pytest.raises(ValidationError):
            ProviderQualityEvent(
                ts=datetime(2026, 3, 28, 10, 0),  # naive — no tzinfo
                symbol="ES",
                tf="1m",
                provider="ibkr",
                event_type="bar_received",
                publish_ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
                consume_ts=datetime(2026, 3, 28, 10, 0, 1, tzinfo=UTC),
                latency_ms=10.0,
            )

    def test_provider_quality_event_publish_ts_must_be_utc(self):
        """ProviderQualityEvent must reject naive publish_ts."""
        from pydantic import ValidationError

        from src.core.schemas.provider_quality import ProviderQualityEvent

        with pytest.raises(ValidationError):
            ProviderQualityEvent(
                ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
                symbol="ES",
                tf="1m",
                provider="ibkr",
                event_type="bar_received",
                publish_ts=datetime(2026, 3, 28, 10, 0),  # naive
                consume_ts=datetime(2026, 3, 28, 10, 0, 1, tzinfo=UTC),
                latency_ms=10.0,
            )

    def test_provider_quality_event_consume_ts_must_be_utc(self):
        """ProviderQualityEvent must reject naive consume_ts."""
        from pydantic import ValidationError

        from src.core.schemas.provider_quality import ProviderQualityEvent

        with pytest.raises(ValidationError):
            ProviderQualityEvent(
                ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
                symbol="ES",
                tf="1m",
                provider="ibkr",
                event_type="bar_received",
                publish_ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
                consume_ts=datetime(2026, 3, 28, 10, 0, 1),  # naive
                latency_ms=10.0,
            )

    def test_provider_quality_event_types(self):
        """event_type Literal only accepts the four defined values."""
        from pydantic import ValidationError

        valid_types = ["bar_received", "gap_detected", "failover", "recovery"]
        for et in valid_types:
            event = self._make_event(event_type=et)
            assert event.event_type == et

        with pytest.raises(ValidationError):
            self._make_event(event_type="unknown_type")

    def test_provider_quality_event_promoted_optional(self):
        """promoted_provider defaults to None and accepts a string."""
        event = self._make_event()
        assert event.promoted_provider is None

        event_with_provider = self._make_event(promoted_provider="alpaca")
        assert event_with_provider.promoted_provider == "alpaca"
