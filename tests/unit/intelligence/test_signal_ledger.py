"""Tests for signal ledger repository."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.persistence.repository.signal_ledger_repository import (
    _SELECT_ACTIVE_SQL,
    LedgerEntry,
    SignalLedgerRepository,
    SignalStatus,
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
# LedgerEntry dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLedgerEntry:
    def test_create_entry(self):
        entry = _make_entry()
        assert entry.symbol == "ES"
        assert entry.direction == 1
        assert entry.status == "pending"

    def test_to_insert_params(self):
        entry = _make_entry()
        params = entry._to_row()

        # 34 params: $28=feature_schema_version; $29-$34=framing audit trail (Phase 115)
        assert len(params) == 36
        # Index 0 = signal_id, 2 = symbol
        assert params[0] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert params[2] == "ES"
        # feature_ts ($13) and feature_tf ($14) default to None — indices 12 and 13
        assert params[12] is None  # feature_ts
        assert params[13] is None  # feature_tf
        # CIS fields: cis_score=$24 (idx 23), bucket_scores=$25 (idx 24), weights_version=$26 (idx 25)
        assert params[23] is None  # cis_score
        assert params[24] is None  # bucket_scores
        assert params[25] is None  # weights_version

    def test_to_insert_params_with_cis_fields(self):
        """LedgerEntry with CIS fields — bucket_scores as Python dict at $25 (index 24)."""
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
        )
        params = entry._to_row()

        # 34 params: $28=feature_schema_version; $29-$34=framing audit trail (Phase 115)
        assert len(params) == 36
        assert params[22] == pytest.approx(0.47)  # cis_score at $23 (index 22)
        # index 23 = bucket_scores as dict (asyncpg serializes to jsonb)
        bucket_scores = params[23]
        assert bucket_scores["trend"] == pytest.approx(0.4)
        assert bucket_scores["momentum"] == pytest.approx(0.3)
        assert params[24] == 0  # weights_version at $25 (index 24)


@pytest.mark.unit
class TestLedgerEntryNewFields:
    def test_ledger_entry_has_zone_fields(self):
        """LedgerEntry dataclass includes entry_zone fields."""
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
            was_selected=True,
        )
        params = entry._to_row()
        # 34 params: $28=feature_schema_version; $29-$34=framing audit trail (Phase 115)
        assert len(params) == 36


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

        # insert() calls execute_batch twice: once for signal_ledger, once for signal_outcomes
        assert db.execute_batch.await_count == 2
        ledger_call = db.execute_batch.call_args_list[0]
        assert len(ledger_call[0][1]) == 1  # one ledger row

    @pytest.mark.asyncio
    async def test_insert_multiple_signals(self):
        db = AsyncMock()
        entries = [_make_entry(signal_id=f"id-{i}") for i in range(3)]
        await SignalLedgerRepository(db).insert_signals(entries)

        assert db.execute_batch.await_count == 2
        ledger_call = db.execute_batch.call_args_list[0]
        assert len(ledger_call[0][1]) == 3

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

        await SignalLedgerRepository(db).record_activation(
            signal_id,
            activated_at=activated_at,
            activation_price=5098.5,
            zone_entry_pct=0.25,
            bars_to_activation=3,
        )

        db.execute_command.assert_awaited_once()
        call_args = db.execute_command.call_args
        assert call_args[0][0] == _RECORD_ACTIVATION_SQL
        assert "market_entry" not in _RECORD_ACTIVATION_SQL  # no cross-contamination

    def test_activation_sql_does_not_touch_zone_resolution_columns(self):
        import re

        # Extract only the SET clause (between SET and WHERE) to verify no resolution columns are written.
        # exit_at IS allowed in the WHERE clause as an idempotency guard but must not appear in SET.
        set_match = re.search(r"SET\s+(.*?)\s+WHERE", _RECORD_ACTIVATION_SQL, re.DOTALL)
        set_clause = set_match.group(1) if set_match else _RECORD_ACTIVATION_SQL
        for col in ["exit_at", "exit_price", "pnl_r"]:
            assert col not in set_clause, f"{col} must not be written by activation SQL"
        # outcome column (not the table name signal_outcomes)
        assert not re.search(r"\boutcome\b\s*=", set_clause)
        # WHERE clause must have the idempotency guard
        assert "exit_at IS NULL" in _RECORD_ACTIVATION_SQL


@pytest.mark.unit
class TestRecordZoneResolution:
    @pytest.mark.asyncio
    async def test_calls_execute_command(self):
        db = AsyncMock()
        db.execute_command = AsyncMock()
        exit_at = datetime(2026, 3, 14, 11, 0, 0, tzinfo=UTC)

        await SignalLedgerRepository(db).record_zone_resolution(
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

        await SignalLedgerRepository(db).record_market_resolution(
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
        await SignalLedgerRepository(db).record_market_resolution(
            "aaaa",
            market_entry_at=None,
            market_entry_exit_price=5115.0,
            market_entry_exit_at=None,
            market_entry_pnl_r=1.0,
            market_entry_mae=0.0,
            market_entry_mfe=1.0,
            market_entry_bars_in_trade=2,
            market_entry_outcome="target_1",
        )
        db.execute_command.assert_awaited_once()


@pytest.mark.unit
class TestRecordZoneWithActivation:
    @pytest.mark.asyncio
    async def test_atomic_write_called_once(self):
        """Same-bar activation+exit must call execute_command exactly once."""
        db = AsyncMock()
        db.execute_command = AsyncMock()
        ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)

        await SignalLedgerRepository(db).record_zone_resolution_with_activation(
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
        params = e._to_row()
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

    def test_to_insert_params_length_64(self):
        entry = _make_entry()
        # 34 params: $28=feature_schema_version; $29-$34=framing audit trail (Phase 115)
        assert len(entry._to_row()) == 36

    def test_to_insert_params_is_shadow_position_false(self):
        entry = _make_entry(is_shadow=False)
        params = entry._to_row()
        # is_shadow is $9 in new schema (index 8)
        assert params[8] is False

    def test_to_insert_params_is_shadow_position_true(self):
        entry = _make_entry(is_shadow=True)
        params = entry._to_row()
        # is_shadow is $9 in new schema (index 8)
        assert params[8] is True

    def test_insert_sql_contains_is_shadow_and_dollar39(self):
        from src.persistence.repository.signal_ledger_repository import _INSERT_SQL

        assert "is_shadow" in _INSERT_SQL


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
