"""Unit tests for TradingSession new methods and ContractUpdateEvent schema.

Phase 58.1-01: Foundational types for contract lifecycle automation.
"""

from datetime import UTC, date, datetime

import pytest

from src.core.models import SESSION_REGISTRY
from src.core.schemas.market_events import ContractUpdateEvent
from src.core.stream_keys import topic_contract_updates, topic_roll_dlq


class TestSessionWindowForDate:
    """Tests for TradingSession.session_window_for_date()."""

    def test_nyse_same_day_monday(self):
        """NYSE Monday: 09:30-16:00 ET (EDT = UTC-4) -> 13:30-20:00 UTC.

        March 23, 2026 is after DST starts (March 8, 2026), so ET = EDT = UTC-4.
        09:30 EDT + 4h = 13:30 UTC. 16:00 EDT + 4h = 20:00 UTC.
        """
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 23))  # Monday
        assert start == datetime(2026, 3, 23, 13, 30, tzinfo=UTC)
        assert end == datetime(2026, 3, 23, 20, 0, tzinfo=UTC)

    def test_nyse_saturday_non_trading(self):
        """NYSE Saturday: non-trading day -> (None, None)."""
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 21))  # Saturday
        assert start is None
        assert end is None

    def test_nyse_sunday_non_trading(self):
        """NYSE Sunday: non-trading day -> (None, None)."""
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 22))  # Sunday
        assert start is None
        assert end is None

    def test_futures_24_5_overnight_monday(self):
        """CME futures Monday: session starts Sunday 18:00 CST, ends Monday 17:00 CST.

        Etc/GMT+6 = UTC-6 year-round (no DST).
        Sunday 18:00 at UTC-6 = 18:00 + 6h = 00:00 UTC Monday.
        Monday 17:00 at UTC-6 = 17:00 + 6h = 23:00 UTC Monday.
        """
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 23))  # Monday
        assert start == datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 23, 23, 0, tzinfo=UTC)

    def test_futures_24_5_saturday_non_trading(self):
        """CME futures: Saturday is not in trading_days -> (None, None)."""
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 21))  # Saturday
        assert start is None
        assert end is None

    def test_futures_24_5_sunday_is_trading(self):
        """CME futures: Sunday is a trading day (trading_days includes 6)."""
        session = SESSION_REGISTRY["futures_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 22))  # Sunday
        assert start == datetime(2026, 3, 22, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 22, 23, 0, tzinfo=UTC)

    def test_crypto_24_7_all_day(self):
        """Crypto 24/7: any day is full 24h UTC window."""
        session = SESSION_REGISTRY["crypto_24_7"]
        start, end = session.session_window_for_date(date(2026, 3, 25))  # Wednesday
        assert start == datetime(2026, 3, 25, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 26, 0, 0, tzinfo=UTC)

    def test_crypto_24_7_saturday(self):
        """Crypto 24/7: Saturday also works (all 7 days)."""
        session = SESSION_REGISTRY["crypto_24_7"]
        start, end = session.session_window_for_date(date(2026, 3, 21))  # Saturday
        assert start == datetime(2026, 3, 21, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 22, 0, 0, tzinfo=UTC)

    def test_fx_24_5_all_day_trading(self):
        """FX 24/5: trading day is full 24h UTC window."""
        session = SESSION_REGISTRY["fx_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 23))  # Monday
        assert start == datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
        assert end == datetime(2026, 3, 24, 0, 0, tzinfo=UTC)

    def test_fx_24_5_saturday_non_trading(self):
        """FX 24/5: Saturday is not a trading day."""
        session = SESSION_REGISTRY["fx_24_5"]
        start, end = session.session_window_for_date(date(2026, 3, 21))  # Saturday
        assert start is None
        assert end is None

    def test_returns_utc_aware_datetimes(self):
        """Returned datetimes must be UTC timezone-aware (not naive)."""
        session = SESSION_REGISTRY["nyse"]
        start, end = session.session_window_for_date(date(2026, 3, 23))
        assert start is not None
        assert start.tzinfo is not None
        assert start.utcoffset().total_seconds() == 0


class TestMaxAchievablePct:
    """Tests for TradingSession.max_achievable_pct()."""

    def test_nyse_no_breaks(self):
        """NYSE: 390 min active / 390 min window = 1.0."""
        session = SESSION_REGISTRY["nyse"]
        assert session.max_achievable_pct() == pytest.approx(1.0)

    def test_crypto_24_7(self):
        """Crypto 24/7: 1440 min / 1440 min = 1.0."""
        session = SESSION_REGISTRY["crypto_24_7"]
        assert session.max_achievable_pct() == pytest.approx(1.0)

    def test_futures_24_5(self):
        """CME futures: 1380 min active / 1380 min window = 1.0 (23h session)."""
        session = SESSION_REGISTRY["futures_24_5"]
        assert session.max_achievable_pct() == pytest.approx(1.0)

    def test_fx_24_5(self):
        """FX 24/5: all-day session = 1.0."""
        session = SESSION_REGISTRY["fx_24_5"]
        assert session.max_achievable_pct() == pytest.approx(1.0)

    def test_tse_with_break(self):
        """TSE: 09:00-15:30 = 390 min, minus 11:30-12:30 = 60 min break.

        Active = 330 min, window = 390 min. max_achievable = 330/390 = 0.846...
        """
        session = SESSION_REGISTRY["tse"]
        pct = session.max_achievable_pct()
        assert pct == pytest.approx(330.0 / 390.0, abs=0.01)
        assert pct < 1.0

    def test_hkex_with_break(self):
        """HKEX: 09:30-16:00 = 390 min, minus 12:00-13:00 = 60 min break.

        Active = 330 min, window = 390 min. max_achievable = 330/390 < 1.0.
        """
        session = SESSION_REGISTRY["hkex"]
        pct = session.max_achievable_pct()
        assert pct < 1.0
        assert pct == pytest.approx(330.0 / 390.0, abs=0.01)

    def test_result_in_valid_range(self):
        """max_achievable_pct always returns value in (0, 1]."""
        for name, session in SESSION_REGISTRY.items():
            pct = session.max_achievable_pct()
            assert 0 < pct <= 1.0, f"Session {name!r} returned {pct!r}"


class TestContractUpdateEvent:
    """Tests for ContractUpdateEvent Pydantic model."""

    def test_create_required_fields(self):
        """ContractUpdateEvent requires 4 fields: base_symbol, old/new_contract, promoted_at."""
        evt = ContractUpdateEvent(
            base_symbol="ES",
            old_contract="ESH6",
            new_contract="ESM6",
            promoted_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        )
        assert evt.base_symbol == "ES"
        assert evt.old_contract == "ESH6"
        assert evt.new_contract == "ESM6"
        assert evt.promoted_at == datetime(2026, 3, 16, 12, 0, tzinfo=UTC)

    def test_serialize_to_json(self):
        """model_dump(mode='json') serializes datetime to ISO-8601 string."""
        evt = ContractUpdateEvent(
            base_symbol="CL",
            old_contract="CLJ6",
            new_contract="CLK6",
            promoted_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        )
        d = evt.model_dump(mode="json")
        assert d["base_symbol"] == "CL"
        assert d["old_contract"] == "CLJ6"
        assert d["new_contract"] == "CLK6"
        assert isinstance(d["promoted_at"], str)  # datetime serialized to ISO string

    def test_missing_field_raises_validation_error(self):
        """All 4 fields are required; missing one raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ContractUpdateEvent(
                base_symbol="ES",
                old_contract="ESH6",
                # missing new_contract and promoted_at
            )


class TestNewStreamKeys:
    """Tests for topic_contract_updates() and topic_roll_dlq()."""

    def test_topic_contract_updates_empty_env(self):
        """Empty env_name returns topic without prefix."""
        assert topic_contract_updates("") == "market.events.contract_update"

    def test_topic_contract_updates_dev_env(self):
        """Dev env_name prepends 'dev.' prefix."""
        assert topic_contract_updates("dev") == "dev.market.events.contract_update"

    def test_topic_contract_updates_prod_env(self):
        """Prod env_name prepends 'prod.' prefix."""
        assert topic_contract_updates("prod") == "prod.market.events.contract_update"

    def test_topic_roll_dlq_empty_env(self):
        """Empty env_name returns topic without prefix."""
        assert topic_roll_dlq("") == "market.events.roll.dlq"

    def test_topic_roll_dlq_dev_env(self):
        """Dev env_name prepends 'dev.' prefix."""
        assert topic_roll_dlq("dev") == "dev.market.events.roll.dlq"

    def test_topic_roll_dlq_prod_env(self):
        """Prod env_name prepends 'prod.' prefix."""
        assert topic_roll_dlq("prod") == "prod.market.events.roll.dlq"
