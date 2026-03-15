"""Signal lifecycle tracker.

Evaluates signal state transitions based on price data. Pure functions —
does not touch the database. Returns Transition objects that the caller
persists via signal_ledger.update_signal_status().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2  # bars_in_trade <= this → stopped_at_entry


@dataclass
class Transition:
    """A state change for a signal."""

    signal_id: str
    new_status: str
    exit_reason: str | None = None
    exit_price: float | None = None
    pnl_ticks: float | None = None
    pnl_r: float | None = None
    pnl_dollars: float | None = None
    # Institutional fields
    activation_price: float | None = None
    zone_entry_pct: float | None = None
    bars_to_activation: int | None = None
    mae: float | None = None
    mfe: float | None = None
    bars_in_trade: int | None = None
    outcome: str | None = None


def evaluate_signal(
    signal: dict[str, Any],
    *,
    high: float,
    low: float,
    close: float,
    current_mae: float = 0.0,
    current_mfe: float = 0.0,
) -> Transition | None:
    """Evaluate whether a signal should transition state.

    Args:
        signal: Dict with signal fields (status, direction, entry_price,
                stop_loss, targets, ttl_bars, bars_elapsed, point_value,
                entry_zone_low, entry_zone_high).
        high: Current bar's high price.
        low: Current bar's low price.
        close: Current bar's close price.
        current_mae: Current maximum adverse excursion (pnl_r units).
        current_mfe: Current maximum favorable excursion (pnl_r units).

    Returns:
        Transition if state changes (with updated mae/mfe on exit),
        None if signal stays in current state.
    """
    sid = signal["signal_id"]
    status = signal["status"]
    direction = signal["direction"]
    entry = signal["entry_price"]
    stop = signal["stop_loss"]
    targets = signal.get("targets") or []
    ttl = signal.get("ttl_bars", 10)
    bars = signal.get("bars_elapsed", 0)
    point_value = signal.get("point_value", 1.0)
    zone_low = signal.get("entry_zone_low") or entry
    zone_high = signal.get("entry_zone_high") or entry
    risk = abs(entry - stop)

    # TTL check first (applies to both pending and active)
    if bars >= ttl:
        exit_price = close
        pnl_ticks = (exit_price - entry) * direction
        pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
        pnl_dollars = round(pnl_ticks * point_value, 2)
        if status == "pending":
            outcome = "never_activated"
        elif current_mfe > 0:
            outcome = "ttl_expired_ahead"
        else:
            outcome = "ttl_expired_behind"
        return Transition(
            signal_id=sid,
            new_status="expired",
            exit_reason="ttl_expired",
            exit_price=exit_price,
            pnl_ticks=round(pnl_ticks, 4),
            pnl_r=pnl_r,
            pnl_dollars=pnl_dollars,
            mae=current_mae,
            mfe=current_mfe,
            outcome=outcome,
        )

    if status == "pending":
        return _check_zone_activation(sid, direction, zone_low, zone_high, high, low, bars)

    if status == "active":
        return _check_active_exit(
            sid,
            direction,
            entry,
            stop,
            targets,
            high,
            low,
            close,
            risk,
            point_value,
            current_mae,
            current_mfe,
        )

    return None


def _check_zone_activation(
    sid: str,
    direction: int,
    zone_low: float,
    zone_high: float,
    high: float,
    low: float,
    bars_elapsed: int,
) -> Transition | None:
    """Zone-aware activation: bar range must overlap the entry zone."""
    bar_overlaps_zone = low <= zone_high and high >= zone_low

    if not bar_overlaps_zone:
        return None

    zone_span = zone_high - zone_low

    if direction == 1:
        # Long: price falls into zone from above; activation = first touch of zone_high
        activation_price = min(high, zone_high)
        # zone_entry_pct: 0.0 = proximal (zone_high), 1.0 = distal (zone_low)
        zone_entry_pct = (
            round((zone_high - activation_price) / zone_span, 4) if zone_span > 0 else 0.5
        )
    else:
        # Short: price rises into zone from below; activation = first touch of zone_low
        activation_price = max(low, zone_low)
        # zone_entry_pct: 0.0 = proximal (zone_low), 1.0 = distal (zone_high)
        zone_entry_pct = (
            round((activation_price - zone_low) / zone_span, 4) if zone_span > 0 else 0.5
        )

    return Transition(
        signal_id=sid,
        new_status="active",
        activation_price=round(activation_price, 4),
        zone_entry_pct=zone_entry_pct,
        bars_to_activation=bars_elapsed,
    )


def _check_active_exit(
    sid: str,
    direction: int,
    entry: float,
    stop: float,
    targets: list[float],
    high: float,
    low: float,
    close: float,
    risk: float,
    point_value: float,
    current_mae: float,
    current_mfe: float,
) -> Transition | None:
    """Check if an active signal should exit; returns None if still in trade."""
    # Stop loss check first (conservative: stop before target on same bar)
    if direction == 1 and low <= stop:
        return _make_exit(
            sid,
            "stopped_out",
            "stop_loss",
            stop,
            entry,
            direction,
            risk,
            point_value,
            current_mae,
            current_mfe,
        )
    if direction == -1 and high >= stop:
        return _make_exit(
            sid,
            "stopped_out",
            "stop_loss",
            stop,
            entry,
            direction,
            risk,
            point_value,
            current_mae,
            current_mfe,
        )

    # Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
        if hit:
            return _make_exit(
                sid,
                f"target_{i + 1}_hit",
                f"target_{i + 1}",
                target,
                entry,
                direction,
                risk,
                point_value,
                current_mae,
                current_mfe,
                target_index=i,
            )

    return None


def _determine_target_outcome(target_index: int) -> str:
    """Map target index (0-based) to outcome label."""
    return ["target_1", "target_1_2", "target_full"][min(target_index, 2)]


def _classify_stop_outcome(current_mfe: float, bars_in_trade_count: int | None) -> str:
    """Resolve fine-grained outcome for a stopped-out signal."""
    if (
        bars_in_trade_count is None
        or bars_in_trade_count <= OUTCOME_THRESHOLD_QUICK_STOP_BARS
        or current_mfe <= 0.05
    ):
        return "stopped_at_entry"
    return "stopped_in_trade"


@dataclass
class MarketTransition:
    """State for the market-entry parallel track. outcome=None means still running."""

    signal_id: str
    exit_price: float | None = None
    pnl_r: float | None = None
    mae: float = 0.0
    mfe: float = 0.0
    outcome: str | None = None  # None = still running; stops resolved by caller
    gap_bars: int | None = None  # replay only; None for live signals


def evaluate_market_entry(
    signal: dict[str, Any],
    *,
    market_entry_price: float,
    high: float,
    low: float,
    close: float,
    current_mae: float = 0.0,
    current_mfe: float = 0.0,
) -> MarketTransition:
    """Evaluate market-entry track for one bar.

    Always "active" from bar 1 — no zone activation.
    Risk is based on market_entry_price (not entry_price).
    Returns MarketTransition with outcome=None while running; populated on exit.
    Stop outcomes (stopped_at_entry vs stopped_in_trade) are resolved by the
    caller via _classify_stop_outcome() using bars_in_trade context.
    """
    sid = signal["signal_id"]
    direction = signal["direction"]
    stop = signal["stop_loss"]
    targets = signal.get("targets") or []
    ttl = signal.get("ttl_bars", 10)
    bars = signal.get("bars_elapsed", 0)
    risk = abs(market_entry_price - stop)

    # TTL check first (mirrors evaluate_signal)
    if bars >= ttl:
        pnl_ticks = (close - market_entry_price) * direction
        pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
        outcome = "ttl_expired_ahead" if current_mfe > 0 else "ttl_expired_behind"
        final_mae = min(current_mae, pnl_r)
        final_mfe = max(current_mfe, pnl_r)
        return MarketTransition(
            signal_id=sid,
            exit_price=close,
            pnl_r=pnl_r,
            mae=round(final_mae, 4),
            mfe=round(final_mfe, 4),
            outcome=outcome,
        )

    # Stop loss check (stop before target on same bar — conservative)
    if (direction == 1 and low <= stop) or (direction == -1 and high >= stop):
        return _make_market_exit(sid, stop, market_entry_price, direction, risk,
                                 current_mae, current_mfe)

    # Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
        if hit:
            pnl_ticks = (target - market_entry_price) * direction
            pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
            final_mae = min(current_mae, pnl_r)
            final_mfe = max(current_mfe, pnl_r)
            return MarketTransition(
                signal_id=sid,
                exit_price=target,
                pnl_r=pnl_r,
                mae=round(final_mae, 4),
                mfe=round(final_mfe, 4),
                outcome=_determine_target_outcome(i),
            )

    # Still running
    return MarketTransition(signal_id=sid)


def _make_market_exit(
    sid: str,
    exit_price: float,
    market_entry_price: float,
    direction: int,
    risk: float,
    current_mae: float,
    current_mfe: float,
) -> MarketTransition:
    """Build a stop-exit MarketTransition. outcome=None — resolved by caller."""
    pnl_ticks = (exit_price - market_entry_price) * direction
    pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
    final_mae = min(current_mae, pnl_r)
    final_mfe = max(current_mfe, pnl_r)
    return MarketTransition(
        signal_id=sid,
        exit_price=exit_price,
        pnl_r=pnl_r,
        mae=round(final_mae, 4),
        mfe=round(final_mfe, 4),
        outcome=None,
    )


def _make_exit(
    sid: str,
    status: str,
    reason: str,
    exit_price: float,
    entry: float,
    direction: int,
    risk: float,
    point_value: float,
    current_mae: float,
    current_mfe: float,
    target_index: int | None = None,
) -> Transition:
    """Build an exit Transition with P&L, MAE/MFE, and outcome."""
    pnl_ticks = (exit_price - entry) * direction
    pnl_r = round(pnl_ticks / risk, 4) if risk > 0 else 0.0
    pnl_dollars = round(pnl_ticks * point_value, 2)

    # Update excursions with this bar's result
    final_mae = min(current_mae, pnl_r)
    final_mfe = max(current_mfe, pnl_r)

    if target_index is not None:
        outcome = _determine_target_outcome(target_index)
    else:
        # Stop loss — outcome needs bars_in_trade context available only in the service
        outcome = None

    return Transition(
        signal_id=sid,
        new_status=status,
        exit_reason=reason,
        exit_price=exit_price,
        pnl_ticks=round(pnl_ticks, 4),
        pnl_r=pnl_r,
        pnl_dollars=pnl_dollars,
        mae=round(final_mae, 4),
        mfe=round(final_mfe, 4),
        outcome=outcome,
    )
