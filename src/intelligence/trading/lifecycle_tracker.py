"""Signal lifecycle tracker.

Evaluates signal state transitions based on price data. Pure functions —
does not touch the database. Returns Transition objects that the caller
persists via signal_ledger.update_signal_status().
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from src.intelligence.trading.signal_outcome import SignalOutcome
from src.observability.metrics import SIGNAL_OUTCOME_TOTAL
from src.observability.metrics import counter as _counter
from src.persistence.repository.signal_events_repository import SignalStatus

# Quick-stop threshold: signals stopped within 2 bars classified as stopped_at_entry
# Rationale: entry slippage + 1 confirmation bar = false positive if stopped here
OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2

# Minimum meaningful risk (entry - stop distance) for pnl_r calculations.
# Signals passing through with fp-epsilon risk (entry ≈ stop at machine precision)
# produce astronomical pnl_r. Belt-and-suspenders guard; primary rejection is the
# W4 emission gate in signal_schema.py using get_tick_size().
_MIN_RISK = 1e-6

# Target outcome lookup table (index 0→target_1, 1→target_1_2, 2+→target_full)
# Module-level tuple avoids reconstruction on every call
_TARGET_OUTCOME_LOOKUP = (
    SignalOutcome.TARGET_1,
    SignalOutcome.TARGET_1_2,
    SignalOutcome.TARGET_FULL,
)

# Staleness score constants — tune after 90 days of outcome data
STALENESS_REGIME_WEIGHT = 0.6  # weight of HMM regime drift component
STALENESS_SIGMA_WEIGHT = 0.4  # weight of GARCH sigma ratio component
assert math.isclose(
    STALENESS_REGIME_WEIGHT + STALENESS_SIGMA_WEIGHT, 1.0
), f"Staleness weights must sum to 1.0; got {STALENESS_REGIME_WEIGHT} + {STALENESS_SIGMA_WEIGHT}"
STALENESS_SIGMA_SCALE = 3.0  # sigma ratio at which sigma_component reaches 1.0
STALENESS_SIGMA_COMPONENT_THRESHOLD = 0.5  # sigma_component level that triggers "both" reason label
STALENESS_SCORE_THRESHOLD = 0.5  # composite score above which a bar counts as "stale"
STALENESS_CONSECUTIVE_THRESHOLD = 3  # consecutive stale bars before condition_expired


# ---------------------------------------------------------------------------
# Labeling Violation Metric (D-06)
# ---------------------------------------------------------------------------

_LABELING_VIOLATIONS = _counter(
    "signal_tracker_labeling_violations_total",
    "Count of signals with activated_at set but status=PENDING at TTL time",
)

_NULL_EXPIRES_AT_COUNTER = _counter(
    "signal_lifecycle_null_expires_at_total",
    "Count of bars where expires_at was NULL — data-integrity alert (D-17)",
)

_logger = structlog.get_logger(__name__)


def _record_outcome(signal: dict, outcome: SignalOutcome | str) -> None:
    """Record signal outcome to Prometheus for quality tracking (Phase 79)."""
    outcome_str = outcome.value if isinstance(outcome, SignalOutcome) else str(outcome)
    SIGNAL_OUTCOME_TOTAL.add(
        1,
        {
            "setup_plugin": signal.get("setup_plugin", "unknown"),
            "outcome": outcome_str,
        },
    )


# ---------------------------------------------------------------------------
# Chandelier Trailing Stop
# ---------------------------------------------------------------------------


def compute_chandelier_stop(
    direction: int,
    highest_high: float,
    lowest_low: float,
    vol: float,  # garch_sigma or atr_14 — caller picks source
    multiplier: float = 3.0,
) -> float:
    """Compute Chandelier Exit trailing stop level.

    Args:
        direction: 1 for long, -1 for short.
        highest_high: Highest high since activation.
        lowest_low: Lowest low since activation.
        vol: Volatility measure (garch_sigma preferred; atr_14 fallback).
        multiplier: ATR multiple for stop distance; default 3.0.

    Returns:
        Trailing stop price level.
    """
    if direction == 1:
        return highest_high - multiplier * vol
    return lowest_low + multiplier * vol


# ---------------------------------------------------------------------------
# Staleness Score
# ---------------------------------------------------------------------------


def compute_staleness_score(
    hmm_regime_now: int | None,
    hmm_regime_at_fire: int | None,
    garch_sigma_now: float | None,
    garch_sigma_at_fire: float | None,
) -> tuple[float, str]:
    """Compute staleness score (0.0-1.0) and trigger reason.

    Staleness components:
    - regime_drift: 1.0 if regimes differ (both non-None), else 0.0
    - sigma_component: continuous log-ratio of sigma growth, capped at 1.0

    Score = round(0.6 * regime_drift + 0.4 * sigma_component, 4)
    Reason = "both" | "hmm_regime_flip" | "vol_drift"

    Returns:
        (score, reason)
    """
    # Regime component
    if (
        hmm_regime_now is not None
        and hmm_regime_at_fire is not None
        and hmm_regime_now != hmm_regime_at_fire
    ):
        regime_drift = 1.0
    else:
        regime_drift = 0.0

    # Sigma component — log-ratio capped at 1.0
    if (
        garch_sigma_now is not None
        and garch_sigma_at_fire is not None
        and garch_sigma_at_fire > 0
        and garch_sigma_now > 0
    ):
        sigma_ratio = garch_sigma_now / garch_sigma_at_fire
        sigma_component = min(
            1.0, math.log(max(sigma_ratio, 1.0)) / math.log(STALENESS_SIGMA_SCALE)
        )
    else:
        sigma_component = 0.0

    score = round(
        STALENESS_REGIME_WEIGHT * regime_drift + STALENESS_SIGMA_WEIGHT * sigma_component, 4
    )

    if regime_drift > 0 and sigma_component >= STALENESS_SIGMA_COMPONENT_THRESHOLD:
        reason = "both"
    elif regime_drift > 0:
        reason = "hmm_regime_flip"
    else:
        reason = "vol_drift"

    return score, reason


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
    # Chandelier state (injected from service, mutated in-place)
    chandelier_state: dict | None = None,
    # Staleness state (injected from service)
    staleness_consecutive_bars: int = 0,
    staleness_score: float = 0.0,
    # D-01: Temporal guard parameters
    signal_timestamp: datetime | None = None,
    bar_time: datetime | None = None,
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
        chandelier_state: Mutable dict with Chandelier tracking state
            (keys: trailing_stop, highest_high, lowest_low, vol, vol_source).
            Updated in-place after each bar for active signals.
        staleness_consecutive_bars: Consecutive bars where staleness_score > 0.5.
        staleness_score: Current bar's staleness score (0.0-1.0).

    Returns:
        Transition if state changes (with updated mae/mfe on exit),
        None if signal stays in current state.
    """
    sid = signal["signal_id"]
    status = signal["status"]
    direction = signal["direction"]
    entry = signal["entry_price"]
    stop = signal["stop_loss"]
    # Normalize targets: proximal-to-distal (ascending for longs, descending for shorts).
    # Guards against plugins emitting targets in arbitrary order, which would corrupt
    # the target_index → outcome mapping and mis-credit P&L.
    raw_targets = signal.get("targets") or []
    targets = sorted(raw_targets, reverse=(direction == -1))
    ttl = signal.get("ttl_bars", 10)
    bars = signal.get("bars_elapsed", 0)
    point_value = signal.get("point_value", 1.0)
    zone_low = signal.get("entry_zone_low") or entry
    zone_high = signal.get("entry_zone_high") or entry
    risk = abs(entry - stop)
    expires_at = signal.get("expires_at")

    # --- Pending: zone activation check (first) ---
    if status == SignalStatus.PENDING:
        # Guard: skip activation if the TTL window has already closed on this bar.
        # A signal that activates past expires_at would immediately TTL-expire next bar.
        if expires_at is None or bar_time is None or bar_time < expires_at:
            activation = _check_zone_activation(
                sid,
                direction,
                zone_low,
                zone_high,
                high,
                low,
                bars,
                signal_timestamp=signal_timestamp,
                bar_time=bar_time,
            )
            if activation is not None:
                return activation
        # No activation (or past TTL) — fall through to TTL check below

    # --- Active signal checks (in priority order) ---

    # 1. Standard stop/target exit (conservative: stop before target on same bar)
    if status == SignalStatus.ACTIVE:
        # Advance be_floor on T1/T2 — T1 does not exit, floor advances to protect profit
        if chandelier_state is not None:
            target_1 = targets[0] if targets else None
            target_2 = targets[1] if len(targets) > 1 else None
            t1_hit = target_1 is not None and (
                (direction == 1 and high >= target_1) or (direction == -1 and low <= target_1)
            )
            t2_hit = target_2 is not None and (
                (direction == 1 and high >= target_2) or (direction == -1 and low <= target_2)
            )
            if t1_hit and chandelier_state.get("be_floor") is None:
                chandelier_state["be_floor"] = entry
            if t2_hit and chandelier_state.get("be_floor") is not None:
                chandelier_state["be_floor"] = target_1

        # Capture intrabar excursion for the exit check only — do NOT mutate current_mae/mfe
        # here because the TTL path (further down) must use the caller-supplied values to
        # stay consistent with cross-bar tracking done by the service layer.
        exit_mae, exit_mfe = current_mae, current_mfe
        if risk >= _MIN_RISK:
            bar_mae = (low - entry) * direction / risk
            bar_mfe = (high - entry) * direction / risk
            exit_mae = min(current_mae, bar_mae)
            exit_mfe = max(current_mfe, bar_mfe)
        exit_result = _check_active_exit(
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
            exit_mae,
            exit_mfe,
        )
        if exit_result is not None:
            if exit_result.outcome is not None:
                _record_outcome(signal, exit_result.outcome)
            return exit_result

    # 2. Chandelier trailing stop
    if status == SignalStatus.ACTIVE and chandelier_state is not None:
        trailing_stop = chandelier_state.get("trailing_stop")
        if trailing_stop is not None:
            # Clamp: chandelier can never trail past the breakeven floor
            be_floor = chandelier_state.get("be_floor")
            if be_floor is not None:
                if direction == 1:
                    trailing_stop = max(trailing_stop, be_floor)
                else:
                    trailing_stop = min(trailing_stop, be_floor)
            chandelier_hit = (direction == 1 and low <= trailing_stop) or (
                direction == -1 and high >= trailing_stop
            )
            if chandelier_hit:
                pnl_ticks = (trailing_stop - entry) * direction
                pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
                pnl_dollars = round(pnl_ticks * point_value, 2)
                final_mae = min(current_mae, pnl_r)
                final_mfe = max(current_mfe, pnl_r)
                if be_floor is not None:
                    _logger.info(
                        "chandelier_floor_exit",
                        signal_id=sid,
                        be_floor=be_floor,
                        trailing_stop=trailing_stop,
                        pnl_r=pnl_r,
                    )
                _record_outcome(signal, SignalOutcome.STOPPED_IN_TRADE)
                return Transition(
                    signal_id=sid,
                    new_status=SignalStatus.EXPIRED,
                    exit_reason="chandelier_stop",
                    exit_price=trailing_stop,
                    pnl_ticks=round(pnl_ticks, 4),
                    pnl_r=pnl_r,
                    pnl_dollars=pnl_dollars,
                    mae=round(final_mae, 4),
                    mfe=round(final_mfe, 4),
                    outcome=SignalOutcome.STOPPED_IN_TRADE,
                )

    # 3. Staleness condition_expired (3-bar confirmation)
    if status == SignalStatus.ACTIVE:
        if (
            staleness_consecutive_bars >= STALENESS_CONSECUTIVE_THRESHOLD
            and staleness_score > STALENESS_SCORE_THRESHOLD
        ):
            pnl_ticks = (close - entry) * direction
            pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
            pnl_dollars = round(pnl_ticks * point_value, 2)
            final_mae = min(current_mae, pnl_r)
            final_mfe = max(current_mfe, pnl_r)
            _record_outcome(signal, "condition_expired")
            return Transition(
                signal_id=sid,
                new_status=SignalStatus.EXPIRED,
                exit_reason="condition_expired",
                exit_price=close,
                pnl_ticks=round(pnl_ticks, 4),
                pnl_r=pnl_r,
                pnl_dollars=pnl_dollars,
                mae=round(final_mae, 4),
                mfe=round(final_mfe, 4),
                outcome="condition_expired",
            )

    # 4. TTL expiry (LAST — only after all price-based checks)
    # Use bar_time >= expires_at for deterministic replay. Never datetime.now(UTC).
    if expires_at is None:
        # D-17: NULL expires_at post-backfill is a data-integrity bug. Fail loud, do NOT
        # fall back to bar-count. Increment counter, warn, and skip TTL check this bar.
        _NULL_EXPIRES_AT_COUNTER.add(
            1,
            {
                "symbol": signal.get("symbol", "unknown"),
                "timeframe": signal.get("timeframe", "unknown"),
            },
        )
        # No TTL transition is produced; signal stays in current state (price exits still applied above).
    elif bar_time is not None and bar_time >= expires_at:
        exit_price = close
        pnl_ticks = (exit_price - entry) * direction
        pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
        pnl_dollars = round(pnl_ticks * point_value, 2)
        activated_at = signal.get("activated_at")
        if activated_at is not None and status == SignalStatus.PENDING:
            _LABELING_VIOLATIONS.add(1)
        was_activated = status == SignalStatus.ACTIVE
        if not was_activated:
            outcome = SignalOutcome.NEVER_ACTIVATED
        elif current_mfe > 0:
            outcome = SignalOutcome.TTL_EXPIRED_AHEAD
        else:
            outcome = SignalOutcome.TTL_EXPIRED_BEHIND
        _record_outcome(signal, outcome)
        return Transition(
            signal_id=sid,
            new_status=SignalStatus.EXPIRED,
            exit_reason="ttl_expired",
            exit_price=exit_price,
            pnl_ticks=round(pnl_ticks, 4),
            pnl_r=pnl_r,
            pnl_dollars=pnl_dollars,
            mae=current_mae,
            mfe=current_mfe,
            outcome=outcome,
        )

    # No transition — update Chandelier state (still running)
    if chandelier_state is not None:
        hh = max(chandelier_state.get("highest_high", high), high)
        ll = min(chandelier_state.get("lowest_low", low), low)
        chandelier_state["highest_high"] = hh
        chandelier_state["lowest_low"] = ll
        vol = chandelier_state.get("vol", 0.0)
        if vol > 0:
            new_stop = compute_chandelier_stop(direction, hh, ll, vol)
            old_stop = chandelier_state.get("trailing_stop")
            if old_stop is None:
                chandelier_state["trailing_stop"] = new_stop
            elif direction == 1 and new_stop > old_stop:
                chandelier_state["trailing_stop"] = new_stop
            elif direction == -1 and new_stop < old_stop:
                chandelier_state["trailing_stop"] = new_stop

    return None


