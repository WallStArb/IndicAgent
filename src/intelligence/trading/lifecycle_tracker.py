"""Signal lifecycle tracker.

Evaluates signal state transitions based on price data. Pure functions —
does not touch the database. Returns Transition objects that the caller
persists via signal_ledger.update_signal_status().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


def evaluate_signal(
    signal: dict[str, Any],
    *,
    high: float,
    low: float,
    close: float,
) -> Transition | None:
    """Evaluate whether a signal should transition state.

    Args:
        signal: Dict with signal fields (status, direction, entry_price,
                stop_loss, targets, ttl_bars, bars_elapsed, point_value).
        high: Current bar's high price.
        low: Current bar's low price.
        close: Current bar's close price.

    Returns:
        Transition if state changes, None if signal stays in current state.
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
    risk = abs(entry - stop)

    # TTL check first (applies to both pending and active)
    if bars > ttl:
        exit_price = close
        return _make_exit(sid, "expired", "ttl_expired", exit_price,
                          entry, direction, risk, point_value)

    if status == "pending":
        return _check_pending_activation(sid, direction, entry, high, low)

    if status == "active":
        return _check_active_exit(sid, direction, entry, stop, targets,
                                  high, low, close, risk, point_value)

    return None


def _check_pending_activation(
    sid: str, direction: int, entry: float,
    high: float, low: float,
) -> Transition | None:
    """Check if a pending signal should activate."""
    if direction == 1 and high >= entry:
        return Transition(signal_id=sid, new_status="active")
    if direction == -1 and low <= entry:
        return Transition(signal_id=sid, new_status="active")
    return None


def _check_active_exit(
    sid: str, direction: int, entry: float, stop: float,
    targets: list[float], high: float, low: float, close: float,
    risk: float, point_value: float,
) -> Transition | None:
    """Check if an active signal should exit (stop, target, or expire)."""
    # Stop loss check first (conservative: stop before target on same bar)
    if direction == 1 and low <= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value)
    if direction == -1 and high >= stop:
        return _make_exit(sid, "stopped_out", "stop_loss", stop,
                          entry, direction, risk, point_value)

    # Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or \
              (direction == -1 and low <= target)
        if hit:
            label = f"target_{i + 1}"
            return _make_exit(sid, f"target_{i + 1}_hit", label, target,
                              entry, direction, risk, point_value)

    return None


def _make_exit(
    sid: str, status: str, reason: str, exit_price: float,
    entry: float, direction: int, risk: float, point_value: float,
) -> Transition:
    """Build an exit Transition with P&L calculations."""
    pnl_ticks = (exit_price - entry) * direction
    pnl_r = pnl_ticks / risk if risk > 0 else 0.0
    pnl_dollars = pnl_ticks * point_value
    return Transition(
        signal_id=sid,
        new_status=status,
        exit_reason=reason,
        exit_price=exit_price,
        pnl_ticks=round(pnl_ticks, 4),
        pnl_r=round(pnl_r, 4),
        pnl_dollars=round(pnl_dollars, 2),
    )
