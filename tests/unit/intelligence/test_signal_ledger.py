"""Tests for signal ledger repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.intelligence.trading.signal_ledger import (
    LedgerEntry,
    get_active_signals,
    insert_signals,
    update_signal_status,
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
        confidence=0.75,
        confluence_score=0.82,
        regime_context="bullish",
        supporting_factors=["ema_alignment", "adx_strong"],
        was_selected=True,
        num_signals_bar=3,
        num_agreeing=2,
        num_conflicting=1,
        resolution_method="confidence_rank",
        composite_rank=1,
        market_context={"vol_regime": "normal"},
        status="pending",
    )
    defaults.update(overrides)
    return LedgerEntry(**defaults)


# ---------------------------------------------------------------------------
# LedgerEntry dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLedgerEntry:
    def test_create_entry(self):
        entry = _make_entry()
        assert entry.symbol == "ES"
        assert entry.direction == 1
        assert entry.status == "pending"
        assert entry.market_context == {"vol_regime": "normal"}

    def test_to_insert_params(self):
        entry = _make_entry()
        params = entry.to_insert_params()

        assert len(params) == 36
        # Index 0 = signal_id, 2 = symbol
        assert params[0] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert params[2] == "ES"
        # JSONB fields are JSON strings
        assert json.loads(params[9]) == [5110.0, 5120.0]
        assert json.loads(params[13]) == ["ema_alignment", "adx_strong"]
        assert json.loads(params[20]) == {"vol_regime": "normal"}
        # feature_ts and feature_tf default to None ($23 and $24)
        assert params[22] is None  # feature_ts
        assert params[23] is None  # feature_tf
        # CIS fields default to None ($25-$28)
        assert params[24] is None  # cis_score
        assert params[25] is None  # bucket_scores (JSON)
        assert params[26] is None  # weights_version
        assert params[27] is None  # signal_quality
        # Timing field ($29)
        assert params[28] is None  # signal_computed_at (default None)

    def test_to_insert_params_with_cis_fields(self):
        """LedgerEntry with CIS fields — bucket_scores serialized to JSON string at index 25."""
        entry = _make_entry(
            cis_score=0.47,
            bucket_scores={"trend": 0.4, "momentum": 0.3, "structure": 0.2,
                           "pattern": 0.0, "institutional": 0.5, "regime": 0.3},
            weights_version=0,
            signal_quality=None,
        )
        params = entry.to_insert_params()

        assert len(params) == 36
        assert params[24] == pytest.approx(0.47)
        # index 25 (0-based) = $26 (1-based) = bucket_scores as JSON
        parsed = json.loads(params[25])
        assert parsed["trend"] == pytest.approx(0.4)
        assert parsed["momentum"] == pytest.approx(0.3)
        assert params[26] == 0  # weights_version
        assert params[27] is None  # signal_quality still None at fire time
        assert params[28] is None  # signal_computed_at default None


@pytest.mark.unit
class TestLedgerEntryNewFields:
    def test_ledger_entry_has_zone_fields(self):
        """LedgerEntry dataclass includes all new institutional fields."""
        entry = LedgerEntry(
            signal_id="test-uuid",
            timestamp=datetime.now(UTC),
            symbol="ES",
            timeframe="5m",
            setup_plugin="TrendFollowing",
            signal_type="trend_long",
            direction=1,
            entry_price=5100.0,
            stop_loss=5085.0,
            targets=[5115.0, 5130.0],
            confidence=0.8,
            confluence_score=0.7,
            regime_context="trending",
            supporting_factors=["rsi_bull"],
            was_selected=True,
            num_signals_bar=2,
            num_agreeing=1,
            num_conflicting=1,
            resolution_method="priority",
            composite_rank=1,
            determined_at=datetime.now(UTC),
            ask_at_signal=5101.5,
            bid_at_signal=5101.0,
            market_price_at_signal=5101.5,
            entry_zone_low=5095.0,
            entry_zone_high=5100.0,
            zone_valid_at_signal=True,
        )
        assert entry.determined_at is not None
        assert entry.ask_at_signal == 5101.5
        assert entry.entry_zone_low == 5095.0
        assert entry.zone_valid_at_signal is True
        assert entry.mae is None
        assert entry.outcome is None

    def test_to_insert_params_length(self):
        """to_insert_params() returns correct number of elements for new SQL."""
        entry = LedgerEntry(
            signal_id="test-uuid",
            timestamp=datetime.now(UTC),
            symbol="ES", timeframe="5m",
            setup_plugin="TrendFollowing", signal_type="trend_long",
            direction=1, entry_price=5100.0, stop_loss=5085.0,
            targets=[5115.0], confidence=0.8, confluence_score=0.7,
            regime_context="trending", supporting_factors=[],
            was_selected=True, num_signals_bar=1, num_agreeing=1,
            num_conflicting=0, resolution_method="sole", composite_rank=1,
        )
        params = entry.to_insert_params()
        assert len(params) == 36  # 29 existing + 7 new fire-time fields


# ---------------------------------------------------------------------------
# insert_signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInsertSignals:
    @pytest.mark.asyncio
    async def test_insert_single_signal(self):
        db = AsyncMock()
        entry = _make_entry()
        await insert_signals(db, [entry])

        db.execute_batch.assert_awaited_once()
        args = db.execute_batch.call_args
        assert len(args[0][1]) == 1  # one row

    @pytest.mark.asyncio
    async def test_insert_multiple_signals(self):
        db = AsyncMock()
        entries = [_make_entry(signal_id=f"id-{i}") for i in range(3)]
        await insert_signals(db, entries)

        db.execute_batch.assert_awaited_once()
        args = db.execute_batch.call_args
        assert len(args[0][1]) == 3

    @pytest.mark.asyncio
    async def test_insert_empty_list_is_noop(self):
        db = AsyncMock()
        await insert_signals(db, [])
        db.execute_batch.assert_not_awaited()


# ---------------------------------------------------------------------------
# update_signal_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateSignalStatus:
    @pytest.mark.asyncio
    async def test_update_status_to_active(self):
        db = AsyncMock()
        activated = datetime(2026, 2, 16, 14, 35, 0, tzinfo=UTC)
        await update_signal_status(
            db, "some-uuid", status="active", activated_at=activated,
        )

        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert args[1] == "some-uuid"
        assert args[2] == "active"
        assert args[3] == activated

    @pytest.mark.asyncio
    async def test_update_status_with_exit(self):
        db = AsyncMock()
        exit_time = datetime(2026, 2, 16, 15, 0, 0, tzinfo=UTC)
        await update_signal_status(
            db,
            "some-uuid",
            status="closed",
            exit_at=exit_time,
            exit_price=5115.0,
            exit_reason="target_hit",
            pnl_ticks=15.0,
            pnl_r=1.5,
            pnl_dollars=750.0,
        )

        db.execute_command.assert_awaited_once()
        args = db.execute_command.call_args[0]
        assert args[2] == "closed"
        assert args[5] == 5115.0
        assert args[6] == "target_hit"


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

        result = await get_active_signals(db, symbol="ES")

        db.execute_query.assert_awaited_once()
        assert len(result) == 2
        assert result[0]["signal_id"] == "a"
