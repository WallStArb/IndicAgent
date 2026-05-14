"""Signal schema definition and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

# Single canonical version tag. All signal producers and consumers reference this.
SIGNAL_SCHEMA_VERSION = "v2"
# Signals produced before v1 have contaminated entry/zone data — skip at consumer boundaries.
LEGACY_SIGNAL_SCHEMA_VERSION = "v0"

if TYPE_CHECKING:
    from src.intelligence.trading.trade_framer import TradeFrame

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
    ttl_bars: int = 10,
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
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "targets": [round(t, 2) for t in targets],
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
    ttl_bars: int = 10,
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

    target_prices = [t.price for t in tf.targets]
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

    sig["zone_low"] = tf.zone_low
    sig["zone_high"] = tf.zone_high
    sig["zone_source"] = (features_snapshot or {}).get("zone_source")
    sig["signal_schema_version"] = SIGNAL_SCHEMA_VERSION

    if features_snapshot is not None:
        sig["features_snapshot"] = features_snapshot

    return sig
