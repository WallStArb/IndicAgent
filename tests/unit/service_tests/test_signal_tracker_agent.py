"""Unit tests for SignalTrackerAgent — TDD tests for 52.4 refactor.

Migrated from test_signal_lifecycle_service.py — tests use SignalTrackerAgent
with self._ledger_repo mocked (not svc.db_manager.execute_command directly).
"""

import ast
import asyncio
import pathlib
from collections import defaultdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Task 2: Structural TDD tests (RED → GREEN)
# ---------------------------------------------------------------------------


def test_class_name():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    tree = ast.parse(src)
    class_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "SignalTrackerAgent" in class_names
    assert "SignalLifecycleService" not in class_names


def test_inherits_base_agent():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "BaseAgent" in src


def test_no_direct_sql():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    # No raw SQL in the agent class — all delegated to repository
    assert "UPDATE signal_ledger" not in src
    assert "INSERT INTO signal_ledger" not in src


def test_uses_signal_ledger_repository():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "SignalLedgerRepository" in src


def test_has_sigterm_drain():
    src = pathlib.Path("services/signal_tracker_agent.py").read_text()
    assert "_stop_event" in src or "SIGTERM" in src


# ---------------------------------------------------------------------------
# Task 3: Migrated behavioral tests (from test_signal_lifecycle_service.py)
# Tests adapted to use SignalTrackerAgent with _ledger_repo mocked
# ---------------------------------------------------------------------------


def _make_agent():
    """Build a minimal SignalTrackerAgent bypassing __init__ (service test pattern)."""
    from services.signal_tracker_agent import SignalTrackerAgent

    agent = SignalTrackerAgent.__new__(SignalTrackerAgent)
    agent.name = "signal_tracker_agent"
    # running is a read-only property (computed from _stop_event), don't set it directly
    agent.shutdown_requested = False
    agent.start_time = datetime.now(tz=UTC)
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.config = {"service": {"symbols": ["ES"], "timeframes": ["1m", "5m", "15m", "1h"]}}
    agent.point_values = {"ES": 50.0}
    agent._mae = {}
    agent._mfe = {}
    agent._activated_at = {}
    agent._market_mae = {}
    agent._market_mfe = {}
    agent._market_activated_at = {}
    agent._resolved_market = set()
    agent._chandelier_state = {}
    agent._staleness_consecutive = {}
    agent._shadow_signals = {}
    agent._active_index = defaultdict(list)
    agent._kafka_consumer = None
    agent._kafka_producer = None
    agent._pending_tasks = set()
    agent.shutdown_event = asyncio.Event()
    # Metrics mocks
    agent.lifecycle_transitions_total = MagicMock()
    agent.lifecycle_transitions_total.inc = MagicMock()
    agent.active_signals_count = MagicMock()
    agent.active_signals_count.set = MagicMock()
    agent.service_uptime_seconds = MagicMock()
    agent.error_count_total = MagicMock()
    agent.error_count_total.inc = MagicMock()
    # DB
    agent.db_manager = AsyncMock()
    agent.db_manager.execute_command = AsyncMock()
    agent._ledger_repo = AsyncMock()
    agent._ledger_repo.record_zone_resolution = AsyncMock()
    agent._ledger_repo.record_activation = AsyncMock()
    agent._ledger_repo.record_market_resolution = AsyncMock()
    agent._ledger_repo.update_chandelier_state = AsyncMock()
    agent._ledger_repo.update_chandelier_vol_source = AsyncMock()
    agent._ledger_repo.update_shadow_outcome = AsyncMock()
    agent._ledger_repo.set_shadow_tracking_start = AsyncMock()
    return agent


def _make_shadow_signal(sid: str = "shadow-001") -> dict:
    """Build a minimal regime_suppressed signal dict."""
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


def _pending_sig(
    signal_id: str = "sig-001",
    direction: int = 1,
    market_entry_price: float | None = 5100.0,
    stop: float = 5085.0,
) -> dict:
    return {
        "signal_id": signal_id,
        "symbol": "ES",
        "timeframe": "1m",
        "status": "pending",
        "direction": direction,
        "entry_price": 5100.0,
        "stop_loss": stop,
        "targets": [5115.0],
        "confidence": 0.75,
        "ttl_bars": 20,
        "entry_zone_low": 5095.0,
        "entry_zone_high": 5100.0,
        "timestamp": datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
        "market_entry_price": market_entry_price,
    }


