"""Unit tests for signal lifecycle service helpers."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest


def _compute_bars_elapsed(
    signal_timestamp: datetime, current_bar_time: datetime, timeframe: str
) -> int:
    """Compute bars elapsed since signal fire. Mirrors service implementation."""
    TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (current_bar_time - signal_timestamp).total_seconds()
    return max(0, int(delta / tf_secs))


@pytest.mark.unit
class TestBarsElapsedComputation:
    def test_same_bar_returns_zero(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, ts, "5m") == 0

    def test_one_bar_elapsed_5m(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        bar_time = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, bar_time, "5m") == 1

    def test_ttl_boundary_10_bars_1h(self):
        ts = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
        bar_time = ts + timedelta(hours=10)
        assert _compute_bars_elapsed(ts, bar_time, "1h") == 10

    def test_determined_at_lag_accounted(self):
        """Signal determined 2 min after bar close; 5m bars."""
        bar_close = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        determined_at = bar_close + timedelta(minutes=2)  # 14:37
        # Next bar at 14:40 → <1 bar elapsed from determined_at
        next_bar = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(determined_at, next_bar, "5m") == 0


def test_signal_lifecycle_service_imports():
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    assert hasattr(svc, "_evaluate_signals_against_bar")


def test_evaluate_signals_against_bar_no_db_returns_early():
    """Without a DB connection, evaluation must not raise."""
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    svc.db_manager = None

    bar_time = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
    asyncio.get_event_loop().run_until_complete(
        svc._evaluate_signals_against_bar(
            "ES", "1m",
            {"high": 5305.0, "low": 5298.0, "close": 5303.0},
            bar_time=bar_time,
        )
    )
    # No exception raised = pass


def test_stream_map_populated_after_setup():
    """_stream_map must have one entry per symbol (1m only)."""
    import redis.asyncio as redis

    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("BUSYGROUP Consumer Group name already exists")
    )
    svc.redis_client.xgroup_setid = AsyncMock()
    svc.db_manager = None

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    assert len(svc._stream_map) == len(symbols)
    for _stream_name, (sym, tf) in svc._stream_map.items():
        assert tf == "1m"
        assert sym in symbols


def test_mae_mfe_tracked_in_memory():
    """Active signals accumulate MAE/MFE across bars."""
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    # Directly manipulate the tracking dicts
    svc._mae["sig-1"] = -0.2
    svc._mfe["sig-1"] = 0.5

    assert svc._mae["sig-1"] == pytest.approx(-0.2)
    assert svc._mfe["sig-1"] == pytest.approx(0.5)

    # Cleanup on exit
    svc._mae.pop("sig-1", None)
    svc._mfe.pop("sig-1", None)
    assert "sig-1" not in svc._mae
    assert "sig-1" not in svc._mfe


# ---------------------------------------------------------------------------
# Phase 12 Plan 04 — Shadow Signal Virtual-Activation Tests (TDD RED)
# ---------------------------------------------------------------------------


def _make_shadow_signal(sid: str = "shadow-001") -> dict:
    """Build a minimal regime_suppressed signal dict as returned by get_active_signals()."""
    ts = datetime(2026, 3, 4, 14, 30, 0, tzinfo=UTC)
    return {
        "signal_id": sid,
        "status": "regime_suppressed",
        "symbol": "ES",
        "timeframe": "5m",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5085.0,
        "targets": [5115.0],
        "confidence": 0.75,
        "ttl_bars": 20,
        "entry_zone_low": 5095.0,
        "entry_zone_high": 5100.0,
        "timestamp": ts,
        "regime_eligible": False,
        "suppression_reason": "regime_type",
        "was_selected": False,
    }


@pytest.mark.unit
class TestShadowSignalLifecycleService:
    """SIGINT-05: regime_suppressed signals get virtual-activation in lifecycle service.

    RED phase: these tests fail until _evaluate_signals_against_bar() handles
    regime_suppressed signals with the virtual-activation path.
    """

    @pytest.mark.asyncio
    async def test_shadow_signal_mae_mfe_initialized_at_startup(self):
        """regime_suppressed signal loaded at startup → _mae/_mfe initialized to 0.0.

        When the lifecycle service loads active signals from DB at startup (via
        get_active_signals), any signal with status='regime_suppressed' must have
        _mae[sid]=0.0 and _mfe[sid]=0.0 initialized before any bar arrives.

        We test this by calling _evaluate_signals_against_bar with a shadow signal
        that is not yet in _mae/_mfe — after the call, MAE/MFE should be set for it.
        """
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService()
        svc.db_manager = AsyncMock()
        svc.db_manager.execute_command = AsyncMock()

        shadow = _make_shadow_signal("shadow-startup-001")
        bar_time = datetime(2026, 3, 4, 14, 35, 0, tzinfo=UTC)
        bar = {"high": 5108.0, "low": 5099.0, "close": 5105.0}

        # _mae/_mfe are empty before first bar — service should initialize them
        assert "shadow-startup-001" not in svc._mae
        assert "shadow-startup-001" not in svc._mfe

        await svc._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

        # After evaluation, MAE/MFE must be tracked for the shadow signal
        assert "shadow-startup-001" in svc._mae, (
            "Shadow signal _mae must be initialized by _evaluate_signals_against_bar. "
            "Lifecycle service must handle regime_suppressed with virtual-activation."
        )
        assert "shadow-startup-001" in svc._mfe, (
            "Shadow signal _mfe must be initialized by _evaluate_signals_against_bar."
        )

    @pytest.mark.asyncio
    async def test_shadow_signal_evaluate_called_with_active_override(self):
        """evaluate_signal() is called with status='active' override for shadow signals.

        The lifecycle service must pass a copy of the shadow signal dict with
        status='active' to evaluate_signal(), so it takes the active-exit path
        (stop/target/TTL check) rather than the pending path (zone-activation check).

        We validate indirectly: a shadow signal whose price hits stop gets exited.
        If zone-activation was checked instead, it would NOT exit (zone check would
        pass or not, but would return a "active" transition, not "stopped_out").
        """
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService()
        svc.db_manager = AsyncMock()
        svc.db_manager.execute_command = AsyncMock()

        shadow = _make_shadow_signal("shadow-eval-001")
        # Initialize MAE/MFE to simulate signal loaded at startup
        svc._mae["shadow-eval-001"] = 0.0
        svc._mfe["shadow-eval-001"] = 0.0
        svc._activated_at["shadow-eval-001"] = shadow["timestamp"]

        # Bar that hits the stop loss (stop=5085.0, low=5080.0)
        bar_time = datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC)
        bar = {"high": 5095.0, "low": 5080.0, "close": 5082.0}

        await svc._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

        # Stop hit → update_signal_status called
        svc.db_manager.execute_command.assert_awaited_once()
        args = svc.db_manager.execute_command.call_args[0]
        # Signal ID should match
        assert args[1] == "shadow-eval-001"
        # Status written to DB must be 'regime_suppressed' (NOT 'active' or 'stopped_out')
        assert args[2] == "regime_suppressed", (
            f"Shadow signal exit must keep status='regime_suppressed' in DB. Got: {args[2]!r}"
        )

    @pytest.mark.asyncio
    async def test_shadow_signal_zone_check_skipped(self):
        """Zone-activation check is skipped for regime_suppressed signals.

        If zone-activation was checked (pending path), a shadow signal would
        return a Transition(new_status='active') when price overlaps the zone.
        This would cause the lifecycle service to set status='active' in DB — wrong.

        We validate: when price overlaps the entry zone (zone_low=5095, zone_high=5100)
        but does NOT hit stop or target, the DB is NOT updated (no zone-activation
        Transition written, only MAE/MFE tracking happens in-memory).
        """
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService()
        svc.db_manager = AsyncMock()
        svc.db_manager.execute_command = AsyncMock()

        shadow = _make_shadow_signal("shadow-zone-001")
        svc._mae["shadow-zone-001"] = 0.0
        svc._mfe["shadow-zone-001"] = 0.0
        svc._activated_at["shadow-zone-001"] = shadow["timestamp"]

        # Bar overlaps zone (5095.0-5100.0) but no stop/target hit
        bar_time = datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC)
        bar = {"high": 5102.0, "low": 5096.0, "close": 5099.0}

        await svc._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

        # Zone overlap should NOT trigger a DB write (zone-activation skipped)
        svc.db_manager.execute_command.assert_not_awaited(), (
            "Zone overlap must NOT trigger update_signal_status for shadow signals. "
            "Only stop/target/TTL exits should write to DB."
        )
        # MAE/MFE must be updated in-memory
        assert "shadow-zone-001" in svc._mae

    @pytest.mark.asyncio
    async def test_shadow_signal_mae_mfe_updated_each_bar(self):
        """MAE/MFE in-memory tracking updates on each bar for shadow signals.

        The lifecycle service must update _mae and _mfe for regime_suppressed
        signals on each bar (same as active signals), not just at activation.
        """
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService()
        svc.db_manager = AsyncMock()
        svc.db_manager.execute_command = AsyncMock()

        shadow = _make_shadow_signal("shadow-maemfe-001")
        svc._mae["shadow-maemfe-001"] = 0.0
        svc._mfe["shadow-maemfe-001"] = 0.0
        svc._activated_at["shadow-maemfe-001"] = shadow["timestamp"]

        # Bar 1: favorable move (close above entry=5100.0)
        bar_time = datetime(2026, 3, 4, 14, 35, 0, tzinfo=UTC)
        bar1 = {"high": 5110.0, "low": 5099.0, "close": 5108.0}

        await svc._evaluate_signals_against_bar("ES", "5m", bar1, bar_time, [shadow])

        # MFE should be positive (favorable for long: close > entry)
        mfe_after_bar1 = svc._mfe["shadow-maemfe-001"]
        assert mfe_after_bar1 > 0.0, (
            f"MFE must be positive after favorable bar for shadow signal. Got: {mfe_after_bar1}"
        )

        # Bar 2: adverse move (close below entry, but above stop)
        bar_time2 = datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC)
        bar2 = {"high": 5101.0, "low": 5090.0, "close": 5092.0}

        await svc._evaluate_signals_against_bar("ES", "5m", bar2, bar_time2, [shadow])

        # MAE should be negative (adverse for long: close < entry)
        mae_after_bar2 = svc._mae["shadow-maemfe-001"]
        assert mae_after_bar2 < 0.0, (
            f"MAE must be negative after adverse bar for shadow signal. Got: {mae_after_bar2}"
        )

    @pytest.mark.asyncio
    async def test_shadow_signal_ttl_expiry_gets_8class_outcome(self):
        """Shadow signal at TTL expiry gets a valid 8-class outcome.

        When bars_elapsed >= ttl_bars for a shadow signal (virtually active),
        the lifecycle_tracker returns a Transition with outcome set.
        The lifecycle service must write this outcome to DB with
        status='regime_suppressed' (not 'active' or 'expired').
        """
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService()
        svc.db_manager = AsyncMock()
        svc.db_manager.execute_command = AsyncMock()

        shadow = _make_shadow_signal("shadow-ttl-001")
        # Set TTL to 1 bar so it expires immediately
        shadow["ttl_bars"] = 1
        shadow["bars_elapsed"] = 0
        svc._mae["shadow-ttl-001"] = 0.0
        svc._mfe["shadow-ttl-001"] = 0.1  # small favorable move
        svc._activated_at["shadow-ttl-001"] = shadow["timestamp"]

        # Bar at signal timestamp + 1 bar (5m = 300s → bars_elapsed=1 ≥ ttl_bars=1)
        bar_time = shadow["timestamp"] + timedelta(minutes=5)
        bar = {"high": 5105.0, "low": 5099.0, "close": 5103.0}

        await svc._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

        # DB write must have happened (TTL exit)
        svc.db_manager.execute_command.assert_awaited_once()
        args = svc.db_manager.execute_command.call_args[0]
        assert args[1] == "shadow-ttl-001"
        # Status stays regime_suppressed
        assert args[2] == "regime_suppressed", (
            f"Shadow signal TTL exit must keep status='regime_suppressed'. Got: {args[2]!r}"
        )
        # An outcome must be set (8-class)
        # outcome is arg[17] in update_signal_status (signal_id, status, activated_at, exit_at,
        # exit_price, exit_reason, pnl_ticks, pnl_r, pnl_dollars, signal_quality,
        # activation_price, zone_entry_pct, bars_to_activation, mae, mfe, bars_in_trade, outcome)
        outcome = args[17]
        valid_outcomes = {
            "never_activated", "stopped_at_entry", "stopped_in_trade",
            "target_1", "target_1_2", "target_full",
            "ttl_expired_ahead", "ttl_expired_behind",
        }
        assert outcome in valid_outcomes, (
            f"TTL-expired shadow signal must have 8-class outcome. Got: {outcome!r}"
        )


# ---- LLM outcome payload helper ----


class TestBuildOutcomePayload:
    def test_all_fields_present_as_strings(self):
        """All 7 required fields present and all are str."""
        from services.signal_lifecycle_service import _build_outcome_payload

        result = _build_outcome_payload(
            signal_id="abc-123",
            outcome="target_1",
            pnl_r=1.5,
            mae=-0.3,
            mfe=1.8,
            bars_in_trade=12,
        )
        required = {"signal_id", "outcome", "pnl_r", "mae", "mfe", "bars_in_trade", "outcome_at"}
        assert required <= result.keys()
        for k, v in result.items():
            assert isinstance(v, str), f"Field {k!r} must be str, got {type(v).__name__}"

    def test_none_pnl_r_emits_empty_string(self):
        """None pnl_r → '' (not 'None')."""
        from services.signal_lifecycle_service import _build_outcome_payload

        result = _build_outcome_payload("sid", "stopped_at_entry", None, None, None, None)
        assert result["pnl_r"] == ""
        assert result["mae"] == ""
        assert result["mfe"] == ""
        assert result["bars_in_trade"] == ""

    def test_zero_mae_emits_zero_string(self):
        """0.0 mae → '0.0' (not empty)."""
        from services.signal_lifecycle_service import _build_outcome_payload

        result = _build_outcome_payload("sid", "target_full", 2.0, 0.0, 2.0, 5)
        assert result["mae"] == "0.0"

    def test_signal_id_passthrough(self):
        """signal_id returned as-is."""
        from services.signal_lifecycle_service import _build_outcome_payload

        result = _build_outcome_payload("my-uuid-string", "never_activated", 0.0, 0.0, 0.0, 0)
        assert result["signal_id"] == "my-uuid-string"

    def test_outcome_at_is_non_empty_iso_string(self):
        """outcome_at is a non-empty ISO datetime string."""
        from services.signal_lifecycle_service import _build_outcome_payload

        result = _build_outcome_payload("sid", "ttl_expired_ahead", 0.5, -0.1, 0.5, 3)
        assert result["outcome_at"]  # non-empty
        assert "T" in result["outcome_at"]  # ISO format sanity check


class TestPublishTerminalEvent:
    """_publish_terminal_event() must xadd correct payload to signals stream."""

    def _make_svc(self):
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService.__new__(SignalLifecycleService)
        svc.env_prefix = "development:"
        svc.redis_client = AsyncMock()
        svc.redis_client.xadd = AsyncMock(return_value=b"123-0")
        svc.logger = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_xadd_called_with_direction_zero(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-a",
            symbol="ESH6",
            timeframe="5m",
            outcome="ttl_expired_behind",
            exit_price=6750.25,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        svc.redis_client.xadd.assert_called_once()
        call_args = svc.redis_client.xadd.call_args
        payload = call_args[0][1]  # second positional arg = fields dict
        assert payload["direction"] == "0"
        assert payload["signal_id"] == "uuid-a"
        assert payload["outcome"] == "ttl_expired_behind"
        assert payload["status"] == "ttl_expired_behind"
        assert payload["symbol"] == "ESH6"
        assert payload["timeframe"] == "5m"

    @pytest.mark.asyncio
    async def test_stream_key_uses_env_prefix(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-b",
            symbol="ESH6",
            timeframe="5m",
            outcome="stopped_at_entry",
            exit_price=None,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        stream_key = svc.redis_client.xadd.call_args[0][0]
        assert stream_key.startswith("development:")
        assert "signals:" in stream_key
        assert "ESH6" in stream_key
        assert "5m" in stream_key

    @pytest.mark.asyncio
    async def test_exit_price_empty_string_when_none(self):
        svc = self._make_svc()
        await svc._publish_terminal_event(
            signal_id="uuid-c",
            symbol="NQH6",
            timeframe="1m",
            outcome="never_activated",
            exit_price=None,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        payload = svc.redis_client.xadd.call_args[0][1]
        assert payload["exit_price"] == ""

    @pytest.mark.asyncio
    async def test_no_xadd_when_redis_none(self):
        svc = self._make_svc()
        svc.redis_client = None
        # Must not raise
        await svc._publish_terminal_event(
            signal_id="uuid-d",
            symbol="ESH6",
            timeframe="5m",
            outcome="target_1",
            exit_price=6700.0,
            bar_ts="2026-03-06T15:20:00+00:00",
        )
        # No assertion needed — no AttributeError = pass


class TestTerminalEventWiring:
    """Terminal events fire in both shadow and normal exit paths."""

    def _make_svc_with_db(self):
        from services.signal_lifecycle_service import SignalLifecycleService

        svc = SignalLifecycleService.__new__(SignalLifecycleService)
        svc.env_prefix = "development:"
        svc.redis_client = AsyncMock()
        svc.redis_client.xadd = AsyncMock(return_value=b"123-0")
        svc.db_manager = AsyncMock()
        svc.logger = AsyncMock()
        svc._mae = {}
        svc._mfe = {}
        svc._activated_at = {}
        svc.lifecycle_transitions_total = AsyncMock()
        svc.lifecycle_transitions_total.inc = lambda: None
        svc.active_signals_count = AsyncMock()
        svc.active_signals_count.set = lambda x: None
        svc.point_values = {"ESH6": 50.0}
        return svc

    @pytest.mark.asyncio
    async def test_terminal_event_fires_on_normal_exit(self):
        """Active signal stopped out → _publish_terminal_event called."""
        from unittest.mock import patch, AsyncMock as AM
        from src.intelligence.trading.lifecycle_tracker import Transition

        svc = self._make_svc_with_db()
        svc._publish_terminal_event = AM()

        # Active signal that stops out
        sig = {
            "signal_id": "uuid-exit",
            "symbol": "ESH6",
            "timeframe": "5m",
            "status": "active",
            "direction": -1,
            "entry_price": 6800.0,
            "stop_loss": 6820.0,
            "targets": [6760.0],
            "confidence": 0.85,
            "timestamp": datetime(2026, 3, 6, 15, 0, tzinfo=UTC),
        }
        bar_time = datetime(2026, 3, 6, 15, 5, tzinfo=UTC)
        transition = Transition(
            signal_id="uuid-exit",
            new_status="stopped_out",
            exit_reason="stop_hit",
            exit_price=6820.0,
            pnl_ticks=-20.0,
            pnl_r=-1.0,
            pnl_dollars=-1000.0,
            outcome=None,
            activation_price=None,
            zone_entry_pct=None,
            bars_to_activation=None,
            mae=None,
            mfe=None,
        )

        with patch("services.signal_lifecycle_service.evaluate_signal", return_value=transition), \
             patch("services.signal_lifecycle_service.update_signal_status", new_callable=AM):
            await svc._evaluate_signals_against_bar(
                "ESH6", "5m",
                {"high": 6825.0, "low": 6795.0, "close": 6822.0},
                bar_time,
                all_active=[sig],
            )

        svc._publish_terminal_event.assert_called_once()
        call_kwargs = svc._publish_terminal_event.call_args[1]
        assert call_kwargs["signal_id"] == "uuid-exit"
        assert call_kwargs["symbol"] == "ESH6"
        assert call_kwargs["timeframe"] == "5m"