def _check_zone_activation(
    sid: str,
    direction: int,
    zone_low: float,
    zone_high: float,
    high: float,
    low: float,
    bars_elapsed: int,
    signal_timestamp: Any = None,
    bar_time: Any = None,
) -> Transition | None:
    """Zone-aware activation: bar range must overlap the entry zone."""
    # D-01: Temporal guard -- never activate on same-or-earlier bar (signal did not exist yet)
    # Signals fired at bar T close cannot use bar T's price action (temporal bias).
    # Activation and exit evaluation must start at bar T+1.
    if isinstance(signal_timestamp, datetime) and isinstance(bar_time, datetime):
        if bar_time <= signal_timestamp:
            return None

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
        new_status=SignalStatus.ACTIVE,
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
    stop_hit = (direction == 1 and low <= stop) or (direction == -1 and high >= stop)
    if stop_hit:
        return _make_exit(
            sid,
            SignalStatus.EXPIRED,
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
    # T1 (i==0) does not exit — be_floor is advanced in evaluate_signal before this call
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
        if hit:
            if i == 0:
                # T1 advances be_floor (handled before this call); does not exit
                break
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


def _determine_target_outcome(target_index: int) -> SignalOutcome:
    """Map target index (0-based) to outcome label."""
    return _TARGET_OUTCOME_LOOKUP[min(target_index, 2)]


def _classify_stop_outcome(current_mfe: float, bars_in_trade_count: int | None) -> SignalOutcome:
    """Resolve fine-grained outcome for a stopped-out signal."""
    if (
        bars_in_trade_count is None
        or bars_in_trade_count <= OUTCOME_THRESHOLD_QUICK_STOP_BARS
        or current_mfe <= 0.05
    ):
        return SignalOutcome.STOPPED_AT_ENTRY
    return SignalOutcome.STOPPED_IN_TRADE


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
    raw_targets = signal.get("targets") or []
    targets = sorted(raw_targets, reverse=(direction == -1))
    ttl = signal.get("ttl_bars", 10)
    bars = signal.get("bars_elapsed", 0)
    risk = abs(market_entry_price - stop)

    # 1. Stop loss check (conservative: stop before target on same bar)
    if (direction == 1 and low <= stop) or (direction == -1 and high >= stop):
        return _make_market_exit(
            sid, stop, market_entry_price, direction, risk, current_mae, current_mfe
        )

    # 2. Target checks (highest target first for maximum credit)
    for i in range(len(targets) - 1, -1, -1):
        target = targets[i]
        hit = (direction == 1 and high >= target) or (direction == -1 and low <= target)
        if hit:
            pnl_ticks = (target - market_entry_price) * direction
            pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
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

    # 3. TTL expiry (last — only after price-based checks)
    if bars >= ttl:
        pnl_ticks = (close - market_entry_price) * direction
        pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
        outcome = (
            SignalOutcome.TTL_EXPIRED_AHEAD if current_mfe > 0 else SignalOutcome.TTL_EXPIRED_BEHIND
        )
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
    pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
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
    pnl_r = round(pnl_ticks / risk, 4) if risk >= _MIN_RISK else 0.0
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