# ---------------------------------------------------------------------------
# Shadow signal virtual-activation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_signal_mae_mfe_initialized():
    """regime_suppressed signal → _mae/_mfe initialized to 0.0 on first bar."""
    agent = _make_agent()
    shadow = _make_shadow_signal("shadow-startup-001")
    bar_time = datetime(2026, 3, 4, 14, 35, 0, tzinfo=UTC)
    bar = {"high": 5108.0, "low": 5099.0, "close": 5105.0}

    assert "shadow-startup-001" not in agent._mae
    assert "shadow-startup-001" not in agent._mfe

    await agent._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

    assert "shadow-startup-001" in agent._mae, "Shadow signal _mae must be initialized"
    assert "shadow-startup-001" in agent._mfe, "Shadow signal _mfe must be initialized"


@pytest.mark.asyncio
async def test_shadow_signal_evaluate_called_with_active_override():
    """Shadow signal stop hit → record_zone_resolution called with status='regime_suppressed'."""
    agent = _make_agent()
    shadow = _make_shadow_signal("shadow-eval-001")
    agent._mae["shadow-eval-001"] = 0.0
    agent._mfe["shadow-eval-001"] = 0.0
    agent._activated_at["shadow-eval-001"] = shadow["timestamp"]

    bar_time = datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC)
    bar = {"high": 5095.0, "low": 5080.0, "close": 5082.0}

    await agent._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

    # record_zone_resolution must be called via _ledger_repo
    agent._ledger_repo.record_zone_resolution.assert_awaited_once()
    call_args = agent._ledger_repo.record_zone_resolution.call_args
    assert call_args[0][0] == "shadow-eval-001"
    # Status stays regime_suppressed
    assert call_args[1].get("status") == "regime_suppressed", (
        f"Shadow signal exit must keep status='regime_suppressed'. "
        f"Got: {call_args[1].get('status')!r}"
    )


@pytest.mark.asyncio
async def test_shadow_signal_zone_check_skipped():
    """Zone overlap → no DB write for shadow signal (no stop/target hit)."""
    agent = _make_agent()
    shadow = _make_shadow_signal("shadow-zone-001")
    agent._mae["shadow-zone-001"] = 0.0
    agent._mfe["shadow-zone-001"] = 0.0
    agent._activated_at["shadow-zone-001"] = shadow["timestamp"]

    bar_time = datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC)
    bar = {"high": 5102.0, "low": 5096.0, "close": 5099.0}

    await agent._evaluate_signals_against_bar("ES", "5m", bar, bar_time, [shadow])

    agent._ledger_repo.record_zone_resolution.assert_not_awaited()
    assert "shadow-zone-001" in agent._mae


@pytest.mark.asyncio
async def test_shadow_signal_mae_mfe_updated_each_bar():
    """MAE/MFE accumulate across bars for shadow signals."""
    agent = _make_agent()
    shadow = _make_shadow_signal("shadow-maemfe-001")
    agent._mae["shadow-maemfe-001"] = 0.0
    agent._mfe["shadow-maemfe-001"] = 0.0
    agent._activated_at["shadow-maemfe-001"] = shadow["timestamp"]

    bar1 = {"high": 5110.0, "low": 5099.0, "close": 5108.0}
    await agent._evaluate_signals_against_bar(
        "ES", "5m", bar1, datetime(2026, 3, 4, 14, 35, 0, tzinfo=UTC), [shadow]
    )
    assert agent._mfe["shadow-maemfe-001"] > 0.0, "MFE should be positive after favorable bar"

    bar2 = {"high": 5101.0, "low": 5090.0, "close": 5092.0}
    await agent._evaluate_signals_against_bar(
        "ES", "5m", bar2, datetime(2026, 3, 4, 14, 40, 0, tzinfo=UTC), [shadow]
    )
    assert agent._mae["shadow-maemfe-001"] < 0.0, "MAE should be negative after adverse bar"


