"""Tests for signal events repository (formerly signal ledger repository).

Updated in Phase 130 (130-02): all SQL now lives in signal_events_repository.py
targeting the 3-table schema (signal_events / trade_frames / trade_executions).
LedgerEntry is a backward-compat shim dataclass; _to_row() no longer exists.
signal_features table is no longer written by this repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.persistence.repository.signal_events_repository import (
    LedgerEntry,
    SignalEventsRepository,
    SignalStatus,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalLedgerRepository,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**overrides) -> LedgerEntry:
    defaults = dict(
        signal_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        timestamp=datetime(2026, 2, 16, 14, 30, 0, tzinfo=UTC),
        symbol="ES",
        timeframe="5m",
        setup_plugin="trad_TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=5100.0,
        stop_loss=5090.0,
        targets=[5110.0, 5120.0],
        was_selected=True,
        status="pending",
    )
    defaults.update(overrides)
    return LedgerEntry(**defaults)


# ---------------------------------------------------------------------------
# LedgerEntry backward-compat shim
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLedgerEntry:
    def test_create_entry(self):
        entry = _make_entry()
        assert entry.symbol == "ES"
        assert entry.direction == 1
        assert entry.status == "pending"

    def test_zone_fields(self):
        """LedgerEntry backward-compat shim has entry_zone fields."""
        entry = LedgerEntry(
            signal_id="test-uuid",
            timestamp=datetime.now(UTC),
            symbol="ES",
            timeframe="5m",
            setup_plugin="TrendFollowing",
            signal_type="trend_long",
            direction=1,
            was_selected=True,
            entry_zone_low=5095.0,
            entry_zone_high=5100.0,
        )
        assert entry.entry_zone_low == 5095.0
        assert entry.entry_zone_high == 5100.0

    def test_market_entry_price_field(self):
        entry = _make_entry(market_entry_price=5098.5)
        assert entry.market_entry_price == 5098.5

    def test_market_entry_price_defaults_none(self):
        entry = _make_entry()
        assert entry.market_entry_price is None

    def test_is_shadow_default_false(self):
        entry = _make_entry()
        assert entry.is_shadow is False

    def test_status_default_pending(self):
        entry = _make_entry()
        assert entry.status == "pending"

    def test_raw_confidence_field(self):
        entry = _make_entry(raw_confidence=0.72, calibrated_confidence=0.65)
        assert entry.raw_confidence == 0.72
        assert entry.calibrated_confidence == 0.65


# ---------------------------------------------------------------------------
# SignalEventsRepository — method existence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepositoryMethods:
    def test_repository_instantiable(self):
        repo = SignalEventsRepository.__new__(SignalEventsRepository)
        assert repo is not None

    def test_shim_alias_is_same_class(self):
        assert SignalLedgerRepository is SignalEventsRepository

    def test_update_lifecycle_state_method_exists(self):
        assert hasattr(SignalEventsRepository, "update_lifecycle_state")

    def test_update_mae_mfe_method_exists(self):
        assert hasattr(SignalEventsRepository, "update_mae_mfe")

    def test_fetch_active_signals_method_exists(self):
        assert hasattr(SignalEventsRepository, "fetch_active_signals")

    def test_fetch_pending_signals_method_exists(self):
        assert hasattr(SignalEventsRepository, "fetch_pending_signals")

    def test_insert_signal_with_frames_method_exists(self):
        assert hasattr(SignalEventsRepository, "insert_signal_with_frames")

    def test_get_active_signals_for_bootstrap_method_exists(self):
        assert hasattr(SignalEventsRepository, "get_active_signals_for_bootstrap")

    def test_update_signal_status_method_exists(self):
        assert hasattr(SignalEventsRepository, "update_signal_status")

    def test_update_frame_details_method_exists(self):
        assert hasattr(SignalEventsRepository, "update_frame_details")

    def test_record_activation_method_exists(self):
        assert hasattr(SignalEventsRepository, "record_activation")

    def test_record_zone_resolution_method_exists(self):
        assert hasattr(SignalEventsRepository, "record_zone_resolution")

    def test_record_market_resolution_method_exists(self):
        assert hasattr(SignalEventsRepository, "record_market_resolution")

    def test_record_zone_resolution_with_activation_method_exists(self):
        assert hasattr(SignalEventsRepository, "record_zone_resolution_with_activation")

    def test_batch_execute_method_exists(self):
        assert hasattr(SignalEventsRepository, "batch_execute")


# ---------------------------------------------------------------------------
# SQL content — 3-table schema assertions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSQLTargetsNewSchema:
    def test_insert_sql_targets_signal_events(self):
        """INSERT SQL must target signal_events, not signal_ledger."""
        import inspect

        from src.persistence.repository import signal_events_repository as mod

        src = inspect.getsource(mod)
        assert "INSERT INTO signal_events" in src
        assert "INSERT INTO trade_frames" in src

    def test_no_insert_into_signal_ledger(self):
        """No INSERT into legacy signal_ledger table."""
        import inspect

        from src.persistence.repository import signal_events_repository as mod

        src = inspect.getsource(mod)
        assert "INSERT INTO signal_ledger " not in src
        assert "INSERT INTO signal_outcomes" not in src

    def test_update_sql_targets_signal_events_status(self):
        """UPDATE SQL targets signal_events.status, not signal_outcomes."""
        import inspect

        from src.persistence.repository import signal_events_repository as mod

        src = inspect.getsource(mod)
        assert "UPDATE signal_events" in src
        assert "UPDATE signal_outcomes" not in src
        assert "UPDATE signal_ledger" not in src

    def test_get_active_signals_query_includes_regime_suppressed(self):
        """Bootstrap SQL must include 'regime_suppressed' in the status IN clause."""
        from src.persistence.repository.signal_events_repository import _BOOTSTRAP_SQL

        assert "regime_suppressed" in _BOOTSTRAP_SQL

    def test_bootstrap_sql_uses_direct_join_not_view(self):
        """Bootstrap query must JOIN signal_events + trade_frames, not signal_ledger_full."""
        from src.persistence.repository.signal_events_repository import _BOOTSTRAP_SQL

        assert "FROM signal_events" in _BOOTSTRAP_SQL
        assert "JOIN trade_frames" in _BOOTSTRAP_SQL
        assert "signal_ledger_full" not in _BOOTSTRAP_SQL

    def test_frame_id_is_uuid5(self):
        """frame_id generation uses uuid5 for idempotency."""
        import inspect

        from src.persistence.repository import signal_events_repository as mod

        src = inspect.getsource(mod)
        assert "uuid5" in src


# ---------------------------------------------------------------------------
# update_signal_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateSignalStatus:
    @pytest.mark.asyncio
    async def test_update_status_to_active(self):
        db = AsyncMock()
        await SignalEventsRepository(db).update_signal_status("some-uuid", "active")

        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert "UPDATE signal_events" in args[0]
        assert args[1] == "some-uuid"
        assert args[2] == "active"

    @pytest.mark.asyncio
    async def test_update_status_to_expired(self):
        db = AsyncMock()
        await SignalEventsRepository(db).update_signal_status("some-uuid", "expired")

        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert args[2] == "expired"


# ---------------------------------------------------------------------------
# update_frame_details
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateFrameDetails:
    @pytest.mark.asyncio
    async def test_calls_execute_command_with_jsonb_meta(self):
        db = AsyncMock()
        meta = {"activated_at": "2026-03-14T10:00:00Z", "activation_price": 5098.5}
        await SignalEventsRepository(db).update_frame_details("some-uuid", meta)

        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert "UPDATE trade_frames" in args[0]
        assert args[1] == "some-uuid"
        assert args[2] == meta


# ---------------------------------------------------------------------------
# get_active_signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetActiveSignals:
    @pytest.mark.asyncio
    async def test_returns_entries(self):
        db = AsyncMock()
        db.execute_query.return_value = [
            {"signal_id": "a", "status": "pending"},
            {"signal_id": "b", "status": "active"},
        ]

        result = await SignalEventsRepository(db).get_active_signals(symbol="ES")

        db.execute_query.assert_awaited_once()
        assert len(result) == 2
        assert result[0]["signal_id"] == "a"


# ---------------------------------------------------------------------------
# record_activation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordActivation:
    @pytest.mark.asyncio
    async def test_calls_update_signal_status_and_frame_details(self):
        db = AsyncMock()
        signal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        activated_at = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)

        await SignalEventsRepository(db).record_activation(
            signal_id,
            activated_at=activated_at,
            activation_price=5098.5,
            zone_entry_pct=0.25,
            bars_to_activation=3,
        )

        # Two calls: update_signal_status + update_frame_details
        assert db.execute_command.await_count == 2


# ---------------------------------------------------------------------------
# record_zone_resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordZoneResolution:
    @pytest.mark.asyncio
    async def test_calls_update_signal_status_and_frame_details(self):
        db = AsyncMock()
        exit_at = datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC)

        await SignalEventsRepository(db).record_zone_resolution(
            "aaaa-bbbb",
            status=SignalStatus.EXPIRED,
            exit_at=exit_at,
            exit_price=5085.0,
            exit_reason="stop_loss",
            pnl_r=-1.0,
            pnl_dollars=-750.0,
            signal_quality=0.0,
            mae=-1.0,
            mfe=0.3,
            bars_in_trade=5,
            outcome="stopped_in_trade",
        )
        # Two calls: update_signal_status + update_frame_details
        assert db.execute_command.await_count == 2


# ---------------------------------------------------------------------------
# record_market_resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordMarketResolution:
    @pytest.mark.asyncio
    async def test_calls_update_frame_details(self):
        db = AsyncMock()

        await SignalEventsRepository(db).record_market_resolution(
            "aaaa-bbbb",
            market_entry_at=None,
            market_entry_exit_price=5084.0,
            market_entry_exit_at=None,
            market_entry_pnl_r=-1.07,
            market_entry_mae=-1.07,
            market_entry_mfe=0.2,
            market_entry_bars_in_trade=3,
            market_entry_outcome="stopped_in_trade",
            market_entry_gap_bars=None,
        )
        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert "UPDATE trade_frames" in args[0]


# ---------------------------------------------------------------------------
# record_zone_resolution_with_activation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordZoneWithActivation:
    @pytest.mark.asyncio
    async def test_atomic_write_via_update_calls(self):
        """Same-bar activation+exit routes through update_signal_status + update_frame_details."""
        db = AsyncMock()
        ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)

        await SignalEventsRepository(db).record_zone_resolution_with_activation(
            "aaaa-bbbb",
            activated_at=ts,
            activation_price=5098.0,
            zone_entry_pct=0.1,
            bars_to_activation=1,
            status=SignalStatus.EXPIRED,
            exit_at=ts,
            exit_price=5085.0,
            exit_reason="stop_loss",
            pnl_r=-0.87,
            pnl_dollars=-650.0,
            signal_quality=0.0,
            mae=-0.87,
            mfe=0.0,
            bars_in_trade=0,
            outcome="stopped_at_entry",
        )
        # Two calls: update_signal_status + update_frame_details
        assert db.execute_command.await_count == 2


# ---------------------------------------------------------------------------
# batch_execute
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchExecute:
    @pytest.mark.asyncio
    async def test_activation_batch_updates_status_and_details(self):
        db = AsyncMock()
        items = [
            {
                "signal_id": "aaa",
                "activated_at": datetime(2026, 3, 14, 10, 0, tzinfo=UTC),
                "activation_price": 5098.5,
                "zone_entry_pct": 0.25,
                "bars_to_activation": 3,
            }
        ]
        await SignalEventsRepository(db).batch_execute("activation", items)
        # At least 2 execute_command calls (status + frame_details)
        assert db.execute_command.await_count >= 2

    @pytest.mark.asyncio
    async def test_empty_items_is_noop(self):
        db = AsyncMock()
        await SignalEventsRepository(db).batch_execute("activation", [])
        db.execute_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_type_raises_value_error(self):
        db = AsyncMock()
        with pytest.raises(ValueError, match="Unknown transition_type"):
            await SignalEventsRepository(db).batch_execute("bad_type", [{"signal_id": "x"}])
