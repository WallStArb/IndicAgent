"""Signal schema definition and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.service_utils import TF_TTL_BARS, TICK_SIZES, round_to_tick

# Single canonical version tag. All signal producers and consumers reference this.
SIGNAL_SCHEMA_VERSION = "v1"

if TYPE_CHECKING:
    from src.intelligence.trading.trade_framer import TradeFrame

# Emission gate thresholds (W4)
MIN_RR_T1 = 0.0  # disabled — aggregator handles RR ranking; gate only checks structural validity

REQUIRED_SIGNAL_FIELDS = frozenset(
    {
        "type",
        "symbol",
        "timeframe",
        "timestamp",
        "signal_type",
        "setup_plugin",
        "direction",
        "entry_price",
        "stop_loss",
        "targets",
        "confidence",
        "risk_reward_ratio",
        "regime_context",
        "confluence_score",
        "supporting_factors",
        "invalidation_conditions",
        "ttl_bars",
    }
)


def validate_signal(signal: dict) -> bool:
    """Validate a signal.v1 dictionary. Returns True if valid."""
    if not isinstance(signal, dict):
        return False
    if not REQUIRED_SIGNAL_FIELDS.issubset(signal.keys()):
        return False
    if signal.get("type") != "signal.v1":
        return False
    conf = signal.get("confidence")
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        return False
    direction = signal.get("direction")
    if direction not in (1, -1, 1.0, -1.0):
        return False
    targets = signal.get("targets")
    if not isinstance(targets, list) or len(targets) == 0:
        return False
    # Stop must be on the correct side of entry.
    entry = signal.get("entry_price")
    stop = signal.get("stop_loss")
    if isinstance(entry, (int, float)) and isinstance(stop, (int, float)):
        if int(direction) == 1 and stop >= entry:
            return False
        if int(direction) == -1 and stop <= entry:
            return False
    return True


def make_signal(
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,
    setup_plugin: str,
    direction: int,
    entry_price: float,
    stop_loss: float,
    targets: list[float],
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int | None = None,
    # Optional framing fields — populated by TradeFramer post-aggregation
    entry_type: str = "at_close",
    stop_type: str = "atr",
    target_labels: list[str] | None = None,
    target_types: list[str] | None = None,
    rr_t1: float | None = None,
    rr_t2: float | None = None,
    rr_t3: float | None = None,
    framing_method: str = "atr_fallback",
) -> dict:
    """Construct a validated signal.v1 dict."""
    if ttl_bars is None:
        ttl_bars = TF_TTL_BARS.get(timeframe, 10)

    risk = abs(entry_price - stop_loss)
    rr = abs(targets[0] - entry_price) / risk if risk > 0 else 0.0
    sig = {
        "type": "signal.v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "signal_type": signal_type,
        "setup_plugin": setup_plugin,
        "direction": direction,
        "entry_price": round_to_tick(entry_price, symbol),
        "stop_loss": round_to_tick(stop_loss, symbol),
        "targets": [round_to_tick(t, symbol) for t in targets],
        "confidence": round(min(1.0, max(0.0, confidence)), 4),
        "risk_reward_ratio": round(rr, 2),
        "regime_context": regime_context,
        "confluence_score": round(confluence_score, 4),
        "supporting_factors": supporting_factors,
        "invalidation_conditions": invalidation_conditions,
        "ttl_bars": ttl_bars,
        "entry_type": entry_type,
        "stop_type": stop_type,
        "target_labels": target_labels or [],
        "target_types": target_types or [],
        "framing_method": framing_method,
    }
    if rr_t1 is not None:
        sig["rr_t1"] = round(rr_t1, 2)
    if rr_t2 is not None:
        sig["rr_t2"] = round(rr_t2, 2)
    if rr_t3 is not None:
        sig["rr_t3"] = round(rr_t3, 2)
    return sig


def make_signal_from_frame(
    tf: TradeFrame,
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,
    setup_plugin: str,
    direction: int,
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int | None = None,
    features_snapshot: dict | None = None,
) -> dict:
    """Build a signal.v1 dict from a TradeFrame, auto-extracting all framing fields.

    Auto-extracts: entry_price (tf.entry, NOT raw close), stop_loss, targets,
    zone_low, zone_high, entry_type, stop_type, rr_t1/t2/t3, target_labels,
    target_types, framing_method. Adds signal_schema_version=SIGNAL_SCHEMA_VERSION.

    Raises ValueError if tf.viable is False.
    """
    if not tf.viable:
        raise ValueError(
            f"Cannot build signal from non-viable TradeFrame: "
            f"{tf.rejection_reason or 'unknown'}"
        )

    if ttl_bars is None:
        ttl_bars = TF_TTL_BARS.get(timeframe, 10)

    # W4: Emission gate — reject structurally invalid signals at construction boundary
    tick = TICK_SIZES.get(symbol, 0)
    entry = tf.entry
    stop = tf.stop
    stop_distance = abs(entry - stop)

    # Gate 1: stop must be at least 1 tick from entry
    if stop_distance < tick:
        raise ValueError(
            f"Emission gate: stop ({stop}) is within 1 tick ({tick}) of entry ({entry})"
        )

    # Gate 2: stop_type must be identified (not "unknown")
    if tf.stop_type == "unknown":
        raise ValueError("Emission gate: stop_type is 'unknown' — structural stop basis required")

    # Gate 3: minimum risk/reward to first target
    target_prices = [t.price for t in tf.targets]
    if target_prices:
        reward = abs(target_prices[0] - entry)
        rr_t1_actual = reward / stop_distance if stop_distance > 0 else 0
        if rr_t1_actual < MIN_RR_T1:
            raise ValueError(
                f"Emission gate: RR to T1 ({rr_t1_actual:.2f}) below minimum ({MIN_RR_T1})"
            )
    target_labels = [t.label for t in tf.targets]
    target_types = [t.level_type for t in tf.targets]

    sig = make_signal(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        signal_type=signal_type,
        setup_plugin=setup_plugin,
        direction=direction,
        entry_price=tf.entry,
        stop_loss=tf.stop,
        targets=target_prices,
        confidence=confidence,
        regime_context=regime_context,
        confluence_score=confluence_score,
        supporting_factors=supporting_factors,
        invalidation_conditions=invalidation_conditions,
        ttl_bars=ttl_bars,
        entry_type=tf.entry_type,
        stop_type=tf.stop_type,
        target_labels=target_labels,
        target_types=target_types,
        rr_t1=tf.rr_t1 if tf.rr_t1 else None,
        rr_t2=tf.rr_t2 if tf.rr_t2 else None,
        rr_t3=tf.rr_t3 if tf.rr_t3 else None,
        framing_method=tf.method,
    )

    sig["zone_low"] = round_to_tick(tf.zone_low, symbol)
    sig["zone_high"] = round_to_tick(tf.zone_high, symbol)
    sig["zone_source"] = (features_snapshot or {}).get("zone_source")
    sig["signal_schema_version"] = SIGNAL_SCHEMA_VERSION

    if features_snapshot is not None:
        sig["features_snapshot"] = features_snapshot

    return sig