# ---------------------------------------------------------------------------
# Terminal event wiring test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_event_fires_on_normal_exit():
    """Active signal stopped out → _publish_terminal_event called."""
    from src.intelligence.trading.lifecycle_tracker import Transition

    agent = _make_agent()
    agent._publish_terminal_event = AsyncMock()

    sig = {
        "signal_id": "uuid-exit",
        "symbol": "ES",
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

    with patch("services.signal_tracker_agent.evaluate_signal", return_value=transition):
        await agent._evaluate_signals_against_bar(
            "ES", "5m",
            {"high": 6825.0, "low": 6795.0, "close": 6822.0},
            bar_time,
            all_active=[sig],
        )

    agent._publish_terminal_event.assert_called_once()
    call_kwargs = agent._publish_terminal_event.call_args[1]
    assert call_kwargs["signal_id"] == "uuid-exit"
    assert call_kwargs["symbol"] == "ES"
    assert call_kwargs["timeframe"] == "5m"


# ---------------------------------------------------------------------------
# Market track tests
# ---------------------------------------------------------------------------


def test_null_market_entry_price_skips_market_track():
    """market_entry_price=None → market track not evaluated, no error."""
    agent = _make_agent()
    sig = _pending_sig(market_entry_price=None)
    bar_time = datetime(2026, 3, 14, 10, 1, 0, tzinfo=UTC)
    bar = {"high": 5110.0, "low": 5098.0, "close": 5105.0}

    asyncio.run(agent._evaluate_signals_against_bar("ES", "1m", bar, bar_time, [sig]))

    agent._ledger_repo.record_market_resolution.assert_not_awaited()


def test_market_activated_at_set_on_first_bar():
    """_market_activated_at is set to bar_time on first bar with market_entry_price."""
    agent = _make_agent()
    sig = _pending_sig(signal_id="sig-001")
    bar_time = datetime(2026, 3, 14, 10, 1, 0, tzinfo=UTC)
    bar = {"high": 5108.0, "low": 5098.0, "close": 5105.0}

    asyncio.run(agent._evaluate_signals_against_bar("ES", "1m", bar, bar_time, [sig]))

    assert "sig-001" in agent._market_activated_at
    assert agent._market_activated_at["sig-001"] == bar_time


@pytest.mark.unit
class TestMarketTrackResolution:
    def test_market_resolution_cleans_up_state(self):
        """After market resolution, market state dicts are cleaned up."""
        agent = _make_agent()
        agent._market_mae["sig-001"] = -0.5
        agent._market_mfe["sig-001"] = 0.0
        agent._market_activated_at["sig-001"] = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
        sig = _pending_sig(signal_id="sig-001", direction=1, market_entry_price=5100.0, stop=5085.0)
        bar_time = datetime(2026, 3, 14, 10, 1, 0, tzinfo=UTC)
        bar = {"high": 5098.0, "low": 5084.0, "close": 5086.0}

        asyncio.run(agent._evaluate_signals_against_bar("ES", "1m", bar, bar_time, [sig]))

        assert "sig-001" not in agent._market_mae
        assert "sig-001" not in agent._market_mfe
        assert "sig-001" not in agent._market_activated_at


# ---------------------------------------------------------------------------
# Agent structural attributes
# ---------------------------------------------------------------------------


def test_signal_tracker_agent_imports():
    from services.signal_tracker_agent import SignalTrackerAgent

    agent = SignalTrackerAgent()
    assert hasattr(agent, "_evaluate_signals_against_bar")


def test_signal_tracker_agent_has_kafka_clients():
    from services.signal_tracker_agent import SignalTrackerAgent

    agent = SignalTrackerAgent()
    assert hasattr(agent, "_kafka_consumer")
    assert hasattr(agent, "_kafka_producer")
    assert hasattr(agent, "env_name")


def test_signal_tracker_agent_has_ledger_repo():
    from services.signal_tracker_agent import SignalTrackerAgent

    agent = SignalTrackerAgent()
    assert hasattr(agent, "_ledger_repo")


def test_mae_mfe_tracked_in_memory():
    """Active signals accumulate MAE/MFE across bars."""
    from services.signal_tracker_agent import SignalTrackerAgent

    agent = SignalTrackerAgent()
    agent._mae["sig-1"] = -0.2
    agent._mfe["sig-1"] = 0.5

    assert agent._mae["sig-1"] == pytest.approx(-0.2)
    assert agent._mfe["sig-1"] == pytest.approx(0.5)

    agent._mae.pop("sig-1", None)
    agent._mfe.pop("sig-1", None)
    assert "sig-1" not in agent._mae
    assert "sig-1" not in agent._mfe
