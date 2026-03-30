"""Tests for signal ledger repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.persistence.repository.signal_ledger_repository import (
    _SELECT_ACTIVE_SQL,
    LedgerEntry,
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

        assert len(params) == 60  # 58 prior + 2 Phase 57 attribution fields
        # Index 0 = signal_id, 2 = symbol
        assert params[0] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert params[2] == "ES"
        # JSONB fields are passed as Python objects (asyncpg handles serialization)
        assert params[9] == [5110.0, 5120.0]  # targets
        assert params[13] == ["ema_alignment", "adx_strong"]  # supporting_factors
        assert params[20] == {"vol_regime": "normal"}  # market_context
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
            bucket_scores={
                "trend": 0.4,
                "momentum": 0.3,
                "structure": 0.2,
                "pattern": 0.0,
                "institutional": 0.5,
                "regime": 0.3,
            },
            weights_version=0,
            signal_quality=None,
        )
        params = entry.to_insert_params()

        assert len(params) == 60  # 58 prior + 2 Phase 57 attribution fields
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
            symbol="ES",
            timeframe="5m",
            setup_plugin="TrendFollowing",
            signal_type="trend_long",
            direction=1,
            entry_price=5100.0,
            stop_loss=5085.0,
            targets=[5115.0],
            confidence=0.8,
            confluence_score=0.7,
            regime_context="trending",
            supporting_factors=[],
            was_selected=True,
            num_signals_bar=1,
            num_agreeing=1,
            num_conflicting=0,
            resolution_method="sole",
            composite_rank=1,
        )
        params = entry.to_insert_params()
        assert len(params) == 60  # 58 prior + 2 Phase 57 attribution fields


def test_ledger_entry_has_cis_attribution_field():
    entry = LedgerEntry(
        signal_id="test-id",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="test",
        signal_type="test",
        direction=1,
        entry_price=5000.0,
        stop_loss=4990.0,
        targets=[5010.0],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="solo",
        composite_rank=1,
        cis_attribution={"momentum": {"rsi_14": 0.038, "williams_r_14": 0.011}},
    )
    assert entry.cis_attribution == {"momentum": {"rsi_14": 0.038, "williams_r_14": 0.011}}


def test_ledger_entry_to_insert_params_includes_attribution():
    entry = LedgerEntry(
        signal_id="test-id",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="test",
        signal_type="test",
        direction=1,
        entry_price=5000.0,
        stop_loss=4990.0,
        targets=[],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="",
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="solo",
        composite_rank=1,
        cis_attribution={"trend": {"psar_direction": 0.05}},
    )
    params = entry.to_insert_params()
    assert len(params) == 60  # 58 prior + 2 Phase 57 attribution fields
    # cis_attribution field at position 36 - checks nested dict structure
    assert params[36] == {"trend": {"psar_direction": 0.05}}


# ---------------------------------------------------------------------------
# insert_signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInsertSignals:
    @pytest.mark.asyncio
    async def test_insert_single_signal(self):
        db = AsyncMock()
        entry = _make_entry()
        await SignalLedgerRepository(db).insert_signals([entry])

        db.execute_batch.assert_awaited_once()
        args = db.execute_batch.call_args
        assert len(args[0][1]) == 1  # one row

    @pytest.mark.asyncio
    async def test_insert_multiple_signals(self):
        db = AsyncMock()
        entries = [_make_entry(signal_id=f"id-{i}") for i in range(3)]
        await SignalLedgerRepository(db).insert_signals(entries)

        db.execute_batch.assert_awaited_once()
        args = db.execute_batch.call_args
        assert len(args[0][1]) == 3

    @pytest.mark.asyncio
    async def test_insert_empty_list_is_noop(self):
        db = AsyncMock()
        await SignalLedgerRepository(db).insert_signals([])
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
        await SignalLedgerRepository(db).update_signal_status(
            "some-uuid",
            status="active",
            activated_at=activated,
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
        await SignalLedgerRepository(db).update_signal_status(
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

        result = await SignalLedgerRepository(db).get_active_signals(symbol="ES")

        db.execute_query.assert_awaited_once()
        assert len(result) == 2
        assert result[0]["signal_id"] == "a"


# ---------------------------------------------------------------------------
# regime_suppressed status SQL coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegimeSuppressedStatus:
    """Verifies _SELECT_ACTIVE_SQL includes regime_suppressed so the lifecycle
    service tracks shadow/suppressed signals alongside pending and active."""

    def test_get_active_signals_query_includes_regime_suppressed(self):
        """_SELECT_ACTIVE_SQL must include 'regime_suppressed' in the status IN clause."""
        assert "regime_suppressed" in _SELECT_ACTIVE_SQL, (
            "_SELECT_ACTIVE_SQL must include 'regime_suppressed' in the status IN clause "
            "so that shadow signals are loaded by the lifecycle service. "
            f"Current SQL:\n{_SELECT_ACTIVE_SQL}"
        )


# ============================================================
# New targeted DB write functions
# ============================================================

from src.persistence.repository.signal_ledger_repository import (  # noqa: E402
    _RECORD_ACTIVATION_SQL,
    _RECORD_MARKET_RESOLUTION_SQL,
    _RECORD_ZONE_RESOLUTION_SQL,
    _RECORD_ZONE_WITH_ACTIVATION_SQL,
)


@pytest.mark.unit
class TestRecordActivation:
    @pytest.mark.asyncio
    async def test_calls_execute_command_with_activation_fields(self):
        db = AsyncMock()
        db.execute_command = AsyncMock()
        signal_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        activated_at = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)

        await SignalLedgerRepository(db).record_activation(signal_id,
                                      activated_at=activated_at,
                                      activation_price=5098.5,
                                      zone_entry_pct=0.25,
                                      bars_to_activation=3)

        db.execute_command.assert_awaited_once()
        call_args = db.execute_command.call_args
        assert call_args[0][0] == _RECORD_ACTIVATION_SQL
        assert "market_entry" not in _RECORD_ACTIVATION_SQL  # no cross-contamination

    def test_activation_sql_does_not_touch_zone_resolution_columns(self):
        for col in ["exit_at", "exit_price", "outcome", "pnl_r"]:
            assert col not in _RECORD_ACTIVATION_SQL


@pytest.mark.unit
class TestRecordZoneResolution:
    @pytest.mark.asyncio
    async def test_calls_execute_command(self):
        db = AsyncMock()
        db.execute_command = AsyncMock()
        exit_at = datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC)

        await SignalLedgerRepository(db).record_zone_resolution("aaaa-bbbb",
                                           status="stopped_out",
                                           exit_at=exit_at,
                                           exit_price=5085.0,
                                           exit_reason="stop_loss",
                                           pnl_r=-1.0,
                                           pnl_dollars=-750.0,
                                           signal_quality=0.0,
                                           mae=-1.0,
                                           mfe=0.3,
                                           bars_in_trade=5,
                                           outcome="stopped_in_trade")
        db.execute_command.assert_awaited_once()

    def test_zone_resolution_sql_does_not_touch_market_columns(self):
        for col in ["market_entry_price", "market_entry_outcome", "market_entry_pnl_r"]:
            assert col not in _RECORD_ZONE_RESOLUTION_SQL


@pytest.mark.unit
class TestRecordMarketResolution:
    @pytest.mark.asyncio
    async def test_calls_execute_command_with_market_fields(self):
        db = AsyncMock()
        db.execute_command = AsyncMock()

        await SignalLedgerRepository(db).record_market_resolution("aaaa-bbbb",
                                             market_entry_at=None,
                                             market_entry_exit_price=5084.0,
                                             market_entry_exit_at=None,
                                             market_entry_pnl_r=-1.07,
                                             market_entry_mae=-1.07,
                                             market_entry_mfe=0.2,
                                             market_entry_bars_in_trade=3,
                                             market_entry_outcome="stopped_in_trade",
                                             market_entry_gap_bars=None)
        db.execute_command.assert_awaited_once()

    def test_market_resolution_sql_does_not_touch_zone_columns(self):
        import re
        for col in ["activated_at", "activation_price", "pnl_ticks"]:
            assert col not in _RECORD_MARKET_RESOLUTION_SQL
        # 'exit_at' and 'outcome' need word boundaries to avoid matching market_entry_exit_at/market_entry_outcome
        for col in ["exit_at", "outcome"]:
            assert not re.search(rf"(?<!market_entry_)\b{col}\b", _RECORD_MARKET_RESOLUTION_SQL)

    @pytest.mark.asyncio
    async def test_gap_bars_defaults_to_none(self):
        """gap_bars=None is the default (live signals)."""
        db = AsyncMock()
        db.execute_command = AsyncMock()
        await SignalLedgerRepository(db).record_market_resolution("aaaa",
                                             market_entry_at=None,
                                             market_entry_exit_price=5115.0,
                                             market_entry_exit_at=None,
                                             market_entry_pnl_r=1.0,
                                             market_entry_mae=0.0,
                                             market_entry_mfe=1.0,
                                             market_entry_bars_in_trade=2,
                                             market_entry_outcome="target_1")
        db.execute_command.assert_awaited_once()


@pytest.mark.unit
class TestRecordZoneWithActivation:
    @pytest.mark.asyncio
    async def test_atomic_write_called_once(self):
        """Same-bar activation+exit must call execute_command exactly once."""
        db = AsyncMock()
        db.execute_command = AsyncMock()
        ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)

        await SignalLedgerRepository(db).record_zone_resolution_with_activation("aaaa-bbbb",
            activated_at=ts, activation_price=5098.0,
            zone_entry_pct=0.1, bars_to_activation=1,
            status="stopped_out", exit_at=ts,
            exit_price=5085.0, exit_reason="stop_loss",
            pnl_r=-0.87, pnl_dollars=-650.0,
            signal_quality=0.0, mae=-0.87, mfe=0.0,
            bars_in_trade=0, outcome="stopped_at_entry")
        db.execute_command.assert_awaited_once()
        assert db.execute_command.call_args[0][0] == _RECORD_ZONE_WITH_ACTIVATION_SQL


@pytest.mark.unit
class TestLedgerEntryMarketEntryPrice:
    def test_market_entry_price_field_exists(self):
        e = _make_entry(market_entry_price=5098.5)
        assert e.market_entry_price == 5098.5

    def test_market_entry_price_defaults_none(self):
        e = _make_entry()
        assert e.market_entry_price is None

    def test_to_insert_params_includes_market_entry_price(self):
        e = _make_entry(market_entry_price=5101.25)
        params = e.to_insert_params()
        assert 5101.25 in params

    def test_insert_sql_includes_market_entry_price(self):
        from src.persistence.repository.signal_ledger_repository import _INSERT_SQL
        assert "market_entry_price" in _INSERT_SQL


# ---------------------------------------------------------------------------
# Phase 31 Plan 03 — is_shadow + _build_feature_rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsShadowField:
    def test_is_shadow_default_false(self):
        entry = _make_entry()
        assert entry.is_shadow is False

    def test_to_insert_params_length_60(self):
        entry = _make_entry()
        assert len(entry.to_insert_params()) == 60  # 58 prior + 2 Phase 57 attribution fields

    def test_to_insert_params_is_shadow_position_false(self):
        entry = _make_entry(is_shadow=False)
        params = entry.to_insert_params()
        assert params[38] is False

    def test_to_insert_params_is_shadow_position_true(self):
        entry = _make_entry(is_shadow=True)
        params = entry.to_insert_params()
        assert params[38] is True

    def test_insert_sql_contains_is_shadow_and_dollar39(self):
        from src.persistence.repository.signal_ledger_repository import _INSERT_SQL
        assert "is_shadow" in _INSERT_SQL
        assert "$39" in _INSERT_SQL


@pytest.mark.unit
class TestBuildFeatureRows:
    def test_extracts_float_values(self):
        from src.persistence.repository.signal_ledger_repository import _build_feature_rows

        ts = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)
        rows = _build_feature_rows(
            "sig-123",
            ts,
            {"rsi_14": 55.0, "adx_14": 30.0, "name": "test", "missing": None},
        )
        # Only numeric non-None values
        assert len(rows) == 2
        names = {r[2] for r in rows}
        assert names == {"rsi_14", "adx_14"}

    def test_maps_bucket_correctly(self):
        from src.persistence.repository.signal_ledger_repository import _build_feature_rows

        ts = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)
        rows = _build_feature_rows("sig-123", ts, {"rsi_14": 55.0})
        assert len(rows) == 1
        row = rows[0]
        # (signal_id, computed_at, feature_name, feature_value, feature_bucket, bucket_contribution)
        assert row[4] == "momentum"

    def test_skips_none_values(self):
        from src.persistence.repository.signal_ledger_repository import _build_feature_rows

        ts = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)
        rows = _build_feature_rows("sig-123", ts, {"rsi_14": None, "adx_14": 30.0})
        assert len(rows) == 1
        assert rows[0][2] == "adx_14"

    def test_skips_string_values(self):
        from src.persistence.repository.signal_ledger_repository import _build_feature_rows

        ts = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)
        rows = _build_feature_rows("sig-123", ts, {"hmm_regime": "trending"})
        assert rows == []

    def test_skips_dict_values(self):
        from src.persistence.repository.signal_ledger_repository import _build_feature_rows

        ts = datetime(2026, 3, 16, 10, 0, 0, tzinfo=UTC)
        rows = _build_feature_rows("sig-123", ts, {"i5": {"some": "dict"}})
        assert rows == []

    def test_insert_features_sql_has_on_conflict(self):
        from src.persistence.repository.signal_ledger_repository import _INSERT_FEATURES_SQL
        assert "ON CONFLICT" in _INSERT_FEATURES_SQL
        assert "DO NOTHING" in _INSERT_FEATURES_SQL


@pytest.mark.unit
class TestLedgerEntryPhase35CalibrationFields:
    """Phase 35: LedgerEntry must carry calibration fields for isotonic regression pipeline."""

    def test_has_raw_cis_score_field(self):
        """raw_cis_score field must exist on LedgerEntry."""
        assert "raw_cis_score" in LedgerEntry.__dataclass_fields__

    def test_has_filtered_cis_score_field(self):
        """filtered_cis_score field must exist on LedgerEntry."""
        assert "filtered_cis_score" in LedgerEntry.__dataclass_fields__

    def test_has_calibrated_confidence_field(self):
        """calibrated_confidence field must exist on LedgerEntry."""
        assert "calibrated_confidence" in LedgerEntry.__dataclass_fields__

    def test_has_regime_type_at_fire_field(self):
        """regime_type_at_fire field must exist on LedgerEntry."""
        assert "regime_type_at_fire" in LedgerEntry.__dataclass_fields__

    def test_calibration_fields_default_none(self):
        """All Phase 35 calibration fields must default to None."""
        entry = _make_entry()
        assert entry.raw_cis_score is None
        assert entry.filtered_cis_score is None
        assert entry.calibrated_confidence is None
        assert entry.regime_type_at_fire is None

    def test_to_insert_params_returns_60_elements(self):
        """to_insert_params() must return 60 elements after Phase 57 extension (was 58)."""
        entry = _make_entry()
        params = entry.to_insert_params()
        assert len(params) == 60, (
            f"Expected 60 elements (58 prior + 2 Phase 57 attribution), got {len(params)}"
        )

    def test_to_insert_params_calibration_fields_at_positions_55_to_58(self):
        """Phase 35 fields are at $55-$58 (0-indexed: 54-57)."""
        entry = _make_entry(
            raw_cis_score=0.72,
            filtered_cis_score=0.68,
            calibrated_confidence=0.61,
            regime_type_at_fire="trend",
        )
        params = entry.to_insert_params()
        assert len(params) == 60
        assert params[54] == pytest.approx(0.72)   # $55 raw_cis_score
        assert params[55] == pytest.approx(0.68)   # $56 filtered_cis_score
        assert params[56] == pytest.approx(0.61)   # $57 calibrated_confidence
        assert params[57] == "trend"               # $58 regime_type_at_fire
        assert params[58] is None                  # $59 pre_quality_confidence
        assert params[59] is None                  # $60 pre_calibration_confidence

    def test_to_insert_params_calibration_fields_nullable(self):
        """Calibration fields must be NULL-able (None passes through unchanged)."""
        entry = _make_entry()
        params = entry.to_insert_params()
        assert params[54] is None  # raw_cis_score
        assert params[55] is None  # filtered_cis_score
        assert params[56] is None  # calibrated_confidence
        assert params[57] is None  # regime_type_at_fire

    def test_insert_sql_contains_calibration_columns(self):
        """_INSERT_SQL must reference all four Phase 35 calibration columns."""
        from src.persistence.repository.signal_ledger_repository import _INSERT_SQL
        assert "raw_cis_score" in _INSERT_SQL
        assert "filtered_cis_score" in _INSERT_SQL
        assert "calibrated_confidence" in _INSERT_SQL
        assert "regime_type_at_fire" in _INSERT_SQL
        assert "$55" in _INSERT_SQL
        assert "$56" in _INSERT_SQL
        assert "$57" in _INSERT_SQL
        assert "$58" in _INSERT_SQL
