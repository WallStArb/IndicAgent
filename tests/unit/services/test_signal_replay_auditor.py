"""Tests for SignalReplayAuditor (Phase 81 plan 07 task 3).

Tests: test_replay_outcome_parametric (16 cases), test_replay_both_tracks_independent,
test_replay_skips_v0_signals, test_replay_skips_ttl_not_elapsed,
test_replay_ohlcv_gap_counter.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_replay_auditor import SignalReplayAuditor
from src.intelligence.trading.signal_outcome import SignalOutcome
from src.persistence.repository.signal_ledger_repository import SignalStatus

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────────

T0 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)


def _make_agent() -> SignalReplayAuditor:
    agent = SignalReplayAuditor.__new__(SignalReplayAuditor)
    agent._log = MagicMock()
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent._producer = AsyncMock()
    agent._pool = AsyncMock()
    agent._stop = asyncio.Event()
    return agent


def _bar(ts: datetime, high: float, low: float, close: float) -> dict:
    """Dict compatible with asyncpg.Record subscript access."""
    return {
        "timestamp": ts,
        "high": high,
        "low": low,
        "close": close,
        "open": close,
        "volume": 1000.0,
    }


def _make_signal(direction: int) -> dict:
    """Standard signal dict for _evaluate_zone_track testing.

    expires_at is set to T0 + ttl_bars * 60s (1m timeframe) so that bar-time TTL
    evaluation fires at bar index ttl_bars (bar_time >= expires_at).
    """
    if direction == 1:
        return {
            "signal_id": str(uuid.uuid4()),
            "status": SignalStatus.PENDING,
            "direction": 1,
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "targets": [102.0, 104.0, 106.0],
            "ttl_bars": 6,
            "bars_elapsed": 0,
            "point_value": 1.0,
            "entry_zone_low": 99.8,
            "entry_zone_high": 100.5,
            "activated_at": None,
            "hmm_regime_at_fire": None,
            "garch_sigma_at_fire": None,
            "setup_plugin": "test",
            # expires_at: T0 + 6 * 60s → bar at T0+6min triggers TTL
            "expires_at": T0 + timedelta(minutes=6),
        }
    else:
        return {
            "signal_id": str(uuid.uuid4()),
            "status": SignalStatus.PENDING,
            "direction": -1,
            "entry_price": 100.0,
            "stop_loss": 102.0,
            "targets": [98.0, 96.0, 94.0],
            "ttl_bars": 6,
            "bars_elapsed": 0,
            "point_value": 1.0,
            "entry_zone_low": 99.5,
            "entry_zone_high": 100.2,
            "activated_at": None,
            "hmm_regime_at_fire": None,
            "garch_sigma_at_fire": None,
            "setup_plugin": "test",
            # expires_at: T0 + 6 * 60s → bar at T0+6min triggers TTL
            "expires_at": T0 + timedelta(minutes=6),
        }


def _make_row(**overrides) -> dict:
    """Minimal asyncpg.Record-compatible dict for _replay_signal."""
    row = {
        "signal_id": uuid.uuid4(),
        "symbol": "ESM6",
        "timeframe": "1m",
        "timestamp": T0 - timedelta(minutes=20),
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "targets": [102.0, 104.0, 106.0],
        "entry_zone_low": 99.8,
        "entry_zone_high": 100.5,
        "market_entry_price": None,
        "ttl_bars": 10,
        "status": SignalStatus.PENDING,
        "activated_at": None,
        "hmm_regime_at_fire": None,
        "garch_sigma_at_fire": None,
        "point_value": 1.0,
        "direction": 1,
    }
    row.update(overrides)
    return row


def _bars_for_outcome(outcome: str, direction: int) -> list[dict]:
    """Generate minimal bar sequences that produce each outcome via _evaluate_zone_track."""
    if direction == 1:
        # Long: entry=100.0→100.5 (post-activation), stop=98.0, targets=[102,104,106]
        # zone: 99.8–100.5, ttl=6
        ACTIVATE = _bar(T0, high=100.5, low=99.8, close=100.2)
        NO_ZONE = _bar(T0, high=99.7, low=98.5, close=99.0)  # high < zone_low → no activation

        if outcome == "never_activated":
            # 6 neutral bars (pending, no zone), then 7th triggers TTL (bars_elapsed=6>=ttl=6)
            return [NO_ZONE] * 7

        elif outcome == "stopped_at_entry":
            # Activate (bars_in_trade=0, mfe=0), then immediately hit stop
            return [
                ACTIVATE,
                _bar(T0 + timedelta(minutes=1), high=100.0, low=97.9, close=98.0),
            ]

        elif outcome == "stopped_in_trade":
            # Activate, 3 active bars with mfe>0.05, then stop
            # entry_price=100.5, stop=98.0, risk=2.5; targets=[102,104,106] — keep high < 102
            return [
                ACTIVATE,
                _bar(T0 + timedelta(minutes=1), high=101.2, low=100.5, close=101.0),  # mfe=0.2
                _bar(T0 + timedelta(minutes=2), high=101.5, low=100.8, close=101.3),  # mfe=0.32
                _bar(
                    T0 + timedelta(minutes=3), high=101.8, low=100.9, close=101.5
                ),  # mfe=0.4, bst=3
                _bar(T0 + timedelta(minutes=4), high=101.0, low=97.9, close=98.0),  # stop
            ]

        elif outcome == "target_1":
            # Activate then high reaches targets[0]=102.0 (but not 104.0)
            return [
                ACTIVATE,
                _bar(T0 + timedelta(minutes=1), high=102.0, low=100.8, close=101.5),
            ]

        elif outcome == "target_1_2":
            # Activate then high reaches targets[1]=104.0 (highest target hit first in loop)
            return [
                ACTIVATE,
                _bar(T0 + timedelta(minutes=1), high=104.0, low=100.8, close=103.0),
            ]

        elif outcome == "target_full":
            # Activate then high reaches targets[2]=106.0
            return [
                ACTIVATE,
                _bar(T0 + timedelta(minutes=1), high=106.0, low=100.8, close=105.0),
            ]

        elif outcome == "ttl_expired_ahead":
            # Activate (bar 0), 5 positive-mfe active bars (bars 1-5), TTL bar 6 (bars_elapsed=6)
            # After activation entry_price=100.5; close=101.0 → pnl_r=0.2>0 → mfe=0.2
            return [
                ACTIVATE,
                *[
                    _bar(T0 + timedelta(minutes=i + 1), high=101.0, low=100.3, close=101.0)
                    for i in range(5)
                ],
                _bar(T0 + timedelta(minutes=6), high=101.0, low=100.3, close=101.0),
            ]

        elif outcome == "ttl_expired_behind":
            # Activate (bar 0), 5 negative-mfe active bars (bars 1-5), TTL bar 6
            # close=100.2 < entry=100.5 → pnl_r=-0.12 → mfe<=0
            return [
                ACTIVATE,
                *[
                    _bar(T0 + timedelta(minutes=i + 1), high=100.6, low=99.9, close=100.2)
                    for i in range(5)
                ],
                _bar(T0 + timedelta(minutes=6), high=100.6, low=99.9, close=100.2),
            ]

    else:  # direction == -1
        # Short: entry=100.0→99.5 (post-activation), stop=102.0, targets=[98,96,94]
        # zone: 99.5–100.2, ttl=6
        # activation: max(low, zone_low)=99.5; entry_price updated to 99.5; risk=2.5
        ACTIVATE_S = _bar(T0, high=100.2, low=99.5, close=99.8)
        NO_ZONE_S = _bar(T0, high=99.3, low=98.5, close=99.0)  # high < zone_low → no overlap

        if outcome == "never_activated":
            return [NO_ZONE_S] * 7

        elif outcome == "stopped_at_entry":
            return [
                ACTIVATE_S,
                _bar(T0 + timedelta(minutes=1), high=102.5, low=99.5, close=101.0),
            ]

        elif outcome == "stopped_in_trade":
            # entry_price=99.5, stop=102.0, risk=2.5; targets=[98,96,94] — keep low > 98.0
            return [
                ACTIVATE_S,
                _bar(T0 + timedelta(minutes=1), high=99.0, low=98.5, close=98.5),  # mfe=0.4
                _bar(T0 + timedelta(minutes=2), high=99.0, low=98.2, close=98.5),  # mfe=0.4, bst=2
                _bar(T0 + timedelta(minutes=3), high=99.0, low=98.3, close=98.5),  # bst=3
                _bar(T0 + timedelta(minutes=4), high=102.5, low=98.5, close=101.5),  # stop
            ]

        elif outcome == "target_1":
            # targets[0]=98.0; short: low <= 98.0 → target_1
            return [
                ACTIVATE_S,
                _bar(T0 + timedelta(minutes=1), high=99.5, low=98.0, close=98.2),
            ]

        elif outcome == "target_1_2":
            # targets[1]=96.0; short: low <= 96.0 → target_1_2
            return [
                ACTIVATE_S,
                _bar(T0 + timedelta(minutes=1), high=99.0, low=96.0, close=96.5),
            ]

        elif outcome == "target_full":
            # targets[2]=94.0; short: low <= 94.0 → target_full
            return [
                ACTIVATE_S,
                _bar(T0 + timedelta(minutes=1), high=99.0, low=94.0, close=95.0),
            ]

        elif outcome == "ttl_expired_ahead":
            # close=98.8 < entry=99.5 → pnl_r=0.28>0 → mfe>0 → ttl_expired_ahead
            return [
                ACTIVATE_S,
                *[
                    _bar(T0 + timedelta(minutes=i + 1), high=99.3, low=98.5, close=98.8)
                    for i in range(5)
                ],
                _bar(T0 + timedelta(minutes=6), high=99.3, low=98.5, close=98.8),
            ]

        elif outcome == "ttl_expired_behind":
            # close=100.2 > entry=99.5 → pnl_r=-0.28 → mfe<=0 → ttl_expired_behind
            return [
                ACTIVATE_S,
                *[
                    _bar(T0 + timedelta(minutes=i + 1), high=100.5, low=99.5, close=100.2)
                    for i in range(5)
                ],
                _bar(T0 + timedelta(minutes=6), high=100.5, low=99.5, close=100.2),
            ]

    return []


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

_ALL_OUTCOMES = [
    "stopped_at_entry",
    "stopped_in_trade",
    # target_1 removed: T1 no longer exits the signal (advances be_floor instead)
    "target_1_2",
    "target_full",
    "ttl_expired_ahead",
    "ttl_expired_behind",
]

_DIRECTIONS = [1, -1]


@pytest.mark.parametrize("direction", _DIRECTIONS)
@pytest.mark.parametrize("outcome", _ALL_OUTCOMES)
def test_replay_outcome_parametric(outcome: str, direction: int) -> None:
    """14 cases (7 outcomes × 2 directions): _evaluate_zone_track produces expected outcome.

    never_activated excluded: _evaluate_zone_track cannot produce it for PENDING signals
    since the TTL reorder moved TTL check after the PENDING short-circuit.
    """
    agent = _make_agent()
    signal_dict = _make_signal(direction)
    bars = _bars_for_outcome(outcome, direction)
    assert bars, f"No bars generated for outcome={outcome}, direction={direction}"

    lt = agent._evaluate_zone_track(signal_dict, bars, T0 - timedelta(minutes=1))

    assert (
        lt is not None
    ), f"Expected terminal transition for outcome={outcome}, direction={direction}"
    actual = lt.data.get("outcome")
    assert actual == outcome, f"outcome mismatch for {outcome} dir={direction}: got {actual!r}"

    pnl_r = lt.data.get("pnl_r")
    assert pnl_r is not None, "pnl_r must be present in EXIT transition"
    assert isinstance(pnl_r, float), f"pnl_r must be float, got {type(pnl_r)}"


@pytest.mark.asyncio
async def test_replay_both_tracks_independent() -> None:
    """Zone never_activated + market track resolves independently; both events published."""
    agent = _make_agent()

    # ttl=3, bars fall short of zone (no activation), then TTL fires
    # market_entry_price set → market track also resolves at TTL
    # 4 bars: 3 non-activating + 1 TTL bar (bars_elapsed=3=ttl)
    # Long: zone=99.8-100.5. Use high=99.7 → no zone overlap
    signal_ts = T0
    bars = [_bar(T0 + timedelta(minutes=i), high=99.7, low=98.5, close=99.0) for i in range(4)]

    row = _make_row(
        ttl_bars=3,
        timestamp=signal_ts
        - timedelta(
            minutes=30
        ),  # well past TTL so _replay_signal's early-return gate doesn't block
        market_entry_price=99.5,  # parallel track was filled
    )

    # Build signal dict manually (mirrors what _build_signal_dict would produce)
    signal_dict = {
        "signal_id": str(row["signal_id"]),
        "status": row["status"] or SignalStatus.PENDING,
        "direction": int(row["direction"]),
        "entry_price": float(row["entry_price"]),
        "stop_loss": float(row["stop_loss"]),
        "targets": list(row["targets"]),
        "ttl_bars": int(row["ttl_bars"]),
        "bars_elapsed": 0,
        "point_value": float(row["point_value"]),
        "entry_zone_low": float(row["entry_zone_low"]),
        "entry_zone_high": float(row["entry_zone_high"]),
        "activated_at": None,
        "hmm_regime_at_fire": None,
        "garch_sigma_at_fire": None,
        "setup_plugin": "replay",
    }

    zone_result = agent._evaluate_zone_track(signal_dict, bars, signal_ts)
    market_result = agent._evaluate_market_track(
        signal_dict, bars, float(row["market_entry_price"]), signal_ts
    )

    # Zone track: pending signals never TTL-expire through _evaluate_zone_track
    # (TTL reorder: PENDING short-circuits to zone activation check only).
    # The never_activated outcome is produced by the calling service, not _evaluate_zone_track.
    assert zone_result is None, (
        "Zone track must return None for PENDING signal that never activates "
        "(never_activated is resolved by the calling service)"
    )

    # Market track: resolves independently (TTL_EXPIRED_AHEAD or BEHIND)
    assert market_result is not None, "Market track must resolve independently"
    market_outcome = market_result.data.get("market_entry_outcome")
    assert market_outcome in (
        SignalOutcome.TTL_EXPIRED_AHEAD.value,
        SignalOutcome.TTL_EXPIRED_BEHIND.value,
    ), f"Unexpected market outcome: {market_outcome}"


def test_fetch_unresolved_filters_on_zone_low() -> None:
    """_fetch_unresolved SQL must filter entry_zone_low IS NOT NULL — the real structural invariant."""
    src = inspect.getsource(SignalReplayAuditor._fetch_unresolved)
    assert "entry_zone_low IS NOT NULL" in src, (
        "_fetch_unresolved must filter entry_zone_low IS NOT NULL. "
        "Version strings are a proxy invariant; column presence is the ground truth."
    )


@pytest.mark.asyncio
async def test_replay_skips_ttl_not_elapsed() -> None:
    """_replay_signal returns False immediately when TTL window has not yet elapsed."""
    agent = _make_agent()

    row = _make_row(
        timestamp=datetime.now(UTC) - timedelta(minutes=1),  # only 1 min elapsed
        ttl_bars=10,
        timeframe="1m",  # ttl window = 10 * 60 = 600 seconds; 60 < 600
    )

    fetch_bars_called = False

    async def _mock_fetch(*_args, **_kwargs):
        nonlocal fetch_bars_called
        fetch_bars_called = True
        return []

    agent._fetch_window_bars = _mock_fetch

    result = await agent._replay_signal(row)

    assert result is False, "_replay_signal must return False when TTL window has not elapsed"
    assert not fetch_bars_called, "_fetch_window_bars must NOT be called when TTL not elapsed"


@pytest.mark.asyncio
async def test_replay_ohlcv_gap_counter() -> None:
    """When _fetch_window_bars returns [], SIGNAL_REPLAY_OHLCV_GAP_TOTAL is incremented."""
    agent = _make_agent()
    symbol = "ESM6_gap_test"
    tf = "1m"

    row = _make_row(
        symbol=symbol,
        timeframe=tf,
        timestamp=datetime.now(UTC) - timedelta(minutes=20),
        ttl_bars=10,
    )

    from unittest.mock import patch

    async def _mock_fetch(*_args, **_kwargs):
        return []  # simulate OHLCV gap

    agent._fetch_window_bars = _mock_fetch

    with patch("services.signal_replay_auditor.SIGNAL_REPLAY_OHLCV_GAP_TOTAL") as mock_gap:
        result = await agent._replay_signal(row)

    assert result is False, "_replay_signal must return False when OHLCV gap detected"
    # OTel counter: .add(1, {"symbol": ..., "timeframe": ...}) must have been called
    mock_gap.add.assert_called()
